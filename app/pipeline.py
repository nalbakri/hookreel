"""
app/pipeline.py

HookReel pipeline coordinator.
Orchestrates the full movie request flow: search -> select -> add torrent -> store hash.
"""

import re
import time

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
    title = re.sub(r'[<>:"/\\|?*;&$(){}]', '', title)
    title = re.sub(r' +', ' ', title)
    title = title.strip()
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
    passed directly to qBittorrent.

    If download_url is not provided, the full pipeline runs:
      1. Metadata lookup (TMDB or OMDB) for canonical title/year
      2. Prowlarr search for matching torrent releases
      3. Add best result to qBittorrent (tries up to 5 candidates)
      4. Hash captured directly from magnet URL or via fallback lookup
      5. Record in database with status 'downloading'

    Returns a result dict with keys:
      success, title, year, status, movie_id, torrent_hash, message.
    """
    title = sanitise_title(title)
    log_audit("download_requested", {"title": title, "year": year or "unknown"}, "system")
    logger.info("[HookReel] Pipeline: request_movie called for '%s'", title)

    # --- Fast path: user confirmed a specific release ---
    # If release_title given but no download_url, re-fetch a fresh URL from Prowlarr
    if release_title and not download_url:
        logger.info(
            "[HookReel] Re-fetching fresh download URL for release: %s", release_title
        )
        fresh_results = prowlarr.search_releases(release_title, category=2000)
        if fresh_results:
            from app.qbittorrent import _resolve_to_magnet
            for candidate in fresh_results:
                candidate_url = candidate.get("download_url", "")
                if not candidate_url:
                    continue
                resolved = _resolve_to_magnet(candidate_url)
                if resolved.startswith("magnet:"):
                    download_url = resolved
                    logger.info(
                        "[HookReel] Re-fetch resolved magnet for '%s'",
                        release_title
                    )
                    break
            if not download_url:
                logger.warning(
                    "[HookReel] Re-fetch could not resolve any magnet for: %s",
                    release_title
                )
        else:
            logger.warning(
                "[HookReel] Re-fetch found no results for release: %s", release_title
            )
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

        # Step 3 -- Add torrent, hash returned directly
        torrent_hash = qbittorrent.add_torrent(
            download_url, save_path=config.DOWNLOADS_PATH
        )
        if torrent_hash is None:
            # add_torrent returns None on qBittorrent rejection
            # but also None when hash cannot be determined
            # distinguish by re-checking torrent list
            time.sleep(2)
            from app.qbittorrent import get_torrent_hash_by_name
            torrent_hash = get_torrent_hash_by_name(used_release_title)
            if torrent_hash is None:
                logger.warning(
                    "[HookReel] qBittorrent may have rejected '%s' or hash unavailable",
                    used_release_title,
                )

        # Step 4 -- Store in database
        try:
            clean_title = title.strip()
            year_hint = year or ""
            year_match = re.search(r'\b(19|20)\d{2}$', clean_title)
            if year_match and not year_hint:
                year_hint = year_match.group(0)
                clean_title = clean_title[:year_match.start()].strip()

            movie_id = database.add_movie(0, clean_title, year_hint)
            new_status = "downloading" if torrent_hash else "failed"
            database.update_movie_status(movie_id, new_status)
            if torrent_hash:
                database.update_movie_torrent_hash(movie_id, torrent_hash)
            logger.info(
                "[HookReel] Movie recorded (fast path): id=%d title='%s' hash=%s",
                movie_id, clean_title, torrent_hash or "none",
            )
        except Exception as error:
            logger.error("[HookReel] Database write failed: %s", error)
            return {"success": False, "message": f"Database error: {error}"}

        log_audit("download_started", {"title": clean_title, "year": year_hint, "path": "fast"}, "system")
        return {
            "success": True,
            "title": clean_title,
            "year": year_hint,
            "status": new_status,
            "movie_id": movie_id,
            "torrent_hash": torrent_hash,
            "message": f"'{clean_title}' added to download queue (user-confirmed release)",
        }

    # --- Standard path: no specific release chosen ---

    # Step 1 -- Metadata lookup
    try:
        provider = get_metadata_provider()

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

    # Step 2 -- Prowlarr search
    try:
        search_query = f"{canonical_title} {year_hint}".strip()
        prowlarr_results = prowlarr.search_releases(search_query)
        if not prowlarr_results:
            return {
                "success": False,
                "message": f"No torrents found for '{search_query}'",
            }

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

    # Step 3 -- Add torrent, hash returned directly
    torrent_hash = None
    try:
        torrent_hash = qbittorrent.add_torrent(magnet_url, save_path=config.DOWNLOADS_PATH)
        if torrent_hash is not None:
            logger.info("[HookReel] Torrent added, hash: %s", torrent_hash)
        else:
            # First candidate failed or hash unavailable -- try alternatives
            logger.warning(
                "[HookReel] First release failed or hash unavailable -- trying alternatives"
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
                alt_hash = qbittorrent.add_torrent(alt_url, save_path=config.DOWNLOADS_PATH)
                if alt_hash is not None:
                    magnet_url = alt_url
                    release_name = alt_title
                    torrent_hash = alt_hash
                    logger.info(
                        "[HookReel] Alternative release accepted: %s hash: %s",
                        alt_title, torrent_hash,
                    )
                    break

        if torrent_hash is None:
            # Last resort -- all candidates returned None
            # Could be rejection or hash-less direct URL
            # Check if anything was actually added
            logger.warning("[HookReel] All candidates returned None -- checking qBittorrent")
            from app.qbittorrent import get_torrent_hash_by_name
            torrent_hash = get_torrent_hash_by_name(release_name)
            if torrent_hash is None:
                return {
                    "success": False,
                    "message": "qBittorrent rejected all available releases",
                }

    except Exception as error:
        logger.error("[HookReel] qBittorrent add failed: %s", error)
        return {"success": False, "message": f"qBittorrent error: {error}"}

    # Step 4 -- Store in database
    try:
        movie_id = database.add_movie(provider_id, canonical_title, year_hint)
        database.update_movie_status(movie_id, "downloading")
        if torrent_hash:
            database.update_movie_torrent_hash(movie_id, torrent_hash)
        logger.info(
            "[HookReel] Movie recorded: id=%d title='%s' hash=%s",
            movie_id, canonical_title, torrent_hash or "none",
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
