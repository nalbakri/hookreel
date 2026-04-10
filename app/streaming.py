# =============================================================
# app/streaming.py - RTMP streaming manager
# Manages FFmpeg process that pushes media to Telegram RTMP.
# =============================================================
import subprocess
import threading
import time
import os
from app.logger import get_logger

logger = get_logger(__name__)

# -------------------------------------------------------
# Module-level state - one stream at a time.
# -------------------------------------------------------
_ffmpeg_process = None
_stream_lock = threading.Lock()
_current_title = None
_stream_start_time = None


def is_streaming() -> bool:
    """Return True if a stream is currently active."""
    global _ffmpeg_process
    with _stream_lock:
        if _ffmpeg_process is None:
            return False
        return _ffmpeg_process.poll() is None


def current_stream_info() -> dict | None:
    """Return info about the current stream, or None if not streaming."""
    if not is_streaming():
        return None
    return {
        "title": _current_title,
        "started_at": _stream_start_time,
    }


def start_stream(file_path: str, rtmp_url: str, rtmp_key: str, title: str = None) -> dict:
    """
    Start streaming a media file to Telegram via RTMP.

    Args:
        file_path: Absolute path to the media file inside the container.
        rtmp_url:  RTMP server URL from Telegram (e.g. rtmps://dc4-1.rtmp.t.me/s/...)
        rtmp_key:  Stream key from Telegram.
        title:     Human-readable title for status messages.

    Returns:
        dict with keys: success (bool), message (str)
    """
    global _ffmpeg_process, _current_title, _stream_start_time

    if not os.path.exists(file_path):
        return {"success": False, "message": f"File not found: {file_path}"}

    if is_streaming():
        return {"success": False, "message": f"Already streaming: {_current_title}"}

    # Build the full RTMP destination URL.
    # Telegram stream key format is "streamID:secretKey" - append as-is after the URL.
    rtmp_dest = f"{rtmp_url.rstrip('/')}/{rtmp_key}"

    # FFmpeg command:
    # -re           - read input at native frame rate (required for live streams)
    # -i            - input file
    # -c:v libx264  - video codec
    # -preset veryfast - fast encode, low CPU on A8-6600K
    # -pix_fmt yuv420p - required pixel format for Telegram
    # -g 50         - keyframe interval for Telegram compatibility
    # -b:v 2500k    - video bitrate suitable for Telegram streams
    # -maxrate / -bufsize - prevent bitrate spikes
    # -c:a aac -b:a 128k - audio encode
    # -f flv        - FLV container required by RTMP
    cmd = [
        "ffmpeg",
        "-re",
        "-i", file_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-g", "50",
        "-b:v", "2500k",
        "-maxrate", "2500k",
        "-bufsize", "5000k",
        "-vf", "scale=1280:-2",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-f", "flv",
        rtmp_dest,
    ]

    logger.info(f"Starting stream: {title or file_path}")
    logger.info(f"RTMP destination: {rtmp_url}/***")

    with _stream_lock:
        try:
            _ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            _current_title = title or os.path.basename(file_path)
            _stream_start_time = time.time()
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {e}")
            return {"success": False, "message": f"Failed to start stream: {e}"}

    # Monitor FFmpeg in background - log errors and clean up when done.
    threading.Thread(target=_monitor_stream, daemon=True).start()

    return {"success": True, "message": f"Streaming started: {_current_title}"}


def stop_stream() -> dict:
    """Stop the current stream if one is running."""
    global _ffmpeg_process, _current_title, _stream_start_time

    with _stream_lock:
        if _ffmpeg_process is None or _ffmpeg_process.poll() is not None:
            return {"success": False, "message": "No stream is currently running."}

        title = _current_title
        _ffmpeg_process.terminate()
        try:
            _ffmpeg_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ffmpeg_process.kill()

        _ffmpeg_process = None
        _current_title = None
        _stream_start_time = None

    logger.info(f"Stream stopped: {title}")
    return {"success": True, "message": f"Stream stopped: {title}"}


def _monitor_stream():
    """Background thread - watches FFmpeg process and logs errors."""
    global _ffmpeg_process, _current_title, _stream_start_time

    process = _ffmpeg_process
    if process is None:
        return

    # Collect stderr output for error reporting.
    stderr_lines = []
    for line in process.stderr:
        stderr_lines.append(line.strip())
        # Keep only last 20 lines to avoid memory bloat.
        if len(stderr_lines) > 20:
            stderr_lines.pop(0)

    process.wait()
    exit_code = process.returncode

    with _stream_lock:
        _ffmpeg_process = None
        _current_title = None
        _stream_start_time = None

    if exit_code == 0:
        logger.info("Stream ended normally.")
    elif exit_code == -15:
        logger.info("Stream stopped by user (SIGTERM).")
    else:
        logger.error(f"FFmpeg exited with code {exit_code}")
        if stderr_lines:
            logger.error(f"Last FFmpeg output: {stderr_lines[-1]}")
