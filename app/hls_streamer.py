"""
HookReel HLS streaming module.
Manages FFmpeg-based HLS streams for Watch Mode Tier 2 fallback.
Only active when JELLYFIN_ENABLED=false in config.
"""

import os
import subprocess
import shutil
from datetime import datetime, timedelta
import app.config as config
from app.logger import get_logger

logger = get_logger(__name__)


class HLSStreamer:
    """
    Manages FFmpeg HLS streams for local media playback.

    Each stream is identified by a media_id (integer database ID).
    FFmpeg processes are tracked in memory and cleaned up automatically
    after two hours of inactivity.
    """

    def __init__(self):
        """
        Initialise the HLS streamer.

        Loads stream directory from config, creates it if it does not
        exist, and sets up the active streams tracking dict.
        """
        self.stream_dir = config.HLS_STREAM_DIR
        self.segment_duration = config.HLS_SEGMENT_DURATION
        self.server_ip = config.JELLYFIN_HOST
        self.stream_port = config.STREAM_PORT
        self.active_streams = {}

        os.makedirs(self.stream_dir, exist_ok=True)
        logger.info(
            "[HookReel] HLSStreamer initialised, stream dir: %s",
            self.stream_dir
        )

    def start_stream(self, media_id: int, file_path: str) -> str:
        """
        Start an HLS stream for the given media file.

        If a stream is already active for this media_id, returns the
        existing stream URL without starting a new FFmpeg process.

        Parameters:
            media_id:  Database ID of the movie or episode.
            file_path: Absolute path to the media file inside the container.

        Returns:
            The HLS playlist URL the client should open, or None on error.
        """
        if media_id in self.active_streams:
            logger.info(
                "[HookReel] Stream already active for media_id=%d", media_id
            )
            return self.get_stream_url(media_id)

        if not os.path.isfile(file_path):
            logger.error(
                "[HookReel] start_stream: file not found: %s", file_path
            )
            return None

        output_dir = os.path.join(self.stream_dir, str(media_id))
        os.makedirs(output_dir, exist_ok=True)
        playlist_path = os.path.join(output_dir, "playlist.m3u8")

        ffmpeg_command = [
            "ffmpeg",
            "-i", file_path,
            "-codec:", "copy",
            "-start_number", "0",
            "-hls_time", str(self.segment_duration),
            "-hls_list_size", "0",
            "-hls_flags", "delete_segments",
            "-f", "hls",
            playlist_path,
        ]

        try:
            process = subprocess.Popen(
                ffmpeg_command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.active_streams[media_id] = {
                "process": process,
                "file_path": file_path,
                "output_dir": output_dir,
                "started_at": datetime.utcnow().isoformat(),
                "last_active": datetime.utcnow(),
            }
            stream_url = self.get_stream_url(media_id)
            logger.info(
                "[HookReel] HLS stream started for media_id=%d url=%s",
                media_id, stream_url
            )
            return stream_url
        except Exception as error:
            logger.error(
                "[HookReel] start_stream error for media_id=%d: %s",
                media_id, error
            )
            return None

    def stop_stream(self, media_id: int) -> bool:
        """
        Stop an active HLS stream and clean up its segments.

        Parameters:
            media_id: Database ID of the media being streamed.

        Returns:
            True if the stream was found and stopped, False otherwise.
        """
        if media_id not in self.active_streams:
            logger.warning(
                "[HookReel] stop_stream: no active stream for media_id=%d",
                media_id
            )
            return False

        stream_info = self.active_streams.pop(media_id)
        process = stream_info["process"]
        output_dir = stream_info["output_dir"]

        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception as error:
            logger.warning(
                "[HookReel] stop_stream: error terminating FFmpeg: %s", error
            )
            try:
                process.kill()
            except Exception:
                pass

        try:
            if os.path.isdir(output_dir):
                shutil.rmtree(output_dir)
                logger.info(
                    "[HookReel] Removed HLS segments: %s", output_dir
                )
        except Exception as error:
            logger.warning(
                "[HookReel] stop_stream: could not remove segments: %s", error
            )

        logger.info(
            "[HookReel] HLS stream stopped for media_id=%d", media_id
        )
        return True

    def get_stream_url(self, media_id: int) -> str:
        """
        Return the HLS playlist URL for an active stream.

        Parameters:
            media_id: Database ID of the media being streamed.

        Returns:
            The playlist URL string, or None if no stream is active.
        """
        if media_id not in self.active_streams:
            return None
        return (
            f"http://{self.server_ip}:{self.stream_port}"
            f"/stream/{media_id}/playlist.m3u8"
        )

    def get_active_streams(self) -> list:
        """
        Return a list of all currently active streams.

        Returns:
            List of dicts with media_id, started_at, and stream_url.
        """
        result = []
        for media_id, info in self.active_streams.items():
            result.append({
                "media_id": media_id,
                "file_path": info["file_path"],
                "started_at": info["started_at"],
                "stream_url": self.get_stream_url(media_id),
            })
        return result

    def cleanup_old_streams(self):
        """
        Stop and remove streams that have been inactive for two or more hours.

        Called periodically from the main polling loop to prevent
        runaway FFmpeg processes accumulating over time.
        """
        cutoff = datetime.utcnow() - timedelta(hours=2)
        stale_ids = [
            media_id
            for media_id, info in self.active_streams.items()
            if info["last_active"] < cutoff
        ]
        for media_id in stale_ids:
            logger.info(
                "[HookReel] cleanup_old_streams: stopping stale stream "
                "media_id=%d", media_id
            )
            self.stop_stream(media_id)

        if stale_ids:
            logger.info(
                "[HookReel] cleanup_old_streams: removed %d stale stream(s)",
                len(stale_ids)
            )


# Module-level singleton — imported by webui.py and watch.py
hls_streamer = HLSStreamer()
