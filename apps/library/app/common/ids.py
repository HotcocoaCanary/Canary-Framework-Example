"""Prefixed identifiers — readable in logs, sortable by creation time."""

from __future__ import annotations

import time
import uuid


def new_id(prefix: str) -> str:
    """``bk_01hq…`` — a millisecond timestamp plus randomness, prefixed by kind."""
    stamp = format(int(time.time() * 1000), "011x")
    return f"{prefix}_{stamp}{uuid.uuid4().hex[:10]}"
