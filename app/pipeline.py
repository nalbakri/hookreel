"""
app/pipeline.py

HookReel pipeline coordinator.
Orchestrates the full movie request flow: search → select → add torrent → store hash.
"""

import re

from app import config, database, prowlarr, qbittorrent
from app.logger import get_logger
from app.audit import log_audit
from app.metadata.tmdb import TmdbProvider as TMDBProvider
from app.metadata.omdb import OmdbProvider as OMDBProvider

logger = get_logger(__name__)

def sanitise_title(title: str) -> str:
    """
    Sanitise a user-supplied title before it touches the filesystem or database.
    Strips dangerous characters, removes leading/trailing whitespace,
    and truncates to 200 characters.
    """
    if not title:
        return ""
    # Strip characters that could affect SQL, filesystem, or shell
    title = re.sub(r'[<>:"/\\|?*;&$(){}]', '', title)
    # Collapse multiple spaces
    title = re.sub(r' +', ' ', title)
    # Strip leading/trailing whitespace
    title = title.strip()
    # Truncate to 200 characters
    return title[:200]

def get_metadata_provider():
    """Return the configured metadata provider instance."""
    provider_name = config.METADATA_PROVIDER.lower()
    if provider_name == "omdb":
        return OMDBProvider(config.METADATA_API_KEY)
    return TMDBProvider(config.METADATA_API_KEY)


def _validate_download_url(url: str) -> bool:
    """
    Validate that a download URL is a safe, expected format.

    Only magnet links and http/https URLs are accepted.
    Anything else is rejected to prevent unexpected input from
    reaching qBittorrent.
    """
    if not url:
        return False
    return url.startswith("magnet:?") or url.startswith("http://") or url.startswith("https://")


