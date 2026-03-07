"""
Black/white list management — file + database backed.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

BLACKLIST_PATH = "data/blacklist.json"
WHITELIST_PATH = "data/whitelist.json"


def load_blacklist() -> set[str]:
    return _load_set(BLACKLIST_PATH)


def load_whitelist() -> set[str]:
    return _load_set(WHITELIST_PATH)


def add_to_blacklist(address: str, reason: str = "") -> None:
    data = _load_dict(BLACKLIST_PATH)
    data[address] = {"reason": reason}
    _save_dict(BLACKLIST_PATH, data)


def add_to_whitelist(address: str, notes: str = "") -> None:
    data = _load_dict(WHITELIST_PATH)
    data[address] = {"notes": notes}
    _save_dict(WHITELIST_PATH, data)


def is_blacklisted(address: str) -> bool:
    return address in load_blacklist()


def _load_set(path: str) -> set[str]:
    data = _load_dict(path)
    return set(data.keys())


def _load_dict(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_dict(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
