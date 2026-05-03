"""
app/webhook.py

Jellyfin webhook handler for HookReel.
Receives playback events from Jellyfin and updates watch history automatically.

Requires the Jellyfin Webhook Plugin to be installed and configured to POST
to http://<hookreel-host>:8765/webhooks/jellyfin

See docs/INSTALL.md for setup instructions.
"""
import hashlib
import hmac
from app import config, database
from app.logger import get_logger

logger = get_logger(__name__)

# Jellyfin playback event names that indicate viewing is complete or stopped
PLAYBACK_STOP_EVENTS = {"PlaybackStop", "PlaybackFinish", "PlaybackStopped"}


def verify_webhook_secret(payload_bytes: bytes, signature: str) -> bool:
    """
    Verify optional HMAC signature from Jellyfin webhook.
    If JELLYFIN_WEBHOOK_SECRET is empty, verification is skipped.
    Returns True if valid or if no secret is configured.
    """
    secret = config.JELLYFIN_WEBHOOK_SECRET
    if not secret:
        return True
    expected = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def handle_jellyfin_event(payload: dict) -> dict:
    """
    Process a Jellyfin webhook payload and update watch history.

    Expected payload fields:
        NotificationType  -- event name e.g. PlaybackStop
        ItemType          -- Movie or Episode
        Name              -- item title
        SeriesName        -- show title (for episodes)
        SeasonNumber      -- season number (for episodes)
        EpisodeNumber     -- episode number (for episodes)
        PlaybackPositionTicks -- position in ticks (10,000 ticks = 1ms)
        PlayedToCompletion -- boolean
        Year              -- release year

    Returns a dict with status and message.
    """
    event = payload.get("NotificationType", "")
    item_type = payload.get("ItemType", "")
    played_to_completion = payload.get("PlayedToCompletion", False)

    if event not in PLAYBACK_STOP_EVENTS:
        logger.debug("[HookReel] Webhook: ignoring event %s", event)
        return {"status": "ignored", "reason": "not a stop event"}

    logger.info(
        "[HookReel] Jellyfin webhook: event=%s type=%s completed=%s",
        event, item_type, played_to_completion
    )

    if item_type == "Movie":
        return _handle_movie_event(payload, played_to_completion)
    elif item_type == "Episode":
        return _handle_episode_event(payload, played_to_completion)
    else:
        return {"status": "ignored", "reason": "unsupported item type"}


def _handle_movie_event(payload: dict, completed: bool) -> dict:
    """Handle a movie playback stop event."""
    title = payload.get("Name", "")
    year = str(payload.get("Year", ""))

    if not title:
        return {"status": "error", "reason": "missing title"}

    movies = database.get_movies_by_title(title)
    if not movies:
        logger.warning(
            "[HookReel] Webhook: movie '%s' not found in library", title
        )
        return {"status": "not_found", "title": title}

    movie = movies[0]
    database.mark_watched(
        "movie",
        movie["id"],
        movie["title"],
        watch_source="jellyfin_webhook",
        completed=completed,
    )
    logger.info(
        "[HookReel] Webhook: marked movie '%s' as watched (completed=%s)",
        movie["title"], completed
    )
    return {"status": "ok", "title": movie["title"], "completed": completed}


def _handle_episode_event(payload: dict, completed: bool) -> dict:
    """Handle a TV episode playback stop event."""
    show_title = payload.get("SeriesName", "")
    season = payload.get("SeasonNumber")
    episode_num = payload.get("EpisodeNumber")

    if not show_title or season is None or episode_num is None:
        return {"status": "error", "reason": "missing show/season/episode"}

    shows = database.get_show_by_title(show_title)
    if not shows:
        logger.warning(
            "[HookReel] Webhook: show '%s' not found in library", show_title
        )
        return {"status": "not_found", "title": show_title}

    show = shows[0]
    ep = database.get_episode(show["id"], int(season), int(episode_num))
    if not ep:
        logger.warning(
            "[HookReel] Webhook: episode S%02dE%02d of '%s' not found",
            season, episode_num, show_title
        )
        return {"status": "not_found", "episode": "S{:02d}E{:02d}".format(season, episode_num)}

    ep_title = "{} S{:02d}E{:02d}".format(show["title"], int(season), int(episode_num))
    database.mark_watched(
        "episode",
        ep["id"],
        ep_title,
        watch_source="jellyfin_webhook",
        completed=completed,
    )
    logger.info(
        "[HookReel] Webhook: marked %s as watched (completed=%s)",
        ep_title, completed
    )
    return {"status": "ok", "title": ep_title, "completed": completed}
