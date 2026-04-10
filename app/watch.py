"""
HookReel Watch Mode coordinator.
Handles watch requests for movies and TV episodes.
Decides between Jellyfin deep links (Tier 1) and FFmpeg HLS (Tier 2).
Records all watch events in the watch_history table.
"""

import app.config as config
import app.database as database
from app.jellyfin import get_jellyfin_item
from app.hls_streamer import hls_streamer
from app.logger import get_logger

logger = get_logger(__name__)


def watch_movie(title: str, movie_id: int = None) -> dict:
    """
    Handle a request to watch a movie.

    Looks up the movie in the database, then attempts Jellyfin
    playback (Tier 1) or falls back to FFmpeg HLS (Tier 2).
    Records a watch event in history on success.

    Parameters:
        title:    Movie title to search for.
        movie_id: Optional database ID — used for direct lookup.

    Returns:
        A dict describing the watch result:
          mode       — 'jellyfin' or 'hls'
          title      — resolved title string
          web_link   — Jellyfin web URL (Jellyfin mode only)
          app_link   — Jellyfin app URL (Jellyfin mode only)
          stream_url — HLS playlist URL (HLS mode only)
          message    — Human-readable status message
          error      — Error message string (on failure)
    """
    # Resolve the movie record from the database
    movie = None
    if movie_id:
        movie = database.get_movie_by_id(movie_id)
    if not movie:
        matches = database.get_movies_by_title(title)
        if matches:
            # Prefer completed entries over other statuses
            completed = [m for m in matches if m["status"] == "complete"]
            movie = completed[0] if completed else matches[0]

    if not movie:
        logger.warning(
            "[HookReel] watch_movie: '%s' not found in database", title
        )
        return {
            "error": (
                f"'{title}' was not found in the library. "
                "Has it been downloaded yet?"
            )
        }

    resolved_title = movie["title"]
    resolved_id = movie["id"]

    # Tier 1 — Jellyfin
    if config.JELLYFIN_ENABLED:
        jellyfin_item = get_jellyfin_item(resolved_title, "Movie")
        if jellyfin_item:
            watch_id = database.add_watch_event(
                media_type="movie",
                media_id=resolved_id,
                title=resolved_title,
                jellyfin_item_id=jellyfin_item["jellyfin_id"],
            )
            links = jellyfin_item["deep_link"]
            logger.info(
                "[HookReel] watch_movie: Jellyfin link generated for '%s'",
                resolved_title
            )
            return {
                "mode": "jellyfin",
                "title": resolved_title,
                "web_link": links["web"],
                "app_link": links["app"],
                "watch_id": watch_id,
                "message": f"Ready to watch {resolved_title}!",
            }
        else:
            logger.warning(
                "[HookReel] watch_movie: '%s' not found in Jellyfin, "
                "falling back to HLS", resolved_title
            )

    # Tier 2 — FFmpeg HLS fallback
    file_path = movie.get("file_path")
    if not file_path:
        return {
            "error": (
                f"'{resolved_title}' has no file path recorded. "
                "Post-processing may not have completed yet."
            )
        }

    stream_url = hls_streamer.start_stream(resolved_id, file_path)
    if not stream_url:
        return {
            "error": (
                f"Failed to start HLS stream for '{resolved_title}'. "
                "Check that FFmpeg is available and the file exists."
            )
        }

    watch_id = database.add_watch_event(
        media_type="movie",
        media_id=resolved_id,
        title=resolved_title,
    )
    logger.info(
        "[HookReel] watch_movie: HLS stream started for '%s'",
        resolved_title
    )
    return {
        "mode": "hls",
        "title": resolved_title,
        "stream_url": stream_url,
        "watch_id": watch_id,
        "message": f"Stream ready for {resolved_title}! Open in VLC or your browser.",
    }


