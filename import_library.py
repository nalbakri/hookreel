#!/usr/bin/env python3
"""
import_library.py -- HookReel library import and enrichment tool.

Scans media folders and upserts records into hookreel.db.
Run manually inside the container. Never imported by the main app.

Usage:
    python import_library.py
    python import_library.py --dry-run
    python import_library.py --verbose
    python import_library.py --enrich
    python import_library.py --rename
    python import_library.py --path /data/extra/1
    python import_library.py --all-sources
    python import_library.py --enrich-jellyfin

Recommended order for new users:
    Step 1: python import_library.py --dry-run --verbose
    Step 2: python import_library.py
    Step 3: python import_library.py --enrich
    Step 4: python import_library.py --rename
    Step 5: Trigger Jellyfin library scan from web UI
"""

import argparse
import os
import re
import shutil
import time

from dotenv import load_dotenv

load_dotenv("/config/.env", override=False)

import app.config as config
from app.logger import get_logger
from app.database import (
    get_movies_by_title,
    get_movies_by_status,
    add_movie,
    update_movie_status,
    update_movie_file_path,
    get_show_by_title,
    add_show,
    get_episode,
    add_episode,
    update_episode_status,
    get_connection,
)

logger = get_logger(__name__)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v"}


# ---------------------------------------------------------------------------
# Extra media sources
# ---------------------------------------------------------------------------

def get_extra_sources():
    """
    Return a list of (label, path) tuples for all configured extra
    media sources. Skips any where the path is empty.
    """
    sources = []
    for i in range(1, 6):
        path = os.environ.get("EXTRA_MEDIA_{}".format(i), "")
        label = os.environ.get(
            "EXTRA_MEDIA_{}_LABEL".format(i), "Extra Source {}".format(i)
        )
        if path:
            sources.append((label, path))
    return sources


# ---------------------------------------------------------------------------
# Title / year parsing
# ---------------------------------------------------------------------------

_TITLE_PATTERNS = [
    re.compile(r"^(?P<title>.+?)\s+\((?P<year>\d{4})\)"),
    re.compile(
        r"^(?P<title>[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*)\."
        r"(?P<year>\d{4})[\.\s]"
    ),
    re.compile(r"^(?P<title>.+?)\s+(?P<year>\d{4})\s"),
    re.compile(r"^(?P<title>.+?)\s+(?P<year>\d{4})$"),
]

_JUNK_TAGS = re.compile(
    r"\b(BluRay|Blu-Ray|WEBRip|WEB-DL|HDRip|DVDRip|BDRip|"
    r"PROPER|REPACK|IMAX|EXTENDED|THEATRICAL|UNRATED|"
    r"1080p|720p|2160p|4K|UHD|x264|x265|HEVC|H264|H265|AAC|DTS|"
    r"YTS|YTS\.AM|YIFY|RARBG|Dual|YG|XviD|AC3|DD5\.1)\b",
    re.IGNORECASE,
)


def parse_movie_folder_name(name):
    """
    Extract title and year from a movie folder name or bare filename.
    Strips extension first if present.
    Returns (title, year) or (name, None).
    """
    base, ext = os.path.splitext(name)
    if ext.lower() in VIDEO_EXTENSIONS:
        name = base

    for pattern in _TITLE_PATTERNS:
        match = pattern.match(name)
        if match:
            raw_title = match.group("title")
            year = match.group("year")
            title = raw_title.replace(".", " ")
            title = _JUNK_TAGS.sub("", title)
            title = re.sub(r"\s{2,}", " ", title).strip()
            return title, year

    logger.warning("[HookReel] Could not parse year from: %s", name)
    return name, None


# ---------------------------------------------------------------------------
# Video file discovery
# ---------------------------------------------------------------------------

def find_largest_video_file(folder_path):
    """
    Walk a directory and return the path of the largest video file.
    Returns None if no video file found.
    """
    best_path = None
    best_size = 0
    for root, _dirs, files in os.walk(folder_path):
        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext.lower() not in VIDEO_EXTENSIONS:
                continue
            full_path = os.path.join(root, filename)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            if size > best_size:
                best_size = size
                best_path = full_path
    return best_path


# ---------------------------------------------------------------------------
# Metadata enrichment
# ---------------------------------------------------------------------------

