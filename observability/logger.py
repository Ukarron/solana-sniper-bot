"""
Structured JSON logging for production.

All log entries are JSON objects — easy to parse, search, filter.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            entry["data"] = record.extra_data
        if record.exc_info and record.exc_info[0]:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured JSON output."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(StructuredFormatter())
    root.addHandler(console)

    # File handler with rotation (max 50MB, keep 3 backups)
    try:
        file_handler = RotatingFileHandler(
            "bot.log", maxBytes=50_000_000, backupCount=3
        )
        file_handler.setFormatter(StructuredFormatter())
        root.addHandler(file_handler)
    except Exception:
        pass  # File logging optional (e.g. permissions issue)

    # Suppress noisy libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
