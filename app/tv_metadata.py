"""
HookReel TV metadata module.
Fetches TV show and episode information from the TVmaze public API.
No API key required.
"""
import httpx
from datetime import date
from app.logger import get_logger

logger = get_logger(__name__)

TVMAZE_BASE = "https://api.tvmaze.com"


def get_show_info(query: str) -> list:
    """
    Search for a TV show by name using TVmaze.
    Parameters:
        query: Show name to search for.
    Returns:
        List of show dicts each containing:
        provider_id, title, year, overview, poster_url,
        rating, status, network, episode_count, genres.
    """
    try:
        response = httpx.get(
            f"{TVMAZE_BASE}/search/shows",
            params={"q": query},
            timeout=10
        )
        response.raise_for_status()
        results = response.json()
        shows = []
        for item in results:
            show = item.get("show", {})
            network = show.get("network") or show.get("webChannel") or {}
            premiered = show.get("premiered") or ""
            year = premiered[:4] if premiered else None
            rating_obj = show.get("rating") or {}
            rating = rating_obj.get("average")
            image = show.get("image") or {}
            poster_url = image.get("medium") or image.get("original")
            shows.append({
                "provider_id": str(show.get("id", "")),
                "title": show.get("name", ""),
                "year": year,
                "overview": show.get("summary", ""),
                "poster_url": poster_url,
                "rating": rating,
                "status": show.get("status", ""),
                "network": network.get("name", ""),
                "episode_count": show.get("_links", {}).get("self", {}),
                "genres": show.get("genres", []),
            })
        logger.info(
            "[HookReel] tv_metadata get_show_info query=%s results=%d",
            query, len(shows)
        )
        return shows
    except Exception as error:
        logger.error("[HookReel] get_show_info error: %s", error)
        return []


def get_show_details(provider_id: str) -> dict:
    """
    Get full show details including season breakdown from TVmaze.
    Parameters:
        provider_id: TVmaze show ID as string.
    Returns:
        Dict with all show fields plus seasons list, or None on error.
    """
    try:
        response = httpx.get(
            f"{TVMAZE_BASE}/shows/{provider_id}",
            params={"embed[]": ["seasons", "episodes"]},
            timeout=10
        )
        response.raise_for_status()
        show = response.json()
        network = show.get("network") or show.get("webChannel") or {}
        premiered = show.get("premiered") or ""
        year = premiered[:4] if premiered else None
        rating_obj = show.get("rating") or {}
        image = show.get("image") or {}
        embedded = show.get("_embedded", {})
        raw_seasons = embedded.get("seasons", [])
        seasons = []
        for season in raw_seasons:
            seasons.append({
                "season_number": season.get("number"),
                "episode_count": season.get("episodeOrder") or 0,
                "air_date": season.get("premiereDate"),
            })
        result = {
            "provider_id": str(show.get("id", "")),
            "title": show.get("name", ""),
            "year": year,
            "overview": show.get("summary", ""),
            "poster_url": (image.get("medium") or image.get("original")),
            "rating": (rating_obj.get("average")),
            "status": show.get("status", ""),
            "network": network.get("name", ""),
            "genres": show.get("genres", []),
            "seasons": seasons,
        }
        logger.info(
            "[HookReel] tv_metadata get_show_details id=%s title=%s",
            provider_id, result["title"]
        )
        return result
    except Exception as error:
        logger.error("[HookReel] get_show_details error: %s", error)
        return None


def get_episode_list(provider_id: str, season: int = None) -> list:
    """
    Get all episodes for a show, optionally filtered by season.
    Parameters:
        provider_id: TVmaze show ID as string.
        season:      If provided, return only episodes from this season.
    Returns:
        List of episode dicts each containing:
        season, episode, title, air_date, overview.
    """
    try:
        params = {}
        if season is not None:
            params["season"] = season
            url = f"{TVMAZE_BASE}/shows/{provider_id}/episodes"
        else:
            url = f"{TVMAZE_BASE}/shows/{provider_id}/episodes"
        response = httpx.get(url, params=params, timeout=10)
        response.raise_for_status()
        raw_episodes = response.json()
        episodes = []
        for ep in raw_episodes:
            ep_season = ep.get("season")
            if season is not None and ep_season != season:
                continue
            episodes.append({
                "season": ep_season,
                "episode": ep.get("number"),
                "title": ep.get("name", ""),
                "air_date": ep.get("airdate"),
                "overview": ep.get("summary", ""),
            })
        logger.info(
            "[HookReel] tv_metadata get_episode_list id=%s season=%s count=%d",
            provider_id, season, len(episodes)
        )
        return episodes
    except Exception as error:
        logger.error("[HookReel] get_episode_list error: %s", error)
        return []


def get_next_unaired(provider_id: str) -> dict:
    """
    Get the next episode of a show that has not yet aired.
    Uses today's date to filter out already-aired episodes.
    Parameters:
        provider_id: TVmaze show ID as string.
    Returns:
        Episode dict for the next unaired episode, or None if
        the show has ended or all episodes have aired.
    """
    try:
        episodes = get_episode_list(provider_id)
        today = date.today().isoformat()
        for ep in sorted(
            episodes,
            key=lambda e: (e["season"] or 0, e["episode"] or 0)
        ):
            air_date = ep.get("air_date") or ""
            if air_date and air_date > today:
                logger.info(
                    "[HookReel] Next unaired for id=%s is S%02dE%02d on %s",
                    provider_id,
                    ep["season"],
                    ep["episode"],
                    air_date
                )
                return ep
        logger.info(
            "[HookReel] No unaired episodes found for id=%s", provider_id
        )
        return None
    except Exception as error:
        logger.error("[HookReel] get_next_unaired error: %s", error)
        return None
