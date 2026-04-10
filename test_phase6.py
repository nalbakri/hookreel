"""
HookReel Phase 6 test suite — TV show support.
Tests 39–45 covering database schema, metadata, pipeline,
tools, post-processing, and monitoring.
Run with:
    docker cp test_phase6.py hookreel:/hookreel/
    docker exec hookreel python -m pytest /hookreel/test_phase6.py -v
"""
import os
import sys
import pytest

sys.path.insert(0, "/hookreel")


# ---------------------------------------------------------------------------
# Test 39 — Database TV schema
# ---------------------------------------------------------------------------

def test_39_database_tv_schema():
    """
    Verify the shows and episodes tables work end to end.
    Adds a show, adds an episode, fetches and checks the result.
    """
    import app.database as db

    # Clean up any leftover test data first
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("DELETE FROM episodes WHERE show_id IN "
                 "(SELECT id FROM shows WHERE title = 'Friends Test 39')")
    conn.execute("DELETE FROM shows WHERE title = 'Friends Test 39'")
    conn.commit()
    conn.close()

    # Add show
    show_id = db.add_show("tt0108778", "Friends Test 39", "1994")
    assert show_id != -1, "add_show returned -1"
    assert show_id > 0, "show_id should be positive integer"

    # Add episode
    ep_id = db.add_episode(show_id, 1, 1, "The Pilot", "1994-09-22")
    assert ep_id != -1, "add_episode returned -1"
    assert ep_id > 0, "episode_id should be positive integer"

    # get_episode
    ep = db.get_episode(show_id, 1, 1)
    assert ep is not None, "get_episode returned None"
    assert ep["season"] == 1
    assert ep["episode"] == 1
    assert ep["title"] == "The Pilot"
    assert ep["status"] == "missing"

    # episode_exists
    assert db.episode_exists(show_id, 1, 1) is True
    assert db.episode_exists(show_id, 1, 99) is False

    # get_show
    show = db.get_show(show_id)
    assert show is not None
    assert show["title"] == "Friends Test 39"
    assert show["status"] == "tracked"

    # get_show_by_title
    results = db.get_show_by_title("Friends Test 39")
    assert len(results) >= 1

    # update_show_status
    ok = db.update_show_status(show_id, "ended")
    assert ok is True
    show = db.get_show(show_id)
    assert show["status"] == "ended"

    # update_episode_status
    ok = db.update_episode_status(ep_id, "downloading", torrent_hash="abc123")
    assert ok is True
    ep = db.get_episode(show_id, 1, 1)
    assert ep["status"] == "downloading"
    assert ep["torrent_hash"] == "abc123"

    # get_missing_episodes (none now — status is downloading)
    missing = db.get_missing_episodes(show_id)
    assert isinstance(missing, list)

    # get_episodes_for_show
    all_eps = db.get_episodes_for_show(show_id)
    assert len(all_eps) >= 1

    # get_next_episode
    db.update_episode_status(ep_id, "complete")
    next_ep = db.get_next_episode(show_id)
    # show is ended with one complete episode — could be None or the episode
    assert next_ep is None or isinstance(next_ep, dict)

    print("Test 39 PASSED — TV database schema works end to end")


# ---------------------------------------------------------------------------
# Test 40 — TV metadata provider
# ---------------------------------------------------------------------------

def test_40_tv_metadata_provider():
    """
    Verify TVmaze returns show info and episode lists for a known show.
    """
    from app.tv_metadata import get_show_info, get_episode_list

    # Search for Friends
    results = get_show_info("Friends")
    assert len(results) > 0, "get_show_info returned no results"

    first = results[0]
    assert "provider_id" in first, "Missing provider_id"
    assert "title" in first, "Missing title"
    assert "year" in first, "Missing year"
    assert "status" in first, "Missing status"
    assert "network" in first, "Missing network"

    # Get episode list for the first result
    provider_id = first["provider_id"]
    episodes = get_episode_list(provider_id, season=1)
    assert len(episodes) > 0, "get_episode_list returned no episodes"

    ep = episodes[0]
    assert "season" in ep, "Missing season"
    assert "episode" in ep, "Missing episode"
    assert "title" in ep, "Missing title"
    assert "air_date" in ep, "Missing air_date"

    print(
        f"Test 40 PASSED — TVmaze returned {len(results)} shows, "
        f"{len(episodes)} S1 episodes for '{first['title']}'"
    )


# ---------------------------------------------------------------------------
# Test 41 — TV Prowlarr search
# ---------------------------------------------------------------------------

def test_41_tv_prowlarr_search():
    """
    Verify search_tv_releases builds the correct query and runs without error.
    Results may be empty depending on indexers — that is acceptable.
    """
    from app.tv_pipeline import search_tv_releases

    # Search for specific episode
    results = search_tv_releases("Friends", season=1, episode=1)
    assert isinstance(results, list), "search_tv_releases should return a list"

    # Search for full season
    results_season = search_tv_releases("Friends", season=1)
    assert isinstance(results_season, list)

    # Search with no season
    results_bare = search_tv_releases("Breaking Bad")
    assert isinstance(results_bare, list)

    print(
        f"Test 41 PASSED — TV Prowlarr search ran without error "
        f"(episode results: {len(results)}, season results: {len(results_season)})"
    )


