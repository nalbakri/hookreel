# HookReel Installation Guide

## Prerequisites

- Linux server (tested on Debian, Ubuntu, OpenMediaVault)
- Docker 24+ and Docker Compose v2
- Python 3.10+ (for setup wizard, on the host)
- 2GB RAM minimum, 4GB recommended
- The following ports available: 8765 (web UI)
- Existing arr stack (Prowlarr + qBittorrent) OR willing to set up fresh

## Hardware recommendations

- CPU: Any modern x86_64 processor
- RAM: 4GB+ recommended (ClamAV uses ~500MB on first load)
- Storage: SSD for appdata, HDD/NAS for media

## Step 1 -- Clone the repository

    git clone https://github.com/nalbakri/hookreel.git
    cd hookreel

## Step 2 -- Run the setup wizard

    python3 setup.py

The wizard will ask you about:
- Agent name
- Media folder paths
- VPN configuration
- AI model (DeepSeek recommended)
- Metadata provider (TMDB recommended)
- Telegram bot
- Jellyfin
- Web UI password
- RTMP cinema (optional)

It generates config/.env and docker-compose.yml for you.
No manual file editing required.

## Step 3 -- Start HookReel

    docker compose up -d

## Step 4 -- Wait for ClamAV

ClamAV downloads virus definitions on first start.
This takes 2-5 minutes. Check progress with:

    docker logs hookreel-clamav -f

Wait until you see "Listening daemon" before using HookReel.

## Step 5 -- Open the web UI

    http://[your-server-ip]:8765

Log in with the password you set during setup.

## Step 6 -- Jellyfin setup (if included)

Open Jellyfin at http://[your-server-ip]:8096
Complete the initial setup wizard.
Add your Movies and TV folders as libraries.
Then go to Dashboard -> API Keys -> Add API key.
Copy the key and paste it in HookReel Settings -> Media Library.

## Step 7 -- Telegram bot setup

1. Open Telegram and search @BotFather
2. Send /newbot
3. Follow the steps to create your bot
4. Copy the token BotFather gives you
5. Paste it in HookReel Settings -> Telegram
6. Add your Telegram user ID to the allowed list
   (search @userinfobot to find your ID)
7. Send /start to your bot

## Step 8 -- Import existing library (optional)

If you have existing media files:

    docker exec hookreel python import_library.py --dry-run
    docker exec hookreel python import_library.py
    docker exec hookreel python import_library.py --enrich

## Step 9 -- Prowlarr setup

1. Open Prowlarr at http://[your-server-ip]:9696
2. Add your preferred indexers
3. Copy your Prowlarr API key from Settings -> General
4. Paste it in HookReel Settings -> Indexer

## Remote access via Tailscale

Install Tailscale on your server:

    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up

Install Tailscale on your phone or laptop.
Sign in to the same account on both.
Access HookReel at http://[tailscale-ip]:8765

## Troubleshooting

See docs/TROUBLESHOOTING.md

## Raspberry Pi installation

HookReel supports ARM64 (Raspberry Pi 4 and 5 with 64-bit OS, Radxa boards,
and other ARM64 SBCs).

Note: ARM64 builds are provided but not yet tested on real hardware.
Community feedback welcome.

Requirements:
- Raspberry Pi 4 or 5 with 4GB+ RAM (8GB recommended)
- 64-bit OS (Raspberry Pi OS 64-bit, Ubuntu 22.04 ARM, Armbian)
- Docker Engine 24+ and Compose v2+

Installation is identical to x86:
    git clone https://github.com/nalbakri/hookreel
    cd hookreel
    python3 setup.py
    docker compose up -d

Note: ClamAV may take longer to start on Raspberry Pi (10-15 minutes on
first run while downloading virus definitions). This is normal.


---

## Optional: Automatic Watch Tracking via Jellyfin

HookReel can automatically update your watch history when you watch content
in Jellyfin. This requires the Jellyfin Webhook Plugin to be installed.

Note: The Jellyfin plugin system is sandboxed -- this step cannot be
automated. You must install the plugin manually.

### Step 1 -- Install the Jellyfin Webhook Plugin

1. Open Jellyfin in your browser
2. Go to Dashboard > Plugins > Catalogue
3. Search for "Webhook"
4. Install the "Webhook" plugin by Jellyfin
5. Restart Jellyfin when prompted

### Step 2 -- Configure the Webhook

1. Go to Dashboard > Plugins > Webhook
2. Click "Add Generic Destination"
3. Set the URL to:

    http://<hookreel-host>:8765/webhooks/jellyfin

   Replace <hookreel-host> with your HookReel server IP or hostname.
   Example: http://192.168.1.21:8765/webhooks/jellyfin

4. Set the following notification types:
   - Playback Stop
   - Playback Start (optional)

5. Set Request Type to POST
6. Set Template to the default JSON template
7. Save

### Step 3 -- Optional: Secure the Webhook

To prevent unauthorised payloads, set a shared secret:

1. In HookReel config/.env, set:

    JELLYFIN_WEBHOOK_SECRET=your-secret-here

2. In the Jellyfin Webhook plugin, set the same value in the
   "Secret" field.

3. Restart HookReel:

    docker compose restart hookreel

### Verification

After setup, play a movie or episode in Jellyfin. HookReel will log:

    [HookReel] Jellyfin webhook: event=PlaybackStop type=Movie completed=True
    [HookReel] Webhook: marked movie 'Movie Title' as watched (completed=True)

If no webhook events are received within 24 hours after enabling Jellyfin
integration, HookReel will log a reminder suggesting you install the plugin.

### Graceful Degradation

If the Jellyfin Webhook Plugin is not installed, all HookReel features
continue to work normally. Watch history can be updated manually via the
agent: "mark Pulp Fiction as watched".
