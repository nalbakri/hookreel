#!/usr/bin/env python3
"""
test_phase8.py -- Phase 8 tests.
Tests 77-88 covering persona, setup wizard, library import,
version constants, security headers, and media sources.
"""

import os
import sys
import json
import tempfile

sys.path.insert(0, "/hookreel")

from dotenv import load_dotenv
load_dotenv("/config/.env", override=False)


def test_77_persona_loads():
    """Persona loads correctly and has required fields."""
    print("--- Test 77: Persona loads correctly ---")
    try:
        from app.persona import load_persona
        persona = load_persona()
        assert "name" in persona, "name field missing"
        assert "personality" in persona, "personality field missing"
        assert "greeting" in persona, "greeting field missing"
        assert persona["name"], "name is empty"
        print("  Persona: name={} personality={}".format(
            persona["name"], persona["personality"]
        ))
        return "PASS", "Persona loaded: {}".format(persona["name"])
    except Exception as exc:
        return "FAIL", str(exc)


def test_78_agent_name_update():
    """Agent name can be updated and round-trips correctly."""
    print("--- Test 78: Agent name update ---")
    try:
        from app.persona import update_name, get_name, save_persona, load_persona
        original = get_name()
        success = update_name("Alfred")
        assert success, "update_name returned False"
        assert get_name() == "Alfred", "get_name did not return Alfred"
        # Restore
        save_persona({**load_persona(), "name": original})
        assert get_name() == original, "restore failed"
        return "PASS", "Round-trip name update works"
    except Exception as exc:
        return "FAIL", str(exc)


def test_79_version_constants():
    """VERSION and VERSION_NAME are set correctly."""
    print("--- Test 79: Version constants ---")
    try:
        import app.config as config
        assert config.VERSION == "1.0", "VERSION != 1.0"
        assert config.VERSION_NAME == "Hook", "VERSION_NAME != Hook"
        return "PASS", "v{} {}".format(config.VERSION, config.VERSION_NAME)
    except Exception as exc:
        return "FAIL", str(exc)


def test_80_scan_library_tool_registered():
    """scan_library tool is registered in TOOL_SCHEMAS."""
    print("--- Test 80: scan_library tool registered ---")
    try:
        from app.tools import TOOL_SCHEMAS
        names = [t["function"]["name"] for t in TOOL_SCHEMAS]
        assert "scan_library" in names, "scan_library not in TOOL_SCHEMAS"
        return "PASS", "scan_library registered ({} tools total)".format(len(names))
    except Exception as exc:
        return "FAIL", str(exc)


def test_81_persona_tools_registered():
    """Persona tools are registered in TOOL_SCHEMAS."""
    print("--- Test 81: Persona tools registered ---")
    try:
        from app.tools import TOOL_SCHEMAS
        names = [t["function"]["name"] for t in TOOL_SCHEMAS]
        for tool in ["get_agent_info", "update_agent_name", "update_personality"]:
            assert tool in names, "{} not in TOOL_SCHEMAS".format(tool)
        return "PASS", "All 3 persona tools registered"
    except Exception as exc:
        return "FAIL", str(exc)


def test_82_build_system_prompt():
    """System prompt uses agent name from persona."""
    print("--- Test 82: System prompt uses persona name ---")
    try:
        from app.persona import update_name, load_persona, save_persona
        from app.agent import _build_system_prompt
        original = load_persona()["name"]
        update_name("TestBot")
        prompt = _build_system_prompt()
        save_persona({**load_persona(), "name": original})
        assert "TestBot" in prompt, "TestBot not in prompt"
        assert "HookReel" not in prompt or original == "HookReel", \
            "Old name still in prompt"
        return "PASS", "System prompt substitution works"
    except Exception as exc:
        return "FAIL", str(exc)


def test_83_database_phase8_columns():
    """Phase 8 columns exist in movies and episodes tables."""
    print("--- Test 83: Phase 8 DB columns present ---")
    try:
        from app.database import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(movies)")
        movie_cols = [r["name"] for r in cur.fetchall()]
        cur.execute("PRAGMA table_info(episodes)")
        ep_cols = [r["name"] for r in cur.fetchall()]
        conn.close()
        for col in ["poster_url", "overview", "rating", "source_path"]:
            assert col in movie_cols, "{} missing from movies".format(col)
        assert "source_path" in ep_cols, "source_path missing from episodes"
        return "PASS", "All Phase 8 columns present"
    except Exception as exc:
        return "FAIL", str(exc)


