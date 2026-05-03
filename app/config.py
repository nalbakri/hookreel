"""
HookReel configuration loader.
Reads all settings from /hookreel/config/.env and validates required keys.
"""
import os
from dotenv import load_dotenv
load_dotenv("/hookreel/config/.env", override=False)
def get(key: str, default=None):
    """Return the value of an environment variable, or default if not set."""
    return os.environ.get(key, default)
def require(key: str) -> str:
    """Return the value of a required environment variable. Raises if missing."""
    value = os.environ.get(key)
    if value is None:
        raise EnvironmentError(f"[HookReel] Required config key missing: {key}")
    return value
# Pre-loaded config values for convenience
QBITTORRENT_HOST = get("QBITTORRENT_HOST", "gluetun")
QBITTORRENT_PORT = get("QBITTORRENT_PORT", "8080")
QBITTORRENT_USER = get("QBITTORRENT_USER", "admin")
QBITTORRENT_PASS = get("QBITTORRENT_PASS", "adminadmin")
PROWLARR_HOST = get("PROWLARR_HOST", "prowlarr")
PROWLARR_PORT = get("PROWLARR_PORT", "9696")
PROWLARR_API_KEY = get("PROWLARR_API_KEY", "")
PROWLARR_URL = "http://{}:{}".format(get("PROWLARR_HOST", "prowlarr"), get("PROWLARR_PORT", "9696"))
JELLYFIN_HOST = get("JELLYFIN_HOST", "192.168.1.21")
JELLYFIN_PORT = get("JELLYFIN_PORT", "8096")
JELLYFIN_API_KEY = get("JELLYFIN_API_KEY", "changeme")
METADATA_PROVIDER = get("METADATA_PROVIDER", "tmdb")
METADATA_API_KEY = get("METADATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_ID = get("TELEGRAM_ALLOWED_USER_ID", "")
AI_MODEL_ENDPOINT = get("AI_MODEL_ENDPOINT", "")
AI_MODEL_NAME = get("AI_MODEL_NAME", "")
AI_API_KEY = get("AI_API_KEY", "")
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "1000"))
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.7"))
AI_MAX_TOOL_ROUNDS = int(os.getenv("AI_MAX_TOOL_ROUNDS", "10"))
MEDIA_BASE_PATH = get("MEDIA_BASE_PATH", "/data")
MOVIES_PATH = get("MOVIES_PATH", "/data/Movies")
TV_PATH = get("TV_PATH", "/data/TV")
AUTO_DOWNLOAD_NEW_EPISODES = get("AUTO_DOWNLOAD_NEW_EPISODES", "false")
DOWNLOADS_PATH = get("DOWNLOADS_PATH", "/data/Downloads")
QUARANTINE_PATH = get("QUARANTINE_PATH", "/quarantine")
LOGS_PATH = get("LOGS_PATH", "/logs")
DB_PATH = get("DB_PATH", "/db/hookreel.db")
CLAMAV_HOST = get("CLAMAV_HOST", "hookreel-clamav")
CLAMAV_PORT = int(get("CLAMAV_PORT", "3310"))
LOG_LEVEL = get("LOG_LEVEL", "INFO")
TZ = get("TZ", "UTC")
WEBUI_PASSWORD = get("WEBUI_PASSWORD", "changeme")
SECRET_KEY = get("SECRET_KEY", "changeme")
# --- Watch Mode (Phase 6.5) ---
JELLYFIN_ENABLED = get("JELLYFIN_ENABLED", "true").lower() == "true"
HLS_STREAM_DIR = get("HLS_STREAM_DIR", "/tmp/hls")
HLS_SEGMENT_DURATION = int(get("HLS_SEGMENT_DURATION", "10"))
STREAM_PORT = int(get("STREAM_PORT", "8765"))
DELETE_ENABLED = get("DELETE_ENABLED", "false").lower() == "true"
# --- RTMP Streaming (Phase 7a) ---
TELEGRAM_RTMP_URL = get("TELEGRAM_RTMP_URL", "")
TELEGRAM_RTMP_KEY = get("TELEGRAM_RTMP_KEY", "")
RTMP_VIDEO_BITRATE = get("RTMP_VIDEO_BITRATE", "2500k")
RTMP_SCALE = get("RTMP_SCALE", "1280:-2")
# --- Security (Phase 7b) ---
SESSION_EXPIRY_HOURS    = int(get("SESSION_EXPIRY_HOURS", "24"))
RATE_LIMIT_ENABLED      = get("RATE_LIMIT_ENABLED", "true").lower() == "true"
# --- Phase 8 ---
VERSION = "1.1.0"
VERSION_NAME = "Alf"
# Extra media sources (up to 5, set during setup wizard)
EXTRA_MEDIA_1 = get("EXTRA_MEDIA_1", "")
EXTRA_MEDIA_1_LABEL = get("EXTRA_MEDIA_1_LABEL", "Extra Source 1")
EXTRA_MEDIA_2 = get("EXTRA_MEDIA_2", "")
EXTRA_MEDIA_2_LABEL = get("EXTRA_MEDIA_2_LABEL", "Extra Source 2")
EXTRA_MEDIA_3 = get("EXTRA_MEDIA_3", "")
EXTRA_MEDIA_3_LABEL = get("EXTRA_MEDIA_3_LABEL", "Extra Source 3")
EXTRA_MEDIA_4 = get("EXTRA_MEDIA_4", "")
EXTRA_MEDIA_4_LABEL = get("EXTRA_MEDIA_4_LABEL", "Extra Source 4")
EXTRA_MEDIA_5 = get("EXTRA_MEDIA_5", "")
EXTRA_MEDIA_5_LABEL = get("EXTRA_MEDIA_5_LABEL", "Extra Source 5")
# Telegram Cinema stream group link
TELEGRAM_CINEMA_LINK = get("TELEGRAM_CINEMA_LINK", "")
# --- v1.1 Alf ---
JELLYFIN_WEBHOOK_SECRET = get("JELLYFIN_WEBHOOK_SECRET", "")
PROACTIVE_RATING_PROMPT = get("PROACTIVE_RATING_PROMPT", "false").lower() == "true"
JELLYFIN_URL = "http://{}:{}".format(get("JELLYFIN_HOST", "192.168.1.21"), get("JELLYFIN_PORT", "8096"))
