"""
app/telegram_bot.py

Telegram bot interface for HookReel.
Connects the AI conversation layer to Telegram using
python-telegram-bot v21. All handlers are async.

Pairing system: users can be approved via a one-time code
generated on the web UI settings page. The static
TELEGRAM_ALLOWED_USER_ID in .env acts as a bootstrap
fallback and is always checked first.
"""

import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import app.config as config
from app.logger import get_logger
from app.audit import log_audit
from app.tools import execute_tool
import app.database as database
import app.streaming as streaming

logger = get_logger(__name__)

WELCOME_MESSAGE = """
Ahoy! Welcome aboard HookReel!

I be yer AI-powered media quartermaster. Tell me what ye want to watch and I'll hunt it down across the seven seas.

What I can do:
- Find and download movies for ye
- Check the status of yer library
- Keep ye updated on downloads in progress
- Stream movies directly to Telegram

Try saying:
- Find me Inception
- Download The Dark Knight
- What's in my library?
- Stream Interstellar

Type /help to see all commands. Now, what'll it be?
"""

HELP_MESSAGE = """
HookReel Commands

/start - Welcome message
/help - Show this message
/status - Show library and active downloads
/reset - Start a fresh conversation
/pair <code> - Pair this Telegram account using a code from the web UI
/setupstream <url> <key> - Save your Telegram RTMP stream credentials
/stopstream - Stop the current stream

Example phrases:
- Find Interstellar
- I want to watch Dune
- What movies do I have?
- Is my download done yet?
- Stream Interstellar to me

Just talk to me like a crew member and I'll handle the rest, Captain!
"""

SETUP_STREAM_INSTRUCTIONS = """
To stream movies to Telegram, set up your cinema channel once - takes about 5 minutes.

--- Step 1: Create the group ---
1. Tap the menu (top left) -> New Group
2. Skip adding members, tap the blue arrow
3. Name it (e.g. "HookReel Cinema") -> tap the blue tick

--- Step 2: Add the bot as admin ---
4. In the group, tap the group name at the top -> Add Members -> search for this bot -> add it
5. Tap the bot's name in the member list -> tap "Add to Group or Channel"
6. Select your HookReel Cinema group
7. On the permissions screen, enable ONLY these four:
   [ON]  Manage Group
   [ON]  Change Group Info
   [ON]  Pin Messages
   [ON]  Manage Live Streams  <- without this, streaming will not work
   [OFF] everything else
8. Tap the tick -> confirm "Add as Admin"

--- Step 3: Get your stream credentials (one time only) ---
9. Go back to the HookReel Cinema group
10. Tap the Video Chat button -> "You can also stream with another app"
11. Tap "another app" -> you will see the Streaming screen
12. Copy the Server URL (starts with rtmps://) and the Stream Key
13. Come back to this chat and send:
    /setupstream <Server URL> <Stream Key>

Example:
/setupstream rtmps://dc5-1.rtmp.t.me/s/ 3853647072:ABCD-EFGH-IJKL

--- Every time you want to watch ---
Before asking HookReel to stream, do this first:
1. Go to HookReel Cinema group
2. Tap Video Chat -> "stream with another app" -> "another app"
3. Tap "Start Streaming" on that screen
4. Come back here and say "stream <movie title>"

You are all set! Just say "stream <movie title>" after starting the stream receiver.
"""

UNAUTHORISED_MESSAGE = (
    "Arrr! You're not on the crew manifest, landlubber.\n\n"
    "Ask the captain to generate a pairing code at the HookReel web UI, "
    "then send it here with: /pair 123456"
)

ERROR_MESSAGE = (
    "Arrr, something went wrong in the engine room. "
    "Try again or use /reset"
)

MAX_MESSAGE_LENGTH = 4096