def request_movie(
    title: str,
    year: str = None,
    download_url: str = None,
    release_title: str = None,
) -> dict:
    """
    Run the full movie request pipeline for the given title string.

    If download_url is provided (user confirmed a specific release),
    Steps 1 and 2 are skipped. The provided URL is validated and
    passed directly to qBittorrent. This ensures the user always
    gets the exact release they chose.

    If download_url is not provided, the full pipeline runs:
      1. Metadata lookup (TMDB or OMDB) for canonical title/year
      2. Prowlarr search for matching torrent releases
      3. Add best result to qBittorrent (tries up to 5 candidates)
      4. Hash lookup for torrent tracking
      5. Record in database with status 'downloading'

    Returns a result dict with keys:
      success, title, year, status, movie_id, message.
    """
    title = sanitise_title(title)
    log_audit("download_requested", {"title": title, "year": year or "unknown"}, "system")
    logger.info("[HookReel] Pipeline: request_movie called for '%s'", title)

    # --- Fast path: user confirmed a specific release ---
    if download_url:
        if not _validate_download_url(download_url):
            logger.warning(
                "[HookReel] Rejected invalid download_url: %s", download_url
            )
            return {
                "success": False,
                "message": f"Invalid download URL format: {download_url}",
            }

        used_release_title = release_title or title
        logger.info(
            "[HookReel] Using user-confirmed release: %s", used_release_title
        )

        # Step 3 — Add torrent directly (skip metadata + Prowlarr search)
        try:
            added = qbittorrent.add_torrent(
                download_url, save_path=config.DOWNLOADS_PATH
            )
            if not added:
                return {
                    "success": False,
                    "message": (
                        f"qBittorrent rejected the release: {used_release_title}"
                    ),
                }
        except Exception as error:
            logger.error("[HookReel] qBittorrent add failed: %s", error)
            return {"success": False, "message": f"qBittorrent error: {error}"}

        # Step 4 — Hash lookup
        torrent_hash = None
        try:
            import time
            time.sleep(3)
            torrent_hash = qbittorrent.get_torrent_hash_by_name(used_release_title)
            if torrent_hash:
                logger.info("[HookReel] Torrent hash found: %s", torrent_hash)
            else:
                logger.warning(
                    "[HookReel] Torrent hash not found for '%s' — will track by name",
                    used_release_title,
                )
        except Exception as error:
            logger.warning("[HookReel] Hash lookup error (non-fatal): %s", error)

        # Step 5 — Store in database
        # Use title as-is for the fast path — no metadata lookup
        try:
            # Strip trailing year from title if present
            clean_title = title.strip()
            year_hint = year or ""
            year_match = re.search(r'\b(19|20)\d{2}$', clean_title)
            if year_match and not year_hint:
                year_hint = year_match.group(0)
                clean_title = clean_title[:year_match.start()].strip()

            movie_id = database.add_movie(0, clean_title, year_hint)
            database.update_movie_status(movie_id, "downloading")
            if torrent_hash:
                database.update_movie_torrent_hash(movie_id, torrent_hash)
            logger.info(
                "[HookReel] Movie recorded (fast path): id=%d title='%s' hash=%s",
                movie_id, clean_title, torrent_hash or "not found",
            )
        except Exception as error:
            logger.error("[HookReel] Database write failed: %s", error)
            return {"success": False, "message": f"Database error: {error}"}
        
        log_audit("download_started", {"title": clean_title, "year": year_hint, "path": "fast"}, "system")
        return {
            "success": True,
            "title": clean_title,
            "year": year_hint,
            "status": "downloading",
            "movie_id": movie_id,
            "torrent_hash": torrent_hash,
            "message": f"'{clean_title}' added to download queue (user-confirmed release)",
        }

    # --- Standard path: no specific release chosen ---

    # Step 1 — Metadata lookup
    try:
        provider = get_metadata_provider()

        # Strip a trailing 4-digit year from the title if the agent included it
        # e.g. 'Spaceballs 1987' → title='Spaceballs', year_hint='1987'
        year_hint = year or ""
        clean_title = title.strip()
        year_match = re.search(r'\b(19|20)\d{2}$', clean_title)
        if year_match and not year_hint:
            year_hint = year_match.group(0)
            clean_title = clean_title[:year_match.start()].strip()

        results = provider.search(clean_title)
        if not results:
            if year_hint:
                results = provider.search(title)
            if not results:
                return {
                    "success": False,
                    "message": f"No metadata found for '{title}'",
                }

        metadata = results[0]
        canonical_title = metadata.get("title", clean_title)
        year_hint = metadata.get("year", year_hint)
        provider_id = metadata.get("provider_id", 0)

        logger.info(
            "[HookReel] Metadata found: %s (%s) provider_id=%s",
            canonical_title, year_hint, provider_id,
        )
    except Exception as error:
        logger.error("[HookReel] Metadata lookup failed: %s", error)
        return {"success": False, "message": f"Metadata lookup error: {error}"}

    # Step 2 — Prowlarr search
    try:
        search_query = f"{canonical_title} {year_hint}".strip()
        prowlarr_results = prowlarr.search_releases(search_query)
        if not prowlarr_results:
            return {
                "success": False,
                "message": f"No torrents found for '{search_query}'",
            }

        # Prefer results with magnet or download links — try up to 5 results
        best_result = None
        magnet_url = ""
        release_name = search_query

        for candidate in prowlarr_results[:5]:
            candidate_url = (
                candidate.get("magnetUrl")
                or candidate.get("downloadUrl")
                or candidate.get("download_url", "")
            )
            if candidate_url:
                best_result = candidate
                magnet_url = candidate_url
                release_name = candidate.get("title", search_query)
                break

        if not best_result:
            return {
                "success": False,
                "message": f"No downloadable releases found for '{search_query}'",
            }

        logger.info("[HookReel] Best release selected: %s", release_name)
    except Exception as error:
        logger.error("[HookReel] Prowlarr search failed: %s", error)
        return {"success": False, "message": f"Search error: {error}"}

    # Step 3 — Add torrent, trying up to 5 results on failure
    added = False
    try:
        added = qbittorrent.add_torrent(magnet_url, save_path=config.DOWNLOADS_PATH)
        if not added:
            logger.warning(
                "[HookReel] First release rejected by qBittorrent — trying alternatives"
            )
            for candidate in prowlarr_results[1:5]:
                alt_url = (
                    candidate.get("magnetUrl")
                    or candidate.get("downloadUrl")
                    or candidate.get("download_url", "")
                )
                if not alt_url:
                    continue
                alt_title = candidate.get("title", "")
                logger.info("[HookReel] Trying alternative release: %s", alt_title)
                if qbittorrent.add_torrent(alt_url, save_path=config.DOWNLOADS_PATH):
                    magnet_url = alt_url
                    release_name = alt_title
                    added = True
                    logger.info(
                        "[HookReel] Alternative release accepted: %s", alt_title
                    )
                    break

        if not added:
            return {
                "success": False,
                "message": "qBittorrent rejected all available releases",
            }
    except Exception as error:
        logger.error("[HookReel] qBittorrent add failed: %s", error)
        return {"success": False, "message": f"qBittorrent error: {error}"}

    # Step 4 — Hash lookup (non-blocking)
    torrent_hash = None
    try:
        import time
        time.sleep(3)
        torrent_hash = qbittorrent.get_torrent_hash_by_name(release_name)
        if torrent_hash:
            logger.info("[HookReel] Torrent hash found: %s", torrent_hash)
        else:
            logger.warning(
                "[HookReel] Torrent hash not found for '%s' — will track by name",
                release_name,
            )
    except Exception as error:
        logger.warning("[HookReel] Hash lookup error (non-fatal): %s", error)

    # Step 5 — Store in database
    try:
        movie_id = database.add_movie(provider_id, canonical_title, year_hint)
        database.update_movie_status(movie_id, "downloading")
        if torrent_hash:
            database.update_movie_torrent_hash(movie_id, torrent_hash)
        logger.info(
            "[HookReel] Movie recorded: id=%d title='%s' hash=%s",
            movie_id, canonical_title, torrent_hash or "not found",
        )
    except Exception as error:
        logger.error("[HookReel] Database write failed: %s", error)
        return {"success": False, "message": f"Database error: {error}"}
    
    log_audit("download_started", {"title": canonical_title, "year": year_hint, "path": "full"}, "system")
    return {
        "success": True,
        "title": canonical_title,
        "year": year_hint,
        "status": "downloading",
        "movie_id": movie_id,
        "torrent_hash": torrent_hash,
        "message": f"'{canonical_title} ({year_hint})' added to download queue",
    }
