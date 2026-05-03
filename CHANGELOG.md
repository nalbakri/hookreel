## v1.1 Alf -- 2026-05-03
### New Features
- Download lifecycle tracking -- full audit trail from request to final file
- Star ratings (1-5) for movies, TV shows, and individual episodes
- Watch tracking -- mark watched/unwatched, track progress per episode
- Jellyfin webhook integration -- automatic watch history from Jellyfin playback
- Suggestion engine -- recommends unwatched and highly rated content
- Dedupe detection -- scans library for duplicate movies and shows
- Download visibility -- file size and progress % via get_download_status
- Prowlarr URL resolution -- download URLs resolved to magnet links at add time,
  eliminating failures caused by expiring Prowlarr proxy URLs
- Re-fetch flow -- pipeline re-searches Prowlarr for a fresh URL when user confirms
  a release, iterating across indexers until one resolves successfully
### Improvements
- Hash capture at add time -- extracts hash directly from magnet URL,
  eliminates fuzzy post-hoc name matching that caused wrong-file assignments
- Search results capped at 5, sorted by seeders, file size always shown
- Agent stops and asks user after any failed download -- no auto-retry
- FastAPI upgraded from 0.115.0 to 0.136.1
- Starlette upgraded from 0.38.6 to 1.0.0 (resolves CVE-2024-47874, CVE-2025-54121)
- python-multipart upgraded from 0.0.9 to 0.0.26 (resolves CVE-2024-53981, CVE-2026-24486)
### Bug Fixes
- Fixed tv_pipeline.py passing categories=[5000] instead of category=5000 to search_releases()
- Fixed tv_pipeline.py fast path inverting _validate_download_url() result, blocking magnet links
- Fixed pipeline.py fast path setting status to downloading when torrent hash is None
- Fixed pipeline.py fast path hardcoding downloading in return dict regardless of actual status
- Fixed pre-existing bug in tv_pipeline.py where chosen_title was passed as save_path
- Added time.sleep(2) before hash name lookup to fix race condition on direct URL downloads
### Agent
- New rules for ratings, watch tracking, suggestions, dedupe, and download history
- get_download_history tool -- agent can explain what happened to any download
- get_stuck_downloads tool -- agent can identify stalled downloads
- download_url removed from search results -- agent passes release_title to request_movie
- Rule 8 updated -- agent must stop and ask user after any failed download, no auto-retry
- Rule 9 updated -- re-fetch flow replaces stale download URL pattern
### Documentation
- INSTALL.md -- added Jellyfin Webhook Plugin setup instructions
### Tests
- 15 new tests (106-120) covering all v1.1 features
- Total: 99 tests passing

---

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
  cannot be auto-recovered. Affected movies will remain as failed and must be re-requested.
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
