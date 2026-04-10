"""
HookReel post-processing coordinator.
Handles everything after a download completes:
  ClamAV scan → rename → move → Jellyfin notify → database update.
"""

import os
import shutil
import re
import requests

from app import config, database, qbittorrent
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Completion detection
# ---------------------------------------------------------------------------

def check_completed_downloads() -> list:
    """
    Check all movies with status='downloading' and return those whose
    qBittorrent torrent is fully complete.

    A torrent is considered complete when:
      - progress == 1.0  AND
      - state is one of: uploading, stalledUP, pausedUP, forcedUP

    Returns a list of movie dicts that are ready for post-processing.
    """
    downloading = database.get_movies_by_status("downloading")
    logger.debug("[HookReel] check_completed_downloads: %d in downloading state", len(downloading))

    completed = []

    for movie in downloading:
        torrent_hash = movie.get("torrent_hash")
        if not torrent_hash:
            logger.debug(
                "[HookReel] Movie id=%d has no hash — cannot check status, skipping",
                movie["id"]
            )
            continue

        torrent_info = qbittorrent.get_torrent_status(torrent_hash)
        if not torrent_info:
            logger.debug(
                "[HookReel] Movie id=%d hash=%s not found in qBittorrent",
                movie["id"], torrent_hash
            )
            continue

        progress = torrent_info.get("progress", 0)
        state = torrent_info.get("state", "")
        complete_states = {"uploading", "stalledUP", "pausedUP", "forcedUP"}

        if progress >= 1.0 and state in complete_states:
            movie["_content_path"] = torrent_info.get("content_path", "")
            movie["_save_path"] = torrent_info.get("save_path", "")
            completed.append(movie)
            logger.info(
                "[HookReel] Download complete: '%s' (id=%d) state=%s",
                movie["title"], movie["id"], state
            )

    logger.info(
        "[HookReel] Completion check: %d downloading, %d complete this cycle",
        len(downloading), len(completed)
    )
    return completed


# ---------------------------------------------------------------------------
# Master post-processing function
# ---------------------------------------------------------------------------

def process_movie(movie: dict) -> bool:
    """
    Run the full post-processing sequence for one completed movie.

    Sequence:
      1. Resolve the downloaded file path
      2. ClamAV malware scan
      3. Rename file to Jellyfin-compatible format
      4. Move file to Movies folder
      5. Update database to 'complete'
      6. Notify Jellyfin to refresh library

    Returns True if the full sequence succeeded, False if any step failed.
    Updates database status at each step so failures are recoverable.
    """
    movie_id = movie["id"]
    title = movie["title"]
    year = movie.get("year", "")

    logger.info("[HookReel] post-process start: '%s' (id=%d)", title, movie_id)

    # Step 1 — Resolve file path
    file_path = _resolve_file_path(movie)
    if not file_path:
        logger.error("[HookReel] Could not resolve file path for movie id=%d", movie_id)
        database.update_movie_status(movie_id, "failed")
        return False

    logger.info("[HookReel] Resolved file path: %s", file_path)

    # Step 2 — ClamAV scan
    scan_passed = scan_file(file_path)
    if not scan_passed:
        logger.error("[HookReel] Scan failed for '%s' — post-processing halted", title)
        database.update_movie_status(movie_id, "quarantined")
        return False

    # Step 3 — Rename
    new_path = rename_file(file_path, title, year)
    if not new_path:
        logger.error("[HookReel] Rename failed for '%s'", title)
        database.update_movie_status(movie_id, "failed")
        return False

    database.update_movie_status(movie_id, "renamed")
    logger.info("[HookReel] Renamed: %s → %s", file_path, new_path)

    # Step 4 — Move
    final_path = _build_final_path(title, year, new_path)
    move_success = move_file(new_path, final_path)
    if not move_success:
        logger.error("[HookReel] Move failed for '%s'", title)
        database.update_movie_status(movie_id, "failed")
        return False

    database.update_movie_file_path(movie_id, final_path)
    database.update_movie_status(movie_id, "complete")
    logger.info("[HookReel] Moved to final location: %s", final_path)

    # Step 5 — Jellyfin notify (best-effort, non-blocking)
    notify_jellyfin(library_path=config.MOVIES_PATH)

    logger.info("[HookReel] Post-processing complete for '%s' (id=%d)", title, movie_id)
    return True