def _enrich_movie_metadata(movie_id, title, year, dry_run=False, verbose=False):
    """
    Look up a movie via the configured metadata provider and store
    poster_url, overview, and rating in the database.
    Returns True if enriched, False if not found or error.
    """
    try:
        provider = config.METADATA_PROVIDER.lower()
        api_key = config.METADATA_API_KEY

        poster_url = None
        overview = None
        rating = None

        if provider == "tmdb":
            import httpx
            url = (
                "https://api.themoviedb.org/3/search/movie"
                "?api_key={}&query={}&year={}".format(api_key, title, year or "")
            )
            r = httpx.get(url, timeout=10)
            data = r.json()
            results = data.get("results", [])
            if results:
                item = results[0]
                poster = item.get("poster_path", "")
                if poster:
                    poster_url = "https://image.tmdb.org/t/p/w500{}".format(poster)
                overview = item.get("overview", "")
                vote = item.get("vote_average")
                if vote:
                    rating = str(vote)

        elif provider == "omdb":
            import httpx
            params = "t={}&apikey={}".format(title, api_key)
            if year:
                params += "&y={}".format(year)
            r = httpx.get(
                "http://www.omdbapi.com/?{}".format(params), timeout=10
            )
            data = r.json()
            if data.get("Response") == "True":
                poster_url = data.get("Poster", "")
                overview = data.get("Plot", "")
                rating = data.get("imdbRating", "")

        if poster_url or overview or rating:
            if not dry_run:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    """UPDATE movies SET poster_url=?, overview=?, rating=?
                       WHERE id=?""",
                    (poster_url, overview, rating, movie_id)
                )
                conn.commit()
                conn.close()
            if verbose:
                print("    [enriched] {} ({})".format(title, year))
            return True
        else:
            if verbose:
                print("    [no metadata] {} ({})".format(title, year))
            return False

    except Exception as exc:
        logger.warning(
            "[HookReel] Enrich failed for '%s': %s", title, exc
        )
        return False


# ---------------------------------------------------------------------------
# Jellyfin enrichment (original flag, kept for compatibility)
# ---------------------------------------------------------------------------

def _jellyfin_lookup(title):
    """Query Jellyfin for a movie by title. Returns jellyfin_item_id or None."""
    try:
        from app.jellyfin import get_jellyfin_item
        item = get_jellyfin_item(title, "Movie")
        if item:
            return item.get("Id")
    except Exception as exc:
        logger.warning(
            "[HookReel] Jellyfin lookup failed for '%s': %s", title, exc
        )
    return None


# ---------------------------------------------------------------------------
# Jellyfin library refresh
# ---------------------------------------------------------------------------

def trigger_jellyfin_refresh(verbose=False):
    """
    Send a library refresh signal to Jellyfin.
    Safe to call even if Jellyfin is disabled -- logs and returns.
    """
    if not config.JELLYFIN_ENABLED:
        if verbose:
            print("[Jellyfin] Jellyfin disabled -- skipping refresh")
        return
    try:
        import httpx
        url = "http://{}:{}/Library/Refresh".format(
            config.JELLYFIN_HOST, config.JELLYFIN_PORT
        )
        headers = {"X-Emby-Token": config.JELLYFIN_API_KEY}
        httpx.post(url, headers=headers, timeout=10)
        if verbose:
            print("[Jellyfin] Library refresh triggered")
        logger.info("[HookReel] Jellyfin library refresh triggered")
    except Exception as exc:
        logger.warning("[HookReel] Jellyfin refresh failed: %s", exc)


# ---------------------------------------------------------------------------
# Movie import
# ---------------------------------------------------------------------------

