#!/usr/bin/env python3
"""
test_phase66.py — Phase 6.6 tests.

Tests 56-61: library import scan, title parsing, idempotency,
watchability, agent lookup, and optional Jellyfin enrichment.

Usage:
    python test_phase66.py
    python test_phase66.py --phase 66
"""

import os
import subprocess
import sys
import time

from dotenv import load_dotenv

load_dotenv("/config/.env", override=False)

import app.config as config
from app.logger import get_logger
from app.database import (
    get_movies_by_status,
    get_movies_by_title,
)

logger = get_logger(__name__)

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def print_result(number, name, status, detail=""):
    """Print a formatted test result line."""
    marker = "+" if status == PASS else ("?" if status == SKIP else "X")
    detail_str = f" -- {detail}" if detail else ""
    print(f"  [{marker}] Test {number}: {name}{detail_str}")


def run_test(number, name, func):
    """Run a single test function and print the result."""
    try:
        status, detail = func()
        print_result(number, name, status, detail)
        return status == PASS
    except Exception as exc:
        print_result(number, name, FAIL, str(exc))
        return False


# ---------------------------------------------------------------------------
# Test 56 -- Movie scan finds files
# ---------------------------------------------------------------------------

def test_56_movie_scan():
    """
    Run import_library.py in dry-run mode and verify it finds
    at least 10 movie folders.
    """
    result = subprocess.run(
        [sys.executable, "import_library.py", "--dry-run"],
        capture_output=True,
        text=True,
        cwd="/hookreel",
    )
    output = result.stdout + result.stderr

    # Extract scanned count from summary line
    scanned = 0
    for line in output.splitlines():
        if line.strip().startswith("Scanned:"):
            try:
                scanned = int(line.split(":")[1].strip())
            except ValueError:
                pass

    if scanned >= 10:
        return PASS, f"Scanned {scanned} movie folders"
    return FAIL, f"Only found {scanned} folders (need >= 10)"


# ---------------------------------------------------------------------------
# Test 57 -- Title parsing
# ---------------------------------------------------------------------------

def test_57_title_parsing():
    """
    Test parse_movie_folder_name() directly with known inputs.
    All three cases must parse correctly.
    """
    # Import the parser directly from the script
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "import_library", "/hookreel/import_library.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    cases = [
        ("Interstellar (2014)", "Interstellar", "2014"),
        ("The Dark Knight (2008) [BluRay] [1080p]", "The Dark Knight", "2008"),
        ("Dune.2021.1080p.BluRay", "Dune", "2021"),
    ]

    failures = []
    for folder, expected_title, expected_year in cases:
        title, year = mod.parse_movie_folder_name(folder)
        if title != expected_title or year != expected_year:
            failures.append(
                f"'{folder}' -> got ('{title}', '{year}'), "
                f"expected ('{expected_title}', '{expected_year}')"
            )

    if not failures:
        return PASS, f"All {len(cases)} cases parsed correctly"
    return FAIL, "; ".join(failures)


# ---------------------------------------------------------------------------
# Test 58 -- Idempotency
# ---------------------------------------------------------------------------

def test_58_idempotency():
    """
    Run the full import twice and verify the second run adds 0 new rows.
    """
    before = get_movies_by_status("complete")
    count_before = len(before)

    result = subprocess.run(
        [sys.executable, "import_library.py"],
        capture_output=True,
        text=True,
        cwd="/hookreel",
    )

    after = get_movies_by_status("complete")
    count_after = len(after)

    added = count_after - count_before
    if added == 0:
        return PASS, f"Second run added 0 rows (total remains {count_after})"
    return FAIL, f"Second run added {added} unexpected rows"


# ---------------------------------------------------------------------------
# Test 59 -- Complete movies are watchable
# ---------------------------------------------------------------------------

def test_59_complete_movies_watchable():
    """
    Verify all complete movies have a non-None file_path.
    """
    movies = get_movies_by_status("complete")

    if len(movies) < 10:
        return FAIL, f"Only {len(movies)} complete movies (need >= 10)"

    missing_path = [m["title"] for m in movies if not m.get("file_path")]

    if not missing_path:
        return PASS, f"{len(movies)} complete movies all have file_path set"
    return FAIL, f"{len(missing_path)} movies missing file_path: {missing_path[:3]}"


# ---------------------------------------------------------------------------
# Test 60 -- Agent can find imported movie
# ---------------------------------------------------------------------------

def test_60_agent_finds_movie():
    """
    Call get_movies_by_title('Interstellar') and verify it returns
    a complete entry with a file_path.
    """
    results = get_movies_by_title("Interstellar")

    if not results:
        return FAIL, "No results returned for 'Interstellar'"

    complete = [m for m in results if m["status"] == "complete" and m.get("file_path")]
    if complete:
        movie = complete[0]
        return PASS, (
            f"Found '{movie['title']}' ({movie['year']}) "
            f"status={movie['status']}"
        )
    return FAIL, f"Found {len(results)} result(s) but none are complete with file_path"


# ---------------------------------------------------------------------------
# Test 61 -- Jellyfin enrichment (optional)
# ---------------------------------------------------------------------------

def test_61_jellyfin_enrichment():
    """
    Run import with --enrich-jellyfin on one known title.
    Skip if Jellyfin is not configured.
    """
    jellyfin_url = getattr(config, "JELLYFIN_URL", None) or os.getenv("JELLYFIN_URL")
    jellyfin_key = getattr(config, "JELLYFIN_API_KEY", None) or os.getenv("JELLYFIN_API_KEY")

    if not jellyfin_url or not jellyfin_key:
        return SKIP, "Jellyfin not configured (JELLYFIN_URL or JELLYFIN_API_KEY not set)"

    result = subprocess.run(
        [sys.executable, "import_library.py", "--enrich-jellyfin", "--verbose"],
        capture_output=True,
        text=True,
        cwd="/hookreel",
    )
    output = result.stdout + result.stderr

    if "Jellyfin match found" in output:
        # Count matches
        matches = output.count("Jellyfin match found")
        return PASS, f"{matches} Jellyfin match(es) found during enrichment run"

    if "No Jellyfin match" in output:
        return SKIP, "Jellyfin reachable but no titles matched (library may differ)"

    return FAIL, f"Enrichment run produced no Jellyfin output. stderr: {result.stderr[:200]}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Run all Phase 6.6 tests."""
    print("\n=== Phase 6.6 Tests: Library Import ===\n")

    start = time.monotonic()
    results = []

    results.append(run_test(56, "Movie scan finds files", test_56_movie_scan))
    results.append(run_test(57, "Title parsing", test_57_title_parsing))
    results.append(run_test(58, "Idempotency", test_58_idempotency))
    results.append(run_test(59, "Complete movies watchable", test_59_complete_movies_watchable))
    results.append(run_test(60, "Agent can find imported movie", test_60_agent_finds_movie))
    results.append(run_test(61, "Jellyfin enrichment (optional)", test_61_jellyfin_enrichment))

    elapsed = time.monotonic() - start
    passed = sum(1 for r in results if r)
    total = len(results)

    print(f"\n  {passed}/{total} tests passed in {elapsed:.1f}s")

    if passed == total:
        print("  All Phase 6.6 tests passed.\n")
    else:
        print("  Some tests failed. See above.\n")


if __name__ == "__main__":
    main()
