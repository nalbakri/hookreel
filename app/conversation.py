"""
app/conversation.py

Conversation session manager.
Wraps HookReelAgent with per-user session management,
automatic history healing, error recovery, and session expiry.
"""

import time
import app.config as config
from app.agent import HookReelAgent
from app.logger import get_logger

logger = get_logger(__name__)


class ConversationManager:
    """
    Manages per-user conversation sessions.

    Each user_id gets its own HookReelAgent instance so Telegram
    users and the web UI have independent conversation histories.
    Sessions inactive for SESSION_EXPIRY_HOURS are cleaned up automatically.
    """

    def __init__(self):
        """Create the session store and record start time."""
        logger.info("[HookReel] ConversationManager initialising.")
        self._sessions = {}
        self.session_start = time.time()
        logger.info("[HookReel] ConversationManager ready.")

    def _get_agent(self, user_id: str) -> HookReelAgent:
        """
        Return the HookReelAgent for this user_id, creating one if needed.
        Updates last_active timestamp on every access.

        Parameters:
            user_id: A string identifying the user — e.g. their Telegram
                     numeric ID, or 'webui' for web UI sessions.

        Returns:
            The HookReelAgent instance for this user.
        """
        if user_id not in self._sessions:
            logger.info("[HookReel] Creating new agent session for user_id=%s", user_id)
            self._sessions[user_id] = {
                "agent": HookReelAgent(),
                "last_active": time.time(),
            }
        else:
            self._sessions[user_id]["last_active"] = time.time()
        return self._sessions[user_id]["agent"]

    def handle_message(self, user_id: str, message: str) -> str:
        """
        Pass an incoming message to the user's agent and return the response.

        If the agent raises a 400 error due to broken conversation history
        (e.g. interrupted tool calls), automatically resets the conversation
        and retries the message once with a fresh history so the user never
        sees a raw error.

        Parameters:
            user_id: The user's identifier string.
            message: The user's message text.

        Returns:
            The agent's response string.
        """
        logger.info(
            "[HookReel] handle_message: user_id=%s length=%d",
            user_id,
            len(message),
        )
        agent = self._get_agent(user_id)

        try:
            response = agent.chat(message)
            return response

        except Exception as error:
            error_str = str(error)
            logger.error(
                "[HookReel] Agent error for user_id=%s: %s", user_id, error_str
            )

            # Auto-recover from broken tool call history
            if "insufficient tool messages" in error_str or \
               "tool_calls" in error_str and "400" in error_str:
                logger.warning(
                    "[HookReel] Broken history detected for user_id=%s — "
                    "resetting and retrying", user_id
                )
                agent.reset()
                try:
                    response = agent.chat(message)
                    logger.info(
                        "[HookReel] Retry successful for user_id=%s", user_id
                    )
                    return response
                except Exception as retry_error:
                    logger.error(
                        "[HookReel] Retry also failed for user_id=%s: %s",
                        user_id, retry_error
                    )
                    return (
                        "I had to reset our conversation due to a technical hiccup. "
                        "Your message has been resent but something went wrong again. "
                        "Please try once more."
                    )

            return (
                "Blimey, something went wrong in the engine room. "
                "Try again in a moment."
            )

    def reset_conversation(self, user_id: str):
        """
        Reset the conversation history for a specific user.

        Parameters:
            user_id: The user's identifier string.
        """
        logger.info("[HookReel] Resetting conversation for user_id=%s", user_id)
        if user_id in self._sessions:
            self._sessions[user_id]["agent"].reset()
        else:
            logger.debug(
                "[HookReel] No session found for user_id=%s — nothing to reset",
                user_id
            )

    def cleanup_expired_sessions(self):
        """
        Remove sessions that have been inactive for SESSION_EXPIRY_HOURS hours.
        Called from the main polling loop once per hour.
        """
        expiry_seconds = config.SESSION_EXPIRY_HOURS * 3600
        now = time.time()
        expired = [
            uid for uid, data in self._sessions.items()
            if now - data["last_active"] > expiry_seconds
        ]
        for uid in expired:
            del self._sessions[uid]
        if expired:
            logger.info(
                "[HookReel] Session cleanup: removed %d expired session(s)", len(expired)
            )
