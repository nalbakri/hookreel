"""
prowlarr.py — Prowlarr integration for HookReel.

Searches all configured Prowlarr indexers for a given query and picks
the best release from the results based on resolution, file size, and
seeder count.

Public functions:
    search_releases(query, category)          → list of release dicts
    pick_best_release(releases, resolution, max_size_gb) → dict or None
"""

from typing import Optional

import requests

import app.config as config
from app.logger import logger

# How long to wait (seconds) for Prowlarr to respond before giving up.
_REQUEST_TIMEOUT = 120


def search_releases(query: str, category: int = 2000) -> list:
    """
    Search all configured Prowlarr indexers for the given query string.

    Parameters:
        query:    The search term, typically a movie title.
        category: Prowlarr numeric category code.  2000 = Movies.
                  Leave as default for movie searches.

    Returns:
        A list of dicts.  Each dict contains:
            title        (str)   — Release name as reported by the indexer
            size_bytes   (int)   — File size in bytes (0 if unknown)
            seeders      (int)   — Number of seeders (0 if unknown)
            leechers     (int)   — Number of leechers (0 if unknown)
            download_url (str)   — Direct download or magnet URL
            indexer      (str)   — Name of the indexer that returned this
            publish_date (str)   — ISO 8601 publish date string, or ''
        Returns an empty list if nothing is found or if an error occurs.
    """
    logger.info(
        "Searching Prowlarr for '%s' (category=%d).", query, category
    )

    url = f"{config.PROWLARR_URL}/api/v1/search"
    headers = {"X-Api-Key": config.PROWLARR_API_KEY}
    params = {"query": query, "categories": category}

    try:
        response = requests.get(
            url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        raw_results = response.json()

    except requests.exceptions.Timeout:
        logger.error("Prowlarr search timed out after %ds.", _REQUEST_TIMEOUT)
        return []
    except requests.exceptions.ConnectionError as exc:
        logger.error("Could not connect to Prowlarr at %s: %s", config.PROWLARR_URL, exc)
        return []
    except requests.exceptions.HTTPError as exc:
        logger.error("Prowlarr returned HTTP error: %s", exc)
        return []
    except Exception as exc:
        logger.error("Unexpected error during Prowlarr search: %s", exc)
        return []

    if not raw_results:
        logger.info("Prowlarr returned no results for '%s'.", query)
        return []

    releases = []
    for item in raw_results:
        # Prefer downloadUrl; fall back to magnetUrl if present.
        download_url = item.get("downloadUrl") or item.get("magnetUrl") or ""

        releases.append(
            {
                "title": item.get("title", ""),
                "size_bytes": item.get("size", 0),
                "seeders": item.get("seeders", 0),
                "leechers": item.get("leechers", 0),
                "download_url": download_url,
                "indexer": item.get("indexer", ""),
                "publish_date": item.get("publishDate", ""),
            }
        )

    # Collect unique indexer names for the log summary.
    indexer_names = sorted({r["indexer"] for r in releases if r["indexer"]})
    logger.info(
        "Prowlarr returned %d release(s) across indexer(s): %s.",
        len(releases),
        ", ".join(indexer_names) if indexer_names else "unknown",
    )
    return releases


def pick_best_release(
    releases: list,
    preferred_resolution: str = "1080p",
    max_size_gb: float = 15.0,
) -> Optional[dict]:
    """
    Choose the best release from a list returned by search_releases.

    Selection logic (applied in order):
      1. Keep only releases whose title contains preferred_resolution.
      2. Discard releases larger than max_size_gb gigabytes.
      3. Sort the survivors by seeder count (highest first).
      4. Return the top result.

    Parameters:
        releases:            List of release dicts from search_releases.
        preferred_resolution: String to look for in the release title,
                              e.g. '1080p', '720p', '2160p'.
        max_size_gb:         Maximum acceptable file size in gigabytes.

    Returns:
        The best matching release dict, or None if no release passes
        all filters.
    """
    if not releases:
        logger.info("pick_best_release called with an empty release list.")
        return None

    max_size_bytes = max_size_gb * 1024 ** 3

    # ── Step 1: filter by resolution ─────────────────────────────────────
    resolution_filtered = [
        r for r in releases if preferred_resolution.lower() in r["title"].lower()
    ]
    logger.info(
        "%d of %d releases contain resolution '%s'.",
        len(resolution_filtered),
        len(releases),
        preferred_resolution,
    )

    # ── Step 2: filter by file size ───────────────────────────────────────
    size_filtered = [
        r for r in resolution_filtered if r["size_bytes"] <= max_size_bytes
    ]
    logger.info(
        "%d release(s) remain after applying %.1f GB size limit.",
        len(size_filtered),
        max_size_gb,
    )

    if not size_filtered:
        logger.warning(
            "No releases passed filters (resolution='%s', max_size=%.1f GB). "
            "Returning None.",
            preferred_resolution,
            max_size_gb,
        )
        return None

    # ── Step 3: sort by seeders ───────────────────────────────────────────
    size_filtered.sort(key=lambda r: r["seeders"], reverse=True)
    best = size_filtered[0]

    size_gb = best["size_bytes"] / 1024 ** 3
    logger.info(
        "Best release selected: '%s' | %.2f GB | %d seeders | indexer=%s",
        best["title"],
        size_gb,
        best["seeders"],
        best["indexer"],
    )
    return best
