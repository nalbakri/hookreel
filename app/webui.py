"""
app/webui.py — HookReel web UI server.

FastAPI application providing:
- Session-based authentication (single admin password)
- Dashboard, library, chat, settings, indexers, downloader pages
- REST API endpoints for the chat interface and management
- Tailscale status detection
- Settings read/write to config/.env
- Bot pairing code generation and verification
- Watch mode routes and HLS stream serving (Phase 6.5)

Runs in a daemon thread alongside the Telegram bot and polling loop.
Port 8765 is already exposed in docker-compose.yml.
"""

import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import app.config as config
import app.database as database
from app.logger import get_logger
from app.audit import log_audit
from app.persona import get_name, get_greeting
logger = get_logger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────────

app_fastapi = FastAPI(title="HookReel", docs_url=None, redoc_url=None)

# Static files and templates — paths are relative to /hookreel inside container
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app_fastapi.mount(
    "/static",
    StaticFiles(directory=os.path.join(_BASE_DIR, "static")),
    name="static",
)
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))

# ── Security headers middleware ────────────────────────────────────────────────
@app_fastapi.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin"
    return response

# ── Session helpers ────────────────────────────────────────────────────────────

_SESSION_COOKIE = "hookreel_session"
_SESSION_MAX_AGE = 86400  # 24 hours in seconds


def _get_serializer() -> URLSafeTimedSerializer:
    """Return a URL-safe timed serializer using the current SECRET_KEY."""
    return URLSafeTimedSerializer(config.SECRET_KEY)

def _get_current_password() -> str:
    """
    Read WEBUI_PASSWORD directly from the .env file on disk.

    This allows password changes via the settings page to take
    effect immediately without requiring a container restart.
    Falls back to config.WEBUI_PASSWORD if the file cannot be read.
    """
    try:
        with open(_ENV_PATH, "r") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("WEBUI_PASSWORD="):
                    return line.partition("=")[2].strip()
    except Exception:
        pass
    return config.WEBUI_PASSWORD

def _create_session_cookie(response: Response) -> None:
    """Sign and set the session cookie on a response."""
    serializer = _get_serializer()
    token = serializer.dumps("authenticated")
    response.set_cookie(
        key=_SESSION_COOKIE,
        value=token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
    )


