"""
HookReel centralised logging.
Creates a logger that writes to Docker stdout and a rotating file.
Log level is controlled by the LOG_LEVEL environment variable.

Usage in any module:
    from app.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Something happened")
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import app.config as config

# ── Constants ────────────────────────────────────────────────────────────────
_LOG_FORMAT = "[HookReel] %(levelname)-8s %(asctime)s — %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 3


def _build_root_logger() -> logging.Logger:
    """
    Construct and configure the root 'hookreel' logger.
    Attaches a stdout StreamHandler and a RotatingFileHandler.
    Safe to call multiple times — handlers are only added once.
    """
    log = logging.getLogger("hookreel")

    if log.handlers:
        return log

    level_name = config.LOG_LEVEL.upper() if config.LOG_LEVEL else "INFO"
    level = getattr(logging, level_name, logging.INFO)
    log.setLevel(level)

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Handler 1: Docker stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    log.addHandler(stdout_handler)

    # Handler 2: Rotating file
    log_dir = Path(config.LOGS_PATH)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "hookreel.log"
        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    except OSError as exc:
        log.warning(
            "Could not create log file at %s: %s — logging to stdout only.",
            log_dir, exc,
        )

    log.info(
        "Logger initialised — level=%s  file=%s/hookreel.log",
        level_name, log_dir
    )
    return log


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the root 'hookreel' logger.
    This is the preferred way to get a logger in any module.

    Usage:
        logger = get_logger(__name__)
    """
    _build_root_logger()
    return logging.getLogger(f"hookreel.{name}")


# Backwards-compatible singleton for any Phase 1 code that imports `logger` directly
logger = _build_root_logger()
