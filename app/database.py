"""
HookReel database layer.
Manages SQLite persistence for movie requests and download tracking.
Includes automatic migration from tmdb_id to provider_id.
"""

import sqlite3
from datetime import datetime
from app import config
from app.logger import get_logger

logger = get_logger(__name__)

DB_PATH = config.DB_PATH


def get_connection():
    """Open and return a SQLite connection with row_factory set to Row."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def migrate():
    """
    Run database migrations safely and idempotently.
    Currently handles: renaming tmdb_id column to provider_id.
    Safe to call multiple times — checks state before acting.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Check current columns in movies table
        cursor.execute("PRAGMA table_info(movies)")
        columns = [row["name"] for row in cursor.fetchall()]

        if "tmdb_id" in columns and "provider_id" not in columns:
            logger.info("[HookReel] Migration: renaming tmdb_id → provider_id")

            # SQLite does not support RENAME COLUMN before version 3.25.
            # Use the safe recreate pattern for compatibility.
            cursor.executescript("""
                BEGIN;

                CREATE TABLE IF NOT EXISTS movies_new (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id  INTEGER NOT NULL,
                    title        TEXT    NOT NULL,
                    year         TEXT,
                    status       TEXT    NOT NULL DEFAULT 'searching',
                    torrent_hash TEXT,
                    download_url TEXT,
                    file_path    TEXT,
                    added_date   TEXT    NOT NULL,
                    updated_date TEXT    NOT NULL
                );

                INSERT INTO movies_new
                    (id, provider_id, title, year, status,
                     torrent_hash, download_url, file_path,
                     added_date, updated_date)
                SELECT
                    id, tmdb_id, title, year, status,
                    torrent_hash, download_url, file_path,
                    added_date, updated_date
                FROM movies;

                DROP TABLE movies;

                ALTER TABLE movies_new RENAME TO movies;

                COMMIT;
            """)
            connection.commit()
            logger.info("[HookReel] Migration complete: tmdb_id renamed to provider_id")

        elif "provider_id" in columns:
            logger.debug("[HookReel] Migration: provider_id already present, skipping")

        else:
            logger.warning("[HookReel] Migration: unexpected schema state — columns: %s", columns)

    except Exception as error:
        logger.error("[HookReel] Migration error: %s", error)
        connection.rollback()
    finally:
        connection.close()


def initialise():
    """
    Create the movies table if it does not exist, then run migrations.
    Called once at startup.
    """
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_id  INTEGER NOT NULL,
            title        TEXT    NOT NULL,
            year         TEXT,
            status       TEXT    NOT NULL DEFAULT 'searching',
            torrent_hash TEXT,
            download_url TEXT,
            file_path    TEXT,
            added_date   TEXT    NOT NULL,
            updated_date TEXT    NOT NULL
        )
    """)

    connection.commit()
    connection.close()

    
    # Always run migration after table creation check
    migrate()
    _create_tv_tables()
    _create_watch_history_table()
    _create_download_events_table()
    _migrate_phase8_columns()
    _migrate_v11_columns()
    logger.info("[HookReel] Database initialised at %s", DB_PATH)


def add_movie(provider_id: int, title: str, year: str) -> int:
    """
    Insert a new movie request into the database.
    Returns the new row id.
    """
    now = datetime.utcnow().isoformat()
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO movies (provider_id, title, year, status, added_date, updated_date)
        VALUES (?, ?, ?, 'searching', ?, ?)
    """, (provider_id, title, year, now, now))

    row_id = cursor.lastrowid
    connection.commit()
    connection.close()

    logger.info("[HookReel] Added movie to database: %s (%s) id=%d", title, year, row_id)
    return row_id


def get_movie_by_id(movie_id: int) -> dict:
    """Return a single movie row by its database id, or None if not found."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
    row = cursor.fetchone()
    connection.close()

    return dict(row) if row else None


def get_movies_by_status(status: str) -> list:
    """Return all movie rows with the given status as a list of dicts."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM movies WHERE status = ?", (status,))
    rows = cursor.fetchall()
    connection.close()

    return [dict(row) for row in rows]


def update_movie_status(movie_id: int, status: str):
    """Update the status field for a movie row."""
    now = datetime.utcnow().isoformat()
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE movies SET status = ?, updated_date = ? WHERE id = ?
    """, (status, now, movie_id))

    connection.commit()
    connection.close()
    logger.debug("[HookReel] Movie id=%d status → %s", movie_id, status)


def update_movie_torrent_hash(movie_id: int, torrent_hash: str):
    """Store the torrent hash for a downloading movie."""
    now = datetime.utcnow().isoformat()
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE movies SET torrent_hash = ?, updated_date = ? WHERE id = ?
    """, (torrent_hash, now, movie_id))

    connection.commit()
    connection.close()
    logger.debug("[HookReel] Movie id=%d torrent_hash stored", movie_id)


