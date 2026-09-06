"""The single supported way to reach the Z-Wave JS driver from this integration.

PRD Decision D2 (a): reuse the zwave_js integration's existing connection rather than
opening a second, unauthenticated WebSocket to zwave-js-server. That couples us to
zwave_js internals, so every such access lives here and is covered by
tests/test_zwave_accessor.py, which fails in CI when upstream moves.

Access is deliberately direct rather than defensive: if upstream renames an attribute we
want an AttributeError naming it, not a None that masquerades as a disconnected client.

Nothing outside this module may import zwave_js internals. `__all__` below is the whole
supported surface; reaching through this module to `homeassistant.components.zwave_js`
would put the coupling back where CI cannot see it.

Upstream failure modes, recorded for the Phase 1 author rather than modelled here:
`async_get_node_from_device_id` raises a bare `ValueError` for five distinct situations.
Three are permanent configuration errors ("Device ID ... is not valid", "... is not from
an existing zwave_js config entry", "Node for device ... can't be found") and two are
transient and worth retrying ("... config entry is not loaded", "Driver is not ready.").
`async_get_node` flattens all five into one `ZWaveAccessorError` on purpose: nothing
retries today, and upstream offers no exception type or error code to key on, so telling
them apart would mean matching on prose that upstream never promised. When Phase 1 needs
retry semantics, that is the decision to revisit, and it needs its own guard test.

Verified against Home Assistant 2026.8.3 and zwave-js-server-python 0.73.0 on
2026-09-05 (Stage 0 item Z1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.components.zwave_js.models import ZwaveJSConfigEntry
    from zwave_js_server.model.driver import Driver
    from zwave_js_server.model.node import Node

__all__ = [
    "ZWaveAccessorError",
    "async_get_driver",
    "async_get_node",
    "async_get_server_version",
]


class ZWaveAccessorError(HomeAssistantError):
    """Raised when the Z-Wave driver or a node cannot be reached.

    This is an internal error type and carries no `translation_key` by design.
    CLAUDE.md Section 7 requires user-facing exceptions to be translated, and that
    responsibility sits with the layer that surfaces a failure to a user: the services
    and WebSocket commands added in Phase 1. Those callers catch this error and raise a
    translated `ServiceValidationError` or `HomeAssistantError` with a `translation_key`
    and placeholders backed by `strings.json`. This class is the first exception type in
    the codebase and later Z-Wave modules will copy it, so copy that contract too rather
    than copying the absent translation key.
    """


@callback
def async_get_driver(zwave_js_entry: ZwaveJSConfigEntry) -> Driver:
    """Return the live driver behind a loaded zwave_js config entry.

    The argument is the *zwave_js* config entry, not this integration's own entry. A
    Phase 1 caller holds a `device_links` entry and has to look the zwave_js one up
    first; the parameter name says so to stop the two being confused.

    The annotations on this function are load-bearing and pinned by a test: see
    tests/test_zwave_accessor.py.
    """
    driver = zwave_js_entry.runtime_data.client.driver
    if driver is None:
        raise ZWaveAccessorError("The Z-Wave JS client is not connected")
    return driver


@callback
def async_get_server_version(zwave_js_entry: ZwaveJSConfigEntry) -> str | None:
    """Return the zwave-js-server version behind a loaded zwave_js config entry.

    Reported by the Health sensor, which is what a remote debugging session reads first
    (PRD Section 17.1): "which Z-Wave JS is this" is the question that decides whether an
    upstream behaviour is worth reproducing locally or is already fixed.

    None rather than raising, because a version is never the reason to fail: the client
    fills `version` in on connect, so it is None exactly while the connection is still
    being made, and an integration that refused to set up over a missing version string
    would be refusing over nothing. It lives here rather than at the call site because it
    reaches into zwave_js internals, and this module is the only place that may.
    """
    version = zwave_js_entry.runtime_data.client.version
    return None if version is None else version.server_version


@callback
def async_get_node(hass: HomeAssistant, device_id: str) -> Node:
    """Resolve a Home Assistant device id to a Z-Wave node."""
    # Imported here, not at module scope, because the library may not exist at all.
    # zwave_js.helpers imports zwave_js_server at its own module scope, and Home
    # Assistant only installs an integration's requirements when that integration is
    # set up. device_links declares zwave_js in after_dependencies, which does not force
    # it to load, and this integration explicitly supports Zigbee-only and Matter-only
    # installs (see the no_backend abort reason in strings.json). On such a system a
    # module-scope import would raise ModuleNotFoundError: zwave_js_server and take the
    # whole integration down. Keeping it local means only Z-Wave calls pay that cost.
    from homeassistant.components.zwave_js import helpers as zwave_js_helpers  # noqa: PLC0415

    try:
        return zwave_js_helpers.async_get_node_from_device_id(hass, device_id)
    except ValueError as err:
        # Upstream reports five different situations this way, three permanent and two
        # transient (see the module docstring). Claiming a cause we cannot tell apart
        # would be wrong for four of them, so report only what is certainly true.
        raise ZWaveAccessorError(
            f"Cannot resolve device {device_id} to a Z-Wave node: {err}"
        ) from err
