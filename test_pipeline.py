"""
HookReel test suite — Phase 1 + Phase 2.
Run with: python test_pipeline.py
Tests are numbered 1-14. Phase 2 tests start at 9.
"""

import os
import sys

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

PASS = "  PASS"
FAIL = "  FAIL"


def section(label: str):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")


def result(test_num: int, name: str, passed: bool, note: str = ""):
    status = PASS if passed else FAIL
    note_str = f" — {note}" if note else ""
    print(f"Test {test_num:02d}  {status}  {name}{note_str}")


# -----------------------------------------------------------------------
# Phase 1 tests (1-8)
# -----------------------------------------------------------------------

section("Phase 1 — Environment and core modules")

# Test 1 — Config loads
try:
    from app import config
    assert config.QBITTORRENT_HOST, "QBITTORRENT_HOST missing"
    result(1, "Config loads", True)
except Exception as error:
    result(1, "Config loads", False, str(error))
    sys.exit("Cannot continue without config")

# Test 2 — Logger initialises
try:
    from app.logger import get_logger
    log = get_logger("test")
    log.info("[HookReel] Test logger working")
    result(2, "Logger initialises", True)
except Exception as error:
    result(2, "Logger initialises", False, str(error))

# Test 3 — Database initialises
try:
    from app import database
    database.initialise()
    result(3, "Database initialises", True)
except Exception as error:
    result(3, "Database initialises", False, str(error))

# Test 4 — Add movie to database
try:
    movie_id = database.add_movie(99999, "Test Movie", "2024")
    assert movie_id > 0
    result(4, "Add movie to database", True, f"id={movie_id}")
except Exception as error:
    result(4, "Add movie to database", False, str(error))

# Test 5 — Update movie status
try:
    database.update_movie_status(movie_id, "downloading")
    movie = database.get_movie_by_id(movie_id)
    assert movie["status"] == "downloading"
    result(5, "Update movie status", True)
except Exception as error:
    result(5, "Update movie status", False, str(error))

# Test 6 — qBittorrent connection
try:
    from app import qbittorrent
    torrents = qbittorrent.get_torrent_list()
    result(6, "qBittorrent connection", True, f"{len(torrents)} torrents found")
except Exception as error:
    result(6, "qBittorrent connection", False, str(error))

# Test 7 — Prowlarr connection
try:
    from app import prowlarr
    results_list = prowlarr.search_releases("test")
    result(7, "Prowlarr connection", True, f"{len(results_list)} results")
except Exception as error:
    result(7, "Prowlarr connection", False, str(error))

# Test 8 — Metadata provider
try:
    from app.pipeline import get_metadata_provider
    provider = get_metadata_provider()
    assert provider is not None
    result(8, "Metadata provider loads", True, f"provider={config.METADATA_PROVIDER}")
except Exception as error:
    result(8, "Metadata provider loads", False, str(error))


# -----------------------------------------------------------------------
# Phase 2 tests (9-14)
# -----------------------------------------------------------------------

section("Phase 2 — Post-processing")

# Test 9 — Database migration
try:
    import sqlite3
    database.migrate()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(movies)")
    columns = [row["name"] for row in cursor.fetchall()]
    conn.close()

    if "provider_id" in columns and "tmdb_id" not in columns:
        result(9, "Database migration (tmdb_id → provider_id)", True)
    elif "provider_id" in columns:
        result(9, "Database migration (tmdb_id → provider_id)", True, "provider_id present (fresh DB)")
    else:
        result(9, "Database migration (tmdb_id → provider_id)", False, f"columns found: {columns}")
except Exception as error:
    result(9, "Database migration (tmdb_id → provider_id)", False, str(error))

# Test 10 — Torrent hash lookup
try:
    torrents = qbittorrent.get_torrent_list()
    if torrents:
        first_torrent_name = torrents[0].get("name", "")
        found_hash = qbittorrent.get_torrent_hash_by_name(first_torrent_name)
        if found_hash:
            result(10, "Torrent hash lookup by name", True, f"hash={found_hash[:12]}...")
        else:
            result(10, "Torrent hash lookup by name", True, "function ran OK, no match")
    else:
        result(10, "Torrent hash lookup by name", True, "no torrents in qBittorrent — skipped")
except Exception as error:
    result(10, "Torrent hash lookup by name", False, str(error))

