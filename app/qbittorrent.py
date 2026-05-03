"""
HookReel qBittorrent integration.
Handles adding torrents, checking status, and hash lookup by name.
"""

import re
import requests
from app import config
from app.logger import get_logger

logger = get_logger(__name__)

QB_BASE = f"http://{config.QBITTORRENT_HOST}:{config.QBITTORRENT_PORT}"
SESSION = requests.Session()
_logged_in = False


def _login():
    """
    Log in to the qBittorrent WebUI and store the session cookie.
    Handles the RecursionError that can occur on the first connection attempt.
    """
    global _logged_in
    try:
        response = SESSION.post(
            f"{QB_BASE}/api/v2/auth/login",
            data={
                "username": config.QBITTORRENT_USER,
                "password": config.QBITTORRENT_PASS,
            },
            timeout=10,
        )
        if response.text.strip() == "Ok.":
            _logged_in = True
            logger.debug("[HookReel] qBittorrent login successful")
        else:
            logger.warning("[HookReel] qBittorrent login unexpected response: %s", response.text)
    except RecursionError:
        logger.warning("[HookReel] qBittorrent RecursionError on login -- will retry next cycle")
        _logged_in = False
    except Exception as error:
        logger.error("[HookReel] qBittorrent login error: %s", error)
        _logged_in = False


def _ensure_logged_in():
    """Log in if not already authenticated."""
    if not _logged_in:
        _login()


def extract_hash_from_magnet(url: str):
    """
    Extract the torrent hash from a magnet URL.
    Magnet links contain xt=urn:btih:HASH which is the canonical hash.
    Returns the hash as a lowercase string, or None if not a magnet URL
    or hash cannot be parsed.
    """
    if not url or not url.startswith("magnet:"):
        return None
    match = re.search(r"xt=urn:btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})", url)
    if match:
        raw = match.group(1)
        # If it looks like base32 (32 chars), convert to hex
        if len(raw) == 32:
            try:
                import base64
                hex_hash = base64.b32decode(raw.upper()).hex()
                return hex_hash.lower()
            except Exception:
                return raw.lower()
        return raw.lower()
    return None


def _resolve_to_magnet(url: str) -> str:
    """
    If url is a Prowlarr HTTP redirect that resolves to a magnet link,
    follow the redirect and return the magnet. Otherwise return url unchanged.
    """
    if url.startswith("magnet:"):
        return url
    try:
        resp = requests.get(url, allow_redirects=False, timeout=5)
        location = resp.headers.get("location", "")
        if location.startswith("magnet:"):
            logger.info("[HookReel] Resolved Prowlarr URL to magnet link")
            return location
    except Exception as error:
        logger.warning("[HookReel] Could not resolve URL to magnet: %s", error)
    return url


def add_torrent(magnet_url: str, save_path: str = None):
    """
    Add a torrent to qBittorrent via magnet link or download URL.
    Returns the torrent hash string if successful, None on failure.
    For magnet URLs the hash is extracted directly from the URL.
    For direct download URLs a short retry lookup is used as fallback.
    """
    _ensure_logged_in()
    if not save_path:
        save_path = config.DOWNLOADS_PATH
    magnet_url = _resolve_to_magnet(magnet_url)

    try:
        response = SESSION.post(
            f"{QB_BASE}/api/v2/torrents/add",
            data={"urls": magnet_url, "savepath": save_path},
            timeout=15,
        )
        if response.text.strip() != "Ok.":
            logger.warning("[HookReel] qBittorrent add response: %s", response.text)
            return None
    except Exception as error:
        logger.error("[HookReel] qBittorrent add_torrent error: %s", error)
        return None

    # Try to extract hash directly from magnet URL first
    torrent_hash = extract_hash_from_magnet(magnet_url)
    if torrent_hash:
        logger.info("[HookReel] Torrent added, hash from magnet: %s", torrent_hash)
        return torrent_hash

    # Direct .torrent URL -- hash cannot be extracted from URL.
    # Return None and let the caller do a name-based lookup with the release title.
    logger.info("[HookReel] Torrent added (direct URL), hash lookup deferred to caller")
    return None


def get_torrent_list() -> list:
    """
    Return the full list of torrents from qBittorrent.
    Each item is a dict with keys including name, hash, progress, state.
    Returns empty list on error.
    """
    _ensure_logged_in()
    try:
        response = SESSION.get(
            f"{QB_BASE}/api/v2/torrents/info",
            timeout=10,
        )
        return response.json()
    except Exception as error:
        logger.error("[HookReel] qBittorrent get_torrent_list error: %s", error)
        return []


def get_torrent_status(torrent_hash: str) -> dict:
    """
    Return status info for a specific torrent by hash.
    Returns a dict with progress, state, name, save_path, content_path.
    Returns None if not found.
    """
    torrent_hash = torrent_hash.lower().strip()
    _ensure_logged_in()
    try:
        response = SESSION.get(
            f"{QB_BASE}/api/v2/torrents/info",
            params={"hashes": torrent_hash},
            timeout=10,
        )
        torrents = response.json()
        if torrents:
            return torrents[0]
        return None
    except Exception as error:
        logger.error("[HookReel] qBittorrent get_torrent_status error: %s", error)
        return None


def get_torrent_hash_by_name(torrent_name: str) -> str:
    """
    Search the qBittorrent torrent list for a torrent whose name closely
    matches torrent_name. Uses fuzzy substring matching because Prowlarr
    release titles often differ slightly from what qBittorrent displays.
    Returns the hash string if a match is found, or None if not found.
    """
    _ensure_logged_in()

    all_torrents = get_torrent_list()
    if not all_torrents:
        logger.warning("[HookReel] Hash lookup: torrent list empty or unavailable")
        return None

    search_term = torrent_name.lower().strip()

    # Strategy 1: exact name match
    for torrent in all_torrents:
        if torrent.get("name", "").lower().strip() == search_term:
            found_hash = (torrent.get("hash") or "").lower().strip()
            logger.info(
                "[HookReel] Hash lookup: exact match for '%s' -> %s",
                torrent_name, found_hash
            )
            return found_hash

    # Strategy 2: substring match
    for torrent in all_torrents:
        torrent_name_lower = torrent.get("name", "").lower().strip()
        if search_term in torrent_name_lower or torrent_name_lower in search_term:
            found_hash = (torrent.get("hash") or "").lower().strip()
            logger.info(
                "[HookReel] Hash lookup: substring match '%s' ~ '%s' -> %s",
                torrent_name, torrent.get("name"), found_hash
            )
            return found_hash

    # Strategy 3: word overlap
    search_words = set(search_term.split())
    best_score = 0
    best_torrent = None

    for torrent in all_torrents:
        torrent_words = set(torrent.get("name", "").lower().split())
        overlap = len(search_words & torrent_words)
        if overlap > best_score:
            best_score = overlap
            best_torrent = torrent

    if best_torrent and best_score >= 3:
        found_hash = (best_torrent.get("hash") or "").lower().strip()
        logger.info(
            "[HookReel] Hash lookup: word-overlap match (%d words) '%s' ~ '%s' -> %s",
            best_score, torrent_name, best_torrent.get("name"), found_hash
        )
        return found_hash

    logger.warning(
        "[HookReel] Hash lookup: no match found for '%s' among %d torrents",
        torrent_name, len(all_torrents)
    )
    return None