def update_movie_file_path(movie_id: int, file_path: str):
    """Store the final file path after post-processing."""
    now = datetime.utcnow().isoformat()
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE movies SET file_path = ?, updated_date = ? WHERE id = ?
    """, (file_path, now, movie_id))

    connection.commit()
    connection.close()
    logger.debug("[HookReel] Movie id=%d file_path stored: %s", movie_id, file_path)


def get_all_movies() -> list:
    """Return all movie rows as a list of dicts."""
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM movies ORDER BY added_date DESC")
    rows = cursor.fetchall()
    connection.close()

    return [dict(row) for row in rows]

def cleanup_stuck_downloads(hours: int = 24) -> int:
    """
    Find movies stuck in 'downloading' status for longer than the given
    number of hours and mark them as 'failed'.

    Parameters:
        hours: How many hours a movie must have been in 'downloading'
               status before it is considered stuck. Default is 24.
               Pass 0 to clean up all downloading rows immediately.

    Returns:
        The number of movies updated.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        if hours == 0:
            cursor.execute(
                "SELECT id, title FROM movies WHERE status = 'downloading'"
            )
        else:
            cursor.execute(
                """
                SELECT id, title FROM movies
                WHERE status = 'downloading'
                AND updated_date < datetime('now', ? || ' hours')
                """,
                ("-{}".format(hours),)
            )

        rows = cursor.fetchall()
        count = 0
        now = datetime.utcnow().isoformat()

        for row in rows:
            cursor.execute(
                "UPDATE movies SET status = 'failed', updated_date = ? WHERE id = ?",
                (now, row["id"])
            )
            logger.info(
                "[HookReel] cleanup_stuck_downloads: marked '%s' (id=%d) as failed",
                row["title"], row["id"]
            )
            count += 1

        connection.commit()
        logger.info("[HookReel] cleanup_stuck_downloads: %d row(s) cleaned up", count)
        return count

    except Exception as error:
        logger.error("[HookReel] cleanup_stuck_downloads error: %s", error)
        connection.rollback()
        return 0

    finally:
        connection.close()


def delete_test_rows() -> int:
    """
    Delete rows from the movies table where the title matches known
    test patterns (e.g. 'Test Movie').

    Returns:
        The number of rows deleted.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT id, title FROM movies
            WHERE title LIKE '%Test Movie%'
               OR title LIKE '%test movie%'
               OR title LIKE '%TestMovie%'
            """
        )
        rows = cursor.fetchall()
        count = 0

        for row in rows:
            cursor.execute("DELETE FROM movies WHERE id = ?", (row["id"],))
            logger.info(
                "[HookReel] delete_test_rows: deleted '%s' (id=%d)",
                row["title"], row["id"]
            )
            count += 1

        connection.commit()
        logger.info("[HookReel] delete_test_rows: %d row(s) deleted", count)
        return count

    except Exception as error:
        logger.error("[HookReel] delete_test_rows error: %s", error)
        connection.rollback()
        return 0

    finally:
        connection.close()

def get_movies_by_title(title: str) -> list:
    """
    Search for movies by title, case-insensitive partial match.

    Returns ALL matching rows regardless of status — including
    failed, quarantined, downloading, and complete entries.
    This allows check_exists to detect previous attempts and
    prevent silent duplicate entries.

    Parameters:
        title: The title string to search for (partial match).

    Returns:
        A list of matching movie dicts, empty list if none found.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT * FROM movies WHERE LOWER(title) LIKE LOWER(?) ORDER BY added_date DESC",
            (f"%{title}%",)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_movies_by_title error: %s", error)
        return []
    finally:
        connection.close()

def initialise_pairing_tables():
    """
    Create the pairing_codes and approved_telegram_ids tables
    if they do not already exist.

    Called once at startup alongside initialise().
    """
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pairing_codes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT    NOT NULL UNIQUE,
            created_at  TEXT    NOT NULL,
            expires_at  TEXT    NOT NULL,
            used        INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approved_telegram_ids (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL UNIQUE,
            added_date  TEXT    NOT NULL
        )
    """)

    connection.commit()
    connection.close()
    logger.info("[HookReel] Pairing tables initialised")