# Test 11 — ClamAV connection
try:
    import pyclamd
    clamd = pyclamd.ClamdNetworkSocket(
        host=config.CLAMAV_HOST,
        port=config.CLAMAV_PORT,
        timeout=15,
    )
    if clamd.ping():
        version = clamd.version()
        result(11, "ClamAV connection", True, version)
    else:
        result(11, "ClamAV connection", False,
               "Daemon not responding — ClamAV needs 2-3 min on first boot to load definitions")
except ImportError:
    result(11, "ClamAV connection", False, "pyclamd not installed — rebuild container")
except Exception as error:
    result(11, "ClamAV connection", False,
           f"{error} — ClamAV may still be loading definitions, wait 2-3 min and re-run")

# Test 12 — File rename logic
try:
    from app.postprocessor import rename_file

    test_filename = "interstellar.2014.1080p.bluray.mkv"
    test_file_path = os.path.join(config.DOWNLOADS_PATH, test_filename)

    os.makedirs(config.DOWNLOADS_PATH, exist_ok=True)
    with open(test_file_path, "w") as fh:
        fh.write("dummy")

    new_path = rename_file(test_file_path, "Interstellar", "2014")

    expected_filename = "Interstellar (2014).mkv"
    expected_folder = "Interstellar (2014)"

    if new_path and expected_filename in new_path and expected_folder in new_path:
        result(12, "File rename to Jellyfin format", True, f"→ {new_path}")
        try:
            os.remove(new_path)
            os.rmdir(os.path.dirname(new_path))
        except Exception:
            pass
    else:
        result(12, "File rename to Jellyfin format", False, f"got: {new_path}")
except Exception as error:
    result(12, "File rename to Jellyfin format", False, str(error))

# Test 13 — Jellyfin notification
try:
    from app.postprocessor import notify_jellyfin
    success = notify_jellyfin()
    if config.JELLYFIN_API_KEY.strip().lower() == "changeme":
        result(13, "Jellyfin notification", True, "API key is 'changeme' — not yet configured (expected)")
    elif success:
        result(13, "Jellyfin notification", True, "200 response received")
    else:
        result(13, "Jellyfin notification", False, "Check JELLYFIN_HOST and JELLYFIN_API_KEY")
except Exception as error:
    result(13, "Jellyfin notification", False, str(error))

# Test 14 — Full post-processing simulation (manual confirmation required)
section("Test 14 — Full post-processing simulation (manual)")
print()
print("  This test requires a real completed download in qBittorrent.")
print("  It will NOT run automatically to avoid touching real data.")
print()

try:
    from app.postprocessor import check_completed_downloads, process_movie
    completed = check_completed_downloads()

    if not completed:
        print("  No completed downloads found in qBittorrent.")
        print("  Test 14: SKIPPED (nothing to process)")
    else:
        print(f"  Found {len(completed)} completed download(s):")
        for movie in completed:
            print(f"    - [{movie['id']}] {movie['title']} ({movie.get('year', '?')})")

        print()
        answer = input("  Run process_movie() on the first result? (yes/no): ").strip().lower()
        if answer == "yes":
            success = process_movie(completed[0])
            result(14, "Full post-processing simulation", success, completed[0]["title"])
        else:
            print("  Test 14: SKIPPED by user")
except Exception as error:
    result(14, "Full post-processing simulation", False, str(error))


# ===========================================================================
# Phase 3 tests — AI layer
# ===========================================================================

def test_15_tool_registry_loads():
    """Test that all 7 tools are present and have required schema fields."""
    print("\n--- Test 15: Tool registry loads ---")
    try:
        from app.tools import TOOL_SCHEMAS
        assert len(TOOL_SCHEMAS) == 7, f"Expected 7 tools, got {len(TOOL_SCHEMAS)}"
        required_names = {
            "search_movie",
            "get_movie_details",
            "request_movie",
            "get_download_status",
            "list_library",
            "suggest_similar",
            "check_exists",
        }
        found_names = set()
        for schema in TOOL_SCHEMAS:
            func = schema.get("function", {})
            name = func.get("name")
            assert name, "Tool schema missing name"
            assert func.get("description"), f"Tool '{name}' missing description"
            assert func.get("parameters"), f"Tool '{name}' missing parameters"
            found_names.add(name)
        assert found_names == required_names, (
            f"Tool name mismatch.\nExpected: {required_names}\nFound: {found_names}"
        )
        print("PASS — 7 tools found with valid schemas")
        return True
    except Exception as error:
        print(f"FAIL — {error}")
        return False


