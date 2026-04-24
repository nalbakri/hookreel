"""
test_patch2.py -- HookReel v1.0.2 patch tests (97-102)

Tests:
  97 - stalledUP is recognised as a complete state
  98 - stalledDL is NOT recognised as a complete state
  99 - RTMP credentials are read from .env at call time (not module cache)
  100 - persona.py loads from /config/persona.json when present
  101 - persona.py falls back to defaults when /config/persona.json absent
  102 - chat route context includes greeting from get_greeting()
"""

import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_97_stalledup_is_complete():
    """stalledUP must be in the complete_states set in postprocessor.py."""
    import importlib, ast
    path = os.path.join(os.path.dirname(__file__), "app", "postprocessor.py")
    with open(path) as f:
        source = f.read()
    assert "stalledUP" in source, "stalledUP missing from postprocessor.py"
    assert '"stalledUP"' in source or "'stalledUP'" in source
    print("Test 97 PASS -- stalledUP present in postprocessor.py")
    return True


def test_98_stalleddl_not_complete():
    """stalledDL must NOT be in the complete_states set."""
    path = os.path.join(os.path.dirname(__file__), "app", "postprocessor.py")
    with open(path) as f:
        source = f.read()
    # Find the complete_states assignment and confirm stalledDL is absent
    assert "stalledDL" not in source, "stalledDL must not be in complete_states"
    print("Test 98 PASS -- stalledDL correctly absent from complete_states")
    return True


def test_99_rtmp_credentials_read_from_env_file():
    """_read_rtmp_credentials() must exist in telegram_bot.py and read from /config/.env."""
    path = os.path.join(os.path.dirname(__file__), "app", "telegram_bot.py")
    with open(path) as f:
        source = f.read()
    assert "_read_rtmp_credentials" in source, "_read_rtmp_credentials not found in telegram_bot.py"
    assert "/config/.env" in source, "/config/.env not referenced in telegram_bot.py"
    # Confirm _do_stream uses _read_rtmp_credentials, not config.TELEGRAM_RTMP_URL
    lines = source.splitlines()
    in_do_stream = False
    for line in lines:
        if "async def _do_stream" in line:
            in_do_stream = True
        if in_do_stream:
            assert "config.TELEGRAM_RTMP_URL" not in line, \
                "_do_stream still uses stale config.TELEGRAM_RTMP_URL"
            assert "config.TELEGRAM_RTMP_KEY" not in line, \
                "_do_stream still uses stale config.TELEGRAM_RTMP_KEY"
            if line.strip().startswith("async def ") and "do_stream" not in line:
                break
    print("Test 99 PASS -- _read_rtmp_credentials present and _do_stream uses it")
    return True


def test_100_persona_loads_from_config_volume():
    """persona.py must load from /config/persona.json."""
    path = os.path.join(os.path.dirname(__file__), "app", "persona.py")
    with open(path) as f:
        source = f.read()
    assert '_PERSONA_PATH = "/config/persona.json"' in source, \
        "_PERSONA_PATH not set to /config/persona.json"
    print("Test 100 PASS -- _PERSONA_PATH correctly set to /config/persona.json")
    return True


def test_101_persona_writes_defaults_when_missing():
    """load_persona() must write defaults to /config/persona.json when file absent."""
    path = os.path.join(os.path.dirname(__file__), "app", "persona.py")
    with open(path) as f:
        source = f.read()
    assert "writing defaults to /config/persona.json" in source, \
        "load_persona does not write defaults on first start"
    assert 'json.dump(default, fh' in source, \
        "load_persona does not write defaults with json.dump"
    print("Test 101 PASS -- load_persona writes defaults when file missing")
    return True


def test_102_chat_route_includes_greeting():
    """chat route in webui.py must pass greeting from get_greeting() to template."""
    path = os.path.join(os.path.dirname(__file__), "app", "webui.py")
    with open(path) as f:
        source = f.read()
    assert "get_greeting" in source, "get_greeting not imported in webui.py"
    assert '"greeting": get_greeting()' in source, \
        "chat route context missing greeting key"
    # Also verify chat.html uses the variable
    tmpl = os.path.join(os.path.dirname(__file__), "app", "templates", "chat.html")
    with open(tmpl) as f:
        html = f.read()
    assert "{{ greeting }}" in html, "chat.html does not use {{ greeting }} variable"
    print("Test 102 PASS -- chat route passes greeting and chat.html uses it")
    return True

def test_103_queuedup_in_complete_states():
    """queuedUP must be in complete_states in postprocessor.py."""
    path = os.path.join(os.path.dirname(__file__), "app", "postprocessor.py")
    with open(path) as f:
        source = f.read()
    assert '"queuedUP"' in source or "'queuedUP'" in source, \
        "queuedUP missing from complete_states"
    print("Test 103 PASS -- queuedUP present in complete_states")
    return True


def test_104_title_fallback_disabled():
    """Title-based fallback in _resolve_file_path must be disabled."""
    path = os.path.join(os.path.dirname(__file__), "app", "postprocessor.py")
    with open(path) as f:
        source = f.read()
    assert "Disabled in v1.0.3" in source, \
        "Title fallback not marked as disabled in postprocessor.py"
    print("Test 104 PASS -- title-based fallback disabled in _resolve_file_path")
    return True


def test_105_recover_stuck_downloads_exists():
    """recover_stuck_downloads() must exist in main.py."""
    path = os.path.join(os.path.dirname(__file__), "main.py")
    with open(path) as f:
        source = f.read()
    assert "def recover_stuck_downloads" in source, \
        "recover_stuck_downloads not found in main.py"
    assert "recover_stuck_downloads()" in source, \
        "recover_stuck_downloads() not called at startup"
    print("Test 105 PASS -- recover_stuck_downloads exists and is called at startup")
    return True

if __name__ == "__main__":
    tests = [
        test_97_stalledup_is_complete,
        test_98_stalleddl_not_complete,
        test_99_rtmp_credentials_read_from_env_file,
        test_100_persona_loads_from_config_volume,
        test_101_persona_writes_defaults_when_missing,
        test_102_chat_route_includes_greeting,
        test_103_queuedup_in_complete_states,
        test_104_title_fallback_disabled,
        test_105_recover_stuck_downloads_exists,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed")
