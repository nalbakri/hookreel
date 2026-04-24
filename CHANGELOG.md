# Changelog

All notable changes to HookReel are documented here.

## v1.0.3 Hook
### Bug fixes
- Fixed v1.0.2 regression where polling loop called undefined function run_post_processing() instead of run_cycle()

## v1.0.3 Hook
### Bug fixes
- Fixed v1.0.2 regression where polling loop called undefined function instead of run_cycle()
- Added queuedUP to complete states so queued-for-seeding torrents are correctly detected as finished
- Added startup recovery for downloads that completed but were never post-processed due to the v1.0.1/v1.0.2 bug
- Disabled unreliable title-based file matching in postprocessor to prevent wrong files being moved

### Known limitation
- Movies downloaded without a torrent hash (due to a pre-existing hash lookup reliability issue)
  cannot be auto-recovered. Affected movies will remain as 'failed' and must be re-requested.
  The postprocessor will log a clear warning. A proper fix with interactive file confirmation
  via Telegram is planned for v1.1 Alf.

## v1.0.2 Hook
### Bug fixes
- Fixed critical bug where completed downloads were never post-processed (files stayed in Downloads indefinitely)
- Fixed RTMP stream credentials being lost after container restart (credentials now read from .env at call time)
- Fixed agent name and personality reverting to defaults after image rebuild (persona.json moved to /config/ volume)
- Fixed chat welcome bubble showing hardcoded greeting instead of current agent name and personality
- Fixed rare bug that might affect users who scan existing media libraries (import_library.py was missing from Docker image)

## v1.0.1 Hook

### UI improvements
- Version and release name now shown in web UI nav bar (e.g. v1.0.1 Hook)
- Agent name shown in chat header
- Personality selector added to settings page
- Agent name field added to settings page
- Favicon added (anchor icon)
- chat.html hardcoded strings replaced with dynamic agent name

### Bug fixes
- TemplateResponse deprecation warning fixed (starlette 0.38.6)
- Tests 18-20 now pass without -s flag (HOOKREEL_RUN_API_TESTS=y to run)
- Torrent hash lookup normalised to lowercase for reliable completion detection
- Telegram bot ConversationManager reference updated correctly on agent restart

### Developer experience
- docker-compose.dev.yml added for live app/ volume mount during development
- CONTRIBUTING.md added with full dev setup and workflow instructions
- GitHub Actions workflow added for multi-arch Docker builds (linux/amd64, linux/arm64)
- ARM64 builds provided for Raspberry Pi 4/5 and other ARM64 SBCs

## v1.0 Hook -- 2026

Initial public release.

### Core pipeline
- AI-powered movie and TV show discovery and download
- Prowlarr integration for indexer searching
- qBittorrent integration for downloading
- ClamAV malware scanning on every download
- Jellyfin-compatible file renaming and library notification
- Post-processing pipeline with quarantine support

### Interfaces
- Telegram bot interface with natural language requests
- Mobile-first web UI with PWA support
- Session-based authentication with signed cookies
- Bot pairing system via one-time codes

### TV show support
- Full TV show tracking with episode-level status
- Automatic new episode detection via TVmaze polling
- Season and episode download requests
- Watch mode with next-episode logic

### Watch mode
- Jellyfin deep link integration
- HLS streaming fallback (FFmpeg)
- RTMP streaming to private Telegram group (watch inline)
- Watch history tracking

### Library management
- Library import tool for existing media collections
- Flat file and subfolder layout support
- Metadata enrichment (poster, overview, rating)
- Jellyfin-compatible rename tool
- Extra media sources (portable drives, NAS, secondary drives)
- Scan Library button in web UI and Telegram /scan command

### Agent identity
- Configurable agent name (default: MrSmee)
- Pirate, professional, and friendly personality styles
- Customisable greeting

### Setup and packaging
- First-run setup wizard (setup.py)
- Uninstaller (uninstall.py)
- Docker Hub image: nalbakri/hookreel

### Security
- Rate limiting on all API endpoints
- Session expiry
- Audit log
- Security headers middleware
- resolv.conf locking for stable DNS

### Configuration
- Pluggable AI model (DeepSeek, Ollama, any OpenAI-compatible endpoint)
- Pluggable metadata provider (TMDB, OMDb, TVmaze)
- VPN optional via Gluetun
- Jellyfin optional with FFmpeg HLS fallback
- DELETE_ENABLED toggle (default: false)

---

Version names follow Peter and Wendy characters:
v1.0 Hook, v1.1 Alf, v1.2 Bill, v1.3 Black Murphy, v1.4 Cecco,
v2.0 Peter (next major release)