def import_movies(
    movies_path,
    dry_run=False,
    verbose=False,
    enrich=False,
    enrich_jellyfin=False,
    source_path=None,
):
    """
    Scan a movies path and upsert records into the database.
    Handles both subfolder layout and flat files in the root.
    Returns counters dict.
    """
    counters = {
        "scanned": 0,
        "already_complete": 0,
        "updated": 0,
        "inserted": 0,
        "skipped_no_video": 0,
        "errors": 0,
    }

    if not os.path.isdir(movies_path):
        logger.warning("[HookReel] Movies path not found: %s", movies_path)
        print("  [warning] Path not found or not mounted: {}".format(movies_path))
        return counters

    effective_source = source_path or movies_path
    entries = sorted(os.listdir(movies_path))

    for entry_name in entries:
        entry_path = os.path.join(movies_path, entry_name)

        # --- Flat file: bare video file directly in movies folder ---
        if os.path.isfile(entry_path):
            _, ext = os.path.splitext(entry_name)
            if ext.lower() not in VIDEO_EXTENSIONS:
                continue
            counters["scanned"] += 1
            title, year = parse_movie_folder_name(entry_name)
            video_path = entry_path

        # --- Subfolder layout ---
        elif os.path.isdir(entry_path):
            counters["scanned"] += 1
            title, year = parse_movie_folder_name(entry_name)
            video_path = find_largest_video_file(entry_path)
            if video_path is None:
                if verbose:
                    print("  [skip]   {} -- no video file".format(entry_name))
                counters["skipped_no_video"] += 1
                continue
        else:
            continue

        try:
            existing = get_movies_by_title(title)
        except Exception as exc:
            logger.error(
                "[HookReel] DB error looking up '%s': %s", title, exc
            )
            counters["errors"] += 1
            continue

        if existing:
            movie = existing[0]
            if movie["status"] == "complete" and movie.get("file_path"):
                if verbose:
                    print(
                        "  [ok]     {} ({}) -- already complete".format(
                            title, year
                        )
                    )
                counters["already_complete"] += 1
                continue

            if dry_run:
                print(
                    "  [would update] {} ({}) -> {}".format(
                        title, year, video_path
                    )
                )
                counters["updated"] += 1
                continue

            try:
                update_movie_file_path(movie["id"], video_path)
                update_movie_status(movie["id"], "complete")
                _set_movie_source_path(movie["id"], effective_source)
                if enrich:
                    _enrich_movie_metadata(
                        movie["id"], title, year,
                        dry_run=dry_run, verbose=verbose
                    )
                if verbose:
                    print(
                        "  [updated] {} ({}) -> {}".format(
                            title, year, video_path
                        )
                    )
                counters["updated"] += 1
            except Exception as exc:
                logger.error(
                    "[HookReel] Failed to update '%s': %s", title, exc
                )
                counters["errors"] += 1

        else:
            jellyfin_id = None
            if enrich_jellyfin:
                jellyfin_id = _jellyfin_lookup(title)

            if dry_run:
                jf = " [jellyfin={}]".format(jellyfin_id) if jellyfin_id else ""
                print(
                    "  [would insert] {} ({}) -> {}{}".format(
                        title, year, video_path, jf
                    )
                )
                counters["inserted"] += 1
                continue

            try:
                movie_id = add_movie(
                    provider_id=0,
                    title=title,
                    year=year or "0000",
                )
                update_movie_file_path(movie_id, video_path)
                update_movie_status(movie_id, "complete")
                _set_movie_source_path(movie_id, effective_source)
                if enrich:
                    _enrich_movie_metadata(
                        movie_id, title, year,
                        dry_run=dry_run, verbose=verbose
                    )
                if verbose:
                    print(
                        "  [inserted] {} ({}) -> {}".format(
                            title, year, video_path
                        )
                    )
                counters["inserted"] += 1
            except Exception as exc:
                logger.error(
                    "[HookReel] Failed to insert '%s': %s", title, exc
                )
                counters["errors"] += 1

    return counters


