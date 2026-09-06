"""The `MatterClient` the Matter adapter is written against, and how it is reached.

Two jobs, both of them the Matter version of something that already exists here.

The **Protocols** are the seam. `backends/matter.py` takes a client rather than reaching
into the `matter` integration itself, for the same reason `zwave.py` takes a driver and
`zigbee2mqtt.py` takes an `MqttClient`: it is what lets the adapter be exercised against
`tests/fakes/matter.py` with no Matter server anywhere. They describe only what the adapter
uses and nothing else, so a change upstream can break at most that much.

The **accessor** is the coupling, in one place, with a test. Decision D2 (a) for Z-Wave says
to reuse the upstream integration's existing connection rather than opening a second one,
and it applies here word for word: Device Links opens no network surface of its own (PRD
Section 10), so it borrows the `matter` config entry's client. Nothing outside this module
may import `matter` internals, exactly as `zwave_accessor.py` fences off `zwave_js`.

**Everything from `homeassistant.components.matter` is imported inside a function.** Home
Assistant installs an integration's requirements when that integration is set up, so on a
house with no Matter fabric the `matter_python_client` distribution is absent, and importing
`homeassistant.components.matter` (which imports `matter_server` at module scope) would
raise `ModuleNotFoundError` and take the whole of Device Links down with it. This integration
explicitly supports Z-Wave-only and Zigbee-only installs, so that is not a theoretical shape.

Verified against Home Assistant 2026.8.3 and matter-python-client 1.3.0 on 2026-09-05
(Stage 0 item M1). Two things that capture settled and that nothing here may quietly change:
`read_attribute` returns a **mapping keyed by the attribute path** rather than the value,
and the distribution that provides `matter_server` was renamed from `python-matter-server`,
so PRD Appendix C cites a retired project while the import path is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from homeassistant.components.matter.helpers import MatterConfigEntry

__all__ = [
    "MatterAccessorError",
    "MatterClient",
    "MatterNodeView",
    "MatterServerInfo",
    "async_get_client",
    "async_matter_is_available",
]


class MatterAccessorError(HomeAssistantError):
    """Raised when the Matter client cannot be reached.

    An internal error type carrying no `translation_key` by design, for the reason
    `zwave_accessor.ZWaveAccessorError` gives: user-facing exceptions are translated by the
    layer that surfaces a failure to a user, and this is not that layer.
    """


class MatterDeviceInfo(Protocol):
    """The two Basic Information fields a device handle is built from.

    Spelled the way the Matter cluster spells them, because they are that cluster's field
    names rather than names this project chose.
    """

    vendorName: str | None  # noqa: N815 - the Matter cluster's field name, not ours
    productName: str | None  # noqa: N815 - the Matter cluster's field name, not ours


class MatterNodeView(Protocol):
    """What the adapter reads off a node object without touching the network.

    Deliberately four things. Everything else the adapter wants it reads as an attribute
    through `read_attribute`, which is the call Stage 0 M1 actually exercised: a node object
    carries more than this, and depending on the rest would be depending on a shape nobody
    has checked against the version Home Assistant ships.
    """

    node_id: int
    available: bool
    name: str | None
    device_info: MatterDeviceInfo | None
    endpoints: Mapping[int, Any]


class MatterServerInfo(Protocol):
    """What the client says about the server and the fabric it is joined to.

    `compressed_fabric_id` is half of the device registry identifier the `matter` integration
    registers (Stage 0 item P2), and it changes when a fabric is re-commissioned, which is
    why it is read live rather than stored.
    """

    compressed_fabric_id: int
    sdk_version: str | None


class MatterClient(Protocol):
    """The four things the Matter adapter needs from a Matter server connection.

    `read_attribute` answers with a **mapping keyed by the attribute path**, not with the
    value. That is the single most consequential fact in this file: reading the mapping as
    the value turns every list-shaped result into "not a list", which reads as "this device
    has no client clusters" rather than as an error, and it was hit for real during Stage 0.
    The adapter unwraps it in exactly one place.
    """

    def get_nodes(self) -> Sequence[MatterNodeView]:
        """Return every node on the fabric. Held by the client, so this does no I/O."""

    async def read_attribute(self, node_id: int, attribute_path: str) -> Any:
        """Read one attribute, answering with `{path: value}`."""

    async def write_attribute(self, node_id: int, attribute_path: str, value: Any) -> Any:
        """Write one attribute. What it answers with is not documented, so it is not read."""

    def subscribe_events(
        self,
        callback: Callable[[Any, Any], None],
        event_filter: Any = None,
        node_filter: int | None = None,
    ) -> Callable[[], None]:
        """Call back on fabric events, returning the callable that unsubscribes."""

    @property
    def server_info(self) -> MatterServerInfo | None:
        """Return what the server said about itself, or None before it has said anything."""


def async_matter_is_available(hass: HomeAssistant) -> bool:
    """Say whether the `matter` integration is loaded and can be reached.

    A plain membership test rather than a call into `matter`, because it has to be
    answerable on a system where the package cannot even be imported. False is not an error:
    a house with no Matter fabric is an ordinary house, and Device Links adapts what is
    there.
    """
    return "matter" in hass.config.components


@callback
def async_get_client(matter_entry: MatterConfigEntry) -> MatterClient:
    """Return the live client behind a loaded `matter` config entry.

    The argument is the **matter** config entry, not this integration's own. A caller holds
    a `device_links` entry and has to look the `matter` one up first; the parameter name says
    so to stop the two being confused, exactly as `zwave_accessor.async_get_driver` does.

    Access is deliberately direct rather than defensive: if upstream renames an attribute we
    want an `AttributeError` naming it, not a None that masquerades as a disconnected client.
    The `cast` is the honest expression of what this module is for. Upstream types the client
    as `matter_server.client.MatterClient`, which is a distribution this repository's test
    environment does not install, so the type checker sees `Any` and the cast is where the
    shape verified in Stage 0 M1 is asserted rather than assumed.
    """
    try:
        client = matter_entry.runtime_data.adapter.matter_client
    except AttributeError as err:
        raise MatterAccessorError(
            f"the matter config entry {matter_entry.entry_id} is loaded but does not hold a "
            f"client where this version of Device Links looks for one: {err}"
        ) from err
    if client is None:
        raise MatterAccessorError("The Matter client is not connected")
    return cast("MatterClient", client)
