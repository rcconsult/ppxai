"""The `remote` config axis (ADR 0013 S1): the hosts the local hub reaches.

Returns the RAW block; `ppxai.remote.parse_hosts` validates it, so a
malformed block reaches the hub (which logs it and stays off) instead of
being silently dropped here.
"""

from __future__ import annotations

from typing import Any

from .store import get_config


def get_remote_config() -> Any:
    """The raw top-level `remote` value; {} when absent or unreadable."""
    try:
        cfg = get_config() or {}
    except Exception:  # config source unreadable -- the hub stays off
        return {}
    value = cfg.get("remote", {})
    return {} if value is None else value