class HookReelBot:
    """
    Telegram bot interface for HookReel.

    Wraps the ConversationManager and exposes it via Telegram.
    All message handling is async as required by
    python-telegram-bot v21.

    Authorization uses a two-tier system:
    1. Static whitelist from TELEGRAM_ALLOWED_USER_ID in .env
    2. Database-backed approved list populated via pairing codes
    """

    def __init__(self, conversation_manager):
        self.conversation_manager = conversation_manager
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN)
        self.static_allowed_ids = self._load_static_allowed_ids()

        self.application = (
            ApplicationBuilder()
            .token(self.token)
            .build()
        )

        self._register_handlers()
        logger.info("[HookReel] Telegram bot initialised")

    def _load_static_allowed_ids(self) -> list:
        raw = config.TELEGRAM_ALLOWED_USER_ID
        ids = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                try:
                    ids.append(int(part))
                except ValueError:
                    logger.warning(
                        "[HookReel] Invalid user ID in config: %s", part
                    )
        logger.info(
            "[HookReel] Telegram static whitelist loaded: %d user(s)", len(ids)
        )
        return ids

    def is_allowed(self, user_id: int) -> bool:
        if user_id in self.static_allowed_ids:
            return True
        if database.is_approved_telegram_id(user_id):
            return True
        logger.warning(
            "[HookReel] Unauthorised access attempt from user_id=%d", user_id
        )
        log_audit("unauthorised_access_attempt", {"user_id": user_id}, str(user_id))
        return False

    def _register_handlers(self):
        self.application.add_handler(
            CommandHandler("start", self.handle_command_start)
        )
        self.application.add_handler(
            CommandHandler("help", self.handle_command_help)
        )
        self.application.add_handler(
            CommandHandler("status", self.handle_command_status)
        )
        self.application.add_handler(
            CommandHandler("reset", self.handle_command_reset)
        )
        self.application.add_handler(
            CommandHandler("pair", self.handle_command_pair)
        )
        self.application.add_handler(
            CommandHandler("setupstream", self.handle_command_setupstream)
        )
        self.application.add_handler(
            CommandHandler("stopstream", self.handle_command_stopstream)
        )
        self.application.add_handler(
            CommandHandler("scan", self.handle_command_scan)
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_callback_query)
        )
        self.application.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self.handle_message,
            )
        )
        self.application.add_error_handler(self.handle_error)
        logger.info("[HookReel] Telegram handlers registered")

    async def _send_long_message(self, update: Update, text: str):
        if len(text) <= MAX_MESSAGE_LENGTH:
            await update.message.reply_text(text)
            return

        chunks = []
        while len(text) > MAX_MESSAGE_LENGTH:
            split_at = text.rfind("\n", 0, MAX_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = MAX_MESSAGE_LENGTH
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        if text:
            chunks.append(text)

        for chunk in chunks:
            await update.message.reply_text(chunk)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        username = update.effective_user.username or "unknown"
        message_text = update.message.text

        logger.info(
            "[HookReel] Message from user_id=%d username=%s: %s",
            user_id, username, message_text[:80]
        )

        if not self.is_allowed(user_id):
            await update.message.reply_text(UNAUTHORISED_MESSAGE)
            return

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        try:
            response = self.conversation_manager.handle_message(
                user_id, message_text
            )
            logger.info(
                "[HookReel] Response to user_id=%d: %s",
                user_id, response[:80]
            )
            await self._send_long_message(update, response)
        except Exception as error:
            logger.error(
                "[HookReel] Error handling message from user_id=%d: %s",
                user_id, error,
                exc_info=True,
            )
            await update.message.reply_text(ERROR_MESSAGE)

    async def handle_command_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info("[HookReel] /start from user_id=%d", user_id)
        await update.message.reply_text(WELCOME_MESSAGE)

    async def handle_command_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info("[HookReel] /help from user_id=%d", user_id)
        await update.message.reply_text(HELP_MESSAGE)

    async def handle_command_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info("[HookReel] /status from user_id=%d", user_id)

        if not self.is_allowed(user_id):
            await update.message.reply_text(UNAUTHORISED_MESSAGE)
            return

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        try:
            result = execute_tool("list_library", {})
            await self._send_long_message(update, result)
        except Exception as error:
            logger.error(
                "[HookReel] Error in /status for user_id=%d: %s",
                user_id, error,
                exc_info=True,
            )
            await update.message.reply_text(ERROR_MESSAGE)

    async def handle_command_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info("[HookReel] /scan from user_id=%d", user_id)
        if not self.is_allowed(user_id):
            await update.message.reply_text(UNAUTHORISED_MESSAGE)
            return
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )
        await update.message.reply_text(
            "Scanning your media folders for new content. "
            "This may take a minute, Captain..."
        )
        try:
            result = execute_tool("scan_library", {})
            await self._send_long_message(update, result)
        except Exception as error:
            logger.error(
                "[HookReel] Error in /scan for user_id=%d: %s",
                user_id, error,
                exc_info=True,
            )
            await update.message.reply_text(ERROR_MESSAGE)

    async def handle_command_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info("[HookReel] /reset from user_id=%d", user_id)

        if not self.is_allowed(user_id):
            await update.message.reply_text(UNAUTHORISED_MESSAGE)
            return

        try:
            self.conversation_manager.reset_conversation(user_id)
            await update.message.reply_text(
                "Aye! The logbook has been cleared. "
                "Fresh seas ahead, Captain!"
            )
        except Exception as error:
            logger.error(
                "[HookReel] Error in /reset for user_id=%d: %s",
                user_id, error,
                exc_info=True,
            )
            await update.message.reply_text(ERROR_MESSAGE)

    async def handle_command_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info("[HookReel] /pair from user_id=%d", user_id)

        if self.is_allowed(user_id):
            await update.message.reply_text(
                "Ye're already on the crew manifest, Captain! "
                "No need to pair again."
            )
            return

        if not context.args or len(context.args) != 1:
            await update.message.reply_text(
                "Usage: /pair <code>\n\n"
                "Generate a pairing code at the HookReel web UI "
                "settings page, then send it here.\n\n"
                "Example: /pair 123456"
            )
            return

        code = context.args[0].strip()

        if not code.isdigit() or len(code) != 6:
            await update.message.reply_text(
                "That doesn't look like a valid code, matey. "
                "The code should be 6 digits.\n\n"
                "Example: /pair 123456"
            )
            return

        try:
            success = database.verify_and_consume_pairing_code(code, user_id)

            if success:
                logger.info(
                    "[HookReel] Pairing successful for user_id=%d", user_id
                )
                await update.message.reply_text(
                    "Ahoy! Ye've been added to the crew manifest!\n\n"
                    "Welcome aboard, Captain. "
                    "Type /help to see what I can do for ye."
                )
            else:
                logger.warning(
                    "[HookReel] Pairing failed for user_id=%d code=%s",
                    user_id, code
                )
                await update.message.reply_text(
                    "That code is invalid or has expired, matey.\n\n"
                    "Ask the captain to generate a fresh code at the "
                    "HookReel web UI settings page."
                )

        except Exception as error:
            logger.error(
                "[HookReel] Error in /pair for user_id=%d: %s",
                user_id, error,
                exc_info=True,
            )
            await update.message.reply_text(ERROR_MESSAGE)

    async def handle_command_setupstream(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /setupstream <url> <key>.

        Saves the RTMP URL and stream key to the .env file so
        HookReel can stream to the user's Telegram group.
        If called with no arguments, sends setup instructions.
        """
        user_id = update.effective_user.id
        logger.info("[HookReel] /setupstream from user_id=%d", user_id)

        if not self.is_allowed(user_id):
            await update.message.reply_text(UNAUTHORISED_MESSAGE)
            return

        if not context.args or len(context.args) < 2:
            await update.message.reply_text(SETUP_STREAM_INSTRUCTIONS)
            return

        rtmp_url = context.args[0].strip()
        rtmp_key = context.args[1].strip()

        # Basic validation — URL should start with rtmp
        if not rtmp_url.startswith("rtmp"):
            await update.message.reply_text(
                "That doesn't look like a valid RTMP URL, matey.\n"
                "It should start with rtmps:// or rtmp://\n\n"
                "Send /setupstream with no arguments to see instructions."
            )
            return

        try:
            _save_rtmp_credentials(rtmp_url, rtmp_key)
            logger.info(
                "[HookReel] RTMP credentials saved for user_id=%d", user_id
            )
            await update.message.reply_text(
                "Stream credentials saved! \n\n"
                "Yer cinema channel is ready, Captain.\n"
                "Just say 'stream <movie title>' and I'll fire up the projector!"
            )
        except Exception as error:
            logger.error(
                "[HookReel] Error saving RTMP credentials: %s", error,
                exc_info=True,
            )
            await update.message.reply_text(
                "Failed to save stream credentials. "
                "Check the logs for details."
            )

    async def handle_command_stopstream(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /stopstream — stop the current RTMP stream.
        """
        user_id = update.effective_user.id
        logger.info("[HookReel] /stopstream from user_id=%d", user_id)

        if not self.is_allowed(user_id):
            await update.message.reply_text(UNAUTHORISED_MESSAGE)
            return

        result = streaming.stop_stream()
        if result["success"]:
            await update.message.reply_text(
                f"Stream stopped. The cinema is dark, Captain."
            )
        else:
            await update.message.reply_text(result["message"])

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle inline keyboard button presses.

        Used for the "Watch now / Maybe later" prompt sent
        after a download completes.
        """
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        data = query.data

        if not self.is_allowed(user_id):
            await query.edit_message_text(UNAUTHORISED_MESSAGE)
            return

        if data.startswith("stream:"):
            file_path = data[len("stream:"):]
            title = query.message.text.split("\n")[0].replace("Download complete: ", "").strip()
            await query.edit_message_text(f"Starting stream: {title}...")
            await _do_stream(query, file_path, title)

        elif data == "stream_later":
            await query.edit_message_text(
                query.message.text + "\n\nSay 'stream <title>' whenever ye're ready, Captain!"
            )

    async def notify_download_complete(self, title: str, file_path: str):
        """
        Send a 'download complete' notification to all allowed users
        with a Watch now / Maybe later prompt.

        Called by the post-processor after a file is moved
        and verified. Runs in the bot's async context.
        """
        if not config.TELEGRAM_RTMP_URL or not config.TELEGRAM_RTMP_KEY:
            # RTMP not configured — send plain notification only.
            text = (
                f"Download complete: {title}\n\n"
                f"Yer movie is ready in the library, Captain!"
            )
            await self._broadcast_to_allowed_users(text)
            return

        text = (
            f"Download complete: {title}\n\n"
            f"Want to watch it now?"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Watch now", callback_data=f"stream:{file_path}"),
                InlineKeyboardButton("Maybe later", callback_data="stream_later"),
            ]
        ])
        await self._broadcast_to_allowed_users(text, reply_markup=keyboard)

    async def _broadcast_to_allowed_users(self, text: str, reply_markup=None):
        """Send a message to all users in the static whitelist."""
        for user_id in self.static_allowed_ids:
            try:
                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup,
                )
            except Exception as e:
                logger.error(
                    "[HookReel] Failed to notify user_id=%d: %s", user_id, e
                )

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(
            "[HookReel] Telegram error: %s",
            context.error,
            exc_info=context.error,
        )
        if isinstance(update, Update) and update.message:
            await update.message.reply_text(ERROR_MESSAGE)

    def run(self):
        """
        Start the Telegram bot with run_polling().

        Blocks until the bot is stopped. Intended to be run
        in a daemon thread alongside the polling loop in main.py.
        Creates its own event loop since it runs in a thread.
        Do not modify this threading pattern.
        """
        import asyncio
        logger.info(
            "[HookReel] Starting Telegram bot — "
            "static whitelist: %d user(s)",
            len(self.static_allowed_ids)
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.application.run_polling(stop_signals=None)


# -------------------------------------------------------
# Module-level helpers
# -------------------------------------------------------

def _save_rtmp_credentials(rtmp_url: str, rtmp_key: str):
    """
    Write RTMP_URL and RTMP_KEY into the .env file.

    Reads the existing file, replaces or appends the two keys,
    and writes it back. This means credential changes survive
    container restarts without a rebuild.
    """
    env_path = "/config/.env"

    # Normalise the URL - strip trailing slashes so the path
    # is always built cleanly in streaming.py
    rtmp_url = rtmp_url.rstrip("/")

    with open(env_path, "r") as f:
        lines = f.readlines()

    new_lines = []
    url_written = False
    key_written = False

    for line in lines:
        if line.startswith("TELEGRAM_RTMP_URL="):
            new_lines.append(f"TELEGRAM_RTMP_URL={rtmp_url}\n")
            url_written = True
        elif line.startswith("TELEGRAM_RTMP_KEY="):
            new_lines.append(f"TELEGRAM_RTMP_KEY={rtmp_key}\n")
            key_written = True
        else:
            new_lines.append(line)

    if not url_written:
        new_lines.append(f"TELEGRAM_RTMP_URL={rtmp_url}\n")
    if not key_written:
        new_lines.append(f"TELEGRAM_RTMP_KEY={rtmp_key}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    # Apply immediately to the running process without restart.
    import os
    os.environ["TELEGRAM_RTMP_URL"] = rtmp_url
    os.environ["TELEGRAM_RTMP_KEY"] = rtmp_key
    config.TELEGRAM_RTMP_URL = rtmp_url
    config.TELEGRAM_RTMP_KEY = rtmp_key


async def _do_stream(query, file_path: str, title: str):
    """
    Start a stream from a callback query context.
    Sends follow-up messages based on result.
    """
    rtmp_url = config.TELEGRAM_RTMP_URL
    rtmp_key = config.TELEGRAM_RTMP_KEY

    if not rtmp_url or not rtmp_key:
        await query.message.reply_text(SETUP_STREAM_INSTRUCTIONS)
        return

    result = streaming.start_stream(
        file_path=file_path,
        rtmp_url=rtmp_url,
        rtmp_key=rtmp_key,
        title=title,
    )

    if result["success"]:
        await query.message.reply_text(
            f"Streaming {title} to yer cinema channel now!\n\n"
            f"Open yer Telegram group to watch.\n"
            f"Send /stopstream to stop."
        )
    else:
        await query.message.reply_text(
            f"Could not start stream: {result['message']}"
        )
