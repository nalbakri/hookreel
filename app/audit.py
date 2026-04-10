"""
app/audit.py — HookReel audit logger.

Writes a separate audit trail for significant autonomous actions:
downloads, deletions, file moves, streaming, logins, pairing, and
settings changes. Audit entries are written to /logs/audit.log in
a structured plain-text format for easy review.

Valid actions:
    download_requested, download_started, download_complete,
    download_failed, file_deleted, file_moved, stream_started,
    stream_stopped, login_success, login_failed,
    pairing_code_generated, pairing_code_used, settings_changed,
    agent_restarted, unauthorised_access_attempt
"""

import os
from datetime import datetime
from app.logger import get_logger

logger = get_logger(__name__)

AUDIT_LOG_PATH = "/logs/audit.log"

def mask(value: str) -> str:
    """
    Mask a credential value for safe logging.
    Shows first 4 and last 4 characters only.
    Example: 'abcdefghijklmnop' -> 'abcd...mnop'
    """
    if not value or len(value) < 8:
        return "[REDACTED]"
    return value[:4] + "..." + value[-4:]

def log_audit(action: str, details: dict, user: str = "system") -> None:
    """
    Write a single audit entry to /logs/audit.log.

    Parameters:
        action:  Short action identifier string, e.g. 'download_requested'
        details: Dict of key/value pairs providing context for the action.
                 Values are converted to strings automatically.
                 Never include raw credentials or tokens in details.
        user:    Who triggered the action. Use 'system' for automated
                 actions, 'webui' for web UI actions, or the Telegram
                 user ID for bot actions.

    Format:
        [AUDIT] 2026-04-05T15:30:00 user=webui action=download_requested title=Interstellar year=2014
    """
    try:
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        parts = [f"[AUDIT] {timestamp}", f"user={user}", f"action={action}"]
        for key, value in details.items():
            # Never log values that look like credentials
            key_lower = key.lower()
            if any(s in key_lower for s in ("token", "key", "password", "secret")):
                parts.append(f"{key}=[REDACTED]")
            else:
                parts.append(f"{key}={value}")
        line = " ".join(parts) + "\n"
        with open(AUDIT_LOG_PATH, "a") as fh:
            fh.write(line)
    except Exception as exc:
        logger.error("[HookReel] Audit log write error: %s", exc)
