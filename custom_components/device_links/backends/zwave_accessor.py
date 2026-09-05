"""The single supported way to reach the Z-Wave JS driver from this integration.

PRD Decision D2 (a): reuse the zwave_js integration's existing connection rather than
opening a second, unauthenticated WebSocket to zwave-js-server. That couples us to
zwave_js internals, so every such access lives here and is covered by
tests/test_zwave_accessor.py, which fails in CI when upstream moves.

Access is deliberately direct rather than defensive: if upstream renames an attribute we
want an AttributeError naming it, not a None that masquerades as a disconnected client.

Verified against Home Assistant 2026.8.3 and zwave-js-server-python 0.73.0 on
2026-09-05 (Stage 0 item Z1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.zwave_js import helpers as zwave_js_helpers
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.components.zwave_js.models import ZwaveJSConfigEntry
    from zwave_js_server.model.driver import Driver
    from zwave_js_server.model.node import Node


class ZWaveAccessorError(HomeAssistantError):
    """Raised when the Z-Wave driver or a node cannot be reached."""


@callback
def get_driver(entry: ZwaveJSConfigEntry) -> Driver:
    """Return the live driver behind a loaded zwave_js config entry."""
    driver = entry.runtime_data.client.driver
    if driver is None:
        raise ZWaveAccessorError("The Z-Wave JS client is not connected")
    return driver


@callback
def async_get_node(hass: HomeAssistant, device_id: str) -> Node:
    """Resolve a Home Assistant device id to a Z-Wave node."""
    try:
        return zwave_js_helpers.async_get_node_from_device_id(hass, device_id)
    except ValueError as err:
        raise ZWaveAccessorError(f"{device_id} is not a Z-Wave device: {err}") from err
