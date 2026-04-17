# HookReel

> Replace your entire *arr stack with one AI-powered media agent.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0%20Hook-orange.svg)](CHANGELOG.md)

HookReel is a self-hosted, AI-powered media automation agent. Instead of
managing Radarr, Sonarr, and Jellyseerr separately, you just ask for what
you want to watch -- in plain language -- and HookReel handles everything.

## What it does

- You say: "Find me Dune Part Two in 1080p"
- HookReel searches your indexers, picks the best release, downloads it,
  scans it for malware, renames it for Jellyfin, and notifies you when
  it is ready to watch
- You can then say "Stream it to Telegram" and watch it inline

## Features

- Natural language requests via Telegram bot and web UI
- Replaces Radarr, Sonarr, and Jellyseerr with a single agent
- AI-powered release selection (pluggable model -- DeepSeek, Ollama, any
  OpenAI-compatible endpoint)
- ClamAV malware scanning on every download
- Jellyfin integration with deep links and library sync
- RTMP streaming to a private Telegram group (watch inline)
- TV show support with automatic episode tracking
- Pluggable metadata provider (TMDB, OMDb, TVmaze)
- Library import tool for existing media collections
- Extra media sources (portable drives, NAS, secondary drives)
- Mobile-first web UI with PWA support
- First-run setup wizard -- one command to configure everything
- Rate limiting, session expiry, audit log, security headers

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A server running Linux (tested on Debian/Ubuntu/OMV)
- The arr stack already running (Prowlarr, qBittorrent via Gluetun)
  OR use HookReel standalone with the setup wizard

### Install

    git clone https://github.com/nalbakri/hookreel.git
    cd hookreel
    python3 setup.py
    docker compose up -d

Open the web UI at http://[your-server-ip]:8765

### Supported architectures
Supports linux/amd64 and linux/arm64.
ARM64 builds are provided for Raspberry Pi 4/5 and other ARM64 SBCs.
Not yet tested on ARM hardware -- community feedback welcome.

### First run checklist

1. Wait 2-3 minutes for ClamAV to load virus definitions
2. Open web UI and log in with the password you set during setup
3. If using Jellyfin, complete setup at http://[your-server-ip]:8096
   then add your Jellyfin API key in HookReel Settings
4. Send /start to your Telegram bot
5. Ask for a movie

## Architecture

HookReel replaces the request and automation layer of the arr stack:

    User (Telegram / Web UI)
            |
        HookReel Agent (AI)
            |
       +----+----+
       |         |
    Prowlarr  qBittorrent (via Gluetun VPN)
                  |
             ClamAV scan
                  |
             Jellyfin library

What HookReel keeps: Prowlarr (indexer proxy), qBittorrent (downloader),
Gluetun (VPN).

What HookReel replaces: Radarr, Sonarr, Jellyseerr, and all their
automation rules and RSS feeds.

## Stack

| Service | Purpose |
|---|---|
| hookreel | Main AI agent, web UI, Telegram bot |
| hookreel-clamav | Malware scanning |
| prowlarr | Indexer proxy |
| qbittorrent | Torrent client (inside Gluetun) |
| gluetun | VPN (optional) |
| jellyfin | Media server (optional) |

## Configuration

All configuration is in config/.env. Key variables:

| Variable | Description |
|---|---|
| AI_MODEL_ENDPOINT | OpenAI-compatible API endpoint |
| AI_MODEL_NAME | Model name (e.g. deepseek-chat) |
| METADATA_PROVIDER | tmdb, omdb, or tvmaze |
| TELEGRAM_BOT_TOKEN | Your Telegram bot token |
| JELLYFIN_API_KEY | Jellyfin API key |
| DELETE_ENABLED | Allow agent to delete files (default: false) |

See docs/CONFIGURATION.md for the full reference.

## Documentation

- [Installation guide](docs/INSTALL.md)
- [Configuration reference](docs/CONFIGURATION.md)
- [Upgrading](docs/UPGRADING.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Version history

| Version | Name | Notes |
|---|---|---|
| 1.0 | Hook | Initial release |

Version names follow Peter and Wendy characters:
v1.0 Hook, v1.1 Alf, v1.2 Bill, v1.3 Black Murphy, v1.4 Cecco,
v2.0 Peter (next major release)

## Contributing

Pull requests are welcome. Please open an issue first to discuss
what you would like to change.

## Security

- Never expose port 8765 to the public internet
- Use Tailscale for remote access (see Settings > Remote Access)
- Keep config/.env secure -- it contains your API keys
- Enable VPN (Gluetun) for all downloads
- DELETE_ENABLED defaults to false -- only enable when needed

## License

MIT -- see [LICENSE](LICENSE)