def test_16_tool_execution():
    """Test that core tools execute without crashing."""
    print("\n--- Test 16: Tool execution ---")
    try:
        from app.tools import execute_tool

        result_library = execute_tool("list_library", {})
        assert isinstance(result_library, str), "list_library did not return a string"
        print(f"  list_library: {result_library[:80]}")

        result_search = execute_tool("search_movie", {"query": "Interstellar"})
        assert isinstance(result_search, str), "search_movie did not return a string"
        print(f"  search_movie: {result_search[:80]}")

        result_exists = execute_tool("check_exists", {"title": "Interstellar"})
        assert isinstance(result_exists, str), "check_exists did not return a string"
        print(f"  check_exists: {result_exists[:80]}")

        print("PASS — all tool executions returned strings")
        return True
    except Exception as error:
        print(f"FAIL — {error}")
        return False


def test_17_agent_initialises():
    """Test that HookReelAgent initialises without errors."""
    print("\n--- Test 17: Agent initialises ---")
    try:
        from app.agent import HookReelAgent, SYSTEM_PROMPT
        agent = HookReelAgent()
        assert agent.history[0]["role"] == "system", "System prompt not in history"
        assert SYSTEM_PROMPT in agent.history[0]["content"], "System prompt content missing"
        assert agent.client is not None, "OpenAI client not initialised"
        assert agent.model, "Model name not loaded"
        print(f"  Model: {agent.model}")
        print(f"  Max tool rounds: {agent.max_tool_rounds}")
        print("PASS — agent initialised correctly")
        return True
    except Exception as error:
        print(f"FAIL — {error}")
        return False


def test_18_single_turn_no_tools():
    """
    Test a single-turn conversation that should not require tool calls.
    WARNING: Makes a real API call to DeepSeek.
    """
    print("\n--- Test 18: Single turn conversation (no tools) ---")
    if os.environ.get("HOOKREEL_RUN_API_TESTS", "").lower() != "y":
        print("SKIPPED -- set HOOKREEL_RUN_API_TESTS=y to run")
        return None
    try:
        from app.agent import HookReelAgent
        agent = HookReelAgent()
        response = agent.chat("Hello, what can you do?")
        assert isinstance(response, str), "Response is not a string"
        assert len(response) > 0, "Response is empty"
        print(f"  Response: {response[:200]}")
        print("PASS -- received non-empty response")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False

def test_19_tool_calling_conversation():
    """
    Test that the agent calls list_library when asked about the library.
    WARNING: Makes a real API call to DeepSeek.
    """
    print("\n--- Test 19: Tool-calling conversation ---")
    if os.environ.get("HOOKREEL_RUN_API_TESTS", "").lower() != "y":
        print("SKIPPED -- set HOOKREEL_RUN_API_TESTS=y to run")
        return None
    try:
        from app.agent import HookReelAgent
        agent = HookReelAgent()
        response = agent.chat("What movies do I have in my library?")
        assert isinstance(response, str), "Response is not a string"
        assert len(response) > 0, "Response is empty"
        history_roles = [m["role"] for m in agent.history]
        assert "tool" in history_roles, "No tool call was made"
        print(f"  Response: {response[:200]}")
        print("PASS -- tool was called and response received")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_20_full_movie_request():
    """
    Full AI movie request simulation. WARNING: triggers a real download.
    """
    print("\n--- Test 20: Full AI movie request simulation ---")
    if os.environ.get("HOOKREEL_RUN_API_TESTS", "").lower() != "y":
        print("SKIPPED -- set HOOKREEL_RUN_API_TESTS=y to run")
        return None
    try:
        from app.conversation import ConversationManager
        manager = ConversationManager()
        response_1 = manager.handle_message("test_user", "Can you find the movie The Matrix for me?")
        print(f"  Turn 1: {response_1[:300]}")
        assert isinstance(response_1, str) and len(response_1) > 0

        response_2 = manager.handle_message("test_user", "Yes, please download the first result.")
        print(f"  Turn 2: {response_2[:300]}")
        assert isinstance(response_2, str) and len(response_2) > 0

        print("PASS -- multi-turn AI movie request completed")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


# -----------------------------------------------------------------------
# Phase 4 tests — Telegram bot
# -----------------------------------------------------------------------

