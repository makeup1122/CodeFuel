"""Logging setup. RotatingFileHandler to %APPDATA%\\UsageTray\\usagetray.log.

Never logs tokens (providers don't pass tokens to the logger).
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from .config import config_dir

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    if os.environ.get("USAGETRAY_DEBUG"):
        level = logging.DEBUG
    log_path = config_dir() / "usagetray.log"
    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger("usagetray")
    root.setLevel(level)
    root.addHandler(handler)
    _configured = True
