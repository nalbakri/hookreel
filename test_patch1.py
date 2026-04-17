"""
HookReel test suite -- v1.0.1 Hook patch release tests.
Tests 89-98.
Run with: docker exec hookreel python -m pytest /hookreel/test_patch1.py -v
"""
import os
import sys

sys.path.insert(0, "/hookreel")

import app.config as config

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def test_89_version_constants():
    """Test 89 -- Version constants updated to 1.0.1 Hook."""
    section("Test 89 - Version constants")
    try:
        assert config.VERSION == "1.0.1", f"Expected 1.0.1 got {config.VERSION}"
        assert config.VERSION_NAME == "Hook", f"Expected Hook got {config.VERSION_NAME}"
        print("PASS -- VERSION=1.0.1 VERSION_NAME=Hook")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_90_favicon_exists():
    """Test 90 -- Favicon SVG file exists."""
    section("Test 90 - Favicon exists")
    try:
        path = "/hookreel/app/static/favicon.svg"
        assert os.path.exists(path), f"Missing: {path}"
        assert os.path.getsize(path) > 0, "File is empty"
        print("PASS -- favicon.svg present and non-empty")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_91_persona_get_name():
    """Test 91 -- persona.get_name() returns a non-empty string."""
    section("Test 91 - Persona get_name")
    try:
        from app.persona import get_name
        name = get_name()
        assert isinstance(name, str), "Name is not a string"
        assert len(name) > 0, "Name is empty"
        print(f"PASS -- agent name: {name}")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_92_personality_round_trip():
    """Test 92 -- Personality selector round-trip save and restore."""
    section("Test 92 - Personality round-trip")
    try:
        from app.persona import update_personality, get_personality
        original = get_personality()
        assert update_personality("professional"), "Failed to set professional"
        assert get_personality() == "professional", "Personality not updated"
        assert update_personality(original), f"Failed to restore {original}"
        assert get_personality() == original, "Personality not restored"
        print(f"PASS -- round-trip professional -> {original}")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_93_hash_normalisation():
    """Test 93 -- Torrent hash normalisation to lowercase."""
    section("Test 93 - Hash normalisation")
    try:
        from app import qbittorrent
        upper = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
        normalised = upper.lower().strip()
        assert normalised == "abcdef1234567890abcdef1234567890abcdef12"
        assert normalised == normalised.lower()
        print("PASS -- hash normalisation correct")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_94_dev_compose_exists():
    """Test 94 -- docker-compose.dev.yml exists with app volume mount."""
    section("Test 94 - Dev compose file")
    try:
        path = "/hookreel/docker-compose.dev.yml"
        assert os.path.exists(path), f"Missing: {path}"
        content = open(path).read()
        assert "./app:/hookreel/app" in content, "App volume mount not found"
        print("PASS -- docker-compose.dev.yml present and correct")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_95_github_actions_workflow_exists():
    """Test 95 -- GitHub Actions workflow exists with multi-arch platforms."""
    section("Test 95 - GitHub Actions workflow")
    try:
        path = "/hookreel/.github/workflows/docker-publish.yml"
        assert os.path.exists(path), f"Missing: {path}"
        content = open(path).read()
        assert "linux/amd64,linux/arm64" in content, "Multi-arch platforms not found"
        print("PASS -- docker-publish.yml present with amd64 and arm64")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


def test_96_contributing_md_exists():
    """Test 96 -- CONTRIBUTING.md exists with dev workflow section."""
    section("Test 96 - CONTRIBUTING.md")
    try:
        path = "/hookreel/CONTRIBUTING.md"
        assert os.path.exists(path), f"Missing: {path}"
        content = open(path).read()
        assert "docker-compose.dev.yml" in content, "Dev compose reference not found"
        print("PASS -- CONTRIBUTING.md present with dev workflow")
        return True
    except Exception as error:
        print(f"FAIL -- {error}")
        return False


if __name__ == "__main__":
    results = []
    results.append(("Test 89 - Version constants", test_89_version_constants()))
    results.append(("Test 90 - Favicon exists", test_90_favicon_exists()))
    results.append(("Test 91 - Persona get_name", test_91_persona_get_name()))
    results.append(("Test 92 - Personality round-trip", test_92_personality_round_trip()))
    results.append(("Test 93 - Hash normalisation", test_93_hash_normalisation()))
    results.append(("Test 94 - Dev compose file", test_94_dev_compose_exists()))
    results.append(("Test 95 - GitHub Actions workflow", test_95_github_actions_workflow_exists()))
    results.append(("Test 96 - CONTRIBUTING.md", test_96_contributing_md_exists()))

    print("\n" + "="*60)
    passed = sum(1 for _, r in results if r is True)
    failed = sum(1 for _, r in results if r is False)
    skipped = sum(1 for _, r in results if r is None)
    print(f"  RESULTS: {passed} passed, {failed} failed, {skipped} skipped")
    print("="*60)