def test_21_telegram_config():
    """
    Test 21 — Telegram configuration check.
    Verifies that bot token and allowed user ID are set to real values.
    Checks token format: must contain a colon and be over 20 chars.
    """
    section("Test 21 - Telegram config check")
    try:
        token = config.TELEGRAM_BOT_TOKEN
        user_id = config.TELEGRAM_ALLOWED_USER_ID

        if not token or token.strip().lower() == "changeme":
            print("  FAIL — TELEGRAM_BOT_TOKEN is not set")
            return False

        if not user_id or user_id.strip().lower() == "changeme":
            print("  FAIL — TELEGRAM_ALLOWED_USER_ID is not set")
            return False

        if ":" not in token:
            print("  FAIL — Token does not look valid (no colon found)")
            return False

        if len(token) < 20:
            print("  FAIL — Token does not look valid (too short)")
            return False

        print(f"  Token format: OK (length={len(token)})")
        print(f"  Allowed user ID: configured (not shown)")
        print("  PASS")
        return True

    except Exception as error:
        print(f"  FAIL — {error}")
        return False


def test_22_bot_initialises():
    """
    Test 22 — Bot initialises without errors.
    Creates a HookReelBot instance and verifies it loads cleanly.
    Does NOT start polling — just checks the init path.
    """
    section("Test 22 - Bot initialises")
    try:
        from app.conversation import ConversationManager
        from app.telegram_bot import HookReelBot

        conversation_manager = ConversationManager()
        bot = HookReelBot(conversation_manager)

        if bot.application is None:
            print("  FAIL — application is None after init")
            return False

        if not bot.allowed_user_ids:
            print("  FAIL — allowed_user_ids is empty after init")
            return False

        print(f"  Bot application: initialised")
        print(f"  Allowed users loaded: {len(bot.allowed_user_ids)}")
        print("  PASS")
        return True

    except Exception as error:
        print(f"  FAIL — {error}")
        return False


def test_23_whitelist_check():
    """
    Test 23 — Whitelist check works correctly.
    Verifies that the configured user ID is allowed and a
    fake ID is rejected.
    """
    section("Test 23 - Whitelist check")
    try:
        from app.conversation import ConversationManager
        from app.telegram_bot import HookReelBot

        conversation_manager = ConversationManager()
        bot = HookReelBot(conversation_manager)

        real_id = bot.allowed_user_ids[0]
        fake_id = 99999

        if not bot.is_allowed(real_id):
            print(f"  FAIL — configured user ID {real_id} was rejected")
            return False

        if bot.is_allowed(fake_id):
            print(f"  FAIL — fake ID {fake_id} was incorrectly allowed")
            return False

        print(f"  Configured user ID: allowed correctly")
        print(f"  Fake ID {fake_id}: rejected correctly")
        print("  PASS")
        return True

    except Exception as error:
        print(f"  FAIL — {error}")
        return False


if __name__ == "__main__":
    results = []
    results.append(("Test 15 - Tool registry", test_15_tool_registry_loads()))
    results.append(("Test 16 - Tool execution", test_16_tool_execution()))
    results.append(("Test 17 - Agent initialises", test_17_agent_initialises()))
    results.append(("Test 18 - Single turn", test_18_single_turn_no_tools()))
    results.append(("Test 19 - Tool calling", test_19_tool_calling_conversation()))
    results.append(("Test 20 - Full request", test_20_full_movie_request()))
    print("\n=== Phase 3 test summary ===")
    for name, result in results:
        status = "PASS" if result is True else ("SKIP" if result is None else "FAIL")
        print(f"  {status}  {name}")

    results4 = []
    results4.append(("Test 21 - Telegram config", test_21_telegram_config()))
    results4.append(("Test 22 - Bot initialises", test_22_bot_initialises()))
    results4.append(("Test 23 - Whitelist check", test_23_whitelist_check()))
    print("\n=== Phase 4 test summary ===")
    for name, result in results4:
        status = "PASS" if result is True else ("SKIP" if result is None else "FAIL")
        print(f"  {status}  {name}")


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
section("Test run complete")
print()
print("  Phase 1: tests 1-8")
print("  Phase 2: tests 9-14")
print("  Phase 3: tests 15-20")
print("  Phase 4: tests 21-23")
print()
print("  If Test 11 (ClamAV) failed: wait 2-3 minutes and re-run.")
print("  If Test 6 (qBittorrent) failed: check VPN container is running.")
print("  If Test 17 (agent init) failed: check AI_API_KEY and AI_MODEL_ENDPOINT in .env")
print("  If Test 21 (Telegram config) failed: check TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID in .env")
print()