def _is_authenticated(request: Request) -> bool:
    """
    Check whether the request carries a valid signed session cookie.

    Returns True if the cookie is present, valid, and not expired.
    Returns False otherwise.
    """
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return False
    try:
        serializer = _get_serializer()
        serializer.loads(token, max_age=_SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def _login_redirect() -> RedirectResponse:
    """Return a redirect response to the login page."""
    return RedirectResponse(url="/login", status_code=302)


# ── Conversation manager reference ────────────────────────────────────────────
# Set by main.py after the ConversationManager is created so the chat
# endpoint can call handle_message().

_conversation_manager = None


def set_conversation_manager(manager) -> None:
    """Register the ConversationManager instance for use by the chat API."""
    global _conversation_manager
    _conversation_manager = manager
    logger.info("[HookReel] WebUI: conversation manager registered")


# ── Restart flag ──────────────────────────────────────────────────────────────
_restart_requested = threading.Event()


def set_restart_event(event: threading.Event) -> None:
    """
    Register an external threading.Event as the restart signal.

    Called by main.py at startup so the polling loop and the web UI
    share the same event object. When the restart button is clicked,
    main.py detects the signal and re-initialises the agent.
    """
    global _restart_requested
    _restart_requested = event
    logger.info("[HookReel] WebUI: restart event registered from main")


# ── Utility — .env read/write ──────────────────────────────────────────────────

_SENSITIVE_KEYS = {
    "QBITTORRENT_PASS", "PROWLARR_API_KEY", "JELLYFIN_API_KEY",
    "METADATA_API_KEY", "AI_API_KEY", "TELEGRAM_BOT_TOKEN",
    "WEBUI_PASSWORD", "SECRET_KEY",
}

_ENV_PATH = "/config/.env"


def read_env() -> dict:
    """
    Read all key=value pairs from config/.env.

    Sensitive keys are masked — only the last 4 characters are shown,
    prefixed with bullet characters.

    Returns:
        A dict of all config keys with masked sensitive values.
    """
    result = {}
    try:
        with open(_ENV_PATH, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key in _SENSITIVE_KEYS and len(value) > 4:
                    result[key] = "••••••••" + value[-4:]
                else:
                    result[key] = value
    except Exception as exc:
        logger.error("[HookReel] read_env error: %s", exc)
    return result


def write_env(updates: dict) -> bool:
    """
    Update key=value pairs in config/.env.

    Creates a backup at config/.env.bak before writing.
    Preserves all comments, blank lines, and ordering.
    Only updates keys that already exist in the file.
    Skips masked values (those starting with ••) to avoid
    overwriting real secrets with masked display values.

    Parameters:
        updates: Dict of key → new value pairs to write.

    Returns:
        True if the file was written successfully, False on error.
    """
    try:
        # Back up first
        shutil.copy2(_ENV_PATH, _ENV_PATH + ".bak")

        with open(_ENV_PATH, "r") as fh:
            lines = fh.readlines()

        new_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue

            key, _, _ = stripped.partition("=")
            key = key.strip()

            if key in updates:
                new_value = updates[key]
                # Never write masked placeholder values back
                if isinstance(new_value, str) and new_value.startswith("••"):
                    new_lines.append(line)
                else:
                    new_lines.append("{}={}\n".format(key, new_value))
            else:
                new_lines.append(line)

        with open(_ENV_PATH, "w") as fh:
            fh.writelines(new_lines)
        
        for key, value in updates.items():
            if isinstance(value, str) and not value.startswith("••"):
                os.environ[key] = value

        logger.info("[HookReel] write_env: updated %d key(s)", len(updates))
        return True

    except Exception as exc:
        logger.error("[HookReel] write_env error: %s", exc)
        return False


# ── Utility — connection testing ───────────────────────────────────────────────

def test_connection(service: str) -> dict:
    """
    Attempt a live connection test to a named HookReel service.

    Parameters:
        service: One of qbittorrent, prowlarr, jellyfin, ai,
                 metadata, clamav, proxy.

    Returns:
        A dict with keys: success (bool), message (str).
    """
    try:
        if service == "qbittorrent":
            url = "http://{}:{}/api/v2/app/version".format(
                config.QBITTORRENT_HOST, config.QBITTORRENT_PORT
            )
            r = httpx.get(url, timeout=5)
            return {"success": True, "message": "qBittorrent {}".format(r.text.strip())}

        elif service == "prowlarr":
            url = "http://{}:{}/api/v1/system/status".format(
                config.PROWLARR_HOST, config.PROWLARR_PORT
            )
            r = httpx.get(url, headers={"X-Api-Key": config.PROWLARR_API_KEY}, timeout=5)
            data = r.json()
            return {"success": True, "message": "Prowlarr {}".format(data.get("version", "OK"))}

        elif service == "jellyfin":
            url = "http://{}:{}/System/Info/Public".format(
                config.JELLYFIN_HOST, config.JELLYFIN_PORT
            )
            r = httpx.get(url, timeout=5)
            data = r.json()
            return {"success": True, "message": "Jellyfin {}".format(data.get("Version", "OK"))}

        elif service == "ai":
            url = "{}/models".format(config.AI_MODEL_ENDPOINT.rstrip("/"))
            r = httpx.get(
                url,
                headers={"Authorization": "Bearer {}".format(config.AI_API_KEY)},
                timeout=5,
            )
            return {"success": r.status_code < 400, "message": "HTTP {}".format(r.status_code)}

        elif service == "metadata":
            if config.METADATA_PROVIDER == "tmdb":
                url = "https://api.themoviedb.org/3/configuration?api_key={}".format(
                    config.METADATA_API_KEY
                )
                r = httpx.get(url, timeout=5)
                return {"success": r.status_code == 200, "message": "TMDB HTTP {}".format(r.status_code)}
            elif config.METADATA_PROVIDER == "omdb":
                url = "http://www.omdbapi.com/?apikey={}&t=test".format(config.METADATA_API_KEY)
                r = httpx.get(url, timeout=5)
                return {"success": r.status_code == 200, "message": "OMDb HTTP {}".format(r.status_code)}
            else:
                return {"success": True, "message": "TVmaze requires no API key"}

        elif service == "clamav":
            import pyclamd
            cd = pyclamd.ClamdNetworkSocket(
                host=config.CLAMAV_HOST, port=config.CLAMAV_PORT
            )
            version = cd.version()
            return {"success": True, "message": str(version)}

        elif service == "proxy":
            r = httpx.get("http://byparr:8191", timeout=5)
            return {"success": r.status_code < 400, "message": "HTTP {}".format(r.status_code)}

        else:
            return {"success": False, "message": "Unknown service: {}".format(service)}

    except Exception as exc:
        return {"success": False, "message": str(exc)}


# ── Utility — Tailscale status ─────────────────────────────────────────────────

def get_tailscale_status() -> dict:
    """
    Query the Tailscale local API for this machine's Tailscale status.

    Connects to host.docker.internal:41112 which maps to the host
    machine's Tailscale daemon via the extra_hosts Docker setting.

    Returns a dict with keys:
        running (bool), ip (str|None), hostname (str|None),
        device_count (int), last_seen (str|None)

    Never raises — if Tailscale is not installed or not running,
    returns running=False with all other fields as None/0.
    """
    try:
        r = httpx.get(
            "http://host.docker.internal:41112/localapi/v0/status",
            timeout=3,
        )
        data = r.json()

        # Extract this machine's Tailscale IP from TailscaleIPs list
        self_node = data.get("Self", {})
        ips = self_node.get("TailscaleIPs", [])
        tailscale_ip = ips[0] if ips else None

        # Count peer devices
        peers = data.get("Peer", {})
        device_count = len(peers) + 1  # peers + self

        # Last seen from self node
        last_seen = self_node.get("LastSeen") or self_node.get("Created")

        return {
            "running": True,
            "ip": tailscale_ip,
            "hostname": self_node.get("HostName") or self_node.get("DNSName", "").split(".")[0],
            "device_count": device_count,
            "last_seen": last_seen,
        }

    except Exception as exc:
        logger.debug("[HookReel] Tailscale not detected: %s", exc)
        return {
            "running": False,
            "ip": None,
            "hostname": None,
            "device_count": 0,
            "last_seen": None,
        }

# ── Rate limiting ──────────────────────────────────────────────────────────────
_rate_limits: dict = {}
_rate_limits_lock = threading.Lock()

def check_rate_limit(ip: str, endpoint: str, max_requests: int, window_seconds: int) -> bool:
    """
    Returns True if the request is allowed, False if rate limited.
    Tracks requests per IP per endpoint using a sliding window.
    Automatically cleans up expired entries.
    """
    if not config.RATE_LIMIT_ENABLED:
        return True
    now = time.time()
    key = f"{ip}:{endpoint}"
    with _rate_limits_lock:
        timestamps = _rate_limits.get(key, [])
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= max_requests:
            logger.warning("[HookReel] Rate limit hit: ip=%s endpoint=%s", ip, endpoint)
            return False
        timestamps.append(now)
        _rate_limits[key] = timestamps
    return True

def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For for reverse proxy setups."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# ── Routes — authentication ────────────────────────────────────────────────────

@app_fastapi.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirect to dashboard if authenticated, otherwise to login."""
    if _is_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@app_fastapi.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login page."""
    if _is_authenticated(request):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "error": None})


