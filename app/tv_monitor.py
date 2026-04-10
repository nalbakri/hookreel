"""
HookReel TV monitor.
Checks tracked shows daily for newly aired episodes.
Adds missing episodes to the database and optionally queues them
for automatic download if AUTO_DOWNLOAD_NEW_EPISODES is enabled.
"""
from datetime import date
import app.database as database
import app.tv_metadata as tv_metadata
from app.logger import get_logger
from app import config

logger = get_logger(__name__)


def check_new_episodes() -> list:
    """
    Check all tracked shows for episodes that have aired but are not
    yet in the database.
    For each tracked show:
        - Fetch the full episode list from the metadata provider.
        - Compare against episodes already in the database.
        - Add any new episodes with status=missing.
    Returns:
        List of newly added episode dicts (show_id, season, episode, title).
    """
    shows = database.get_all_shows()
    tracked = [s for s in shows if s["status"] == "tracked"]
    newly_added = []
    today = date.today().isoformat()

    logger.info(
        "[HookReel] check_new_episodes: checking %d tracked shows",
        len(tracked)
    )

    for show in tracked:
        show_id = show["id"]
        provider_id = show["provider_id"]
        show_title = show["title"]
        try:
            episodes = tv_metadata.get_episode_list(provider_id)
            for ep in episodes:
                season = ep.get("season")
                episode = ep.get("episode")
                air_date = ep.get("air_date") or ""

                if season is None or episode is None:
                    continue

                # Only process episodes that have already aired
                if air_date and air_date > today:
                    continue

                if not database.episode_exists(show_id, season, episode):
                    ep_id = database.add_episode(
                        show_id,
                        season,
                        episode,
                        ep.get("title"),
                        air_date
                    )
                    if ep_id != -1:
                        newly_added.append({
                            "show_id": show_id,
                            "show_title": show_title,
                            "episode_id": ep_id,
                            "season": season,
                            "episode": episode,
                            "title": ep.get("title"),
                            "air_date": air_date
                        })
                        logger.info(
                            "[HookReel] New episode found: %s S%02dE%02d",
                            show_title, season, episode
                        )
        except Exception as error:
            logger.error(
                "[HookReel] check_new_episodes error for show_id=%d: %s",
                show_id, error
            )

    logger.info(
        "[HookReel] check_new_episodes complete: %d new episodes found",
        len(newly_added)
    )
    return newly_added


def auto_download_new_episodes(show_id: int = None) -> list:
    """
    Automatically queue newly discovered episodes for download.
    Only runs if AUTO_DOWNLOAD_NEW_EPISODES=true in .env.
    If show_id is provided, only processes that show.
    Parameters:
        show_id: Optional database show ID to limit scope.
    Returns:
        List of episode dicts that were queued for download.
    """
    auto_enabled = str(
        getattr(config, "AUTO_DOWNLOAD_NEW_EPISODES", "false")
    ).lower() == "true"

    if not auto_enabled:
        logger.info(
            "[HookReel] auto_download_new_episodes: disabled in config"
        )
        return []

    # Import here to avoid circular imports at module load time
    from app.tv_pipeline import request_show

    missing = database.get_episodes_by_status("missing")
    if show_id is not None:
        missing = [e for e in missing if e["show_id"] == show_id]

    queued = []
    for episode in missing:
        ep_show_id = episode["show_id"]
        show = database.get_show(ep_show_id)
        if not show:
            continue
        try:
            result = request_show(
                title=show["title"],
                season=episode["season"],
                episode=episode["episode"]
            )
            if result.get("success"):
                queued.append(episode)
                logger.info(
                    "[HookReel] Auto-queued: %s S%02dE%02d",
                    show["title"],
                    episode["season"],
                    episode["episode"]
                )
        except Exception as error:
            logger.error(
                "[HookReel] auto_download_new_episodes error "
                "episode_id=%d: %s",
                episode["id"], error
            )

    logger.info(
        "[HookReel] auto_download_new_episodes: queued %d episodes",
        len(queued)
    )
    return queued