def store_pairing_code(code: str, expires_at: str) -> bool:
    """
    Store a new one-time pairing code in the database.

    Parameters:
        code:       The 6-digit code string.
        expires_at: ISO format datetime string when the code expires.

    Returns:
        True if stored successfully, False on error.
    """
    now = datetime.utcnow().isoformat()
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO pairing_codes (code, created_at, expires_at, used)
            VALUES (?, ?, ?, 0)
            """,
            (code, now, expires_at)
        )
        connection.commit()
        logger.info("[HookReel] Pairing code stored (expires %s)", expires_at)
        return True
    except Exception as error:
        logger.error("[HookReel] store_pairing_code error: %s", error)
        connection.rollback()
        return False
    finally:
        connection.close()


def verify_and_consume_pairing_code(code: str, telegram_id: int) -> bool:
    """
    Verify a pairing code and approve the Telegram user if valid.

    Checks the code exists, is not used, and has not expired.
    If valid: marks code as used and adds telegram_id to approved list.

    Parameters:
        code:        The 6-digit code string submitted by the user.
        telegram_id: The Telegram user ID to approve.

    Returns:
        True if the code was valid and the user was approved.
        False if the code was invalid, expired, or already used.
    """
    now = datetime.utcnow().isoformat()
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT id, expires_at, used FROM pairing_codes
            WHERE code = ?
            """,
            (code,)
        )
        row = cursor.fetchone()

        if not row:
            logger.warning("[HookReel] Pairing code not found: %s", code)
            return False

        if row["used"]:
            logger.warning("[HookReel] Pairing code already used: %s", code)
            return False

        if row["expires_at"] < now:
            logger.warning("[HookReel] Pairing code expired: %s", code)
            return False

        cursor.execute(
            "UPDATE pairing_codes SET used = 1 WHERE id = ?",
            (row["id"],)
        )

        cursor.execute(
            """
            INSERT OR IGNORE INTO approved_telegram_ids
            (telegram_id, added_date) VALUES (?, ?)
            """,
            (telegram_id, now)
        )

        connection.commit()
        logger.info(
            "[HookReel] Pairing successful: telegram_id=%d approved", telegram_id
        )
        return True

    except Exception as error:
        logger.error("[HookReel] verify_and_consume_pairing_code error: %s", error)
        connection.rollback()
        return False
    finally:
        connection.close()


def is_approved_telegram_id(telegram_id: int) -> bool:
    """
    Check whether a Telegram user ID is in the approved list.

    Parameters:
        telegram_id: The Telegram user ID to check.

    Returns:
        True if the ID is approved, False otherwise.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT id FROM approved_telegram_ids WHERE telegram_id = ?",
            (telegram_id,)
        )
        row = cursor.fetchone()
        return row is not None
    except Exception as error:
        logger.error("[HookReel] is_approved_telegram_id error: %s", error)
        return False
    finally:
        connection.close()


def get_approved_telegram_ids() -> list:
    """
    Return all approved Telegram user IDs as a list of integers.

    Returns:
        A list of approved telegram_id integers.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "SELECT telegram_id FROM approved_telegram_ids ORDER BY added_date"
        )
        rows = cursor.fetchall()
        return [row["telegram_id"] for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_approved_telegram_ids error: %s", error)
        return []
    finally:
        connection.close()


def remove_approved_telegram_id(telegram_id: int) -> bool:
    """
    Remove a Telegram user ID from the approved list.

    Parameters:
        telegram_id: The Telegram user ID to remove.

    Returns:
        True if removed, False on error.
    """
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "DELETE FROM approved_telegram_ids WHERE telegram_id = ?",
            (telegram_id,)
        )
        connection.commit()
        logger.info(
            "[HookReel] Removed approved telegram_id=%d", telegram_id
        )
        return True
    except Exception as error:
        logger.error("[HookReel] remove_approved_telegram_id error: %s", error)
        connection.rollback()
        return False
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# TV shows — table creation
# ---------------------------------------------------------------------------

def _create_tv_tables():
    """
    Create the shows and episodes tables if they do not exist.
    Called automatically by initialise() at startup.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shows (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id  TEXT NOT NULL,
                title        TEXT NOT NULL,
                year         TEXT,
                status       TEXT DEFAULT 'tracked',
                added_date   TEXT NOT NULL,
                updated_date TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id      INTEGER NOT NULL,
                season       INTEGER NOT NULL,
                episode      INTEGER NOT NULL,
                title        TEXT,
                air_date     TEXT,
                status       TEXT DEFAULT 'missing',
                torrent_hash TEXT,
                download_url TEXT,
                file_path    TEXT,
                added_date   TEXT NOT NULL,
                updated_date TEXT NOT NULL,
                FOREIGN KEY (show_id) REFERENCES shows(id)
            )
        """)
        connection.commit()
        logger.info("[HookReel] TV tables ready")
    except Exception as error:
        logger.error("[HookReel] _create_tv_tables error: %s", error)
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# TV shows — show-level functions
# ---------------------------------------------------------------------------

def add_show(provider_id: str, title: str, year: str) -> int:
    """
    Add a TV show to the shows table.
    Parameters:
        provider_id: External provider ID (e.g. TVmaze show ID as string).
        title:       Show title.
        year:        Premiere year as string.
    Returns:
        The new show's database ID, or -1 on error.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        now = datetime.utcnow().isoformat()
        cursor.execute(
            """
            INSERT INTO shows
                (provider_id, title, year, status, added_date, updated_date)
            VALUES (?, ?, ?, 'tracked', ?, ?)
            """,
            (str(provider_id), title, year, now, now)
        )
        connection.commit()
        show_id = cursor.lastrowid
        logger.info("[HookReel] Added show id=%d title=%s", show_id, title)
        return show_id
    except Exception as error:
        logger.error("[HookReel] add_show error: %s", error)
        connection.rollback()
        return -1
    finally:
        connection.close()


def get_show(show_id: int) -> dict:
    """
    Fetch a single show by its database ID.
    Parameters:
        show_id: The show's database ID.
    Returns:
        Dict of show fields, or None if not found.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT * FROM shows WHERE id = ?", (show_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as error:
        logger.error("[HookReel] get_show error: %s", error)
        return None
    finally:
        connection.close()


