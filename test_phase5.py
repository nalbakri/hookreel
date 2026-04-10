"""
HookReel test suite — Phase 5 (Web UI).

Run with:
    python test_phase5.py           # all phase 5 tests
    python test_phase5.py --quick   # skip live service tests

Tests 24-34 cover:
    24 — TmdbProvider methods
    25 — Web UI imports and routes
    26 — Auth config (password and secret key)
    27 — Database cleanup utilities
    28 — read_env function
    29 — Settings routes registered
    30 — Connection test functions
    31 — Prowlarr management functions
    32 — qBittorrent management functions
    33 — Categories check
    34 — Tailscale status function
"""

import sys
from app import config, database

QUICK_MODE = "--quick" in sys.argv

# ── Helpers ────────────────────────────────────────────────────────────────────

def section(label):
    print("\n{}".format("=" * 60))
    print("  {}".format(label))
    print("=" * 60)


def result(test_num, name, passed, note=""):
    status = "  PASS" if passed else "  FAIL"
    note_str = " — {}".format(note) if note else ""
    print("Test {:02d}  {}  {}{}".format(test_num, status, name, note_str))


def skip(test_num, name, reason="quick mode"):
    print("Test {:02d}    SKIP  {} — {}".format(test_num, name, reason))


# ── Tests ──────────────────────────────────────────────────────────────────────

section("Phase 5 — Web UI")


def test_24_tmdb_methods():
    """TmdbProvider search(), get_details(), get_similar()."""
    try:
        from app.pipeline import get_metadata_provider
        provider = get_metadata_provider()

        if config.METADATA_PROVIDER != "tmdb":
            skip(24, "TmdbProvider methods", "provider is not tmdb")
            return None

        results = provider.search("Interstellar")
        assert isinstance(results, list) and len(results) > 0, \
            "search() returned empty list"
        assert "provider_id" in results[0], "Missing provider_id"
        provider_id = results[0]["provider_id"]

        details = provider.get_details(provider_id)
        assert details is not None, "get_details() returned None"
        assert "genres" in details, "Missing genres in details"

        similar = provider.get_similar(provider_id)
        assert isinstance(similar, list), "get_similar() did not return list"

        result(24, "TmdbProvider methods", True,
               "search={}, similar={}".format(len(results), len(similar)))
        return True
    except Exception as error:
        result(24, "TmdbProvider methods", False, str(error))
        return False


def test_25_webui_imports():
    """Web UI module imports and all required routes registered."""
    try:
        from app.webui import app_fastapi, run_webui, set_conversation_manager
        assert app_fastapi is not None

        routes = [r.path for r in app_fastapi.routes]
        required = [
            "/", "/login", "/dashboard", "/library", "/chat",
            "/settings", "/indexers", "/downloader",
            "/api/chat", "/api/status", "/api/pair/generate",
            "/api/tailscale/status",
        ]
        missing = [r for r in required if r not in routes]
        assert not missing, "Missing routes: {}".format(missing)

        result(25, "Web UI imports", True,
               "{} routes registered".format(len(routes)))
        return True
    except Exception as error:
        result(25, "Web UI imports", False, str(error))
        return False


def test_26_auth_config():
    """WEBUI_PASSWORD and SECRET_KEY are not default changeme values."""
    try:
        assert config.WEBUI_PASSWORD != "changeme", \
            "WEBUI_PASSWORD is still 'changeme'"
        assert config.SECRET_KEY != "changeme", \
            "SECRET_KEY is still 'changeme'"
        assert len(config.SECRET_KEY) >= 32, \
            "SECRET_KEY too short — use secrets.token_hex(32)"
        result(26, "Auth config", True, "password and secret key configured")
        return True
    except Exception as error:
        result(26, "Auth config", False, str(error))
        return False


