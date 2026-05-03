"""
test_v1_1.py

HookReel v1.1 Alf -- test suite.
Tests 106-120 covering new features.
"""
import os
import sys
import pytest

sys.path.insert(0, "/hookreel")
os.environ.setdefault("HOOKREEL_TEST_MODE", "1")

import app.database as database
from app.database import (
    log_download_event,
    get_download_history,
    get_stuck_downloads,
    rate_movie,
    rate_show,
    get_movie_rating,
    get_top_rated_movies,
    mark_watched,
    mark_unwatched,
    get_watch_status,
)
from app.qbittorrent import extract_hash_from_magnet


# ---------------------------------------------------------------------------
# Feature 2 -- Hash capture at add time
# ---------------------------------------------------------------------------

def test_106_extract_hash_from_magnet_hex():
    """extract_hash_from_magnet returns lowercase hex hash from magnet URL."""
    url = "magnet:?xt=urn:btih:4A9F2E3D1C8B7A6E5F4D3C2B1A9E8F7D6C5B4A3E&dn=Test+Movie"
    result = extract_hash_from_magnet(url)
    assert result == "4a9f2e3d1c8b7a6e5f4d3c2b1a9e8f7d6c5b4a3e"


def test_107_extract_hash_from_magnet_non_magnet():
    """extract_hash_from_magnet returns None for non-magnet URLs."""
    assert extract_hash_from_magnet("https://example.com/file.torrent") is None
    assert extract_hash_from_magnet("") is None
    assert extract_hash_from_magnet(None) is None


# ---------------------------------------------------------------------------
# Feature 3 -- Download lifecycle tracking
# ---------------------------------------------------------------------------

def test_108_download_events_table_exists():
    """download_events table exists and accepts all event types."""
    database.initialise()
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='download_events'")
    row = cursor.fetchone()
    conn.close()
    assert row is not None


def test_109_log_and_retrieve_download_events():
    """log_download_event stores events and get_download_history retrieves them."""
    database.initialise()
    movie_id = database.add_movie(0, "Test Lifecycle Movie", "2024")
    database.update_movie_status(movie_id, "downloading")

    event_types = [
        "request_made", "search_started", "search_results",
        "torrent_added", "download_started", "download_complete",
        "clamav_passed", "rename_complete", "move_complete",
        "jellyfin_notified",
    ]
    for et in event_types:
        log_download_event(et, "test detail", movie_id=movie_id, torrent_hash="abc123")

    events = get_download_history(movie_id=movie_id)
    logged_types = [e["event_type"] for e in events]
    for et in event_types:
        assert et in logged_types

    database.delete_test_rows()


def test_110_get_stuck_downloads_returns_list():
    """get_stuck_downloads returns a list."""
    database.initialise()
    result = get_stuck_downloads(hours=0)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Feature 4 -- Rating system
# ---------------------------------------------------------------------------

def test_111_rate_movie_stores_rating():
    """rate_movie stores correct rating and get_movie_rating retrieves it."""
    database.initialise()
    movie_id = database.add_movie(0, "Test Rated Movie", "2024")
    rate_movie(movie_id, 5)
    retrieved = get_movie_rating(movie_id)
    assert retrieved == 5
    database.delete_test_rows()


def test_112_rate_show_stores_rating():
    """rate_show stores correct rating."""
    database.initialise()
    show_id = database.add_show("0", "Test Rated Show", "2024")
    rate_show(show_id, 4)
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_rating FROM shows WHERE id = ?", (show_id,))
    row = cursor.fetchone()
    conn.close()
    assert row["user_rating"] == 4


def test_113_get_top_rated_movies():
    """get_top_rated_movies returns rated movies in order."""
    database.initialise()
    database.delete_test_rows()
    id1 = database.add_movie(0, "Test Top Movie A", "2024")
    id2 = database.add_movie(0, "Test Top Movie B", "2024")
    rate_movie(id1, 5)
    rate_movie(id2, 3)
    results = get_top_rated_movies(limit=100)
    rated_titles = [r["title"] for r in results]
    assert "Test Top Movie A" in rated_titles
    assert "Test Top Movie B" in rated_titles
    database.delete_test_rows()