def watch_episode(
    show_title: str,
    season: int = None,
    episode: int = None,
    show_id: int = None
) -> dict:
    """
    Handle a request to watch a TV episode.

    If season and episode are not provided, automatically determines
    the next unwatched episode using watch history.
    Records a watch event in history on success.

    Parameters:
        show_title: TV show title to search for.
        season:     Season number — optional, inferred if not provided.
        episode:    Episode number — optional, inferred if not provided.
        show_id:    Optional database show ID for direct lookup.

    Returns:
        Same structure as watch_movie().
    """
    # Resolve the show record
    show = None
    if show_id:
        show = database.get_show(show_id)
    if not show:
        matches = database.get_show_by_title(show_title)
        if matches:
            show = matches[0]

    if not show:
        return {
            "error": (
                f"Show '{show_title}' was not found in the library. "
                "Has it been added yet?"
            )
        }

    resolved_show_id = show["id"]
    resolved_show_title = show["title"]

    # Resolve which episode to play
    episode_row = None
    if season is not None and episode is not None:
        episode_row = database.get_episode(resolved_show_id, season, episode)
        if not episode_row:
            return {
                "error": (
                    f"S{season:02d}E{episode:02d} of '{resolved_show_title}' "
                    "was not found in the library."
                )
            }
    else:
        episode_row = database.get_next_episode_to_watch(resolved_show_id)
        if not episode_row:
            return {
                "error": (
                    f"No unwatched episodes found for '{resolved_show_title}'. "
                    "All episodes may have been watched already."
                )
            }

    episode_id = episode_row["id"]
    ep_season = episode_row["season"]
    ep_episode = episode_row["episode"]
    ep_title = episode_row.get("title", "")
    display_title = (
        f"{resolved_show_title} S{ep_season:02d}E{ep_episode:02d}"
        + (f" — {ep_title}" if ep_title else "")
    )

    # Tier 1 — Jellyfin
    if config.JELLYFIN_ENABLED:
        jellyfin_item = get_jellyfin_item(
            resolved_show_title,
            media_type="Episode",
            season=ep_season,
            episode=ep_episode,
        )
        if jellyfin_item:
            watch_id = database.add_watch_event(
                media_type="episode",
                media_id=episode_id,
                title=display_title,
                jellyfin_item_id=jellyfin_item["jellyfin_id"],
            )
            links = jellyfin_item["deep_link"]
            logger.info(
                "[HookReel] watch_episode: Jellyfin link for '%s'",
                display_title
            )
            return {
                "mode": "jellyfin",
                "title": display_title,
                "season": ep_season,
                "episode": ep_episode,
                "web_link": links["web"],
                "app_link": links["app"],
                "watch_id": watch_id,
                "message": f"Ready to watch {display_title}!",
            }
        else:
            logger.warning(
                "[HookReel] watch_episode: '%s' not found in Jellyfin, "
                "falling back to HLS", display_title
            )

    # Tier 2 — FFmpeg HLS fallback
    file_path = episode_row.get("file_path")
    if not file_path:
        return {
            "error": (
                f"'{display_title}' has no file path recorded. "
                "Post-processing may not have completed yet."
            )
        }

    stream_url = hls_streamer.start_stream(episode_id, file_path)
    if not stream_url:
        return {
            "error": (
                f"Failed to start HLS stream for '{display_title}'. "
                "Check that FFmpeg is available and the file exists."
            )
        }

    watch_id = database.add_watch_event(
        media_type="episode",
        media_id=episode_id,
        title=display_title,
    )
    logger.info(
        "[HookReel] watch_episode: HLS stream started for '%s'", display_title
    )
    return {
        "mode": "hls",
        "title": display_title,
        "season": ep_season,
        "episode": ep_episode,
        "stream_url": stream_url,
        "watch_id": watch_id,
        "message": f"Stream ready for {display_title}! Open in VLC or your browser.",
    }


def get_watch_history(limit: int = 10) -> list:
    """
    Return recent watch history formatted for agent responses.

    Parameters:
        limit: Maximum number of entries to return (default 10).

    Returns:
        List of watch history dicts from the database.
    """
    return database.get_watch_history(limit=limit)
