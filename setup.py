#!/usr/bin/env python3
"""
setup.py -- HookReel first-run setup wizard.

Run on the HOST (not inside the container) to generate
config/.env and docker-compose.yml before first launch.

Usage:
    python3 setup.py
"""

import os
import re
import sys
import getpass
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ask(prompt, default=None, secret=False):
    """Prompt the user for input. Returns default if Enter pressed."""
    if default:
        display = "{} [{}]: ".format(prompt, default)
    else:
        display = "{}: ".format(prompt)
    try:
        if secret:
            value = getpass.getpass(display)
        else:
            value = input(display).strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\nSetup cancelled.")
        sys.exit(0)
    if not value and default is not None:
        return default
    return value


def ask_choice(prompt, choices, default="1"):
    """Present a numbered menu and return the chosen number as a string."""
    while True:
        value = ask(prompt, default=default)
        if value in choices:
            return value
        print("  Please enter one of: {}".format(", ".join(choices)))


def ask_yes_no(prompt, default="n"):
    """Ask a yes/no question. Returns True for yes."""
    hint = "[Y/n]" if default.lower() == "y" else "[y/N]"
    while True:
        value = ask("{} {}".format(prompt, hint), default=default)
        if value.lower() in ("y", "yes"):
            return True
        if value.lower() in ("n", "no"):
            return False
        print("  Please enter y or n.")


def ensure_path(path, label):
    """Check a path exists. Offer to create it if not."""
    if os.path.isdir(path):
        return True
    print("  WARNING: {} does not exist: {}".format(label, path))
    if ask_yes_no("  Create it now?", default="y"):
        try:
            os.makedirs(path, exist_ok=True)
            print("  Created: {}".format(path))
            return True
        except Exception as exc:
            print("  Could not create: {}".format(exc))
            return False
    return False


def banner(text):
    print("\n" + "=" * 50)
    print(text)
    print("=" * 50)


def section(text):
    print("\n--- {} ---".format(text))


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------

def step_agent_name():
    section("Step 1 -- Agent Name")
    print("What would you like to name your AI agent?")
    print("This is the name it uses when talking to you.")
    name = ask("Agent name", default="MrSmee")
    if not re.match(r"^[A-Za-z][A-Za-z0-9 \-]*$", name) or len(name) > 30:
        print("  Invalid name -- using MrSmee")
        name = "MrSmee"
    return name


def step_media_folders():
    section("Step 2 -- Media Folders")
    print("Where is your media stored?")

    movies = ask("Movies folder path", default="/srv/mergerfs/pool/Torrents/Movies")
    ensure_path(movies, "Movies folder")

    tv = ask("TV folder path", default="/srv/mergerfs/pool/Torrents/TV")
    ensure_path(tv, "TV folder")

    downloads = ask("Downloads folder path", default="/srv/mergerfs/pool/Torrents/Downloads")
    ensure_path(downloads, "Downloads folder")

    return movies, tv, downloads


def step_extra_sources():
    section("Step 2b -- Extra Media Sources (optional)")
    print("Do you have extra media folders? (portable drives, NAS, etc.)")
    extras = []
    for i in range(1, 6):
        if not ask_yes_no("Add extra media folder?", default="n"):
            break
        path = ask("  Folder path")
        label = ask("  Label (e.g. Portable Drive)", default="Extra Source {}".format(i))
        if path:
            extras.append((label, path))
    return extras


