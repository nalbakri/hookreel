"""
HookReel main entry point.

Runs the polling loop every 60 seconds.
Each cycle: checks for completed downloads and runs post-processing.
Runs the Telegram bot in a parallel daemon thread.
Runs the FastAPI web UI in a parallel daemon thread.

The polling loop also watches a restart_event flag. When the web UI
triggers a restart (via the Settings page), the loop re-initialises
the ConversationManager and reloads in-memory config without
restarting the Docker container.
"""

import os
import re
import time
import sys
import threading

from app import config, database, qbittorrent
from app.logger import get_logger
from app.postprocessor import check_completed_downloads, process_movie
from app.tv_postprocessor import check_completed_tv_downloads, process_episode
from app.tv_monitor import check_new_episodes
from app.conversation import ConversationManager
from app.telegram_bot import HookReelBot
from app.webui import run_webui, set_conversation_manager, set_restart_event

logger = get_logger("hookreel.main")

POLL_INTERVAL = 60  # seconds
EPISODE_CHECK_INTERVAL = 86400  # seconds — once per day
HLS_CLEANUP_EVERY = 10  # polling cycles — every ~10 minutes
SESSION_CLEANUP_EVERY = 60  # polling cycles — every ~1 hour

# Shared restart event — set by the web UI, checked by the polling loop
restart_event = threading.Event()


def run_cycle():
    """
    Execute one polling cycle.

    Checks for completed downloads and processes each one.
    Logs a summary at the end of each cycle.
    """
    downloading = database.get_movies_by_status("downloading")
    completed_this_cycle = check_completed_downloads()
    processed_count = 0

    for movie in completed_this_cycle:
        logger.info(
            "[HookReel] Processing completed download: '%s'",
            movie["title"]
        )
        success = process_movie(movie)
        if success:
            processed_count += 1
        else:
            logger.warning(
                "[HookReel] Post-processing failed for '%s' (id=%d)",
                movie["title"], movie["id"]
            )

    total_complete = len(database.get_movies_by_status("complete"))
    logger.info(
        "[HookReel] Cycle — %d downloading, %d completed this cycle, %d total complete",
        len(downloading),
        processed_count,
        total_complete,
    )

def recover_stuck_downloads():
    """
    One-time startup recovery for downloads that completed in qBittorrent
    but were never post-processed due to the v1.0.1 polling loop bug.

    For movies: finds failed entries, checks qBittorrent for 100% progress,
    resets to 'downloading' so run_cycle() picks them up.

    For TV episodes: finds failed entries with no file_path, scans the
    Downloads folder for matching files by show title and S##E## pattern,
    sets file_path and resets to 'downloading' so run_cycle() picks them up.

    Safe: only recovers entries confirmed complete by qBittorrent or with
    a matching physical file in Downloads. Partial or missing downloads
    are left as 'failed'.
    """
    logger.info("[HookReel] Running startup recovery for stuck downloads")
    recovered_movies = 0
    recovered_episodes = 0

    # --- Movie recovery ---
    failed_movies = database.get_movies_by_status("failed")
    torrent_list = qbittorrent.get_torrent_list()
    torrent_by_hash = {}
    for t in torrent_list:
        h = (t.get("hash") or "").lower().strip()
        if h:
            torrent_by_hash[h] = t

    for movie in failed_movies:
        torrent_hash = (movie.get("torrent_hash") or "").lower().strip()
        if not torrent_hash:
            continue
        torrent = torrent_by_hash.get(torrent_hash)
        if not torrent:
            continue
        progress = torrent.get("progress", 0)
        if progress < 1.0:
            logger.info(
                "[HookReel] Recovery: skipping '%s' -- progress %.0f%%",
                movie["title"], progress * 100
            )
            continue
        database.update_movie_status(movie["id"], "downloading")
        logger.info(
            "[HookReel] Recovery: reset movie '%s' (id=%d) to downloading",
            movie["title"], movie["id"]
        )
        recovered_movies += 1

    # --- TV episode recovery ---
    failed_episodes = database.get_episodes_by_status("failed")
    downloads_path = config.DOWNLOADS_PATH
    try:
        downloads_files = os.listdir(downloads_path)
    except Exception:
        downloads_files = []

    for episode in failed_episodes:
        if episode.get("file_path"):
            continue
        show = database.get_show(episode["show_id"])
        if not show:
            continue
        season = episode.get("season") or 0
        ep_num = episode.get("episode") or 0
        ep_pattern = re.compile(
            r"[Ss]%02d[Ee]%02d" % (season, ep_num)
        )
        show_title = show.get("title", "").lower()
        show_words = re.sub(r"[^a-z0-9]", ".", show_title)
        matched_file = None
        for fname in downloads_files:
            fname_lower = fname.lower()
            if not ep_pattern.search(fname):
                continue
            if show_title.replace(" ", "") in fname_lower.replace(".", "").replace(" ", "") or \
               show_words[:10] in fname_lower:
                candidate = os.path.join(downloads_path, fname)
                if os.path.isfile(candidate):
                    matched_file = candidate
                    break
        if not matched_file:
            continue
        database.update_episode_status(
            episode["id"], "downloading", file_path=matched_file
        )
        logger.info(
            "[HookReel] Recovery: reset episode id=%d S%02dE%02d to downloading, path=%s",
            episode["id"], season, ep_num, matched_file
        )
        recovered_episodes += 1

    logger.info(
        "[HookReel] Recovery complete: %d movie(s), %d episode(s) re-queued",
        recovered_movies, recovered_episodes
    )