def get_show_by_title(title: str) -> list:
    """
    Search shows table by title (case-insensitive partial match).
    Parameters:
        title: Search string.
    Returns:
        List of matching show dicts.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT * FROM shows WHERE LOWER(title) LIKE LOWER(?)",
            (f"%{title}%",)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_show_by_title error: %s", error)
        return []
    finally:
        connection.close()


def get_all_shows() -> list:
    """
    Return all shows in the database ordered by title.
    Returns:
        List of show dicts.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT * FROM shows ORDER BY title")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_all_shows error: %s", error)
        return []
    finally:
        connection.close()


def update_show_status(show_id: int, status: str) -> bool:
    """
    Update the status of a show.
    Valid values: tracked, ended, abandoned.
    Parameters:
        show_id: The show's database ID.
        status:  New status string.
    Returns:
        True on success, False on error.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        now = datetime.utcnow().isoformat()
        cursor.execute(
            "UPDATE shows SET status = ?, updated_date = ? WHERE id = ?",
            (status, now, show_id)
        )
        connection.commit()
        logger.info(
            "[HookReel] Updated show id=%d status=%s", show_id, status
        )
        return True
    except Exception as error:
        logger.error("[HookReel] update_show_status error: %s", error)
        connection.rollback()
        return False
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# TV shows — episode-level functions
# ---------------------------------------------------------------------------

def add_episode(
    show_id: int,
    season: int,
    episode: int,
    title: str,
    air_date: str
) -> int:
    """
    Add an episode to the episodes table.
    Parameters:
        show_id:  Parent show database ID.
        season:   Season number (integer).
        episode:  Episode number within season (integer).
        title:    Episode title.
        air_date: Air date as ISO string or None.
    Returns:
        The new episode's database ID, or -1 on error.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        now = datetime.utcnow().isoformat()
        cursor.execute(
            """
            INSERT INTO episodes
                (show_id, season, episode, title, air_date,
                 status, added_date, updated_date)
            VALUES (?, ?, ?, ?, ?, 'missing', ?, ?)
            """,
            (show_id, season, episode, title, air_date, now, now)
        )
        connection.commit()
        episode_id = cursor.lastrowid
        logger.info(
            "[HookReel] Added episode show_id=%d S%02dE%02d id=%d",
            show_id, season, episode, episode_id
        )
        return episode_id
    except Exception as error:
        logger.error("[HookReel] add_episode error: %s", error)
        connection.rollback()
        return -1
    finally:
        connection.close()


def get_episode(show_id: int, season: int, episode: int) -> dict:
    """
    Fetch a single episode by show, season, and episode number.
    Parameters:
        show_id:  Parent show database ID.
        season:   Season number.
        episode:  Episode number.
    Returns:
        Dict of episode fields, or None if not found.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM episodes
            WHERE show_id = ? AND season = ? AND episode = ?
            """,
            (show_id, season, episode)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as error:
        logger.error("[HookReel] get_episode error: %s", error)
        return None
    finally:
        connection.close()


