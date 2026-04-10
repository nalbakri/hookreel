"""
test_phase65.py — Phase 6.5 test suite (Watch Mode + File Management)

Tests 46–55 covering:
- FFmpeg availability
- Watch history database round-trip
- Jellyfin connection
- Deep link generation
- Watch tools registered
- Next episode logic
- HLS streamer init
- Delete disabled by default
- File management tools registered
- Path validation
"""

import sys
import os
import argparse

sys.path.insert(0, "/hookreel")
os.environ.setdefault("PYTHONPATH", "/hookreel")

# ── Helpers ────────────────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results = []


def record(number, description, status, note=""):
    """Record a test result and print it immediately."""
    icon = "✓" if status == PASS else ("⚠" if status == SKIP else "✗")
    line = f"  Test {number}: [{status}] {icon} {description}"
    if note:
        line += f"\n         → {note}"
    print(line)
    results.append((number, description, status, note))


def summary():
    """Print final summary and return exit code."""
    passed = sum(1 for r in results if r[2] == PASS)
    failed = sum(1 for r in results if r[2] == FAIL)
    skipped = sum(1 for r in results if r[2] == SKIP)
    print(f"\n{'─'*55}")
    print(f"  Phase 6.5 results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'─'*55}\n")
    return 0 if failed == 0 else 1


# ── Test 46 — FFmpeg available ─────────────────────────────────────────────────