@app_fastapi.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, password: str = Form(...)):
    """
    Handle login form submission.

    Checks the submitted password against WEBUI_PASSWORD from config.
    On success sets a signed session cookie and redirects to dashboard.
    On failure re-renders the login page with an error message.
    """
    if password == _get_current_password():
        response = RedirectResponse(url="/dashboard", status_code=302)
        _create_session_cookie(response)
        logger.info("[HookReel] WebUI: successful login from %s", request.client.host)
        log_audit("login_success", {"ip": request.client.host}, "webui")
        return response
    else:
        logger.warning("[HookReel] WebUI: failed login attempt from %s", request.client.host)
        log_audit("login_failed", {"ip": request.client.host}, "webui")
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context= {"request": request, "error": "Incorrect password. Try again."},
            status_code=401,
        )


@app_fastapi.get("/logout")
async def logout():
    """Clear the session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(_SESSION_COOKIE)
    return response


# ── Routes — main pages ────────────────────────────────────────────────────────

@app_fastapi.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """
    Render the dashboard page.

    Shows active downloads, recent completions, and library stats.
    """
    if not _is_authenticated(request):
        return _login_redirect()

    try:
        from app.qbittorrent import list_active_torrents
        active_downloads = list_active_torrents()
    except Exception:
        active_downloads = []

    recent_complete = database.get_movies_by_status("complete")[-10:]
    all_movies = database.get_all_movies()
    downloading = database.get_movies_by_status("downloading")

    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "request": request,
        "active_page": "dashboard",
        "active_downloads": active_downloads,
        "recent_complete": recent_complete,
        "library_count": len(all_movies),
        "downloading_count": len(downloading),
        "version": config.VERSION, "version_name": config.VERSION_NAME,
    })


@app_fastapi.get("/library", response_class=HTMLResponse)
async def library(request: Request, search: str = ""):
    """
    Render the library page.

    Shows all movies in the database with optional search filtering.
    """
    if not _is_authenticated(request):
        return _login_redirect()

    movies = database.get_all_movies()
    if search:
        search_lower = search.lower()
        movies = [m for m in movies if search_lower in m["title"].lower()]

    return templates.TemplateResponse(request=request, name="library.html", context={
        "request": request,
        "active_page": "library",
        "movies": movies,
        "search": search,
        "version": config.VERSION, "version_name": config.VERSION_NAME,
    })


@app_fastapi.get("/chat", response_class=HTMLResponse)
async def chat(request: Request):
    """Render the chat interface page."""
    if not _is_authenticated(request):
        return _login_redirect()
    return templates.TemplateResponse(request=request, name="chat.html", context={
        "request": request,
        "active_page": "chat",
        "version": config.VERSION, "version_name": config.VERSION_NAME,
        "agent_name": get_name(),
        "greeting": get_greeting(),
    })


@app_fastapi.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    """Render the settings page with current config values."""
    if not _is_authenticated(request):
        return _login_redirect()
    env = read_env()
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "request": request,
        "active_page": "settings",
        "settings": env,
        "delete_enabled": config.DELETE_ENABLED,
        "version": config.VERSION, "version_name": config.VERSION_NAME,
    })


@app_fastapi.get("/indexers", response_class=HTMLResponse)
async def indexers(request: Request):
    """Render the Prowlarr indexer management page."""
    if not _is_authenticated(request):
        return _login_redirect()
    return templates.TemplateResponse(request=request, name="indexers.html", context={
        "request": request,
        "active_page": "indexers",
        "version": config.VERSION, "version_name": config.VERSION_NAME,
    })


@app_fastapi.get("/downloader", response_class=HTMLResponse)
async def downloader(request: Request):
    """Render the qBittorrent downloader management page."""
    if not _is_authenticated(request):
        return _login_redirect()
    return templates.TemplateResponse(request=request, name="downloader.html", context={
        "request": request,
        "active_page": "downloader",
        "version": config.VERSION, "version_name": config.VERSION_NAME,
    })


@app_fastapi.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """
    Render a simple log viewer showing the last 200 lines of hookreel.log.
    Auto-refreshes every 30 seconds.
    """
    if not _is_authenticated(request):
        return _login_redirect()

    log_lines = []
    try:
        with open("/logs/hookreel.log", "r") as fh:
            log_lines = fh.readlines()[-200:]
    except Exception:
        log_lines = ["Log file not found or unreadable."]

    log_content = "".join(log_lines)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="30">
  <link rel="stylesheet" href="/static/style.css">
  <title>Logs — HookReel</title>
</head>
<body>
<nav class="nav">
  <a href="/dashboard" class="nav-brand">⚓ Hook<span>Reel</span></a>
  <ul class="nav-links">
    <li><a href="/dashboard">Dashboard</a></li>
    <li><a href="/settings" class="active">Settings</a></li>
    <li><a href="/logout">Logout</a></li>
  </ul>
  <button class="nav-hamburger" onclick="document.getElementById('nd').classList.toggle('open')">☰</button>
</nav>
<div class="nav-drawer" id="nd">
  <a href="/dashboard">📊 Dashboard</a>
  <a href="/settings">⚙️ Settings</a>
  <a href="/logout">🚪 Logout</a>
</div>
<div class="page">
  <div class="page-header flex-between">
    <div>
      <h1 class="page-title">Log Viewer</h1>
      <p class="page-subtitle">Last 200 lines — auto-refreshes every 30s</p>
    </div>
    <a href="/logs/download" class="btn btn-secondary btn-sm">Download Full Log</a>
  </div>
  <div class="log-box">""" + log_content.replace("&", "&amp;").replace("<", "&lt;") + """</div>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app_fastapi.get("/logs/download")
async def logs_download(request: Request):
    """Serve the full hookreel.log file as a download."""
    if not _is_authenticated(request):
        return _login_redirect()
    try:
        with open("/logs/hookreel.log", "r") as fh:
            content = fh.read()
        return Response(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=hookreel.log"},
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Routes — watch mode (Phase 6.5) ───────────────────────────────────────────

@app_fastapi.get("/watch", response_class=HTMLResponse)
async def watch_page(request: Request, stream: str = ""):
    """
    Render the watch history and active streams page.

    Optional query parameter:
        stream: HLS playlist URL to auto-load in the embedded player.
    """
    if not _is_authenticated(request):
        return _login_redirect()

    history = database.get_watch_history(limit=20)

    from app.hls_streamer import hls_streamer
    active_streams = hls_streamer.get_active_streams()

    return templates.TemplateResponse(request=request, name="watch.html", context={
        "request": request,
        "active_page": "watch",
        "history": history,
        "active_streams": active_streams,
        "jellyfin_enabled": config.JELLYFIN_ENABLED,
        "autoplay_stream": stream,
        "version": config.VERSION, "version_name": config.VERSION_NAME,
    })


@app_fastapi.get("/stream/{media_id}/{filename}")
async def serve_hls_segment(request: Request, media_id: int, filename: str):
    """
    Serve an HLS playlist or segment file for a given media_id.

    Only active when JELLYFIN_ENABLED=false. Requires authentication.
    Files are served from HLS_STREAM_DIR/{media_id}/{filename}.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    if config.JELLYFIN_ENABLED:
        return JSONResponse(
            {"error": "HLS streaming is disabled — Jellyfin mode is active."},
            status_code=404,
        )

    # Sanitise filename — no path traversal
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(config.HLS_STREAM_DIR, str(media_id), safe_filename)

    if not os.path.isfile(file_path):
        return JSONResponse({"error": "Segment not found"}, status_code=404)

    # Determine correct media type
    if safe_filename.endswith(".m3u8"):
        media_type = "application/vnd.apple.mpegurl"
    elif safe_filename.endswith(".ts"):
        media_type = "video/MP2T"
    else:
        media_type = "application/octet-stream"

    return FileResponse(file_path, media_type=media_type)


