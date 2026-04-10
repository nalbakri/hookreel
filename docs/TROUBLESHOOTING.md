# HookReel Troubleshooting

## Bot not responding

1. Check the bot token is correct in Settings -> Telegram
2. Check your Telegram user ID is in the allowed list
3. Check the container is running: docker ps | grep hookreel
4. Check logs: docker logs hookreel --tail 50
5. Try restarting the agent: Settings -> System -> Restart Agent

## Downloads not starting

1. Test the qBittorrent connection in Settings -> Download Client
2. Check qBittorrent is accessible: docker ps | grep gluetun
3. Check Prowlarr has active indexers: open Prowlarr at port 9696
4. Test Prowlarr connection in Settings -> Indexer
5. Check logs for pipeline errors: docker logs hookreel --tail 100

## ClamAV not scanning

ClamAV is best-effort -- the pipeline continues if it is unavailable.
To check ClamAV status:

    docker logs hookreel-clamav --tail 20

On first start ClamAV takes 2-5 minutes to load definitions.
The log will show "Listening daemon" when ready.

## Jellyfin not updating

1. Check the Jellyfin API key in Settings -> Media Library
2. Test the connection with the Test Connection button
3. Trigger a manual library scan from the web UI
4. Check Jellyfin logs at http://[your-ip]:8096/web/index.html#/dashboard/logs

## RTMP stream not appearing in Telegram

1. Make sure you tapped Start Streaming in your Telegram cinema group FIRST
2. Then ask your agent to stream the movie
3. Check RTMP settings in Settings -> RTMP Cinema
4. The stream key format must be: rtmps://dc5-1.rtmp.t.me/s/[id]:[key]
   Note the colon between ID and key -- not a slash

## DNS issues

If containers cannot resolve hostnames, check resolv.conf is locked:

    lsattr /etc/resolv.conf

Should show: ----i---- /etc/resolv.conf

If not locked:

    echo "nameserver 8.8.8.8" > /etc/resolv.conf
    echo "nameserver 8.8.4.4" >> /etc/resolv.conf
    chattr +i /etc/resolv.conf

## Tailscale conflict with DNS

Tailscale can overwrite resolv.conf. Lock it after running tailscale up:

    sudo tailscale up
    chattr +i /etc/resolv.conf

## Container cannot reach qBittorrent (403 error)

In qBittorrent settings -> Web UI -> IP subnets whitelist, add:

    172.16.0.0/12

Also disable Host header validation in qBittorrent Web UI settings.

## Web UI session expires too quickly

Change SESSION_EXPIRY_HOURS in Settings -> Web UI.
Default is 24 hours.

## Log file location

Inside the container: /logs/hookreel.log
On the host: [project-dir]/logs/hookreel.log
View in web UI: Settings -> System -> View Logs

## Getting help

Open an issue at https://github.com/nalbakri/hookreel/issues
Include the output of: docker logs hookreel --tail 100