def get_episodes_for_show(show_id: int) -> list:
    """
    Return all episodes for a show ordered by season and episode number.
    Parameters:
        show_id: Parent show database ID.
    Returns:
        List of episode dicts.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM episodes
            WHERE show_id = ?
            ORDER BY season, episode
            """,
            (show_id,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_episodes_for_show error: %s", error)
        return []
    finally:
        connection.close()


def get_missing_episodes(show_id: int) -> list:
    """
    Return all episodes for a show with status=missing.
    Parameters:
        show_id: Parent show database ID.
    Returns:
        List of missing episode dicts ordered by season and episode.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM episodes
            WHERE show_id = ? AND status = 'missing'
            ORDER BY season, episode
            """,
            (show_id,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_missing_episodes error: %s", error)
        return []
    finally:
        connection.close()


def get_episodes_by_status(status: str) -> list:
    """
    Return all episodes across all shows with the given status.
    Parameters:
        status: Episode status string to filter by.
    Returns:
        List of episode dicts.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT * FROM episodes WHERE status = ? ORDER BY show_id, season, episode",
            (status,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_episodes_by_status error: %s", error)
        return []
    finally:
        connection.close()


def update_episode_status(episode_id: int, status: str, **kwargs) -> bool:
    """
    Update the status of an episode, with optional field updates.
    Parameters:
        episode_id: The episode's database ID.
        status:     New status string.
        **kwargs:   Optional fields to update:
                    torrent_hash, download_url, file_path
    Returns:
        True on success, False on error.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        now = datetime.utcnow().isoformat()
        allowed_fields = {"torrent_hash", "download_url", "file_path"}
        extra_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        set_clauses = ["status = ?", "updated_date = ?"]
        values = [status, now]
        for field, value in extra_fields.items():
            set_clauses.append(f"{field} = ?")
            values.append(value)
        values.append(episode_id)
        query = f"UPDATE episodes SET {', '.join(set_clauses)} WHERE id = ?"
        cursor.execute(query, values)
        connection.commit()
        logger.info(
            "[HookReel] Updated episode id=%d status=%s", episode_id, status
        )
        return True
    except Exception as error:
        logger.error("[HookReel] update_episode_status error: %s", error)
        connection.rollback()
        return False
    finally:
        connection.close()


def episode_exists(show_id: int, season: int, episode: int) -> bool:
    """
    Check whether an episode already exists in the database.
    Parameters:
        show_id:  Parent show database ID.
        season:   Season number.
        episode:  Episode number.
    Returns:
        True if the episode row exists, False otherwise.
    """
    return get_episode(show_id, season, episode) is not None


def get_next_episode(show_id: int) -> dict:
    """
    Find the next episode to watch or download for a show.
    Returns the lowest season/episode with status=missing or status=complete.
    Parameters:
        show_id: Parent show database ID.
    Returns:
        Episode dict, or None if nothing is missing or show is complete.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM episodes
            WHERE show_id = ? AND status IN ('missing', 'complete')
            ORDER BY season, episode
            LIMIT 1
            """,
            (show_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as error:
        logger.error("[HookReel] get_next_episode error: %s", error)
        return None
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Watch history — table creation
# ---------------------------------------------------------------------------

def _create_watch_history_table():
    """
    Create the watch_history table if it does not exist.
    Called automatically by initialise() at startup.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watch_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                media_type       TEXT    NOT NULL,
                media_id         INTEGER NOT NULL,
                title            TEXT    NOT NULL,
                watched_at       TEXT    NOT NULL,
                position_seconds INTEGER DEFAULT 0,
                completed        INTEGER DEFAULT 0,
                jellyfin_item_id TEXT
            )
        """)
        connection.commit()
        logger.info("[HookReel] Watch history table ready")
    except Exception as error:
        logger.error("[HookReel] _create_watch_history_table error: %s", error)
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Watch history — functions
# ---------------------------------------------------------------------------

def add_watch_event(
    media_type: str,
    media_id: int,
    title: str,
    jellyfin_item_id: str = None
) -> int:
    """
    Record a watch event in the watch_history table.

    Parameters:
        media_type:       Either 'movie' or 'episode'.
        media_id:         The database ID of the movie or episode.
        title:            Human-readable title for display.
        jellyfin_item_id: Optional Jellyfin internal item ID.

    Returns:
        The new watch_history row ID, or -1 on error.
    """
    now = datetime.utcnow().isoformat()
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO watch_history
                (media_type, media_id, title, watched_at,
                 position_seconds, completed, jellyfin_item_id)
            VALUES (?, ?, ?, ?, 0, 0, ?)
            """,
            (media_type, media_id, title, now, jellyfin_item_id)
        )
        connection.commit()
        watch_id = cursor.lastrowid
        logger.info(
            "[HookReel] Watch event recorded: %s id=%d watch_id=%d",
            title, media_id, watch_id
        )
        return watch_id
    except Exception as error:
        logger.error("[HookReel] add_watch_event error: %s", error)
        connection.rollback()
        return -1
    finally:
        connection.close()


def get_watch_history(limit: int = 20) -> list:
    """
    Return the most recent watch events.

    Parameters:
        limit: Maximum number of rows to return (default 20).

    Returns:
        List of watch_history dicts ordered by most recent first.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM watch_history
            ORDER BY watched_at DESC
            LIMIT ?
            """,
            (limit,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_watch_history error: %s", error)
        return []
    finally:
        connection.close()


def get_last_watched_episode(show_id: int) -> dict:
    """
    Return the most recently watched episode for a given show.

    Joins watch_history against the episodes table to find the
    last episode watched for this show_id.

    Parameters:
        show_id: The show's database ID.

    Returns:
        A dict with episode fields plus watched_at, or None if
        no watch history exists for this show.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT e.*, wh.watched_at, wh.completed
            FROM watch_history wh
            JOIN episodes e ON wh.media_id = e.id
            WHERE e.show_id = ? AND wh.media_type = 'episode'
            ORDER BY wh.watched_at DESC
            LIMIT 1
            """,
            (show_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as error:
        logger.error("[HookReel] get_last_watched_episode error: %s", error)
        return None
    finally:
        connection.close()


def mark_completed(watch_id: int) -> bool:
    """
    Mark a watch event as completed (completed=1).

    Parameters:
        watch_id: The watch_history row ID to update.

    Returns:
        True on success, False on error.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE watch_history SET completed = 1 WHERE id = ?",
            (watch_id,)
        )
        connection.commit()
        logger.info("[HookReel] Watch event id=%d marked completed", watch_id)
        return True
    except Exception as error:
        logger.error("[HookReel] mark_completed error: %s", error)
        connection.rollback()
        return False
    finally:
        connection.close()


def get_next_episode_to_watch(show_id: int) -> dict:
    """
    Determine the next unwatched episode for a show.

    Logic:
      1. Find the most recently completed episode for this show.
      2. Return the next episode in sequence (by season then episode number).
      3. If no watch history exists, return S01E01.
      4. If the last completed episode was a season finale, return
         the first episode of the next season.
      5. If all episodes have been watched, return None.

    Parameters:
        show_id: The show's database ID.

    Returns:
        An episode dict for the next episode to watch, or None if
        all episodes are watched or no episodes exist.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        # Find the most recently completed episode for this show
        cursor.execute(
            """
            SELECT e.season, e.episode
            FROM watch_history wh
            JOIN episodes e ON wh.media_id = e.id
            WHERE e.show_id = ? AND wh.media_type = 'episode'
                AND wh.completed = 1
            ORDER BY e.season DESC, e.episode DESC
            LIMIT 1
            """,
            (show_id,)
        )
        last = cursor.fetchone()

        if last is None:
            # No watch history — return S01E01
            cursor.execute(
                """
                SELECT * FROM episodes
                WHERE show_id = ?
                ORDER BY season, episode
                LIMIT 1
                """,
                (show_id,)
            )
        else:
            last_season = last["season"]
            last_episode = last["episode"]

            # Try the next episode in the same season first
            cursor.execute(
                """
                SELECT * FROM episodes
                WHERE show_id = ? AND season = ? AND episode > ?
                ORDER BY episode
                LIMIT 1
                """,
                (show_id, last_season, last_episode)
            )
            row = cursor.fetchone()

            if row is None:
                # Season finale reached — try first episode of next season
                cursor.execute(
                    """
                    SELECT * FROM episodes
                    WHERE show_id = ? AND season > ?
                    ORDER BY season, episode
                    LIMIT 1
                    """,
                    (show_id, last_season)
                )
                row = cursor.fetchone()

            if row is None:
                # All episodes watched
                logger.info(
                    "[HookReel] get_next_episode_to_watch: "
                    "all episodes watched for show_id=%d", show_id
                )
                return None

            return dict(row)

        row = cursor.fetchone()
        return dict(row) if row else None

    except Exception as error:
        logger.error("[HookReel] get_next_episode_to_watch error: %s", error)
        return None
    finally:
        connection.close()

# ---------------------------------------------------------------------------
# Phase 8 migrations
# ---------------------------------------------------------------------------

def _migrate_phase8_columns():
    """
    Add Phase 8 columns to movies and episodes tables if not present.
    Safe to call multiple times -- checks before adding each column.
    movies:   poster_url, overview, rating, source_path
    episodes: source_path
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA table_info(movies)")
        movie_cols = [row["name"] for row in cursor.fetchall()]

        if "poster_url" not in movie_cols:
            cursor.execute("ALTER TABLE movies ADD COLUMN poster_url TEXT")
            logger.info("[HookReel] Migration: added poster_url to movies")

        if "overview" not in movie_cols:
            cursor.execute("ALTER TABLE movies ADD COLUMN overview TEXT")
            logger.info("[HookReel] Migration: added overview to movies")

        if "rating" not in movie_cols:
            cursor.execute("ALTER TABLE movies ADD COLUMN rating TEXT")
            logger.info("[HookReel] Migration: added rating to movies")

        if "source_path" not in movie_cols:
            cursor.execute(
                "ALTER TABLE movies ADD COLUMN source_path TEXT DEFAULT '/data/Movies'"
            )
            logger.info("[HookReel] Migration: added source_path to movies")

        cursor.execute("PRAGMA table_info(episodes)")
        ep_cols = [row["name"] for row in cursor.fetchall()]

        if "source_path" not in ep_cols:
            cursor.execute(
                "ALTER TABLE episodes ADD COLUMN source_path TEXT DEFAULT '/data/TV'"
            )
            logger.info("[HookReel] Migration: added source_path to episodes")

        connection.commit()
        logger.info("[HookReel] Phase 8 column migration complete")

    except Exception as error:
        logger.error("[HookReel] _migrate_phase8_columns error: %s", error)
        connection.rollback()
    finally:
        connection.close()

# ---------------------------------------------------------------------------
# Download lifecycle events
# ---------------------------------------------------------------------------

def _create_download_events_table():
    """
    Create the download_events table if it does not exist.
    Called automatically by initialise() at startup.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS download_events (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id      INTEGER,
                episode_id    INTEGER,
                event_type    TEXT    NOT NULL,
                event_detail  TEXT,
                torrent_name  TEXT,
                torrent_hash  TEXT,
                file_path     TEXT,
                timestamp     TEXT    NOT NULL
            )
        """)
        connection.commit()
        logger.info("[HookReel] Download events table ready")
    except Exception as error:
        logger.error("[HookReel] _create_download_events_table error: %s", error)
    finally:
        connection.close()