# ── API routes — watch mode (Phase 6.5) ───────────────────────────────────────

@app_fastapi.post("/api/watch/movie")
async def api_watch_movie(request: Request):
    """
    Generate a watch link or start an HLS stream for a movie.

    Accepts JSON: {"title": "...", "movie_id": 1}
    Returns JSON with mode, links or stream_url, and message.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
        title = body.get("title", "")
        movie_id = body.get("movie_id")

        from app.watch import watch_movie
        result = watch_movie(title=title, movie_id=movie_id)
        return JSONResponse(result)

    except Exception as exc:
        logger.error("[HookReel] WebUI api_watch_movie error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app_fastapi.post("/api/watch/episode")
async def api_watch_episode(request: Request):
    """
    Generate a watch link or start an HLS stream for a TV episode.

    Accepts JSON: {"show_title": "...", "season": 1, "episode": 1}
    Returns JSON with mode, links or stream_url, and message.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
        show_title = body.get("show_title", "")
        season = body.get("season")
        episode = body.get("episode")

        from app.watch import watch_episode
        result = watch_episode(
            show_title=show_title,
            season=season,
            episode=episode,
        )
        return JSONResponse(result)

    except Exception as exc:
        logger.error("[HookReel] WebUI api_watch_episode error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app_fastapi.get("/api/watch/history")
async def api_watch_history(request: Request):
    """Return watch history as JSON. Defaults to last 20 entries."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        history = database.get_watch_history(limit=20)
        return JSONResponse(history)
    except Exception as exc:
        logger.error("[HookReel] WebUI api_watch_history error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app_fastapi.post("/api/watch/stop/{media_id}")
async def api_watch_stop(request: Request, media_id: int):
    """
    Stop an active HLS stream for the given media_id.

    Only relevant when JELLYFIN_ENABLED=false.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        from app.hls_streamer import hls_streamer
        stopped = hls_streamer.stop_stream(media_id)
        return JSONResponse({"success": stopped})
    except Exception as exc:
        logger.error("[HookReel] WebUI api_watch_stop error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── API routes — chat ──────────────────────────────────────────────────────────

@app_fastapi.post("/api/chat")
async def api_chat(request: Request):
    """
    Handle a chat message from the web UI.

    Accepts JSON: {"message": "user text"}
    Returns JSON: {"response": "agent reply"}
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    ip = _get_client_ip(request)
    if not check_rate_limit(ip, "chat", 10, 60):
        return JSONResponse({"error": "Too many requests. Please wait before retrying."}, status_code=429)
    try:
        body = await request.json()
        message = body.get("message", "").strip()
        if not message:
            return JSONResponse({"error": "Empty message"}, status_code=400)

        if _conversation_manager is None:
            return JSONResponse({"response": "Agent not ready yet. Please wait a moment."})

        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            _conversation_manager.handle_message,
            "webui",
            message,
        )
        return JSONResponse({"response": response})

    except Exception as exc:
        logger.error("[HookReel] WebUI chat error: %s", exc)
        return JSONResponse({"response": "Something went wrong. Please try again."})


# ── API routes — status ────────────────────────────────────────────────────────

@app_fastapi.get("/api/status")
async def api_status(request: Request):
    """
    Return a JSON summary of current system status.

    Used by the dashboard for live polling every 10 seconds.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        from app.qbittorrent import list_active_torrents
        active = list_active_torrents()
        dl_speed = sum(t.get("dlspeed", 0) for t in active)
    except Exception:
        active = []
        dl_speed = 0

    all_movies = database.get_all_movies()
    downloading = database.get_movies_by_status("downloading")

    # Check Tailscale for remote URL in status
    ts = get_tailscale_status()
    remote_url = "http://{}:8765".format(ts["ip"]) if ts["running"] and ts["ip"] else None

    return JSONResponse({
        "library_count": len(all_movies),
        "active_downloads": len(downloading),
        "active_torrents": len(active),
        "dl_speed": dl_speed,
        "remote_url": remote_url,
    })


# ── API routes — pairing ───────────────────────────────────────────────────────

@app_fastapi.post("/api/pair/generate")
async def api_pair_generate(request: Request):
    """
    Generate a one-time 6-digit pairing code.

    The code is stored in the database with a 10-minute expiry.
    The user sends this code to the Telegram bot via /pair <code>
    to get their Telegram ID added to the approved list.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    ip = _get_client_ip(request)
    if not check_rate_limit(ip, "pair", 5, 60):
        return JSONResponse({"error": "Too many requests. Please wait before retrying."}, status_code=429)
    code = "{:06d}".format(secrets.randbelow(1000000))
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    success = database.store_pairing_code(code, expires_at)
    if success:
        logger.info("[HookReel] WebUI: pairing code generated, expires %s", expires_at)
        return JSONResponse({"code": code})
    else:
        return JSONResponse({"error": "Failed to generate code"}, status_code=500)


@app_fastapi.post("/api/pair/verify")
async def api_pair_verify(request: Request):
    """
    Verify a pairing code submitted by the Telegram bot.

    Accepts JSON: {"code": "123456", "telegram_id": 12345678}
    Returns JSON: {"success": true/false}
    """
    try:
        ip = _get_client_ip(request)
        if not check_rate_limit(ip, "pair", 5, 60):
            return JSONResponse({"success": False, "error": "Too many requests. Please wait before retrying."}, status_code=429)
        body = await request.json()
        code = str(body.get("code", "")).strip()
        telegram_id = int(body.get("telegram_id", 0))
        if not code or not telegram_id:
            return JSONResponse({"success": False, "error": "Missing fields"})
        success = database.verify_and_consume_pairing_code(code, telegram_id)
        return JSONResponse({"success": success})
    except Exception as exc:
        logger.error("[HookReel] WebUI pair verify error: %s", exc)
        return JSONResponse({"success": False, "error": str(exc)})


# ── API routes — settings ──────────────────────────────────────────────────────

@app_fastapi.post("/api/settings")
async def api_settings_post(request: Request):
    """
    Update settings in config/.env or perform a maintenance action.

    Accepts JSON with either:
    - Key/value pairs to write to .env
    - {"action": "cleanup_stuck"} to clean orphaned downloads
    - {"action": "delete_test_rows"} to remove test database rows
    - {"action": "restart_agent"} to signal a polling loop restart

    Returns JSON: {"success": bool, "restart_required": bool}
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    ip = _get_client_ip(request)
    if not check_rate_limit(ip, "settings", 60, 60):
        return JSONResponse({"error": "Too many requests. Please wait before retrying."}, status_code=429)
   
    try:
        body = await request.json()

        # Handle maintenance actions
        action = body.get("action")
        if action == "cleanup_stuck":
            count = database.cleanup_stuck_downloads(hours=24)
            return JSONResponse({"success": True, "count": count})

        if action == "delete_test_rows":
            count = database.delete_test_rows()
            return JSONResponse({"success": True, "count": count})

        if action == "restart_agent":
            log_audit("agent_restarted", {"triggered_by": "webui"}, "webui")
            _restart_requested.set()
            return JSONResponse({"success": True, "message": "Restart signal sent."})

        # Keys that require a container restart to take effect
        restart_keys = {
            "QBITTORRENT_HOST", "QBITTORRENT_PORT", "PROWLARR_HOST",
            "PROWLARR_PORT", "PROWLARR_API_KEY", "JELLYFIN_HOST",
            "JELLYFIN_PORT", "JELLYFIN_API_KEY", "AI_MODEL_ENDPOINT",
            "AI_MODEL_NAME", "AI_API_KEY", "TELEGRAM_BOT_TOKEN",
            "CLAMAV_HOST", "CLAMAV_PORT",
        }

        needs_restart = any(k in restart_keys for k in body.keys())
        success = write_env(body)
        if success:
            log_audit("settings_changed", {"keys": ",".join(body.keys())}, "webui")
        return JSONResponse({"success": success, "restart_required": needs_restart})

    except Exception as exc:
        logger.error("[HookReel] WebUI settings post error: %s", exc)
        return JSONResponse({"success": False, "error": str(exc)})


@app_fastapi.post("/api/settings/test")
async def api_settings_test(request: Request):
    """
    Test a live connection to a named service.

    Accepts JSON: {"service": "qbittorrent"}
    Returns JSON: {"success": bool, "message": str}
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
        service = body.get("service", "")
        result = test_connection(service)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"success": False, "message": str(exc)})

# ── API routes — Persona ──────────────────────────────────────────────────────
@app_fastapi.get("/api/settings/persona")
async def api_get_persona(request: Request):
    """Return current persona name and personality."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.persona import load_persona
    persona = load_persona()
    return JSONResponse({"name": persona.get("name", "MrSmee"), "personality": persona.get("personality", "pirate")})

@app_fastapi.post("/api/settings/persona")
async def api_save_persona(request: Request):
    """Save agent name and personality style."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        personality = body.get("personality", "").strip()
        from app.persona import update_name, update_personality
        errors = []
        if name:
            if not update_name(name):
                errors.append("Invalid name")
        if personality:
            if not update_personality(personality):
                errors.append("Invalid personality")
        if errors:
            return JSONResponse({"ok": False, "error": ", ".join(errors)})
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})


# ── API routes — Tailscale ─────────────────────────────────────────────────────

@app_fastapi.get("/api/tailscale/status")
async def api_tailscale_status(request: Request):
    """Return Tailscale status as JSON for the settings page."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return JSONResponse(get_tailscale_status())


# ── API routes — Prowlarr management ──────────────────────────────────────────

@app_fastapi.get("/api/indexers")
async def api_get_indexers(request: Request):
    """Return all Prowlarr indexers as JSON."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.prowlarr_mgmt import get_indexers
    return JSONResponse(get_indexers())


@app_fastapi.get("/api/indexers/stats")
async def api_indexer_stats(request: Request):
    """Return Prowlarr indexer statistics as JSON."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.prowlarr_mgmt import get_indexer_stats
    return JSONResponse(get_indexer_stats())


@app_fastapi.post("/api/indexers/testall")
async def api_test_all_indexers(request: Request):
    """Trigger a test of all Prowlarr indexers."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.prowlarr_mgmt import test_all_indexers
    return JSONResponse(test_all_indexers())


@app_fastapi.post("/api/indexers/{indexer_id}/toggle")
async def api_toggle_indexer(request: Request, indexer_id: int):
    """Enable or disable a Prowlarr indexer."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    from app.prowlarr_mgmt import toggle_indexer
    success = toggle_indexer(indexer_id, body.get("enabled", True))
    return JSONResponse({"success": success})


@app_fastapi.post("/api/indexers/{indexer_id}/test")
async def api_test_indexer(request: Request, indexer_id: int):
    """Test a single Prowlarr indexer."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.prowlarr_mgmt import test_indexer
    return JSONResponse(test_indexer(indexer_id))


@app_fastapi.delete("/api/indexers/{indexer_id}")
async def api_delete_indexer(request: Request, indexer_id: int):
    """Delete a Prowlarr indexer."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.prowlarr_mgmt import delete_indexer
    success = delete_indexer(indexer_id)
    return JSONResponse({"success": success})


# ── API routes — qBittorrent management ───────────────────────────────────────

@app_fastapi.get("/api/downloader/transfer")
async def api_transfer_info(request: Request):
    """Return qBittorrent global transfer stats."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.qbittorrent_mgmt import get_transfer_info
    return JSONResponse(get_transfer_info())


@app_fastapi.get("/api/downloader/torrents")
async def api_get_torrents(request: Request, filter: str = "all"):
    """Return torrent list with optional filter."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.qbittorrent_mgmt import get_all_torrents
    return JSONResponse(get_all_torrents(torrent_filter=filter))


@app_fastapi.post("/api/downloader/torrents/{torrent_hash}/pause")
async def api_pause_torrent(request: Request, torrent_hash: str):
    """Pause a torrent by hash."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.qbittorrent_mgmt import pause_torrent
    return JSONResponse({"success": pause_torrent(torrent_hash)})


@app_fastapi.post("/api/downloader/torrents/{torrent_hash}/resume")
async def api_resume_torrent(request: Request, torrent_hash: str):
    """Resume a torrent by hash."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.qbittorrent_mgmt import resume_torrent
    return JSONResponse({"success": resume_torrent(torrent_hash)})


@app_fastapi.post("/api/downloader/torrents/{torrent_hash}/delete")
async def api_delete_torrent(request: Request, torrent_hash: str):
    """Delete a torrent, optionally with files."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    from app.qbittorrent_mgmt import delete_torrent
    return JSONResponse({"success": delete_torrent(torrent_hash, body.get("delete_files", False))})


@app_fastapi.post("/api/downloader/torrents/bulk/{action}")
async def api_bulk_torrent_action(request: Request, action: str):
    """Pause or resume all torrents matching the current filter."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    torrent_filter = body.get("filter", "all")
    from app.qbittorrent_mgmt import get_all_torrents, pause_torrent, resume_torrent
    torrents = get_all_torrents(torrent_filter=torrent_filter)
    count = 0
    for t in torrents:
        h = t.get("hash", "")
        if not h:
            continue
        if action == "pause":
            pause_torrent(h)
        elif action == "resume":
            resume_torrent(h)
        count += 1
    return JSONResponse({"success": True, "count": count})


@app_fastapi.get("/api/downloader/categories")
async def api_get_categories(request: Request):
    """Return all qBittorrent categories."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.qbittorrent_mgmt import get_categories
    return JSONResponse(get_categories())


@app_fastapi.post("/api/downloader/categories")
async def api_add_category(request: Request):
    """Add a new qBittorrent category."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    from app.qbittorrent_mgmt import add_category
    success = add_category(body.get("name", ""), body.get("save_path", ""))
    return JSONResponse({"success": success})


@app_fastapi.delete("/api/downloader/categories/{name}")
async def api_remove_category(request: Request, name: str):
    """Remove a qBittorrent category."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.qbittorrent_mgmt import remove_category
    return JSONResponse({"success": remove_category(name)})


@app_fastapi.get("/api/downloader/preferences")
async def api_get_preferences(request: Request):
    """Return qBittorrent preferences."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    from app.qbittorrent_mgmt import get_preferences
    return JSONResponse(get_preferences())


@app_fastapi.post("/api/downloader/preferences")
async def api_set_preferences(request: Request):
    """Update qBittorrent preferences."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    from app.qbittorrent_mgmt import set_preferences
    return JSONResponse({"success": set_preferences(body)})


@app_fastapi.post("/api/downloader/speed")
async def api_set_speed(request: Request):
    """Set global download and upload speed limits."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    body = await request.json()
    from app.qbittorrent_mgmt import set_speed_limits
    success = set_speed_limits(body.get("dl_limit", 0), body.get("ul_limit", 0))
    return JSONResponse({"success": success})


# ── TV show routes ─────────────────────────────────────────────────────────────

@app_fastapi.get("/tv")
async def tv_library(request: Request):
    """
    Render the TV show library page.
    Displays all tracked shows with episode counts and statuses.
    """
    if not _is_authenticated(request):
        return _login_redirect()
    shows = database.get_all_shows()
    shows_with_counts = []
    for show in shows:
        episodes = database.get_episodes_for_show(show["id"])
        complete = sum(1 for e in episodes if e["status"] == "complete")
        shows_with_counts.append({
            **show,
            "episode_count": len(episodes),
            "complete_count": complete,
        })
    return templates.TemplateResponse(
        request=request,
        name="tv.html",
        context={"request": request, "active_page": "tv", "shows": shows_with_counts, "version": config.VERSION, "version_name": config.VERSION_NAME}
    )


@app_fastapi.get("/api/tv/shows")
async def api_tv_shows(request: Request):
    """Return all tracked TV shows as JSON with episode counts."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    shows = database.get_all_shows()
    result = []
    for show in shows:
        episodes = database.get_episodes_for_show(show["id"])
        complete = sum(1 for e in episodes if e["status"] == "complete")
        result.append({
            **show,
            "episode_count": len(episodes),
            "complete_count": complete,
        })
    return JSONResponse(result)


@app_fastapi.get("/api/tv/shows/{show_id}/episodes")
async def api_tv_episodes(request: Request, show_id: int):
    """Return all episodes for a specific show as JSON."""
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    show = database.get_show(show_id)
    if not show:
        return JSONResponse({"error": "Show not found"}, status_code=404)
    episodes = database.get_episodes_for_show(show_id)
    return JSONResponse({"show": show, "episodes": episodes})


# ── Server startup ─────────────────────────────────────────────────────────────

def run_webui() -> None:
    """
    Start the FastAPI web server with uvicorn on port 8765.

    Intended to be called in a daemon thread from main.py.
    Blocks until the server stops.
    """
    logger.info("[HookReel] WebUI starting on port 8765")
    uvicorn.run(
        app_fastapi,
        host="0.0.0.0",
        port=8765,
        log_level="warning",
    )

# ── API routes — library scan (Phase 8) ───────────────────────────────────────

_scan_lock = threading.Lock()
_scan_running = False


@app_fastapi.post("/api/library/scan")
async def api_library_scan(request: Request):
    """
    Trigger a library scan and stream progress via Server-Sent Events.

    Runs import_library.py --all-sources --enrich inside the container.
    Only one scan can run at a time.
    Returns SSE stream: each line is a JSON object with a 'line' field.
    Final message has 'done': true and a 'summary' dict.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    global _scan_running
    if _scan_running:
        return JSONResponse(
            {"error": "Scan already in progress"}, status_code=409
        )

    import asyncio
    import subprocess
    from fastapi.responses import StreamingResponse

    async def scan_stream():
        global _scan_running
        _scan_running = True
        movies_added = 0
        tv_added = 0
        errors = 0

        try:
            proc = await asyncio.create_subprocess_exec(
                "python", "/hookreel/import_library.py",
                "--all-sources", "--enrich", "--verbose",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue

                # Track counters from output
                if "Newly inserted:" in line:
                    try:
                        n = int(line.strip().split(":")[-1].strip())
                        movies_added += n
                    except ValueError:
                        pass
                if "TV episodes added:" in line:
                    try:
                        part = line.split("TV episodes added:")[-1].strip()
                        tv_added += int(part.split()[0])
                    except (ValueError, IndexError):
                        pass
                if "[error]" in line.lower():
                    errors += 1

                import json as _json
                yield "data: {}\n\n".format(
                    _json.dumps({"line": line})
                )

            await proc.wait()

            # Trigger Jellyfin refresh
            try:
                if config.JELLYFIN_ENABLED:
                    import httpx as _httpx
                    _httpx.post(
                        "http://{}:{}/Library/Refresh".format(
                            config.JELLYFIN_HOST, config.JELLYFIN_PORT
                        ),
                        headers={"X-Emby-Token": config.JELLYFIN_API_KEY},
                        timeout=10,
                    )
            except Exception:
                pass

            import json as _json
            yield "data: {}\n\n".format(
                _json.dumps({
                    "done": True,
                    "summary": {
                        "movies_added": movies_added,
                        "tv_added": tv_added,
                        "errors": errors,
                    }
                })
            )

        except Exception as exc:
            import json as _json
            yield "data: {}\n\n".format(
                _json.dumps({"error": str(exc), "done": True})
            )
        finally:
            _scan_running = False

    return StreamingResponse(
        scan_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app_fastapi.get("/api/library/sources")
async def api_library_sources(request: Request):
    """
    Return all configured media sources as JSON.
    Used by the settings page Media Sources section.
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    sources = [
        {
            "label": "Movies",
            "path": config.MOVIES_PATH,
            "type": "default",
            "mounted": os.path.isdir(config.MOVIES_PATH),
        },
        {
            "label": "TV",
            "path": config.TV_PATH,
            "type": "default",
            "mounted": os.path.isdir(config.TV_PATH),
        },
    ]

    for i in range(1, 6):
        path = os.environ.get("EXTRA_MEDIA_{}".format(i), "")
        label = os.environ.get(
            "EXTRA_MEDIA_{}_LABEL".format(i), "Extra Source {}".format(i)
        )
        if path:
            sources.append({
                "label": label,
                "path": path,
                "type": "extra",
                "index": i,
                "mounted": os.path.isdir(path),
            })

    return JSONResponse(sources)


@app_fastapi.post("/api/library/sources")
async def api_library_sources_add(request: Request):
    """
    Add a new extra media source to config/.env.
    Finds the first unused EXTRA_MEDIA_N slot (1-5).
    Accepts JSON: {"label": "Portable Drive", "path": "/data/extra/1"}
    Returns JSON: {"success": bool, "index": N, "restart_required": true}
    """
    if not _is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        body = await request.json()
        label = body.get("label", "").strip()
        path = body.get("path", "").strip()

        if not label or not path:
            return JSONResponse(
                {"success": False, "error": "Label and path are required"},
                status_code=400,
            )

        # Find first free slot
        slot = None
        for i in range(1, 6):
            existing = os.environ.get("EXTRA_MEDIA_{}".format(i), "")
            if not existing:
                slot = i
                break

        if slot is None:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Maximum of 5 extra media sources reached",
                },
                status_code=400,
            )

        updates = {
            "EXTRA_MEDIA_{}".format(slot): path,
            "EXTRA_MEDIA_{}_LABEL".format(slot): label,
        }
        success = write_env(updates)
        if success:
            log_audit(
                "media_source_added",
                {"slot": slot, "label": label, "path": path},
                "webui",
            )

        return JSONResponse({
            "success": success,
            "index": slot,
            "restart_required": True,
        })

    except Exception as exc:
        logger.error("[HookReel] api_library_sources_add error: %s", exc)
        return JSONResponse(
            {"success": False, "error": str(exc)}, status_code=500
        )