def step_vpn():
    section("Step 3 -- VPN")
    print("Route downloads through a VPN? (strongly recommended)")
    print("")
    print("  [1] Yes -- I have VPN credentials")
    print("  [2] No  -- I handle VPN at the router level")
    print("  [3] No  -- No VPN (not recommended)")
    choice = ask_choice("Choice", ["1", "2", "3"], default="1")

    vpn_config = {"enabled": False, "provider": "", "private_key": "", "country": ""}

    if choice == "1":
        vpn_config["enabled"] = True
        vpn_config["provider"] = ask("VPN provider (e.g. nordvpn, mullvad)", default="nordvpn")
        vpn_config["private_key"] = ask("WireGuard private key", secret=True)
        vpn_config["country"] = ask("Server country", default="Malaysia")
    elif choice == "3":
        print("")
        print("  WARNING: Downloading without a VPN exposes your IP address")
        print("  to torrent peers and your ISP. This may be illegal in your country.")
        if not ask_yes_no("  Are you sure you want to continue without a VPN?", default="n"):
            return step_vpn()

    return vpn_config


def step_ai_model():
    section("Step 4 -- AI Model")
    print("Which AI model would you like to use?")
    print("")
    print("  [1] DeepSeek API (recommended -- fast, low cost)")
    print("  [2] Local Ollama (privacy-first, runs on your hardware)")
    print("  [3] Custom OpenAI-compatible endpoint")
    choice = ask_choice("Choice", ["1", "2", "3"], default="1")

    if choice == "1":
        api_key = ask("DeepSeek API key (get free at platform.deepseek.com)", secret=True)
        return {
            "endpoint": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": api_key,
        }
    elif choice == "2":
        endpoint = ask("Ollama endpoint", default="http://localhost:11434")
        model = ask("Model name", default="llama3.1")
        return {"endpoint": endpoint, "model": model, "api_key": ""}
    else:
        endpoint = ask("Endpoint URL")
        model = ask("Model name")
        api_key = ask("API key (press Enter if none)", default="")
        return {"endpoint": endpoint, "model": model, "api_key": api_key}


def step_metadata():
    section("Step 5 -- Metadata Provider")
    print("Which metadata provider for movie and TV information?")
    print("")
    print("  [1] TMDB - The Movie Database (most comprehensive)")
    print("      Note: review TMDB terms at themoviedb.org/documentation/api")
    print("  [2] OMDb - Open Movie Database (1000 free requests/day)")
    print("  [3] TVmaze (TV shows only, no key needed)")
    choice = ask_choice("Choice", ["1", "2", "3"], default="1")

    providers = {"1": "tmdb", "2": "omdb", "3": "tvmaze"}
    provider = providers[choice]
    api_key = ""
    if choice in ("1", "2"):
        api_key = ask("{} API key".format(provider.upper()), secret=True)
    return {"provider": provider, "api_key": api_key}


def step_telegram():
    section("Step 6 -- Telegram Bot (optional)")
    print("Connect a Telegram bot to control HookReel from your phone.")
    if not ask_yes_no("Set up Telegram bot?", default="y"):
        return {"token": "", "user_id": ""}

    print("")
    print("  To create a bot:")
    print("  1. Open Telegram and search for @BotFather")
    print("  2. Send /newbot and follow the steps")
    print("  3. BotFather will give you a token")
    print("")
    token = ask("Bot token", secret=True)
    print("")
    print("  To find your Telegram user ID:")
    print("  Search @userinfobot in Telegram and send any message.")
    user_id = ask("Your Telegram user ID")
    return {"token": token, "user_id": user_id}


def step_jellyfin():
    section("Step 7 -- Jellyfin (optional but recommended)")
    print("Jellyfin is the recommended media server for HookReel.")
    include = ask_yes_no("Include Jellyfin in your Docker stack?", default="y")
    if include:
        print("")
        print("  After first run, complete Jellyfin setup at http://[your-ip]:8096")
        print("  then add your Jellyfin API key in HookReel Settings.")
    return include


def step_password():
    section("Step 8 -- Web UI Password")
    print("Choose a password for the HookReel web interface.")
    while True:
        pw = ask("Password (min 8 characters)", secret=True)
        if len(pw) < 8:
            print("  Password must be at least 8 characters.")
            continue
        pw2 = ask("Confirm password", secret=True)
        if pw != pw2:
            print("  Passwords do not match. Try again.")
            continue
        return pw