def _set_movie_source_path(movie_id, source_path):
    """Update source_path for a movie row."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE movies SET source_path=? WHERE id=?",
            (source_path, movie_id)
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning(
            "[HookReel] Could not set source_path for movie %d: %s",
            movie_id, exc
        )


# ---------------------------------------------------------------------------
# File renaming
# ---------------------------------------------------------------------------

def _jellyfin_movie_name(title, year):
    """Return Jellyfin-compatible folder and filename for a movie."""
    safe = re.sub(r'[<>:"/\\|?*]', "", "{} ({})".format(title, year or "0000"))
    return safe, "{}.mkv".format(safe)


def rename_movies(movies_path, dry_run=False, verbose=False):
    """
    Rename movie files and folders to Jellyfin-compatible format.
    Prints a plan and asks for confirmation before doing anything.
    Returns count of renames performed.
    """
    plan = []
    entries = sorted(os.listdir(movies_path))

    for entry_name in entries:
        entry_path = os.path.join(movies_path, entry_name)

        if os.path.isfile(entry_path):
            _, ext = os.path.splitext(entry_name)
            if ext.lower() not in VIDEO_EXTENSIONS:
                continue
            title, year = parse_movie_folder_name(entry_name)
            folder_name, file_name = _jellyfin_movie_name(title, year)
            target_folder = os.path.join(movies_path, folder_name)
            target_file = os.path.join(target_folder, file_name)
            plan.append(("flat", entry_path, target_folder, target_file))

        elif os.path.isdir(entry_path):
            title, year = parse_movie_folder_name(entry_name)
            folder_name, file_name = _jellyfin_movie_name(title, year)
            target_folder = os.path.join(movies_path, folder_name)
            video = find_largest_video_file(entry_path)
            if not video:
                continue
            target_file = os.path.join(target_folder, file_name)
            if entry_path != target_folder:
                plan.append(("folder", entry_path, target_folder, target_file))

    if not plan:
        print("Nothing to rename.")
        return 0

    print("\n--- Rename plan ({} items) ---".format(len(plan)))
    for kind, src, tgt_folder, tgt_file in plan:
        print("  {} -> {}".format(src, tgt_file))

    if dry_run:
        print("\n[dry-run] No changes made.")
        return 0

    answer = input("\nProceed with rename? [y/N]: ").strip().lower()
    if answer != "y":
        print("Rename cancelled.")
        return 0

    count = 0
    for kind, src, tgt_folder, tgt_file in plan:
        try:
            os.makedirs(tgt_folder, exist_ok=True)
            if kind == "flat":
                shutil.move(src, tgt_file)
            else:
                video = find_largest_video_file(src)
                if video:
                    shutil.move(video, tgt_file)
            if verbose:
                print("  [renamed] -> {}".format(tgt_file))
            logger.info(
                "[HookReel] Renamed: %s -> %s", src, tgt_file
            )
            count += 1
        except Exception as exc:
            logger.error(
                "[HookReel] Rename failed for %s: %s", src, exc
            )
            print("  [error] {} -- {}".format(src, exc))

    return count


# ---------------------------------------------------------------------------
# TV import
# ---------------------------------------------------------------------------

_EPISODE_PATTERNS = [
    re.compile(r"[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,3})"),
    re.compile(r"(?P<season>\d{1,2})x(?P<episode>\d{2,3})"),
]


def parse_episode_numbers(filename):
    """Extract (season, episode) integers from filename or (None, None)."""
    for pattern in _EPISODE_PATTERNS:
        match = pattern.search(filename)
        if match:
            return int(match.group("season")), int(match.group("episode"))
    return None, None


def _get_or_create_show(show_name):
    """Return show row for show_name, creating it if needed."""
    existing = get_show_by_title(show_name)
    for show in existing:
        if show["title"].lower() == show_name.lower():
            return show
    show_id = add_show(
        provider_id="imported",
        title=show_name,
        year="0000",
    )
    results = get_show_by_title(show_name)
    for show in results:
        if show["title"].lower() == show_name.lower():
            return show
    return {"id": show_id, "title": show_name}


def _upsert_episode(
    show_id, season, episode, file_path, source, dry_run, verbose
):
    """Insert or update an episode record. Returns result string."""
    existing = get_episode(show_id, season, episode)

    if existing:
        if existing["status"] == "complete" and existing.get("file_path"):
            if verbose:
                print(
                    "    [ok] S{:02d}E{:02d} -- already complete".format(
                        season, episode
                    )
                )
            return "already_complete"

        if dry_run:
            print(
                "    [would update] S{:02d}E{:02d} -> {}".format(
                    season, episode, file_path
                )
            )
            return "updated"

        success = update_episode_status(
            existing["id"], "complete", file_path=file_path
        )
        if success:
            _set_episode_source_path(existing["id"], source)
            if verbose:
                print(
                    "    [updated] S{:02d}E{:02d} -> {}".format(
                        season, episode, file_path
                    )
                )
            return "updated"
        return "error"

    else:
        if dry_run:
            print(
                "    [would insert] S{:02d}E{:02d} -> {}".format(
                    season, episode, file_path
                )
            )
            return "inserted"

        episode_id = add_episode(
            show_id=show_id,
            season=season,
            episode=episode,
            title="S{:02d}E{:02d}".format(season, episode),
            air_date=None,
        )
        if episode_id == -1:
            logger.error(
                "[HookReel] add_episode failed S%02dE%02d show_id=%d",
                season, episode, show_id,
            )
            return "error"

        success = update_episode_status(
            episode_id, "complete", file_path=file_path
        )
        if success:
            _set_episode_source_path(episode_id, source)
            if verbose:
                print(
                    "    [inserted] S{:02d}E{:02d} -> {}".format(
                        season, episode, file_path
                    )
                )
            return "inserted"
        return "error"


def _set_episode_source_path(episode_id, source_path):
    """Update source_path for an episode row."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE episodes SET source_path=? WHERE id=?",
            (source_path, episode_id)
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning(
            "[HookReel] Could not set source_path for episode %d: %s",
            episode_id, exc
        )