def test_27_database_cleanup():
    """cleanup_stuck_downloads() and delete_test_rows() return integers."""
    try:
        count = database.cleanup_stuck_downloads(hours=0)
        assert isinstance(count, int), "cleanup_stuck_downloads did not return int"

        deleted = database.delete_test_rows()
        assert isinstance(deleted, int), "delete_test_rows did not return int"

        result(27, "Database cleanup", True,
               "cleaned={}, test rows deleted={}".format(count, deleted))
        return True
    except Exception as error:
        result(27, "Database cleanup", False, str(error))
        return False


def test_28_read_env():
    """read_env() returns dict with expected keys, sensitive values masked."""
    try:
        from app.webui import read_env
        env = read_env()
        assert isinstance(env, dict) and len(env) > 0

        required_keys = ["QBITTORRENT_HOST", "PROWLARR_HOST",
                         "METADATA_PROVIDER", "LOG_LEVEL"]
        missing = [k for k in required_keys if k not in env]
        assert not missing, "Missing keys: {}".format(missing)

        # Sensitive key must be masked
        if "PROWLARR_API_KEY" in env:
            assert "••" in env["PROWLARR_API_KEY"] or \
                   len(env["PROWLARR_API_KEY"]) <= 4, \
                   "PROWLARR_API_KEY does not appear masked"

        result(28, "read_env function", True,
               "{} keys loaded".format(len(env)))
        return True
    except Exception as error:
        result(28, "read_env function", False, str(error))
        return False


def test_29_settings_routes():
    """/settings, /api/settings, /api/settings/test routes exist."""
    try:
        from app.webui import app_fastapi
        routes = {r.path for r in app_fastapi.routes}
        required = ["/settings", "/api/settings", "/api/settings/test"]
        missing = [r for r in required if r not in routes]
        assert not missing, "Missing routes: {}".format(missing)
        result(29, "Settings routes registered", True)
        return True
    except Exception as error:
        result(29, "Settings routes registered", False, str(error))
        return False


def test_30_connection_tests():
    """test_connection() returns correct structure for qbittorrent and prowlarr."""
    if QUICK_MODE:
        skip(30, "Connection test functions")
        return None
    try:
        from app.webui import test_connection
        for service in ["qbittorrent", "prowlarr"]:
            res = test_connection(service)
            assert isinstance(res, dict), "{} did not return dict".format(service)
            assert "success" in res, "{} missing success key".format(service)
            assert "message" in res, "{} missing message key".format(service)
            print("  {}: success={} message={}".format(
                service, res["success"], res["message"][:60]))
        result(30, "Connection test functions", True)
        return True
    except Exception as error:
        result(30, "Connection test functions", False, str(error))
        return False


def test_31_prowlarr_management():
    """get_indexers() returns list, get_indexer_stats() returns dict."""
    if QUICK_MODE:
        skip(31, "Prowlarr management functions")
        return None
    try:
        from app.prowlarr_mgmt import get_indexers, get_indexer_stats
        indexers = get_indexers()
        assert isinstance(indexers, list), "get_indexers did not return list"
        print("  get_indexers: {} indexer(s)".format(len(indexers)))

        stats = get_indexer_stats()
        assert isinstance(stats, dict), "get_indexer_stats did not return dict"
        print("  get_indexer_stats: {} key(s)".format(len(stats)))

        result(31, "Prowlarr management functions", True)
        return True
    except Exception as error:
        result(31, "Prowlarr management functions", False, str(error))
        return False


def test_32_qbittorrent_management():
    """get_preferences() and get_transfer_info() return dicts."""
    if QUICK_MODE:
        skip(32, "qBittorrent management functions")
        return None
    try:
        from app.qbittorrent_mgmt import get_preferences, get_transfer_info
        prefs = get_preferences()
        assert isinstance(prefs, dict), "get_preferences did not return dict"
        print("  get_preferences: {} key(s)".format(len(prefs)))

        info = get_transfer_info()
        assert isinstance(info, dict), "get_transfer_info did not return dict"
        print("  get_transfer_info: {} key(s)".format(len(info)))

        result(32, "qBittorrent management functions", True)
        return True
    except Exception as error:
        result(32, "qBittorrent management functions", False, str(error))
        return False