# ---------------------------------------------------------------------------
# Individual steps
# ---------------------------------------------------------------------------

def scan_file(file_path: str) -> bool:
    """
    Scan a file using the ClamAV daemon via pyclamd.

    Returns True if the file is clean (or ClamAV is unreachable — best-effort).
    Returns False if the file is infected and moves it to quarantine.

    ClamAV is treated as best-effort: if the daemon is not ready or unreachable,
    the pipeline continues with a warning rather than blocking.
    """
    try:
        import pyclamd
        clamd = pyclamd.ClamdNetworkSocket(
            host=config.CLAMAV_HOST,
            port=config.CLAMAV_PORT,
            timeout=30,
        )

        if not clamd.ping():
            logger.warning(
                "[HookReel] ClamAV daemon not responding at %s:%d — skipping scan (best-effort)",
                config.CLAMAV_HOST, config.CLAMAV_PORT
            )
            return True

        logger.info("[HookReel] Scanning: %s", file_path)
        result = clamd.scan_file(file_path)

        if result is None:
            logger.info("[HookReel] Scan clean: %s", file_path)
            return True

        for scanned_path, scan_result in result.items():
            status, threat_name = scan_result
            if status == "FOUND":
                logger.error(
                    "[HookReel] THREAT DETECTED in '%s': %s — quarantining",
                    file_path, threat_name
                )
                _quarantine_file(file_path)
                return False

        logger.info("[HookReel] Scan clean: %s", file_path)
        return True

    except ImportError:
        logger.warning("[HookReel] pyclamd not installed — skipping scan (best-effort)")
        return True

    except Exception as error:
        logger.warning("[HookReel] ClamAV error (non-fatal, best-effort): %s", error)
        return True


def rename_file(file_path: str, title: str, year: str) -> str:
    """
    Rename a downloaded file to Jellyfin-compatible format:
      Movie Title (Year).ext

    Creates a staging folder inside the Downloads directory.
    Returns the new full file path, or None if the rename fails.

    Example:
      interstellar.2014.1080p.bluray.mkv → Interstellar (2014).mkv
    """
    try:
        ext = os.path.splitext(file_path)[1].lower()
        clean_title = _sanitise_filename(title)
        new_filename = f"{clean_title} ({year}){ext}"

        staging_dir = os.path.join(config.DOWNLOADS_PATH, f"{clean_title} ({year})")
        os.makedirs(staging_dir, exist_ok=True)

        new_path = os.path.join(staging_dir, new_filename)

        os.rename(file_path, new_path)
        logger.info("[HookReel] Renamed '%s' → '%s'", os.path.basename(file_path), new_filename)
        return new_path

    except Exception as error:
        logger.error("[HookReel] rename_file error: %s", error)
        return None


def move_file(src_path: str, dest_path: str) -> bool:
    """
    Move a file from src_path to dest_path.
    Creates destination directory if it does not exist.
    Handles cross-device moves by falling back to copy-then-delete.
    Returns True on success, False on failure.
    """
    try:
        dest_dir = os.path.dirname(dest_path)
        os.makedirs(dest_dir, exist_ok=True)

        try:
            os.rename(src_path, dest_path)
            logger.info("[HookReel] Moved (rename): %s → %s", src_path, dest_path)
        except OSError:
            shutil.copy2(src_path, dest_path)
            os.remove(src_path)
            logger.info("[HookReel] Moved (copy+delete): %s → %s", src_path, dest_path)

        # Clean up empty staging directory if left behind
        staging_dir = os.path.dirname(src_path)
        try:
            if staging_dir != config.DOWNLOADS_PATH and not os.listdir(staging_dir):
                os.rmdir(staging_dir)
        except Exception:
            pass

        return True

    except Exception as error:
        logger.error("[HookReel] move_file error: %s → %s : %s", src_path, dest_path, error)
        return False


