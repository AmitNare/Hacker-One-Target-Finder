"""
Centralised logging setup.
Import `get_logger` from any module to get a consistently configured logger.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

import config

_loggers: dict = {}


def _configure_stdio() -> None:
    """Avoid Windows cp1252 crashes on Unicode log/print characters."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configure_stdio()


def get_logger(name: str = "h1_finder", log_file: Optional[str] = None) -> logging.Logger:
    """Return (and cache) a configured logger for *name*."""
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------ #
    # Console handler – INFO and above                                    #
    # ------------------------------------------------------------------ #
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # ------------------------------------------------------------------ #
    # File handler – DEBUG and above                                      #
    # ------------------------------------------------------------------ #
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    log_path = log_file or os.path.join(config.OUTPUT_DIR, config.LOG_FILENAME)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s – %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger
