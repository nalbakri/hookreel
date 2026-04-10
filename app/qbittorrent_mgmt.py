"""
qbittorrent_mgmt.py — qBittorrent management functions for HookReel web UI.

Provides full torrent and client management: preferences, speed limits,
torrent list, pause/resume/delete, categories, and transfer stats.

All functions use the qbittorrentapi library with credentials from
app.config. Used by the /downloader web UI page.
"""

import qbittorrentapi
import app.config as config
from app.logger import get_logger

logger = get_logger(__name__)


def _get_client() -> qbittorrentapi.Client:
    """
    Create and return an authenticated qBittorrent API client.

    Returns:
        An authenticated qbittorrentapi.Client instance.
    """
    client = qbittorrentapi.Client(
        host=config.QBITTORRENT_HOST,
        port=int(config.QBITTORRENT_PORT),
        username=config.QBITTORRENT_USER,
        password=config.QBITTORRENT_PASS,
        REQUESTS_ARGS={"timeout": 15},
        VERIFY_WEBUI_CERTIFICATE=False,
    )
    client.auth_log_in()
    return client


def get_preferences() -> dict:
    """
    Fetch the full qBittorrent application preferences.

    Returns:
        A dict of all qBittorrent preferences, or empty dict on error.
    """
    try:
        client = _get_client()
        prefs = client.app_preferences()
        client.auth_log_out()
        return dict(prefs)
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt get_preferences error: %s", exc)
        return {}


def set_preferences(prefs: dict) -> bool:
    """
    Update qBittorrent application preferences.

    Only the keys provided in prefs are updated — all other settings
    are left unchanged.

    Parameters:
        prefs: A partial or full dict of preference key/value pairs.

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.app_set_preferences(prefs)
        client.auth_log_out()
        logger.info("[HookReel] qbittorrent_mgmt: preferences updated")
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt set_preferences error: %s", exc)
        return False


def get_transfer_info() -> dict:
    """
    Fetch global transfer statistics from qBittorrent.

    Returns a dict containing download speed, upload speed, DHT nodes,
    and free disk space.

    Returns:
        A dict of transfer info, or empty dict on error.
    """
    try:
        client = _get_client()
        info = client.transfer_info()
        client.auth_log_out()
        return dict(info)
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt get_transfer_info error: %s", exc)
        return {}


def get_all_torrents(torrent_filter: str = "all", category: str = None) -> list:
    """
    Fetch torrents from qBittorrent with optional filtering.

    Parameters:
        torrent_filter: One of: all, downloading, seeding, paused,
                        active, inactive. Default is 'all'.
        category:       Optional category name to filter by.

    Returns:
        A list of torrent info dicts, or empty list on error.
    """
    try:
        client = _get_client()
        kwargs = {"status_filter": torrent_filter}
        if category:
            kwargs["category"] = category
        torrents = client.torrents_info(**kwargs)
        client.auth_log_out()
        return [dict(t) for t in torrents]
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt get_all_torrents error: %s", exc)
        return []


def pause_torrent(torrent_hash: str) -> bool:
    """
    Pause a torrent by its hash.

    Parameters:
        torrent_hash: The torrent's info hash string.

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.torrents_pause(torrent_hashes=torrent_hash)
        client.auth_log_out()
        logger.info("[HookReel] qbittorrent_mgmt: paused torrent %s", torrent_hash[:8])
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt pause_torrent error: %s", exc)
        return False


def resume_torrent(torrent_hash: str) -> bool:
    """
    Resume a paused torrent by its hash.

    Parameters:
        torrent_hash: The torrent's info hash string.

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.torrents_resume(torrent_hashes=torrent_hash)
        client.auth_log_out()
        logger.info("[HookReel] qbittorrent_mgmt: resumed torrent %s", torrent_hash[:8])
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt resume_torrent error: %s", exc)
        return False


def delete_torrent(torrent_hash: str, delete_files: bool = False) -> bool:
    """
    Delete a torrent, optionally also deleting its downloaded files.

    Parameters:
        torrent_hash: The torrent's info hash string.
        delete_files: If True, also delete files from disk.
                      Default is False (removes torrent only).

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.torrents_delete(
            delete_files=delete_files,
            torrent_hashes=torrent_hash,
        )
        client.auth_log_out()
        logger.info(
            "[HookReel] qbittorrent_mgmt: deleted torrent %s (files=%s)",
            torrent_hash[:8], delete_files
        )
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt delete_torrent error: %s", exc)
        return False


def get_categories() -> dict:
    """
    Fetch all torrent categories defined in qBittorrent.

    Returns:
        A dict of category name → category info dicts.
        Returns empty dict on error.
    """
    try:
        client = _get_client()
        categories = client.torrents_categories()
        client.auth_log_out()
        return dict(categories)
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt get_categories error: %s", exc)
        return {}


def add_category(name: str, save_path: str) -> bool:
    """
    Add a new torrent category in qBittorrent.

    Parameters:
        name:      The category name (e.g. 'hookreel-movies').
        save_path: The save path for torrents in this category.

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.torrents_create_category(name=name, save_path=save_path)
        client.auth_log_out()
        logger.info("[HookReel] qbittorrent_mgmt: added category '%s'", name)
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt add_category error: %s", exc)
        return False


def edit_category(name: str, save_path: str) -> bool:
    """
    Edit the save path of an existing torrent category.

    Parameters:
        name:      The category name to update.
        save_path: The new save path.

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.torrents_edit_category(name=name, save_path=save_path)
        client.auth_log_out()
        logger.info("[HookReel] qbittorrent_mgmt: edited category '%s'", name)
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt edit_category error: %s", exc)
        return False


def remove_category(name: str) -> bool:
    """
    Remove a torrent category from qBittorrent.

    Parameters:
        name: The category name to remove.

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.torrents_remove_categories(categories=name)
        client.auth_log_out()
        logger.info("[HookReel] qbittorrent_mgmt: removed category '%s'", name)
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt remove_category error: %s", exc)
        return False


def set_speed_limits(dl_limit: int, ul_limit: int) -> bool:
    """
    Set global download and upload speed limits in qBittorrent.

    Parameters:
        dl_limit: Download limit in bytes per second. 0 = unlimited.
        ul_limit: Upload limit in bytes per second. 0 = unlimited.

    Returns:
        True if successful, False on error.
    """
    try:
        client = _get_client()
        client.transfer_set_download_limit(limit=dl_limit)
        client.transfer_set_upload_limit(limit=ul_limit)
        client.auth_log_out()
        logger.info(
            "[HookReel] qbittorrent_mgmt: speed limits set dl=%d ul=%d",
            dl_limit, ul_limit
        )
        return True
    except Exception as exc:
        logger.error("[HookReel] qbittorrent_mgmt set_speed_limits error: %s", exc)
        return False