def log_download_event(
    event_type,
    event_detail=None,
    movie_id=None,
    episode_id=None,
    torrent_name=None,
    torrent_hash=None,
    file_path=None,
):
    """
    Insert a lifecycle event into download_events.
    event_type must be one of the defined event type strings.
    """
    import datetime
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            INSERT INTO download_events
                (movie_id, episode_id, event_type, event_detail,
                 torrent_name, torrent_hash, file_path, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            movie_id,
            episode_id,
            event_type,
            event_detail,
            torrent_name,
            torrent_hash,
            file_path,
            datetime.datetime.utcnow().isoformat(),
        ))
        connection.commit()
    except Exception as error:
        logger.error("[HookReel] log_download_event error: %s", error)
    finally:
        connection.close()


def get_download_history(movie_id=None, title=None, episode_id=None):
    """
    Return lifecycle events for a given movie or episode.
    Accepts movie_id (int), title (str), or episode_id (int).
    Returns a list of event dicts ordered by timestamp ascending.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        if movie_id:
            cursor.execute("""
                SELECT * FROM download_events
                WHERE movie_id = ?
                ORDER BY timestamp ASC
            """, (movie_id,))
        elif episode_id:
            cursor.execute("""
                SELECT * FROM download_events
                WHERE episode_id = ?
                ORDER BY timestamp ASC
            """, (episode_id,))
        elif title:
            cursor.execute("""
                SELECT de.* FROM download_events de
                LEFT JOIN movies m ON de.movie_id = m.id
                WHERE LOWER(m.title) LIKE LOWER(?)
                ORDER BY de.timestamp ASC
            """, (f"%{title}%",))
        else:
            return []
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_download_history error: %s", error)
        return []
    finally:
        connection.close()


def get_stuck_downloads(hours=2):
    """
    Find movies or episodes that have been in downloading state
    for more than the given number of hours with no recent events.
    Returns a list of dicts with title, movie_id, last_event_time.
    """
    import datetime
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cutoff = (
            datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        ).isoformat()
        cursor.execute("""
            SELECT m.id, m.title, m.year,
                   MAX(de.timestamp) as last_event
            FROM movies m
            LEFT JOIN download_events de ON de.movie_id = m.id
            WHERE m.status = 'downloading'
            GROUP BY m.id
            HAVING last_event IS NULL OR last_event < ?
            ORDER BY last_event ASC
        """, (cutoff,))
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_stuck_downloads error: %s", error)
        return []
    finally:
        connection.close()

# ---------------------------------------------------------------------------
# v1.1 column migrations
# ---------------------------------------------------------------------------

def _migrate_v11_columns():
    """
    Add v1.1 columns to movies, shows, and episodes tables if not present.
    Safe to call multiple times -- checks before adding each column.
    movies:   user_rating INTEGER
    shows:    user_rating INTEGER
    episodes: user_rating INTEGER
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA table_info(movies)")
        movie_cols = [row["name"] for row in cursor.fetchall()]
        if "user_rating" not in movie_cols:
            cursor.execute("ALTER TABLE movies ADD COLUMN user_rating INTEGER")
            logger.info("[HookReel] Migration: added user_rating to movies")

        cursor.execute("PRAGMA table_info(shows)")
        show_cols = [row["name"] for row in cursor.fetchall()]
        if "user_rating" not in show_cols:
            cursor.execute("ALTER TABLE shows ADD COLUMN user_rating INTEGER")
            logger.info("[HookReel] Migration: added user_rating to shows")

        cursor.execute("PRAGMA table_info(episodes)")
        ep_cols = [row["name"] for row in cursor.fetchall()]
        if "user_rating" not in ep_cols:
            cursor.execute("ALTER TABLE episodes ADD COLUMN user_rating INTEGER")
            logger.info("[HookReel] Migration: added user_rating to episodes")

        connection.commit()
        cursor.execute("PRAGMA table_info(watch_history)")
        wh_cols = [row["name"] for row in cursor.fetchall()]
        if "watch_source" not in wh_cols:
            cursor.execute("ALTER TABLE watch_history ADD COLUMN watch_source TEXT DEFAULT \"manual\"")
            logger.info("[HookReel] Migration: added watch_source to watch_history")
        logger.info("[HookReel] v1.1 column migration complete")
    except Exception as error:
        logger.error("[HookReel] _migrate_v11_columns error: %s", error)
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Rating functions
# ---------------------------------------------------------------------------