def do_agent_restart(conversation_manager_ref: list, bot=None) -> None:
    """
    Re-initialise the ConversationManager in response to a restart signal.

    Accepts a single-element list so the reference can be updated in-place
    and remain visible to the polling loop that called this function.

    Steps:
      1. Clear the restart flag
      2. Create a new ConversationManager (re-reads config via load_dotenv)
      3. Register it with the web UI so new chat sessions use the fresh agent
      4. Log confirmation

    Parameters:
        conversation_manager_ref: A one-element list holding the current
                                  ConversationManager instance. Updated
                                  in-place with the new instance.
    """
    logger.info("[HookReel] Restart signal received — reinitialising agent")
    restart_event.clear()

    try:
        new_manager = ConversationManager()
        conversation_manager_ref[0] = new_manager
        set_conversation_manager(new_manager)
        if bot is not None:
            bot.update_conversation_manager(new_manager)
        logger.info("[HookReel] Agent restart complete — all sessions reset")
    except Exception as error:
        logger.error("[HookReel] Agent restart failed: %s", error)


def main():
    """Start HookReel and run the polling loop indefinitely."""
    logger.info("[HookReel] Starting up — poll interval: %ds", POLL_INTERVAL)

    # Initialise database tables and run migrations
    database.initialise()
    database.initialise_pairing_tables()
    logger.info("[HookReel] Database ready")

    # Clean up any downloads stuck from a previous session
    cleaned = database.cleanup_stuck_downloads(hours=24)
    if cleaned:
        logger.info("[HookReel] Cleaned up %d stuck download(s) at startup", cleaned)

    # Recover downloads that completed but were never post-processed
    try:
        recover_stuck_downloads()
    except Exception as recovery_error:
        logger.error("[HookReel] Recovery error: %s", recovery_error)

    while True:
        try:
            run_cycle()
        except Exception as error:
            logger.error("[HookReel] Unhandled error in cycle: %s", error)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    from app.database import migrate
    migrate()
    database.initialise()
    database.initialise_pairing_tables()
    cleaned = database.cleanup_stuck_downloads(hours=24)
    if cleaned:
        logger.info("[HookReel] Cleaned up %d stuck download(s) at startup", cleaned)
    try:
        recover_stuck_downloads()
    except Exception as recovery_error:
        logger.error("[HookReel] Recovery error: %s", recovery_error)
    
    # Create initial ConversationManager
    conversation_manager = ConversationManager()
    logger.info("[HookReel] ConversationManager initialised and ready.")

    if "--chat" in sys.argv:
        print("\nHookReel AI — interactive chat mode")
        print("Type 'quit' or 'exit' to leave.\n")
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSetting sail. Goodbye!")
                break
            if user_input.lower() in ("quit", "exit", "q"):
                print("Setting sail. Goodbye!")
                break
            if not user_input:
                continue
            response = conversation_manager.handle_message("repl_user", user_input)
            print("HookReel: {}\n".format(response))

    else:
        # Register conversation manager and restart event with web UI
        set_conversation_manager(conversation_manager)
        set_restart_event(restart_event)

        # Use a list so do_agent_restart() can update the reference in-place
        conversation_manager_ref = [conversation_manager]

        # Start Telegram bot thread — must use its own event loop
        bot = HookReelBot(conversation_manager)
        bot_thread = threading.Thread(target=bot.run, daemon=True)
        bot_thread.start()
        logger.info("[HookReel] Telegram bot thread started.")

        # Start web UI thread
        webui_thread = threading.Thread(target=run_webui, daemon=True)
        webui_thread.start()
        logger.info("[HookReel] Web UI thread started on port 8765.")

        # Start polling loop — checks restart_event after each sleep
        logger.info("[HookReel] Starting polling loop.")
        last_episode_check = 0.0
        poll_cycle_count = 0

        while True:
            try:
                run_cycle()
            except Exception as poll_error:
                logger.error("[HookReel] Polling loop error: %s", poll_error)

            try:
                tv_completed = check_completed_tv_downloads()
                for episode in tv_completed:
                    show = database.get_show(episode["show_id"])
                    if show:
                        process_episode(episode, show)
            except Exception as tv_error:
                logger.error("[HookReel] TV polling loop error: %s", tv_error)

            now = time.time()
            if now - last_episode_check >= EPISODE_CHECK_INTERVAL:
                try:
                    check_new_episodes()
                    last_episode_check = now
                except Exception as monitor_error:
                    logger.error(
                        "[HookReel] Episode monitor error: %s", monitor_error
                    )

            # HLS stream cleanup — runs every HLS_CLEANUP_EVERY cycles
            # Only relevant when JELLYFIN_ENABLED=false
            poll_cycle_count += 1
            if not config.JELLYFIN_ENABLED and poll_cycle_count % HLS_CLEANUP_EVERY == 0:
                try:
                    from app.hls_streamer import hls_streamer
                    hls_streamer.cleanup_old_streams()
                except Exception as hls_error:
                    logger.error(
                        "[HookReel] HLS cleanup error: %s", hls_error
                    )
            # Session cleanup — runs every SESSION_CLEANUP_EVERY cycles
            if poll_cycle_count % SESSION_CLEANUP_EVERY == 0:
                try:
                    conversation_manager_ref[0].cleanup_expired_sessions()
                except Exception as session_error:
                    logger.error(
                        "[HookReel] Session cleanup error: %s", session_error
                    )
            time.sleep(POLL_INTERVAL)

            # Check for restart signal from the web UI settings page
            if restart_event.is_set():
                do_agent_restart(conversation_manager_ref, bot)