def test_46():
    """FFmpeg binary is present and executable inside the container."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and "ffmpeg version" in result.stdout:
            version_line = result.stdout.splitlines()[0]
            record(46, "FFmpeg available", PASS, version_line)
        else:
            record(46, "FFmpeg available", FAIL, result.stderr[:100])
    except FileNotFoundError:
        record(46, "FFmpeg available", FAIL, "ffmpeg binary not found")
    except Exception as e:
        record(46, "FFmpeg available", FAIL, str(e))


# ── Test 47 — Watch history database ──────────────────────────────────────────

def test_47():
    """Watch history round-trip: add event then retrieve it."""
    try:
        import app.database as database
        database.initialise()

        watch_id = database.add_watch_event(
            media_type="movie",
            media_id=9999,
            title="Test Watch Movie Phase65",
        )
        if watch_id == -1:
            record(47, "Watch history database", FAIL, "add_watch_event returned -1")
            return

        history = database.get_watch_history(limit=5)
        found = any(
            e.get("title") == "Test Watch Movie Phase65"
            for e in history
        )
        if found:
            record(47, "Watch history database", PASS,
                   f"watch_id={watch_id}, retrieved from history")
        else:
            record(47, "Watch history database", FAIL,
                   "Event added but not found in get_watch_history()")

        # Clean up test row
        conn = database.get_connection()
        conn.execute(
            "DELETE FROM watch_history WHERE title = 'Test Watch Movie Phase65'"
        )
        conn.commit()
        conn.close()

    except Exception as e:
        record(47, "Watch history database", FAIL, str(e))


# ── Test 48 — Jellyfin connection ──────────────────────────────────────────────

def test_48():
    """Jellyfin API responds and get_jellyfin_item runs without crashing."""
    try:
        from app.jellyfin import get_jellyfin_item
        result = get_jellyfin_item("Spaceballs", "Movie")
        if result is not None:
            record(48, "Jellyfin connection", PASS,
                   f"Found in Jellyfin: '{result.get('title')}' id={result.get('jellyfin_id')[:8]}...")
        else:
            record(48, "Jellyfin connection", PASS,
                   "Jellyfin responded — Spaceballs not in library (function ran cleanly)")
    except Exception as e:
        record(48, "Jellyfin connection", FAIL, str(e))


# ── Test 49 — Deep link generation ────────────────────────────────────────────

def test_49():
    """generate_deep_link returns dict with web and app keys containing Jellyfin host."""
    try:
        from app.jellyfin import generate_deep_link
        import app.config as config

        links = generate_deep_link("test-id-abc123")
        if not isinstance(links, dict):
            record(49, "Deep link generation", FAIL, f"Expected dict, got {type(links)}")
            return
        if "web" not in links or "app" not in links:
            record(49, "Deep link generation", FAIL, f"Missing keys: {links.keys()}")
            return
        if config.JELLYFIN_HOST not in links["web"]:
            record(49, "Deep link generation", FAIL,
                   f"Jellyfin host not in web link: {links['web']}")
            return
        if "test-id-abc123" not in links["web"]:
            record(49, "Deep link generation", FAIL,
                   f"Item ID not in web link: {links['web']}")
            return
        record(49, "Deep link generation", PASS,
               f"web={links['web'][:50]}...")
    except Exception as e:
        record(49, "Deep link generation", FAIL, str(e))


# ── Test 50 — Watch tools registered ──────────────────────────────────────────

def test_50():
    """All 8 new tools are present in TOOL_SCHEMAS."""
    try:
        from app.tools import TOOL_SCHEMAS

        expected = {
            "watch_movie", "watch_next_episode", "watch_episode",
            "get_watch_history", "stop_stream", "get_active_streams",
            "delete_media", "move_media",
        }
        registered = {
            t["function"]["name"]
            for t in TOOL_SCHEMAS
            if t.get("type") == "function"
        }
        missing = expected - registered
        if missing:
            record(50, "Watch tools registered", FAIL,
                   f"Missing tools: {missing}")
        else:
            record(50, "Watch tools registered", PASS,
                   f"All 8 tools present ({len(registered)} total tools registered)")
    except Exception as e:
        record(50, "Watch tools registered", FAIL, str(e))


# ── Test 51 — Next episode logic ───────────────────────────────────────────────

def test_51():
    """get_next_episode_to_watch returns correct next episode after watch history."""
    try:
        import app.database as database
        database.initialise()

        # Add a test show
        show_id = database.add_show(
            provider_id="test-phase65-show",
            title="Test Show Phase65",
            year="2020"
        )
        if show_id == -1:
            record(51, "Next episode logic", FAIL, "Could not add test show")
            return

        # Add episodes S01E01, S01E02, S01E03
        ep1_id = database.add_episode(show_id, 1, 1, "Pilot", "2020-01-01")
        ep2_id = database.add_episode(show_id, 1, 2, "Episode 2", "2020-01-08")
        ep3_id = database.add_episode(show_id, 1, 3, "Episode 3", "2020-01-15")

        # Mark S01E01 and S01E02 as complete
        database.update_episode_status(ep1_id, "complete")
        database.update_episode_status(ep2_id, "complete")

        # Add watch history for S01E01 and S01E02 (both completed)
        w1 = database.add_watch_event("episode", ep1_id, "Test Show Phase65 S01E01")
        database.mark_completed(w1)
        w2 = database.add_watch_event("episode", ep2_id, "Test Show Phase65 S01E02")
        database.mark_completed(w2)

        # Now ask for next episode — should be S01E03
        next_ep = database.get_next_episode_to_watch(show_id)

        if next_ep is None:
            record(51, "Next episode logic", FAIL,
                   "get_next_episode_to_watch returned None — expected S01E03")
        elif next_ep["season"] == 1 and next_ep["episode"] == 3:
            record(51, "Next episode logic", PASS,
                   f"Correctly returned S01E03 (id={next_ep['id']})")
        else:
            record(51, "Next episode logic", FAIL,
                   f"Expected S01E03, got S{next_ep['season']:02d}E{next_ep['episode']:02d}")

        # Clean up
        conn = database.get_connection()
        conn.execute("DELETE FROM watch_history WHERE media_id IN (?,?,?)",
                     (ep1_id, ep2_id, ep3_id))
        conn.execute("DELETE FROM episodes WHERE show_id = ?", (show_id,))
        conn.execute("DELETE FROM shows WHERE id = ?", (show_id,))
        conn.commit()
        conn.close()

    except Exception as e:
        record(51, "Next episode logic", FAIL, str(e))


# ── Test 52 — HLS streamer init ────────────────────────────────────────────────

def test_52():
    """HLSStreamer initialises cleanly (skipped if Jellyfin is enabled)."""
    try:
        import app.config as config
        if config.JELLYFIN_ENABLED:
            record(52, "HLS streamer init", SKIP,
                   "JELLYFIN_ENABLED=true — HLS tier is fallback only, skipping")
            return

        from app.hls_streamer import HLSStreamer
        streamer = HLSStreamer()
        if os.path.isdir(streamer.stream_dir):
            record(52, "HLS streamer init", PASS,
                   f"Stream dir created: {streamer.stream_dir}")
        else:
            record(52, "HLS streamer init", FAIL,
                   f"Stream dir not created: {streamer.stream_dir}")
    except Exception as e:
        record(52, "HLS streamer init", FAIL, str(e))


# ── Test 53 — Delete disabled by default ──────────────────────────────────────

def test_53():
    """delete_media tool returns disabled message when DELETE_ENABLED=false."""
    try:
        import app.config as config
        if config.DELETE_ENABLED:
            record(53, "Delete disabled by default", SKIP,
                   "DELETE_ENABLED=true in this environment — skipping")
            return

        from app.tools import execute_tool
        result = execute_tool("delete_media", {
            "media_type": "movie",
            "media_id": 1,
            "confirm": True,
        })
        if "disabled" in result.lower() or "enable" in result.lower():
            record(53, "Delete disabled by default", PASS,
                   f"Tool correctly blocked: {result[:80]}")
        else:
            record(53, "Delete disabled by default", FAIL,
                   f"Expected disabled message, got: {result[:80]}")
    except Exception as e:
        record(53, "Delete disabled by default", FAIL, str(e))


# ── Test 54 — File manipulation tools registered ──────────────────────────────

def test_54():
    """stop_stream, get_active_streams, delete_media, move_media all in TOOL_SCHEMAS."""
    try:
        from app.tools import TOOL_SCHEMAS
        expected = {"stop_stream", "get_active_streams", "delete_media", "move_media"}
        registered = {
            t["function"]["name"]
            for t in TOOL_SCHEMAS
            if t.get("type") == "function"
        }
        missing = expected - registered
        if missing:
            record(54, "File manipulation tools registered", FAIL,
                   f"Missing: {missing}")
        else:
            record(54, "File manipulation tools registered", PASS,
                   "All 4 file/stream tools present")
    except Exception as e:
        record(54, "File manipulation tools registered", FAIL, str(e))


# ── Test 55 — Path validation ──────────────────────────────────────────────────

def test_55():
    """_validate_path rejects paths outside MOVIES_PATH and TV_PATH."""
    try:
        from app.tools import _validate_path

        # Path that must be rejected
        bad_path = "/etc/passwd"
        if _validate_path(bad_path):
            record(55, "Path validation", FAIL,
                   f"'/etc/passwd' was incorrectly allowed")
            return

        # Path within MOVIES_PATH must be accepted
        import app.config as config
        good_path = os.path.join(config.MOVIES_PATH, "SomeMovie", "movie.mkv")
        if not _validate_path(good_path):
            record(55, "Path validation", FAIL,
                   f"Valid path '{good_path}' was incorrectly rejected")
            return

        record(55, "Path validation", PASS,
               f"'/etc/passwd' rejected, '{good_path[:40]}...' accepted")
    except Exception as e:
        record(55, "Path validation", FAIL, str(e))


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 6.5 test suite")
    parser.add_argument("--quick", action="store_true",
                        help="Skip tests that require network calls")
    args = parser.parse_args()

    print("\n" + "═"*55)
    print("  HookReel — Phase 6.5 Test Suite")
    print("  Watch Mode + File Management")
    print("═"*55 + "\n")

    test_46()
    test_47()

    if args.quick:
        record(48, "Jellyfin connection", SKIP, "--quick flag set")
    else:
        test_48()

    test_49()
    test_50()
    test_51()
    test_52()
    test_53()
    test_54()
    test_55()

    return summary()


if __name__ == "__main__":
    sys.exit(main())
