"""
HookReel Jellyfin integration.
Provides library search, deep link generation, and library refresh
for Watch Mode Tier 1 (Jellyfin-first playback).
"""

import httpx
import app.config as config
from app.logger import get_logger

logger = get_logger(__name__)

JELLYFIN_BASE = "http://{}:{}".format(config.JELLYFIN_HOST, config.JELLYFIN_PORT)
JELLYFIN_HEADERS = {"X-Emby-Token": config.JELLYFIN_API_KEY}


def get_jellyfin_item(
    title: str,
    media_type: str = "Movie",
    season: int = None,
    episode: int = None
) -> dict:
    """
    Search the Jellyfin library for a media item by title.

    For TV episodes, pass season and episode numbers to narrow
    the search to the correct episode.

    Parameters:
        title:      Title to search for (movie or show title).
        media_type: 'Movie' or 'Episode' (Jellyfin type string).
        season:     Season number — used for episode searches.
        episode:    Episode number — used for episode searches.

    Returns:
        A dict with jellyfin_id, title, type, stream_url, deep_link,
        or None if not found or on error.
    """
    try:
        params = {
            "searchTerm": title,
            "IncludeItemTypes": media_type,
            "Recursive": "true",
            "Limit": "10",
            "Fields": "Path,Overview",
        }

        response = httpx.get(
            f"{JELLYFIN_BASE}/Items",
            headers=JELLYFIN_HEADERS,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("Items", [])
        if not items:
            logger.info(
                "[HookReel] Jellyfin: no results for '%s' type=%s",
                title, media_type
            )
            return None

        # For episode searches, filter by season and episode number
        if media_type == "Episode" and season is not None and episode is not None:
            for item in items:
                if (
                    item.get("ParentIndexNumber") == season
                    and item.get("IndexNumber") == episode
                ):
                    return _build_item_dict(item)
            logger.info(
                "[HookReel] Jellyfin: no episode match for "
                "'%s' S%02dE%02d", title, season, episode
            )
            return None

        # For movies and general searches return the first result
        return _build_item_dict(items[0])

    except httpx.HTTPError as error:
        logger.error("[HookReel] Jellyfin HTTP error: %s", error)
        return None
    except Exception as error:
        logger.error("[HookReel] get_jellyfin_item error: %s", error)
        return None


def _build_item_dict(item: dict) -> dict:
    """
    Build a standardised item dict from a raw Jellyfin Items response.

    Parameters:
        item: A single item dict from the Jellyfin /Items response.

    Returns:
        Dict with jellyfin_id, title, type, stream_url, and deep_link.
    """
    jellyfin_id = item.get("Id", "")
    links = generate_deep_link(jellyfin_id)
    stream_url = (
        f"{JELLYFIN_BASE}/Videos/{jellyfin_id}/stream"
        f"?api_key={config.JELLYFIN_API_KEY}"
    )
    return {
        "jellyfin_id": jellyfin_id,
        "title": item.get("Name", ""),
        "type": item.get("Type", ""),
        "stream_url": stream_url,
        "deep_link": links,
    }


def generate_deep_link(jellyfin_id: str) -> dict:
    """
    Generate Jellyfin deep links for a given item ID.

    Returns both a web browser link and a Jellyfin app protocol link.

    Parameters:
        jellyfin_id: The Jellyfin internal item ID string.

    Returns:
        Dict with 'web' (http://) and 'app' (jellyfin://) keys.
    """
    web_link = (
        f"http://{config.JELLYFIN_HOST}:{config.JELLYFIN_PORT}"
        f"/web/#/details?id={jellyfin_id}"
    )
    app_link = (
        f"jellyfin://{config.JELLYFIN_HOST}"
        f"/Items/{jellyfin_id}"
    )
    return {"web": web_link, "app": app_link}


def get_jellyfin_library() -> list:
    """
    Return all items in the Jellyfin library.

    Fetches movies and episodes in a single recursive call.
    Used to check what Jellyfin currently knows about.

    Returns:
        List of item dicts, each with jellyfin_id, title, and type.
        Returns empty list on error.
    """
    try:
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Episode",
            "Fields": "Path",
            "Limit": "500",
        }
        response = httpx.get(
            f"{JELLYFIN_BASE}/Items",
            headers=JELLYFIN_HEADERS,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("Items", [])
        logger.info(
            "[HookReel] Jellyfin library fetched: %d items", len(items)
        )
        return [
            {
                "jellyfin_id": item.get("Id", ""),
                "title": item.get("Name", ""),
                "type": item.get("Type", ""),
            }
            for item in items
        ]
    except Exception as error:
        logger.error("[HookReel] get_jellyfin_library error: %s", error)
        return []


def refresh_jellyfin_library() -> bool:
    """
    Trigger a Jellyfin library scan.

    Sends a POST request to the Jellyfin refresh endpoint.
    This is an alias for the same call made in postprocessor.py,
    centralised here for cleaner imports in watch mode.

    Returns:
        True if the refresh was accepted, False on error.
    """
    try:
        response = httpx.post(
            f"{JELLYFIN_BASE}/Library/Refresh",
            headers=JELLYFIN_HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        logger.info("[HookReel] Jellyfin library refresh triggered")
        return True
    except Exception as error:
        logger.error("[HookReel] refresh_jellyfin_library error: %s", error)
        return False