def step_rtmp():
    section("Step 9 -- Telegram Cinema / RTMP Streaming (optional)")
    print("Stream movies directly to a private Telegram group.")
    if not ask_yes_no("Set up Telegram Cinema?", default="n"):
        return {"url": "", "key": "", "link": ""}

    print("")
    print("  To set up your cinema group:")
    print("  1. Create a private Telegram group")
    print("  2. Add your HookReel bot as admin")
    print("  3. Tap the group name -> More -> Start Live Stream")
    print("     -> Stream with third-party app")
    print("  4. Copy the Server URL and Stream Key shown")
    print("")
    url = ask("RTMP Server URL")
    key = ask("Stream Key", secret=True)
    link = ask("Cinema group link (t.me/...)", default="")
    print("")
    print("  IMPORTANT: Each time you stream, tap Start Streaming in")
    print("  your cinema group first. Your agent will remind you.")
    return {"url": url, "key": key, "link": link}


def step_library_import():
    section("Step 10 -- Existing Library (optional)")
    print("Do you have existing movies or TV shows to import?")
    if ask_yes_no("Import existing library after setup?", default="y"):
        print("")
        print("  After setup, run:")
        print("  docker exec hookreel python import_library.py --enrich")
        return True
    return False

# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------

def generate_env(cfg, project_dir):
    """Write config/.env from wizard answers."""
    import secrets as _secrets
    secret_key = _secrets.token_hex(32)

    lines = [
        "# =============================================================",
        "# HookReel Environment Configuration",
        "# NEVER commit this file to git!",
        "# =============================================================",
        "",
        "# --- qBittorrent ---",
        "QBITTORRENT_HOST={}".format("gluetun" if cfg["vpn"]["enabled"] else "qbittorrent"),
        "QBITTORRENT_PORT=8080",
        "QBITTORRENT_USER=admin",
        "QBITTORRENT_PASS=adminadmin",
        "",
        "# --- Prowlarr ---",
        "PROWLARR_HOST=prowlarr",
        "PROWLARR_PORT=9696",
        "PROWLARR_API_KEY=",
        "",
        "# --- Jellyfin ---",
        "JELLYFIN_HOST={}".format(cfg.get("server_ip", "192.168.1.21")),
        "JELLYFIN_PORT=8096",
        "JELLYFIN_API_KEY=",
        "JELLYFIN_ENABLED={}".format("true" if cfg["jellyfin"] else "false"),
        "",
        "# --- Metadata Provider ---",
        "METADATA_PROVIDER={}".format(cfg["metadata"]["provider"]),
        "METADATA_API_KEY={}".format(cfg["metadata"]["api_key"]),
        "",
        "# --- Telegram ---",
        "TELEGRAM_BOT_TOKEN={}".format(cfg["telegram"]["token"]),
        "TELEGRAM_ALLOWED_USER_ID={}".format(cfg["telegram"]["user_id"]),
        "",
        "# --- AI Model ---",
        "AI_MODEL_ENDPOINT={}".format(cfg["ai"]["endpoint"]),
        "AI_MODEL_NAME={}".format(cfg["ai"]["model"]),
        "AI_API_KEY={}".format(cfg["ai"]["api_key"]),
        "AI_MAX_TOKENS=1000",
        "AI_TEMPERATURE=0.7",
        "AI_MAX_TOOL_ROUNDS=10",
        "",
        "# --- Media Paths ---",
        "MEDIA_BASE_PATH=/data",
        "MOVIES_PATH=/data/Movies",
        "TV_PATH=/data/TV",
        "DOWNLOADS_PATH=/data/Downloads",
        "",
        "# --- Extra Media Sources ---",
    ]

    for i, (label, path) in enumerate(cfg["extras"], start=1):
        lines.append("EXTRA_MEDIA_{}=/data/extra/{}".format(i, i))
        lines.append("EXTRA_MEDIA_{}_LABEL={}".format(i, label))
    for i in range(len(cfg["extras"]) + 1, 6):
        lines.append("EXTRA_MEDIA_{}=".format(i))
        lines.append("EXTRA_MEDIA_{}_LABEL=Extra Source {}".format(i, i))

    lines += [
        "",
        "# --- Storage ---",
        "QUARANTINE_PATH=/quarantine",
        "LOGS_PATH=/logs",
        "DB_PATH=/db/hookreel.db",
        "",
        "# --- ClamAV ---",
        "CLAMAV_HOST=hookreel-clamav",
        "CLAMAV_PORT=3310",
        "",
        "# --- Web UI ---",
        "WEBUI_PASSWORD={}".format(cfg["password"]),
        "SECRET_KEY={}".format(secret_key),
        "",
        "# --- Watch Mode ---",
        "JELLYFIN_ENABLED={}".format("true" if cfg["jellyfin"] else "false"),
        "HLS_STREAM_DIR=/tmp/hls",
        "HLS_SEGMENT_DURATION=10",
        "STREAM_PORT=8765",
        "",
        "# --- RTMP Streaming ---",
        "TELEGRAM_RTMP_URL={}".format(cfg["rtmp"]["url"]),
        "TELEGRAM_RTMP_KEY={}".format(cfg["rtmp"]["key"]),
        "TELEGRAM_CINEMA_LINK={}".format(cfg["rtmp"]["link"]),
        "RTMP_VIDEO_BITRATE=2500k",
        "RTMP_SCALE=1280:-2",
        "",
        "# --- File Management ---",
        "DELETE_ENABLED=false",
        "",
        "# --- Download Preferences ---",
        "PREFERRED_RESOLUTION=1080p",
        "MAX_FILE_SIZE_GB=0",
        "PREFERRED_CODEC=any",
        "QBITTORRENT_CATEGORY=hookreel-movies",
        "AUTO_DOWNLOAD_NEW_EPISODES=false",
        "",
        "# --- Security ---",
        "SESSION_EXPIRY_HOURS=24",
        "RATE_LIMIT_ENABLED=true",
        "",
        "# --- Logging ---",
        "LOG_LEVEL=INFO",
        "TZ=UTC",
        "",
        "# --- Agent ---",
        "AGENT_NAME={}".format(cfg["agent_name"]),
    ]

    config_dir = os.path.join(project_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    env_path = os.path.join(config_dir, ".env")

    if os.path.exists(env_path):
        shutil.copy2(env_path, env_path + ".bak")
        print("  Backed up existing .env to .env.bak")

    with open(env_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    print("  Written: {}".format(env_path))
    return env_path


def generate_compose(cfg, project_dir):
    """Write docker-compose.yml from wizard answers."""
    movies_path = cfg["movies"]
    tv_path = cfg["tv"]
    downloads_path = cfg["downloads"]

    # Extra volume mounts
    extra_volumes = ""
    for i, (label, path) in enumerate(cfg["extras"], start=1):
        extra_volumes += "      - {}:/data/extra/{}:ro\n".format(path, i)

    # qBittorrent service block
    if cfg["vpn"]["enabled"]:
        qbt_network = "      network_mode: service:gluetun"
        qbt_depends = "      - gluetun"
        qbt_ports = ""
    else:
        qbt_network = """\
      networks:
        - hookreel_net
        - vpn_net"""
        qbt_depends = ""
        qbt_ports = """\
      ports:
        - "8080:8080\""""

    # Gluetun service block
    if cfg["vpn"]["enabled"]:
        gluetun_block = """\
  gluetun:
    image: qmcgaw/gluetun:latest
    container_name: gluetun
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
    networks:
      - hookreel_net
      - vpn_net
    environment:
      - VPN_SERVICE_PROVIDER={provider}
      - VPN_TYPE=wireguard
      - WIREGUARD_PRIVATE_KEY={key}
      - SERVER_COUNTRIES={country}
    ports:
      - "8080:8080"
""".format(
            provider=cfg["vpn"]["provider"],
            key=cfg["vpn"]["private_key"],
            country=cfg["vpn"]["country"],
        )
    else:
        gluetun_block = "  # VPN disabled -- direct connection\n  # Enable VPN_ENABLED in setup to add Gluetun\n"

    # Jellyfin service block
    if cfg["jellyfin"]:
        jellyfin_block = """\
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    restart: unless-stopped
    networks:
      - hookreel_net
    ports:
      - "8096:8096"
    volumes:
      - jellyfin_config:/config
      - jellyfin_cache:/cache
      - {movies}:/data/Movies:ro
      - {tv}:/data/TV:ro
""".format(movies=movies_path, tv=tv_path)
        jellyfin_volume = """\
  jellyfin_config:
  jellyfin_cache:"""
    else:
        jellyfin_block = "  # Jellyfin disabled -- using HLS fallback\n"
        jellyfin_volume = ""

    compose = """\
# =============================================================
# HookReel -- Docker Compose
# Generated by setup.py
# =============================================================
services:
  clamav:
    image: clamav/clamav:latest
    container_name: hookreel-clamav
    restart: unless-stopped
    networks:
      - hookreel_net
    volumes:
      - clamav_data:/var/lib/clamav
    environment:
      - CLAMAV_NO_FRESHCLAM=false

{gluetun}
  hookreel:
    image: hookreel/hookreel:latest
    # build: .   # uncomment to build locally
    container_name: hookreel
    restart: unless-stopped
    depends_on:
      - clamav
    env_file:
      - config/.env
    environment:
      - PUID=1000
      - PGID=100
      - TZ=UTC
    ports:
      - "8765:8765"
    dns:
      - 8.8.8.8
      - 8.8.4.4
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./config:/config:rw
      - ./logs:/logs
      - ./data:/db
      - ./quarantine:/quarantine
      - {movies}:/data/Movies
      - {tv}:/data/TV
      - {downloads}:/data/Downloads
{extra_vols}    #security_opt:
    #  - no-new-privileges:true
    networks:
      - hookreel_net
      - vpn_net

{jellyfin}
# =============================================================
# Networks
# =============================================================
networks:
  hookreel_net:
    driver: bridge
  vpn_net:
    name: qbittorentvpnsuite_vpn_net
    external: true

# =============================================================
# Volumes
# =============================================================
volumes:
  clamav_data:
{jellyfin_vol}
""".format(
        gluetun=gluetun_block,
        movies=movies_path,
        tv=tv_path,
        downloads=downloads_path,
        extra_vols=extra_volumes,
        jellyfin=jellyfin_block,
        jellyfin_vol=jellyfin_volume,
    )

    compose_path = os.path.join(project_dir, "docker-compose.yml")
    if os.path.exists(compose_path):
        shutil.copy2(compose_path, compose_path + ".bak")
        print("  Backed up existing docker-compose.yml")

    with open(compose_path, "w") as fh:
        fh.write(compose)

    print("  Written: {}".format(compose_path))
    return compose_path


def print_summary(cfg):
    """Print a summary of all choices before generating files."""
    banner("HookReel Setup Summary")
    print("Agent name:    {}".format(cfg["agent_name"]))
    print("Movies:        {}".format(cfg["movies"]))
    print("TV:            {}".format(cfg["tv"]))
    print("Downloads:     {}".format(cfg["downloads"]))
    if cfg["extras"]:
        for label, path in cfg["extras"]:
            print("Extra source:  {} ({})".format(label, path))
    print("VPN:           {}".format(
        cfg["vpn"]["provider"] if cfg["vpn"]["enabled"] else "Disabled"
    ))
    print("AI model:      {}".format(cfg["ai"]["endpoint"]))
    print("Metadata:      {}".format(cfg["metadata"]["provider"].upper()))
    print("Telegram:      {}".format(
        "Configured" if cfg["telegram"]["token"] else "Skipped"
    ))
    print("Jellyfin:      {}".format("Included" if cfg["jellyfin"] else "Skipped"))
    print("Web UI:        Password set")
    print("RTMP Cinema:   {}".format(
        "Configured" if cfg["rtmp"]["url"] else "Skipped"
    ))


def print_checklist(cfg, project_dir):
    """Print the post-setup next steps."""
    banner("Setup complete! Next steps:")
    print("1. Start HookReel:")
    print("   cd {}".format(project_dir))
    print("   docker compose up -d")
    print("")
    print("2. Wait 2-3 minutes for ClamAV to load virus definitions.")
    print("")
    print("3. Open the web UI:")
    print("   http://[your-server-ip]:8765")
    print("")
    if cfg["jellyfin"]:
        print("4. Complete Jellyfin setup:")
        print("   http://[your-server-ip]:8096")
        print("   Then add your Jellyfin API key in HookReel Settings.")
        print("")
    if cfg["library_import"]:
        print("5. Import your existing library:")
        print("   docker exec hookreel python import_library.py --enrich")
        print("")
    if cfg["rtmp"]["url"]:
        print("6. To stream a movie:")
        print("   - Tap Start Streaming in your Telegram cinema group first")
        print("   - Then ask your agent to stream the movie")
        print("")
    if cfg["telegram"]["token"]:
        print("7. Send /start to your Telegram bot to begin.")
        print("")
    print("Enjoy HookReel v1.0 Hook!")
    banner("")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    banner("HookReel v1.0 Hook\nYour AI-powered media automation agent")
    print("Welcome, Captain! Let's get you set up.")
    print("This will only take a few minutes.")

    # Determine project directory
    project_dir = os.path.dirname(os.path.abspath(__file__))

    # Detect server IP
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        server_ip = s.getsockname()[0]
        s.close()
    except Exception:
        server_ip = "192.168.1.21"

    # Run wizard steps
    agent_name    = step_agent_name()
    movies, tv, downloads = step_media_folders()
    extras        = step_extra_sources()
    vpn           = step_vpn()
    ai            = step_ai_model()
    metadata      = step_metadata()
    telegram      = step_telegram()
    jellyfin      = step_jellyfin()
    password      = step_password()
    rtmp          = step_rtmp()
    library_import = step_library_import()

    # Collect all config
    cfg = {
        "agent_name":     agent_name,
        "movies":         movies,
        "tv":             tv,
        "downloads":      downloads,
        "extras":         extras,
        "vpn":            vpn,
        "ai":             ai,
        "metadata":       metadata,
        "telegram":       telegram,
        "jellyfin":       jellyfin,
        "password":       password,
        "rtmp":           rtmp,
        "library_import": library_import,
        "server_ip":      server_ip,
    }

    # Show summary and confirm
    print_summary(cfg)
    print("")
    if not ask_yes_no("Ready to generate your configuration?", default="y"):
        print("Setup cancelled. No files were written.")
        sys.exit(0)

    # Generate files
    print("")
    print("Generating configuration files...")
    generate_env(cfg, project_dir)
    generate_compose(cfg, project_dir)

    # Update persona.json if agent name changed
    persona_path = os.path.join(project_dir, "app", "persona.json")
    if os.path.exists(persona_path):
        try:
            import json
            with open(persona_path, "r") as fh:
                persona = json.load(fh)
            persona["name"] = agent_name
            with open(persona_path, "w") as fh:
                json.dump(persona, fh, indent=4)
            print("  Updated: app/persona.json")
        except Exception as exc:
            print("  Could not update persona.json: {}".format(exc))

    print_checklist(cfg, project_dir)


if __name__ == "__main__":
    main()

