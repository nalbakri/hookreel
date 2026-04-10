# HookReel Configuration Reference

All configuration is stored in config/.env.
Changes take effect after clicking Restart Agent in the web UI,
or after restarting the container for service-level changes.

## qBittorrent

| Variable | Default | Description |
|---|---|---|
| QBITTORRENT_HOST | gluetun | qBittorrent hostname (gluetun if using VPN) |
| QBITTORRENT_PORT | 8080 | qBittorrent web UI port |
| QBITTORRENT_USER | admin | qBittorrent username |
| QBITTORRENT_PASS | adminadmin | qBittorrent password |

## Prowlarr

| Variable | Default | Description |
|---|---|---|
| PROWLARR_HOST | prowlarr | Prowlarr hostname |
| PROWLARR_PORT | 9696 | Prowlarr port |
| PROWLARR_API_KEY | | Prowlarr API key (required) |

## Jellyfin

| Variable | Default | Description |
|---|---|---|
| JELLYFIN_HOST | 192.168.1.21 | Jellyfin hostname or IP |
| JELLYFIN_PORT | 8096 | Jellyfin port |
| JELLYFIN_API_KEY | | Jellyfin API key |
| JELLYFIN_ENABLED | true | Enable Jellyfin integration |

## Metadata provider

| Variable | Default | Description |
|---|---|---|
| METADATA_PROVIDER | tmdb | Provider: tmdb, omdb, or tvmaze |
| METADATA_API_KEY | | API key (not required for tvmaze) |

Note: METADATA_PROVIDER must be lowercase.

## AI model

| Variable | Default | Description |
|---|---|---|
| AI_MODEL_ENDPOINT | | OpenAI-compatible endpoint URL |
| AI_MODEL_NAME | | Model name (e.g. deepseek-chat) |
| AI_API_KEY | | API key for the model endpoint |
| AI_MAX_TOKENS | 1000 | Maximum tokens per response |
| AI_TEMPERATURE | 0.7 | Model temperature (0.0-1.0) |
| AI_MAX_TOOL_ROUNDS | 10 | Maximum tool call rounds per request |

## Telegram

| Variable | Default | Description |
|---|---|---|
| TELEGRAM_BOT_TOKEN | | Bot token from BotFather |
| TELEGRAM_ALLOWED_USER_ID | | Comma-separated allowed Telegram user IDs |

## RTMP Cinema

| Variable | Default | Description |
|---|---|---|
| TELEGRAM_RTMP_URL | | RTMP server URL from Telegram |
| TELEGRAM_RTMP_KEY | | Stream key from Telegram |
| TELEGRAM_CINEMA_LINK | | t.me link to your cinema group |
| RTMP_VIDEO_BITRATE | 2500k | Video bitrate for RTMP stream |
| RTMP_SCALE | 1280:-2 | Output resolution for RTMP stream |

## Media paths

| Variable | Default | Description |
|---|---|---|
| MOVIES_PATH | /data/Movies | Movies folder inside container |
| TV_PATH | /data/TV | TV folder inside container |
| DOWNLOADS_PATH | /data/Downloads | Downloads folder inside container |
| EXTRA_MEDIA_1 | | Extra media source path 1 |
| EXTRA_MEDIA_1_LABEL | | Label for extra source 1 |

Up to EXTRA_MEDIA_5 supported.

## Web UI

| Variable | Default | Description |
|---|---|---|
| WEBUI_PASSWORD | | Web UI login password |
| SECRET_KEY | | Session signing key (auto-generated) |

## Security

| Variable | Default | Description |
|---|---|---|
| SESSION_EXPIRY_HOURS | 24 | Session cookie lifetime in hours |
| RATE_LIMIT_ENABLED | true | Enable API rate limiting |
| DELETE_ENABLED | false | Allow agent to delete media files |

## System

| Variable | Default | Description |
|---|---|---|
| LOG_LEVEL | INFO | Logging level: DEBUG, INFO, WARNING, ERROR |
| TZ | UTC | Container timezone |
| CLAMAV_HOST | hookreel-clamav | ClamAV hostname |
| CLAMAV_PORT | 3310 | ClamAV port |