def import_tv(tv_path, dry_run=False, verbose=False, source_path=None):
    """
    Scan a TV path for show folders, season subfolders, and episode files.
    Returns counters dict.
    """
    counters = {
        "shows_found": 0,
        "episodes_found": 0,
        "already_complete": 0,
        "updated": 0,
        "inserted": 0,
        "errors": 0,
    }

    if not os.path.isdir(tv_path):
        logger.warning("[HookReel] TV path not found: %s", tv_path)
        print("  [warning] Path not found or not mounted: {}".format(tv_path))
        return counters

    effective_source = source_path or tv_path
    show_folders = sorted(os.listdir(tv_path))

    for show_folder in show_folders:
        show_path = os.path.join(tv_path, show_folder)
        if not os.path.isdir(show_path):
            continue

        show_name = show_folder
        counters["shows_found"] += 1

        if verbose:
            print("  Show: {}".format(show_name))

        if not dry_run:
            show = _get_or_create_show(show_name)
            show_id = show["id"]
        else:
            show_id = None

        for root, _dirs, files in os.walk(show_path):
            for filename in sorted(files):
                _, ext = os.path.splitext(filename)
                if ext.lower() not in VIDEO_EXTENSIONS:
                    continue

                season, episode = parse_episode_numbers(filename)
                if season is None:
                    if verbose:
                        print(
                            "    [skip] {} -- could not parse episode".format(
                                filename
                            )
                        )
                    continue

                file_path = os.path.join(root, filename)
                counters["episodes_found"] += 1

                if dry_run:
                    print(
                        "    [would import] S{:02d}E{:02d} -> {}".format(
                            season, episode, file_path
                        )
                    )
                    counters["inserted"] += 1
                    continue

                result = _upsert_episode(
                    show_id, season, episode,
                    file_path, effective_source,
                    dry_run, verbose
                )
                counters[result] = counters.get(result, 0) + 1

    return counters


# ---------------------------------------------------------------------------
# Scan a single path (--path flag)
# ---------------------------------------------------------------------------