def rate_movie(movie_id, rating):
    """Set user_rating (1-5) for a movie."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE movies SET user_rating = ? WHERE id = ?",
            (rating, movie_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception as error:
        logger.error("[HookReel] rate_movie error: %s", error)
        return False
    finally:
        connection.close()


def rate_show(show_id, rating):
    """Set user_rating (1-5) for a show."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE shows SET user_rating = ? WHERE id = ?",
            (rating, show_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception as error:
        logger.error("[HookReel] rate_show error: %s", error)
        return False
    finally:
        connection.close()


def rate_episode(episode_id, rating):
    """Set user_rating (1-5) for an episode."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "UPDATE episodes SET user_rating = ? WHERE id = ?",
            (rating, episode_id)
        )
        connection.commit()
        return cursor.rowcount > 0
    except Exception as error:
        logger.error("[HookReel] rate_episode error: %s", error)
        return False
    finally:
        connection.close()


def get_movie_rating(movie_id):
    """Get user_rating for a movie. Returns None if not rated."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT user_rating FROM movies WHERE id = ?", (movie_id,)
        )
        row = cursor.fetchone()
        return row["user_rating"] if row else None
    except Exception as error:
        logger.error("[HookReel] get_movie_rating error: %s", error)
        return None
    finally:
        connection.close()