# ---------------------------------------------------------------------------
# Test 42 — TV tool registry
# ---------------------------------------------------------------------------

def test_42_tv_tool_registry():
    """
    Verify all 6 new TV tools are present in TOOL_SCHEMAS.
    """
    from app.tools import TOOL_SCHEMAS

    required_tools = {
        "search_show",
        "request_show",
        "get_show_status",
        "list_tracked_shows",
        "get_episode_list",
        "check_show_exists",
    }

    found_tools = {
        schema["function"]["name"]
        for schema in TOOL_SCHEMAS
    }

    missing = required_tools - found_tools
    assert len(missing) == 0, f"Missing TV tools in TOOL_SCHEMAS: {missing}"
    assert len(TOOL_SCHEMAS) >= 13, (
        f"Expected at least 13 tools, found {len(TOOL_SCHEMAS)}"
    )

    print(
        f"Test 42 PASSED — All 6 TV tools present. "
        f"Total tools: {len(TOOL_SCHEMAS)}"
    )


# ---------------------------------------------------------------------------
# Test 43 — TV rename format
# ---------------------------------------------------------------------------

def test_43_tv_rename_format():
    """
    Verify rename_episode produces the correct Jellyfin-compatible path.
    Creates a dummy file, calls rename_episode, checks the output path.
    """
    import tempfile
    import os
    from app.tv_postprocessor import rename_episode
    from app import config

    # Create a dummy source file
    with tempfile.NamedTemporaryFile(
        suffix=".mkv", delete=False, dir="/data/Downloads"
    ) as tmp:
        tmp_path = tmp.name

    try:
        new_path = rename_episode(
            file_path=tmp_path,
            show_title="Friends",
            show_year="1994",
            season=1,
            episode=1,
            episode_title="The Pilot"
        )

        expected_dir = os.path.join(
            config.TV_PATH, "Friends (1994)", "Season 01"
        )
        expected_filename = "Friends (1994) - S01E01 - The Pilot.mkv"
        expected_path = os.path.join(expected_dir, expected_filename)

        assert new_path == expected_path, (
            f"Expected:\n  {expected_path}\nGot:\n  {new_path}"
        )
        assert os.path.exists(new_path), f"Renamed file not found at {new_path}"

        print(f"Test 43 PASSED — Rename format correct:\n  {new_path}")
    finally:
        # Clean up
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if os.path.exists(new_path):
            os.unlink(new_path)


# ---------------------------------------------------------------------------
# Test 44 — TV pipeline (no actual download)
# ---------------------------------------------------------------------------

def test_44_tv_pipeline_no_download():
    """
    Verify request_show runs through metadata lookup and Prowlarr search
    without crashing. The qBittorrent step is mocked.
    """
    import unittest.mock as mock
    import app.tv_pipeline as tv_pipeline
    import app.database as db

    # Clean up leftover test data
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    conn.execute("DELETE FROM episodes WHERE show_id IN "
                 "(SELECT id FROM shows WHERE title LIKE 'Breaking Bad%')")
    conn.execute("DELETE FROM shows WHERE title LIKE 'Breaking Bad%'")
    conn.commit()
    conn.close()

    # Mock add_torrent so nothing actually gets added to qBittorrent
    with mock.patch("app.tv_pipeline.add_torrent", return_value="mockhash123"):
        result = tv_pipeline.request_show(
            title="Breaking Bad",
            season=1,
            episode=1,
            download_url=None
        )

    assert isinstance(result, dict), "request_show should return a dict"
    assert "success" in result, "Result missing 'success' key"
    assert "message" in result, "Result missing 'message' key"
    assert "show_id" in result, "Result missing 'show_id' key"

    print(
        f"Test 44 PASSED — TV pipeline ran to completion. "
        f"success={result['success']} message={result['message'][:60]}"
    )


# ---------------------------------------------------------------------------
# Test 45 — check_show_exists tool
# ---------------------------------------------------------------------------

def test_45_check_show_exists():
    """
    Verify check_show_exists returns the correct status for a tracked show.
    Uses the Friends show added in Test 39.
    """
    from app.tools import execute_tool
    import app.database as db

    # Ensure Friends Test 39 exists (may have been cleaned up)
    existing = db.get_show_by_title("Friends Test 45")
    if not existing:
        db.add_show("tt0108778", "Friends Test 45", "1994")

    result = execute_tool("check_show_exists", {"title": "Friends Test 45"})
    assert isinstance(result, str), "execute_tool should return a string"
    assert "tracked" in result.lower() or "already" in result.lower(), (
        f"Expected tracked status in result, got: {result}"
    )

    # Check a show that does not exist
    result_missing = execute_tool(
        "check_show_exists", {"title": "ThisShowDoesNotExistXYZ999"}
    )
    assert "not currently tracked" in result_missing.lower(), (
        f"Expected 'not currently tracked', got: {result_missing}"
    )

    print(f"Test 45 PASSED — check_show_exists works correctly")