def notify_jellyfin(library_path: str = None) -> bool:
    """
    Trigger a Jellyfin library refresh via the API.

    Uses POST /Library/Refresh with X-Emby-Token authentication.
    Returns True on success (HTTP 200 or 204).
    Returns False and logs a warning if Jellyfin is unreachable.
    Does nothing and returns True if JELLYFIN_API_KEY is 'changeme'.
    """
    api_key = config.JELLYFIN_API_KEY

    if not api_key or api_key.strip().lower() == "changeme":
        logger.info("[HookReel] Jellyfin not configured (API key is 'changeme') — skipping notify")
        return True

    jellyfin_url = f"http://{config.JELLYFIN_HOST}:{config.JELLYFIN_PORT}"

    try:
        response = requests.post(
            f"{jellyfin_url}/Library/Refresh",
            headers={"X-Emby-Token": api_key},
            timeout=10,
        )
        if response.status_code in (200, 204):
            logger.info("[HookReel] Jellyfin library refresh triggered successfully")
            return True
        else:
            logger.warning(
                "[HookReel] Jellyfin returned unexpected status %d",
                response.status_code
            )
            return False

    except Exception as error:
        logger.warning("[HookReel] Jellyfin notify failed (non-fatal): %s", error)
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_file_path(movie: dict) -> str:
    """
    Determine the actual file path of a completed download.
    Tries content_path from qBittorrent first, then falls back to
    scanning the Downloads folder for a file matching the movie title.
    """
    content_path = movie.get("_content_path", "")

    if content_path and os.path.isfile(content_path):
        return content_path

    if content_path and os.path.isdir(content_path):
        video_file = _find_largest_video_file(content_path)
        if video_file:
            return video_file

    # Fallback: scan Downloads folder
    downloads = config.DOWNLOADS_PATH
    title_lower = movie["title"].lower()

    if os.path.isdir(downloads):
        for filename in os.listdir(downloads):
            if title_lower.replace(" ", ".") in filename.lower() or \
               title_lower in filename.lower():
                candidate = os.path.join(downloads, filename)
                if os.path.isfile(candidate):
                    return candidate

    logger.warning("[HookReel] Could not resolve file path for movie id=%d", movie["id"])
    return None


def _find_largest_video_file(directory: str) -> str:
    """
    Recursively find the largest video file in a directory.
    Used when a torrent downloads as a folder.
    """
    video_extensions = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v"}
    largest_file = None
    largest_size = 0

    for root, dirs, files in os.walk(directory):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext in video_extensions:
                full_path = os.path.join(root, filename)
                size = os.path.getsize(full_path)
                if size > largest_size:
                    largest_size = size
                    largest_file = full_path

    return largest_file


def _build_final_path(title: str, year: str, renamed_path: str) -> str:
    """
    Build the final destination path in the Movies folder.
    Format: /data/Movies/Movie Title (Year)/Movie Title (Year).ext
    """
    ext = os.path.splitext(renamed_path)[1].lower()
    clean_title = _sanitise_filename(title)
    folder_name = f"{clean_title} ({year})"
    filename = f"{clean_title} ({year}){ext}"
    return os.path.join(config.MOVIES_PATH, folder_name, filename)


def _quarantine_file(file_path: str):
    """Move an infected file to the quarantine directory."""
    try:
        os.makedirs(config.QUARANTINE_PATH, exist_ok=True)
        filename = os.path.basename(file_path)
        dest = os.path.join(config.QUARANTINE_PATH, filename)
        shutil.move(file_path, dest)
        logger.info("[HookReel] Quarantined: %s → %s", file_path, dest)
    except Exception as error:
        logger.error("[HookReel] Failed to quarantine '%s': %s", file_path, error)


def _sanitise_filename(name: str) -> str:
    """
    Remove or replace characters that are invalid in filenames.
    Keeps letters, numbers, spaces, hyphens, apostrophes, and periods.
    """
    sanitised = re.sub(r'[<>:"/\\|?*]', "", name)
    sanitised = sanitised.strip()
    return sanitised