def get_top_rated_movies(limit=10):
    """Return top rated movies ordered by user_rating descending."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT id, title, year, user_rating FROM movies
            WHERE user_rating IS NOT NULL
            ORDER BY user_rating DESC, title ASC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_top_rated_movies error: %s", error)
        return []
    finally:
        connection.close()


def get_top_rated_shows(limit=10):
    """Return top rated shows ordered by user_rating descending."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT id, title, year, user_rating FROM shows
            WHERE user_rating IS NOT NULL
            ORDER BY user_rating DESC, title ASC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    except Exception as error:
        logger.error("[HookReel] get_top_rated_shows error: %s", error)
        return []
    finally:
        connection.close()

# ---------------------------------------------------------------------------
# Watch tracking functions (v1.1)
# ---------------------------------------------------------------------------

def mark_watched(media_type, media_id, title, watch_source="manual", completed=True):
    """
    Mark a movie or episode as watched.
    media_type: 'movie' or 'episode'
    media_id:   database ID of the movie or episode
    title:      human readable title
    watch_source: 'manual', 'jellyfin_webhook', or 'stream'
    completed:  True if watched to completion
    """
    import datetime
    connection = get_connection()
    cursor = connection.cursor()
    try:
        now = datetime.datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT INTO watch_history
                (media_type, media_id, title, watched_at,
                 position_seconds, completed, watch_source)
            VALUES (?, ?, ?, ?, 0, ?, ?)
        """, (media_type, media_id, title, now, 1 if completed else 0, watch_source))
        connection.commit()
        logger.info("[HookReel] mark_watched: %s id=%d source=%s", title, media_id, watch_source)
        return cursor.lastrowid
    except Exception as error:
        logger.error("[HookReel] mark_watched error: %s", error)
        return -1
    finally:
        connection.close()


def mark_unwatched(media_type, media_id):
    """
    Remove all watch history entries for a movie or episode.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "DELETE FROM watch_history WHERE media_type = ? AND media_id = ?",
            (media_type, media_id)
        )
        connection.commit()
        logger.info("[HookReel] mark_unwatched: %s id=%d", media_type, media_id)
        return True
    except Exception as error:
        logger.error("[HookReel] mark_unwatched error: %s", error)
        return False
    finally:
        connection.close()


def get_watch_status(media_type, media_id=None, title=None, show_id=None):
    """
    Get watch status for a movie or show.
    For movies: returns last watched date and completion status.
    For shows: returns last watched episode and completion summary.
    """
    connection = get_connection()
    cursor = connection.cursor()
    try:
        if media_type == "movie" and media_id:
            cursor.execute("""
                SELECT * FROM watch_history
                WHERE media_type = 'movie' AND media_id = ?
                ORDER BY watched_at DESC LIMIT 1
            """, (media_id,))
            row = cursor.fetchone()
            if not row:
                return {"watched": False}
            return {
                "watched": True,
                "watched_at": row["watched_at"][:10],
                "completed": bool(row["completed"]),
                "title": row["title"],
            }
        elif media_type == "episode" and show_id:
            cursor.execute("""
                SELECT wh.*, e.season, e.episode FROM watch_history wh
                JOIN episodes e ON wh.media_id = e.id
                WHERE wh.media_type = 'episode' AND e.show_id = ?
                ORDER BY e.season DESC, e.episode DESC LIMIT 1
            """, (show_id,))
            row = cursor.fetchone()
            if not row:
                return {"watched": False}
            return {
                "watched": True,
                "last_season": row["season"],
                "last_episode": row["episode"],
                "watched_at": row["watched_at"][:10],
                "completed": bool(row["completed"]),
            }
        return {"watched": False}
    except Exception as error:
        logger.error("[HookReel] get_watch_status error: %s", error)
        return {"watched": False}
    finally:
        connection.close()
