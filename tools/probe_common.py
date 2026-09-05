"""Shared helpers for Stage 0 probe scripts.

Imports nothing from Home Assistant so the same module runs inside the HA Core
container, inside an add-on container, and under pytest on the laptop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_SECRET_KEYS = frozenset({"home_id", "homeId", "dsk", "network_key", "s2_access_control"})
_TAIL_KEYS = frozenset({"ieee_address", "ieeeAddress", "ieee"})


def redact(value: Any) -> Any:
    """Recursively mask identifiers that must never reach a committed fixture.

    Node ids, endpoints, and group ids are deliberately preserved: the fixtures are
    useless without them and they identify nothing outside this network.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _SECRET_KEYS:
                out[key] = "<redacted>"
            elif key in _TAIL_KEYS and isinstance(item, str):
                out[key] = f"<redacted:...{item[-4:]}>"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def envelope(name: str, data: Any, *, versions: dict[str, str] | None = None) -> dict[str, Any]:
    """Wrap probe output with provenance so a stale fixture is obvious."""
    return {
        "fixture": name,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "versions": versions or {},
        "data": redact(data),
    }