def scan_path(
    path,
    dry_run=False,
    verbose=False,
    enrich=False,
    enrich_jellyfin=False,
    is_tv=False,
):
    """
    Scan a single arbitrary path as either movies or TV content.
    Tries to auto-detect based on folder structure if is_tv not set.
    """
    if is_tv:
        return None, import_tv(
            path, dry_run=dry_run, verbose=verbose, source_path=path
        )
    else:
        return import_movies(
            path,
            dry_run=dry_run,
            verbose=verbose,
            enrich=enrich,
            enrich_jellyfin=enrich_jellyfin,
            source_path=path,
        ), None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Parse arguments and run the import."""
    parser = argparse.ArgumentParser(
        description="Import existing media library into HookReel."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be imported without writing to database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every file found and the action taken.",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Fetch metadata (poster, overview, rating) from provider.",
    )
    parser.add_argument(
        "--enrich-jellyfin",
        action="store_true",
        help="Query Jellyfin for each movie to populate jellyfin_item_id.",
    )
    parser.add_argument(
        "--rename",
        action="store_true",
        help="Rename files to Jellyfin-compatible format after import.",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Scan only this specific path instead of default folders.",
    )
    parser.add_argument(
        "--all-sources",
        action="store_true",
        help="Scan default folders plus all configured EXTRA_MEDIA paths.",
    )

    args = parser.parse_args()

    if args.dry_run:
        print("[HookReel] DRY RUN -- no database changes will be made.\n")

    start = time.monotonic()
    total_movies_inserted = 0
    total_tv_inserted = 0

    # --- Single path mode ---
    if args.path:
        print("=== Scanning {} ===".format(args.path))
        m_counters = import_movies(
            args.path,
            dry_run=args.dry_run,
            verbose=args.verbose,
            enrich=args.enrich,
            enrich_jellyfin=args.enrich_jellyfin,
            source_path=args.path,
        )
        _print_movie_counters(m_counters)
        total_movies_inserted += m_counters["inserted"]

    else:
        # --- Default movies path ---
        movies_path = config.MOVIES_PATH
        print("=== Movie Import ({}) ===".format(movies_path))
        m_counters = import_movies(
            movies_path,
            dry_run=args.dry_run,
            verbose=args.verbose,
            enrich=args.enrich,
            enrich_jellyfin=args.enrich_jellyfin,
            source_path=movies_path,
        )
        _print_movie_counters(m_counters)
        total_movies_inserted += m_counters["inserted"]

        # --- Default TV path ---
        tv_path = config.TV_PATH
        print("\n=== TV Import ({}) ===".format(tv_path))
        tv_counters = import_tv(
            tv_path,
            dry_run=args.dry_run,
            verbose=args.verbose,
            source_path=tv_path,
        )
        _print_tv_counters(tv_counters)
        total_tv_inserted += tv_counters["inserted"]

        # --- Extra sources (--all-sources flag) ---
        if args.all_sources:
            extra_sources = get_extra_sources()
            if not extra_sources:
                print("\n[No extra media sources configured]")
            for label, path in extra_sources:
                if not os.path.isdir(path):
                    print(
                        "\n[warning] Extra source '{}' at {} is not "
                        "mounted or does not exist -- skipping".format(
                            label, path
                        )
                    )
                    logger.warning(
                        "[HookReel] Extra media source '%s' at '%s' "
                        "appears empty or unmounted",
                        label, path
                    )
                    continue

                print("\n=== Extra Source: {} ({}) ===".format(label, path))
                ec = import_movies(
                    path,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                    enrich=args.enrich,
                    enrich_jellyfin=args.enrich_jellyfin,
                    source_path=path,
                )
                _print_movie_counters(ec)
                total_movies_inserted += ec["inserted"]

    # --- Rename pass (after all imports) ---
    if args.rename and not args.path:
        print("\n=== Rename Pass ===")
        count = rename_movies(
            config.MOVIES_PATH,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        print("Renamed: {}".format(count))

    # --- Jellyfin refresh ---
    if not args.dry_run and (total_movies_inserted > 0 or total_tv_inserted > 0):
        trigger_jellyfin_refresh(verbose=args.verbose)

    elapsed = time.monotonic() - start
    print("\n=== Done in {:.1f}s ===".format(elapsed))
    print(
        "Movies added: {}  TV episodes added: {}".format(
            total_movies_inserted, total_tv_inserted
        )
    )


def _print_movie_counters(c):
    print("  Scanned:           {}".format(c["scanned"]))
    print("  Already complete:  {}".format(c["already_complete"]))
    print("  Updated:           {}".format(c["updated"]))
    print("  Newly inserted:    {}".format(c["inserted"]))
    print("  Skipped/no video:  {}".format(c["skipped_no_video"]))
    print("  Errors:            {}".format(c["errors"]))


def _print_tv_counters(c):
    print("  Shows found:       {}".format(c["shows_found"]))
    print("  Episodes found:    {}".format(c["episodes_found"]))
    print("  Already complete:  {}".format(c["already_complete"]))
    print("  Updated:           {}".format(c["updated"]))
    print("  Newly inserted:    {}".format(c["inserted"]))
    print("  Errors:            {}".format(c["errors"]))


if __name__ == "__main__":
    main()
