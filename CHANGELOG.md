# Changelog

All notable changes to HookReel are documented here.

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