def test_33_categories_check():
    """get_categories() works and hookreel-movies exists or is created."""
    if QUICK_MODE:
        skip(33, "Categories check")
        return None
    try:
        from app.qbittorrent_mgmt import get_categories, add_category
        cats = get_categories()
        assert isinstance(cats, dict), "get_categories did not return dict"

        if "hookreel-movies" not in cats:
            print("  hookreel-movies not found — creating...")
            add_category("hookreel-movies", config.MOVIES_PATH)
            cats = get_categories()

        assert "hookreel-movies" in cats, "hookreel-movies missing after create"
        result(33, "Categories check", True,
               "{} categories, hookreel-movies present".format(len(cats)))
        return True
    except Exception as error:
        result(33, "Categories check", False, str(error))
        return False


def test_34_tailscale_status():
    """get_tailscale_status() returns correct structure, never crashes."""
    try:
        from app.webui import get_tailscale_status
        status = get_tailscale_status()

        assert isinstance(status, dict), "Did not return dict"
        required_keys = ["running", "ip", "hostname", "device_count", "last_seen"]
        missing = [k for k in required_keys if k not in status]
        assert not missing, "Missing keys: {}".format(missing)
        assert isinstance(status["running"], bool), "running is not bool"
        assert isinstance(status["device_count"], int), "device_count is not int"

        print("  Tailscale running: {}".format(status["running"]))
        if status["running"]:
            print("  IP: {}".format(status["ip"]))
            print("  Hostname: {}".format(status["hostname"]))
            print("  Devices on tailnet: {}".format(status["device_count"]))
        else:
            print("  Tailscale not detected (this is fine)")

        result(34, "Tailscale status function", True)
        return True
    except Exception as error:
        result(34, "Tailscale status function", False, str(error))
        return False


# ── Run all and summarise ──────────────────────────────────────────────────────

if __name__ == "__main__":
    all_results = [
        ("Test 24 - TMDB methods",         test_24_tmdb_methods()),
        ("Test 25 - Web UI imports",        test_25_webui_imports()),
        ("Test 26 - Auth config",           test_26_auth_config()),
        ("Test 27 - DB cleanup",            test_27_database_cleanup()),
        ("Test 28 - read_env",              test_28_read_env()),
        ("Test 29 - Settings routes",       test_29_settings_routes()),
        ("Test 30 - Connection tests",      test_30_connection_tests()),
        ("Test 31 - Prowlarr mgmt",         test_31_prowlarr_management()),
        ("Test 32 - qBT mgmt",              test_32_qbittorrent_management()),
        ("Test 33 - Categories",            test_33_categories_check()),
        ("Test 34 - Tailscale status",      test_34_tailscale_status()),
        ("Test 35 - Release URL selection", test_35_release_selection_with_url()),
        ("Test 36 - check_exists failed",   test_36_check_exists_returns_failed_status()),
        ("Test 37 - Tool descriptions",     test_37_get_movie_details_description()),
        ("Test 38 - Restart event",         test_38_restart_event_exists()),
    ]
    section("Phase 5.1 test summary")
    passed  = sum(1 for _, r in all_results if r is True)
    failed  = sum(1 for _, r in all_results if r is False)
    skipped = sum(1 for _, r in all_results if r is None)
    print()
    for name, r in all_results:
        status = "PASS" if r is True else ("SKIP" if r is None else "FAIL")
        print("  {}  {}".format(status, name))
    print()
    print("  Results: {} passed, {} failed, {} skipped".format(
        passed, failed, skipped))
    print()
    print("  Tip: python test_phase5.py --quick  (skip live service tests)")
    print()

# ── Phase 5.1 tests ────────────────────────────────────────────────────────────

