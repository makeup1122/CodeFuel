"""Logging setup. RotatingFileHandler to %APPDATA%\\CodeFuel\\codefuel.log.

Never logs tokens (providers don't pass tokens to the logger).
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from .config import config_dir

_configured = False

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def resolve_level(name: str | int | None) -> int:
    """Map a config log-level name to a logging constant.

    Accepts a level name (case-insensitive), an int level, or None. Unknown
    values fall back to INFO.
    """
    if isinstance(name, int):
        return name
    if isinstance(name, str):
        return _LEVELS.get(name.strip().upper(), logging.INFO)
    return logging.INFO


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    if os.environ.get("CODEFUEL_DEBUG"):
        level = logging.DEBUG
    log_path = config_dir() / "codefuel.log"
    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("codefuel")
    root.setLevel(level)
    root.addHandler(handler)
    _configured = True