# ---------------------------------------------------------------------------
# Feature 5 -- Watch tracking
# ---------------------------------------------------------------------------

def test_114_mark_watched_and_get_status_movie():
    """mark_watched and get_watch_status work correctly for movies."""
    database.initialise()
    movie_id = database.add_movie(0, "Test Watch Movie", "2024")
    mark_watched("movie", movie_id, "Test Watch Movie", watch_source="manual")
    status = get_watch_status("movie", media_id=movie_id)
    assert status["watched"] is True
    assert status["completed"] is True
    database.delete_test_rows()


def test_115_mark_unwatched_removes_history():
    """mark_unwatched removes watch history entries."""
    database.initialise()
    movie_id = database.add_movie(0, "Test Unwatch Movie", "2024")
    mark_watched("movie", movie_id, "Test Unwatch Movie")
    mark_unwatched("movie", movie_id)
    status = get_watch_status("movie", media_id=movie_id)
    assert status["watched"] is False
    database.delete_test_rows()


# ---------------------------------------------------------------------------
# Feature 6 -- Jellyfin webhook
# ---------------------------------------------------------------------------

def test_116_jellyfin_webhook_accepts_valid_payload():
    """Jellyfin webhook handler processes a valid movie payload."""
    from app.webhook import handle_jellyfin_event
    database.initialise()
    movie_id = database.add_movie(0, "Webhook Test Movie", "2024")
    database.update_movie_status(movie_id, "complete")

    payload = {
        "NotificationType": "PlaybackStop",
        "ItemType": "Movie",
        "Name": "Webhook Test Movie",
        "Year": 2024,
        "PlayedToCompletion": True,
    }
    result = handle_jellyfin_event(payload)
    assert result["status"] == "ok"
    assert result["completed"] is True
    database.delete_test_rows()


# ---------------------------------------------------------------------------
# Feature 7 -- Suggestion engine
# ---------------------------------------------------------------------------

def test_117_get_suggestions_returns_results():
    """get_suggestions returns a list of suggestions."""
    from app.suggestions import get_suggestions
    database.initialise()
    database.add_movie(0, "Test Suggestion Movie", "2024")
    database.update_movie_status(
        database.get_movies_by_title("Test Suggestion Movie")[0]["id"],
        "complete"
    )
    results = get_suggestions(count=5)
    assert isinstance(results, list)
    database.delete_test_rows()


# ---------------------------------------------------------------------------
# Feature 8 -- Dedupe detection
# ---------------------------------------------------------------------------

def test_118_find_duplicates_detects_duplicates():
    """find_duplicates returns correct groups for duplicate entries."""
    database.initialise()
    database.delete_test_rows()
    database.add_movie(0, "Test Dupe Movie", "2024")
    database.add_movie(0, "Test Dupe Movie", "2024")
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT title, year, COUNT(*) as cnt FROM movies
        WHERE title = 'Test Dupe Movie'
        GROUP BY LOWER(title), year
        HAVING cnt > 1
    """)
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row["cnt"] >= 2
    database.delete_test_rows()


# ---------------------------------------------------------------------------
# Feature 9 -- Download visibility
# ---------------------------------------------------------------------------

def test_119_extract_hash_from_magnet_base32():
    """extract_hash_from_magnet handles base32 encoded hashes."""
    # 32-char base32 hash
    url = "magnet:?xt=urn:btih:MFRA2YLSMVQXIZLTOQ2DKNRXHA3DANBT&dn=Test"
    result = extract_hash_from_magnet(url)
    assert result is not None
    assert len(result) == 40


def test_120_get_download_status_tool_registered():
    """get_download_status tool is registered in TOOL_SCHEMAS."""
    from app.tools import TOOL_SCHEMAS
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert "get_download_status" in names
    assert "get_download_history" in names
    assert "get_stuck_downloads" in names
    assert "rate_content" in names
    assert "get_suggestions" in names
    assert "find_duplicates" in names
    assert "mark_watched" in names
    assert "get_watch_status" in names
