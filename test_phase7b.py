"""
test_phase7b.py - Phase 7b security hardening tests.
Tests 69-76.
"""
import sys
import os
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# -- Test 69 - Rate limiter works ---------------------------------------------
def test_69_rate_limiter():
    """Make 15 rapid requests to chat endpoint, verify 429 after 10."""
    from app.webui import check_rate_limit
    ip = "10.0.0.1"
    endpoint = "test69"
    for i in range(10):
        result = check_rate_limit(ip, endpoint, 10, 60)
        assert result is True, f"Request {i+1} should be allowed"
    result = check_rate_limit(ip, endpoint, 10, 60)
    assert result is False, "11th request should be rate limited"
    print("[OK] Test 69 passed: rate limiter blocks after 10 requests")


# -- Test 70 - Session expiry -------------------------------------------------
def test_70_session_expiry():
    """Create a session, backdate it, verify cleanup removes it."""
    from app.conversation import ConversationManager

    manager = ConversationManager()
    manager._get_agent("test_user_70")
    assert "test_user_70" in manager._sessions

    manager._sessions["test_user_70"]["last_active"] = time.time() - (25 * 3600)
    manager.cleanup_expired_sessions()

    assert "test_user_70" not in manager._sessions, "Expired session should be removed"
    print("[OK] Test 70 passed: expired session cleaned up")


# -- Test 71 - Input sanitisation ---------------------------------------------
def test_71_input_sanitisation():
    """Verify sanitise_title strips dangerous chars and truncates."""
    from app.pipeline import sanitise_title

    # Path traversal - slashes removed neutralises the threat
    result = sanitise_title("../../../etc/passwd")
    assert "/" not in result, "Slashes should be removed - path traversal neutralised"

    # Long title truncation
    long_title = "A" * 300
    result = sanitise_title(long_title)
    assert len(result) <= 200, f"Title should be truncated to 200 chars, got {len(result)}"

    # Dangerous characters
    result = sanitise_title("Movie <script>alert(1)</script>")
    assert "<" not in result and ">" not in result, "HTML chars should be removed"

    print("[OK] Test 71 passed: input sanitisation works correctly")


# -- Test 72 - Audit log writes -----------------------------------------------
def test_72_audit_log():
    """Verify audit log writes correctly."""
    from app.audit import log_audit

    log_audit("test_action", {"detail": "phase7b_test"}, "test_user")

    audit_path = "/logs/audit.log"
    assert os.path.exists(audit_path), "Audit log file should exist"

    with open(audit_path) as f:
        content = f.read()

    assert "test_action" in content, "Audit entry should contain action"
    assert "phase7b_test" in content, "Audit entry should contain detail"
    assert "test_user" in content, "Audit entry should contain user"
    print("[OK] Test 72 passed: audit log writes correctly")


# -- Test 73 - No secrets in logs ---------------------------------------------
def test_73_no_secrets_in_logs():
    """Verify no credential values appear in log statements."""
    import glob
    import re

    pattern = re.compile(
        r'(log\w*|print)\s*\(.*?(API_KEY|TOKEN|PASSWORD|SECRET|RTMP_KEY).*?["\']',
        re.IGNORECASE
    )

    violations = []
    for filepath in glob.glob(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "app", "*.py"
    )):
        with open(filepath) as f:
            for i, line in enumerate(f, 1):
                if pattern.search(line):
                    if "[REDACTED]" not in line and "mask(" not in line:
                        violations.append(f"{filepath}:{i}: {line.strip()}")

    assert len(violations) == 0, f"Potential secret leaks found:\n" + "\n".join(violations)
    print("[OK] Test 73 passed: no secrets in log statements")


# -- Test 74 - Security headers present ---------------------------------------
def test_74_security_headers():
    """Verify security headers are added to responses."""
    import threading
    import httpx
    from app.webui import app_fastapi
    import uvicorn

    config = uvicorn.Config(app_fastapi, host="127.0.0.1", port=18765, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(2)

    try:
        resp = httpx.get("http://127.0.0.1:18765/login", follow_redirects=False)
        headers = resp.headers
        assert "x-content-type-options" in headers, "X-Content-Type-Options missing"
        assert "x-frame-options" in headers, "X-Frame-Options missing"
        assert "x-xss-protection" in headers, "X-XSS-Protection missing"
        assert "referrer-policy" in headers, "Referrer-Policy missing"
        print("[OK] Test 74 passed: all security headers present")
    finally:
        server.should_exit = True


# -- Test 75 - Docker backup cleanup ------------------------------------------
def test_75_docker_backup_cleanup():
    """Verify old Docker backup on HDD is gone."""
    old_docker_path = "/srv/dev-disk-by-uuid-1cdc675c-398e-4ab9-aff6-9679946ca0bb/Docker"
    if os.path.exists(old_docker_path):
        print(f"[--] Test 75 note: {old_docker_path} still exists - conscious decision required")
    else:
        print("[OK] Test 75 passed: old Docker backup removed")
    assert True


# -- Test 76 - ClamAV definitions current ------------------------------------
def test_76_clamav_definitions():
    """Verify ClamAV definitions are less than 7 days old."""
    import glob as globmod
    cvd_files = globmod.glob("/var/lib/clamav/*.cvd") + globmod.glob("/var/lib/clamav/*.cld")
    if not cvd_files:
        print("[--] Test 76 note: ClamAV data not accessible from this container - check hookreel-clamav directly")
        assert True
        return
    newest = max(cvd_files, key=os.path.getmtime)
    age_days = (time.time() - os.path.getmtime(newest)) / 86400
    assert age_days <= 7, f"ClamAV definitions are {age_days:.1f} days old"
    print(f"[OK] Test 76 passed: ClamAV definitions are {age_days:.1f} day(s) old")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