def test_35_release_selection_with_url():
    """
    Test 35 — pipeline.request_movie accepts download_url and skips Prowlarr.

    Passes a fake magnet URL directly to the pipeline fast path.
    The test passes if the function runs without crashing before
    reaching qBittorrent (which will reject the fake URL — that is OK).
    """
    try:
        from app.pipeline import request_movie, _validate_download_url

        # Verify URL validation accepts valid formats
        assert _validate_download_url("magnet:?xt=urn:test") is True
        assert _validate_download_url("https://example.com/file.torrent") is True
        assert _validate_download_url("http://example.com/file.torrent") is True
        assert _validate_download_url("ftp://bad.example.com") is False
        assert _validate_download_url("") is False
        assert _validate_download_url(None) is False

        # Call the pipeline fast path — it will fail at qBittorrent stage
        # with a fake magnet, but must not crash before that
        pipeline_result = request_movie(
            title="Test Movie",
            year="2024",
            download_url="magnet:?xt=urn:btih:0000000000000000000000000000000000000000",
            release_title="Test.Movie.2024.1080p.BluRay.x265-TEST",
        )

        # Result must be a dict — success or failure both acceptable
        # (qBittorrent will likely reject the fake magnet)
        assert isinstance(pipeline_result, dict), "Expected dict result"
        assert "success" in pipeline_result, "Expected 'success' key in result"

        result(35, "Release selection with download_url", True)
        return True

    except Exception as error:
        result(35, "Release selection with download_url", False, str(error))
        return False


def test_36_check_exists_returns_failed_status():
    """
    Test 36 — check_exists detects entries with status=failed.

    Inserts a movie with status=failed directly into the database,
    then calls the check_exists tool and verifies the response
    mentions the failed status.
    """
    try:
        from app import database
        from app.tools import execute_tool

        # Clean up any leftover test rows first
        database.delete_test_rows()

        # Insert a movie and force it to failed status
        movie_id = database.add_movie(0, "Test Movie Phase51", "2024")
        database.update_movie_status(movie_id, "failed")

        # Call check_exists via the tool dispatcher
        response = execute_tool("check_exists", {"title": "Test Movie Phase51"})

        # Clean up before asserting so we don't leave junk in the DB
        database.delete_test_rows()

        assert "failed" in response.lower(), (
            "Expected 'failed' in check_exists response, got: {}".format(response)
        )

        result(36, "check_exists returns failed status", True)
        return True

    except Exception as error:
        result(36, "check_exists returns failed status", False, str(error))
        return False


def test_37_get_movie_details_description():
    """
    Test 37 — get_movie_details tool schema contains updated descriptions.

    Verifies the tool description and parameter description both
    include the required wording to prevent the agent from passing
    torrent filenames as provider IDs.
    """
    try:
        from app.tools import TOOL_SCHEMAS

        # Find the get_movie_details schema
        schema = next(
            (s for s in TOOL_SCHEMAS
             if s["function"]["name"] == "get_movie_details"),
            None,
        )
        assert schema is not None, "get_movie_details schema not found"

        tool_description = schema["function"]["description"].lower()
        param_description = (
            schema["function"]["parameters"]
            ["properties"]["provider_id"]["description"].lower()
        )

        assert "numeric" in tool_description or "numeric" in param_description, (
            "Expected 'numeric' in get_movie_details description"
        )
        assert "not" in param_description and (
            "filename" in param_description or "torrent" in param_description
        ), "Expected warning about torrent filenames in provider_id description"

        result(37, "get_movie_details tool description updated", True)
        return True

    except Exception as error:
        result(37, "get_movie_details tool description updated", False, str(error))
        return False


def test_38_restart_event_exists():
    """
    Test 38 — restart_event is a threading.Event importable from main.

    Verifies the shared restart event object exists and is the
    correct type so the polling loop can detect web UI restart signals.
    """
    try:
        import threading
        from main import restart_event

        assert isinstance(restart_event, threading.Event), (
            "restart_event must be a threading.Event instance"
        )

        # Verify it starts cleared (not set)
        assert not restart_event.is_set(), (
            "restart_event should not be set at startup"
        )

        result(38, "restart_event is threading.Event", True)
        return True

    except Exception as error:
        result(38, "restart_event is threading.Event", False, str(error))
        return False
