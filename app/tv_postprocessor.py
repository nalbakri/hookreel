"""
HookReel TV post-processor.
Handles ClamAV scanning, renaming, and moving completed TV episode downloads.
Mirrors postprocessor.py but uses Jellyfin-compatible TV naming conventions.
"""
import os
import shutil
import app.database as database
from app.logger import get_logger
from app import config

logger = get_logger(__name__)


def check_completed_tv_downloads() -> list:
    """
    Check qBittorrent for completed TV episode downloads.
    Looks up all episodes with status=downloading and checks
    whether the file now exists on disk.
    Returns:
        List of episode dicts that are complete and ready to process.
    """
    downloading = database.get_episodes_by_status("downloading")
    completed = []
    for episode in downloading:
        file_path = episode.get("file_path") or ""
        if file_path and os.path.exists(file_path):
            completed.append(episode)
            logger.info(
                "[HookReel] TV download complete: episode_id=%d path=%s",
                episode["id"], file_path
            )
    logger.info(
        "[HookReel] check_completed_tv_downloads: %d ready to process",
        len(completed)
    )
    return completed


def rename_episode(
    file_path: str,
    show_title: str,
    show_year: str,
    season: int,
    episode: int,
    episode_title: str
) -> str:
    """
    Rename and move a downloaded episode file to the correct TV folder.
    Creates the show and season folders if they do not exist.
    Target format:
        {TV_PATH}/{Show Title} ({Year})/Season {NN}/
            {Show Title} ({Year}) - S{NN}E{NN} - {Episode Title}.mkv
    Parameters:
        file_path:     Current path of the downloaded file.
        show_title:    Title of the show.
        show_year:     Premiere year as string.
        season:        Season number.
        episode:       Episode number.
        episode_title: Title of the episode.
    Returns:
        New file path after move, or original path on error.
    """
    try:
        tv_path = config.TV_PATH
        year_suffix = f" ({show_year})" if show_year else ""
        show_folder_name = f"{show_title}{year_suffix}"
        season_folder_name = f"Season {season:02d}"
        episode_code = f"S{season:02d}E{episode:02d}"
        safe_episode_title = episode_title or "Unknown"
        filename = (
            f"{show_folder_name} - {episode_code} - {safe_episode_title}.mkv"
        )
        target_dir = os.path.join(tv_path, show_folder_name, season_folder_name)
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)
        shutil.move(file_path, target_path)
        logger.info(
            "[HookReel] Renamed episode: %s → %s", file_path, target_path
        )
        return target_path
    except Exception as error:
        logger.error("[HookReel] rename_episode error: %s", error)
        return file_path


def _scan_episode(file_path: str) -> bool:
    """
    Scan a file with ClamAV via pyclamd.
    Parameters:
        file_path: Path to the file to scan.
    Returns:
        True if clean, False if infected or scan failed.
    """
    try:
        import pyclamd
        clamd_host = getattr(config, "CLAMAV_HOST", "hookreel-clamav")
        clamd_port = int(getattr(config, "CLAMAV_PORT", 3310))
        scanner = pyclamd.ClamdNetworkSocket(
            host=clamd_host, port=clamd_port
        )
        result = scanner.scan_file(file_path)
        if result is None:
            logger.info("[HookReel] ClamAV scan clean: %s", file_path)
            return True
        logger.warning(
            "[HookReel] ClamAV detected threat in %s: %s", file_path, result
        )
        return False
    except Exception as error:
        logger.error("[HookReel] ClamAV scan error: %s", error)
        return False


def _notify_jellyfin_tv(show_title: str) -> None:
    """
    Send a best-effort library refresh notification to Jellyfin.
    Failures are logged but never raise — Jellyfin may not be running.
    Parameters:
        show_title: Show title for log context.
    """
    try:
        import httpx
        jellyfin_url = getattr(config, "JELLYFIN_URL", "")
        jellyfin_key = getattr(config, "JELLYFIN_API_KEY", "")
        if not jellyfin_url or not jellyfin_key or jellyfin_key == "changeme":
            return
        httpx.post(
            f"{jellyfin_url}/Library/Refresh",
            headers={"X-Emby-Token": jellyfin_key},
            timeout=5
        )
        logger.info(
            "[HookReel] Jellyfin TV library refresh triggered for %s",
            show_title
        )
    except Exception as error:
        logger.warning(
            "[HookReel] Jellyfin TV notify failed (non-fatal): %s", error
        )


def process_episode(episode: dict, show: dict) -> bool:
    """
    Full post-processing pipeline for one completed TV episode.
    Steps:
        1. ClamAV scan — quarantine if infected.
        2. Rename to Jellyfin format and move to TV folder.
        3. Update episode status to complete.
        4. Notify Jellyfin (best-effort).
    Parameters:
        episode: Episode dict from database.
        show:    Show dict from database.
    Returns:
        True if processing completed successfully, False otherwise.
    """
    episode_id = episode["id"]
    file_path = episode.get("file_path", "")
    show_title = show.get("title", "Unknown")
    show_year = show.get("year", "")
    season = episode.get("season")
    ep_num = episode.get("episode")
    ep_title = episode.get("title", "Unknown")

    if not file_path or not os.path.exists(file_path):
        logger.warning(
            "[HookReel] process_episode: file not found for episode_id=%d path=%s",
            episode_id, file_path
        )
        database.update_episode_status(episode_id, "failed")
        return False

    # Step 1: ClamAV scan
    is_clean = _scan_episode(file_path)
    if not is_clean:
        database.update_episode_status(episode_id, "quarantined")
        logger.warning(
            "[HookReel] Episode quarantined: episode_id=%d", episode_id
        )
        return False

    database.update_episode_status(episode_id, "renamed")

    # Step 2: Rename and move
    new_path = rename_episode(
        file_path, show_title, show_year, season, ep_num, ep_title
    )
    database.update_episode_status(
        episode_id, "complete", file_path=new_path
    )

    # Step 3: Notify Jellyfin
    _notify_jellyfin_tv(show_title)

    logger.info(
        "[HookReel] Episode processing complete: episode_id=%d path=%s",
        episode_id, new_path
    )
    return True