def test_84_import_library_flags():
    """import_library.py has all required flags."""
    print("--- Test 84: import_library flags ---")
    try:
        result = os.popen(
            "python /hookreel/import_library.py --help 2>&1"
        ).read()
        for flag in ["--dry-run", "--verbose", "--enrich",
                     "--rename", "--path", "--all-sources"]:
            assert flag in result, "{} flag missing".format(flag)
        return "PASS", "All flags present"
    except Exception as exc:
        return "FAIL", str(exc)


def test_85_extra_media_config():
    """EXTRA_MEDIA config vars are readable from config."""
    print("--- Test 85: Extra media source config ---")
    try:
        import app.config as config
        # Just verify the attributes exist
        for i in range(1, 6):
            assert hasattr(config, "EXTRA_MEDIA_{}".format(i)), \
                "EXTRA_MEDIA_{} missing".format(i)
            assert hasattr(config, "EXTRA_MEDIA_{}_LABEL".format(i)), \
                "EXTRA_MEDIA_{}_LABEL missing".format(i)
        return "PASS", "All EXTRA_MEDIA_1..5 vars present"
    except Exception as exc:
        return "FAIL", str(exc)


def test_86_scan_api_endpoint_registered():
    """POST /api/library/scan endpoint is registered."""
    print("--- Test 86: Scan API endpoint registered ---")
    try:
        from app.webui import app_fastapi
        routes = [r.path for r in app_fastapi.routes]
        assert "/api/library/scan" in routes, \
            "/api/library/scan not registered"
        assert "/api/library/sources" in routes, \
            "/api/library/sources not registered"
        return "PASS", "Library scan endpoints registered"
    except Exception as exc:
        return "FAIL", str(exc)


def test_87_setup_wizard_syntax():
    """setup.py and uninstall.py have valid Python syntax."""
    print("--- Test 87: Setup wizard syntax ---")
    try:
        import ast
        for fname in ["setup.py", "uninstall.py"]:
            path = "/hookreel/{}".format(fname)
            with open(path) as f:
                ast.parse(f.read())
        return "PASS", "setup.py and uninstall.py syntax OK"
    except Exception as exc:
        return "FAIL", str(exc)


def test_88_no_placeholder_credentials():
    """No critical placeholder values remain in .env."""
    print("--- Test 88: No placeholder credentials ---")
    try:
        placeholders = ["changeme"]
        critical_keys = [
            "WEBUI_PASSWORD", "SECRET_KEY",
        ]
        env = {}
        with open("/config/.env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
        found = []
        for key in critical_keys:
            val = env.get(key, "")
            if val in placeholders:
                found.append(key)
        if found:
            return "FAIL", "Placeholder values in: {}".format(found)
        return "PASS", "No placeholder credentials found"
    except Exception as exc:
        return "FAIL", str(exc)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all():
    tests = [
        test_77_persona_loads,
        test_78_agent_name_update,
        test_79_version_constants,
        test_80_scan_library_tool_registered,
        test_81_persona_tools_registered,
        test_82_build_system_prompt,
        test_83_database_phase8_columns,
        test_84_import_library_flags,
        test_85_extra_media_config,
        test_86_scan_api_endpoint_registered,
        test_87_setup_wizard_syntax,
        test_88_no_placeholder_credentials,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            result = test()
            status = result[0] if result else "PASS"
            detail = result[1] if result and len(result) > 1 else ""
        except Exception as exc:
            status = "FAIL"
            detail = str(exc)
        icon = "[OK]" if status == "PASS" else "[FAIL]"
        print("  {} {}: {}".format(icon, test.__name__, detail))
        if status == "PASS":
            passed += 1
        else:
            failed += 1
    print("\n--- Phase 8 results: {} passed, {} failed ---".format(
        passed, failed
    ))
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
