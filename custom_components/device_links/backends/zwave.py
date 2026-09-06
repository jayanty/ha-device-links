"""The Z-Wave adapter: the only module that talks to a real Z-Wave network.

This is deliberately the thinnest layer in the codebase. Every decision that can be made
without touching a radio already lives in `zwave_protocol.py`, `compiler.py` and
`planner.py`, where it is property-tested against the Stage 0 capture; what is left here is
fetch, delegate, translate. A branch in this module that does not touch the driver is a
branch in the wrong place.

Two things it does that nothing else may:

- It reaches `zwave_js_server` objects. The driver arrives from `zwave_accessor.py`
  (Decision D2 (a): reuse the `zwave_js` integration's connection rather than opening a
  second WebSocket), and the library symbols this module constructs are imported inside the
  functions that need them, for the reason `zwave_accessor` records: `zwave_js_server` is
  installed only when the `zwave_js` integration is set up, and Device Links explicitly
  supports Zigbee-only and Matter-only installs. A module-scope import would take the whole
  integration down on such a system.
- It decides nothing about whether a write should happen. It offers single-link add and
  remove, and the executor (Phase 1C) sequences them.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import TYPE_CHECKING, Final

from custom_components.device_links.backends import zwave_protocol
from custom_components.device_links.backends.base import BackendDevice, ObservedDevice
from custom_components.device_links.backends.zwave_accessor import ZWaveAccessorError
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Feature,
    LinkTarget,
    ObservedLink,
    SettingsAdapter,
    ZWaveFingerprint,
)

if TYPE_CHECKING:
    from zwave_js_server.model.association import AssociationAddress, AssociationGroup
    from zwave_js_server.model.driver import Driver
    from zwave_js_server.model.node import Node
    from zwave_js_server.model.value import ConfigurationValue

    from custom_components.device_links.profile_db import ProfileDatabase, ProfileEntry

_LOGGER = logging.getLogger(__name__)

# Every node on Jayant's network is on the root endpoint, and a device's own controls are
# reported there. Endpoint-addressed emitters are a Phase 2 concern; the observed state
# below already reads whatever endpoints a device reports.
_ROOT_ENDPOINT: Final = 0

# What a Z-Wave association target can be made to do by an association. The driver reports
# a per-node command class list that would narrow this per device, but the Stage 0 capture
# did not record it, so this is the set every association target in that capture supports
# rather than a claim about a device nobody has looked at. See docs/open-items.md T9.
RECEIVABLE_FEATURES: Final = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})


class ZWaveBackend:
    """One Z-Wave network, as the `Backend` protocol sees it.

    Holds the driver and the curated profile database, and fetches nothing until it is
    asked: constructing this is not an I/O operation, so a config entry can build one
    before the mesh is interesting.
    """

    def __init__(self, *, driver: Driver, profiles: ProfileDatabase | None) -> None:
        """Hold what this adapter needs, and read nothing yet."""
        self._driver = driver
        self._profiles = profiles

    # Reading.

    async def async_devices(self) -> list[BackendDevice]:
        """Return every node this network holds."""
        return [
            BackendDevice(handle=self._handle_of(node))
            for node in self._driver.controller.nodes.values()
        ]

    async def async_capabilities(self, handle: DeviceHandle) -> DeviceCapabilities:
        """Return what this device can emit and receive, and the settings it exposes."""
        node = self._node(handle)
        groups = await self._groups(node)
        entry = self._entry_of(node)
        warnings: list[str] = []
        emitters = zwave_protocol.resolve_emitters(
            groups.get(_ROOT_ENDPOINT, {}), entry, warnings=warnings
        )
        for warning in warnings:
            _LOGGER.debug("node %s: %s", node.node_id, warning)
        return DeviceCapabilities(
            handle=handle,
            emitters=tuple(emitters),
            receivable=RECEIVABLE_FEATURES,
            is_long_range=zwave_protocol.is_long_range(node.node_id, node.protocol),
            settings={} if entry is None else entry.settings,
        )

    async def async_observed(self, handle: DeviceHandle, deep: bool = False) -> ObservedDevice:
        """Return what is really on this device now."""
        node = self._node(handle)
        groups = await self._groups(node)
        associations = await self._driver.controller.async_get_all_associations(node)
        # Stage 0 read this dump one level too shallow and got plausible-looking empty
        # groups rather than an error. Assert that the node key is the one asked for
        # rather than trusting position, which is the check that would have caught it.
        if node.node_id not in associations:
            raise ZWaveAccessorError(
                f"the association dump for node {node.node_id} is about "
                f"{sorted(associations)} instead"
            )
        return ObservedDevice(
            handle=handle,
            links=tuple(self._observed_links(handle, node, associations, groups)),
            settings=self._settings_of(node),
        )

    def _observed_links(
        self,
        handle: DeviceHandle,
        node: Node,
        associations: Mapping[int, Mapping[int, Mapping[int, list[AssociationAddress]]]],
        groups: Mapping[int, Mapping[str, zwave_protocol.AssociationGroup]],
    ) -> list[ObservedLink]:
        """Turn one node's association dump into links, one per entry on the device."""
        links: list[ObservedLink] = []
        for endpoint, in_endpoint in associations[node.node_id].items():
            reported = groups.get(endpoint, {})
            for group_id, addresses in in_endpoint.items():
                links.extend(
                    self._observed_link(handle, endpoint, str(group_id), reported, address)
                    for address in addresses
                )
        return links

    def _observed_link(
        self,
        handle: DeviceHandle,
        endpoint: int,
        group: str,
        groups: Mapping[str, zwave_protocol.AssociationGroup],
        address: AssociationAddress,
    ) -> ObservedLink:
        """Turn one association entry into the link the planner diffs against.

        `managed_by` stays None. Only the coordinator knows which profile is active and
        which rule claims which fingerprint, so ownership resolved here would be a guess,
        and a wrong guess is what makes somebody else's association removable.
        """
        return ObservedLink(
            backend=BackendId.ZWAVE,
            source=handle,
            source_endpoint=endpoint,
            emitter_id=f"g{group}",
            emitter_group=group,
            target=LinkTarget(
                handle=self._handle_of_node_id(address.node_id), endpoint=address.endpoint
            ),
            feature=_feature_of(groups, group),
            is_system=zwave_protocol.is_lifeline_group(groups, group),
            managed_by=None,
        )

    # Devices and their identity.

    def _handle_of(self, node: Node) -> DeviceHandle:
        """Return the handle a rule refers to this node by.

        `ha_device_id` is left empty: it is convenience only and takes no part in identity
        (see `models.DeviceHandle`), and resolving it needs the device registry, which
        needs `hass`, which this adapter deliberately does not hold. The coordinator fills
        it in when it merges this listing with the registry.
        """
        return DeviceHandle(
            backend=BackendId.ZWAVE,
            protocol_id=self._protocol_id(node.node_id),
            ha_device_id="",
            fingerprint=_fingerprint_of(node),
            name_at_authoring=node.name or node.label or f"Node {node.node_id}",
        )

    def _handle_of_node_id(self, node_id: int) -> DeviceHandle:
        """Return a handle for a node id an association points at.

        An association can name a node the driver does not list, and one always does: the
        controller is the target of every lifeline and is not in the node list. Such a
        target still needs a handle, because the link it is part of is real, so it gets one
        with an empty fingerprint rather than being dropped from the observed state.
        """
        node = self._driver.controller.nodes.get(node_id)
        if node is None:
            return DeviceHandle(
                backend=BackendId.ZWAVE,
                protocol_id=self._protocol_id(node_id),
                ha_device_id="",
                fingerprint=ZWaveFingerprint(
                    manufacturer_id=0, product_type=0, product_id=0, firmware=""
                ),
                name_at_authoring=f"Node {node_id}",
            )
        return self._handle_of(node)

    def _protocol_id(self, node_id: int) -> str:
        """Return the network-level address of a node: home id and node id."""
        return f"{self._driver.controller.home_id}:{node_id}"

    def _node(self, handle: DeviceHandle) -> Node:
        """Return the node a handle names, or say which one is missing.

        Answering for an unknown node with an empty result would read as a device that has
        nothing on it, which is exactly how a planner comes to remove everything.
        """
        node_id = _node_id_of(handle)
        node = self._driver.controller.nodes.get(node_id)
        if node is None:
            raise ZWaveAccessorError(f"node {node_id} is not on this Z-Wave network")
        return node

    async def _groups(self, node: Node) -> dict[int, dict[str, zwave_protocol.AssociationGroup]]:
        """Return a node's association groups in the shape the pure module reads.

        The library reports `{endpoint: {group: AssociationGroup}}`, with integer keys and
        a dataclass per group. `zwave_protocol` is written against string group ids and a
        TypedDict so that it can be handed the JSON fixtures directly and stay free of any
        `zwave_js_server` import, and this is the whole of the difference between the two.
        """
        dump = await self._driver.controller.async_get_all_association_groups(node)
        return {
            endpoint: {
                str(group_id): _as_protocol_group(group) for group_id, group in groups.items()
            }
            for endpoint, groups in dump.items()
        }

    def _entry_of(self, node: Node) -> ProfileEntry | None:
        """Return the curated entry for this model, or None when none claims it."""
        if self._profiles is None:
            return None
        return self._profiles.lookup(_fingerprint_of(node))

    def _settings_of(self, node: Node) -> dict[str, int]:
        """Return every setting the profile knows about that the device has reported."""
        entry = self._entry_of(node)
        if entry is None:
            return {}
        values = node.get_configuration_values()
        found: dict[str, int] = {}
        for capability, adapter in entry.settings.items():
            value = _value_for(values, adapter)
            if value is not None and isinstance(value.value, int):
                found[capability] = value.value
        return found


def _fingerprint_of(node: Node) -> ZWaveFingerprint:
    """Return what identifies this node's model, which is what a profile is keyed by."""
    return ZWaveFingerprint(
        manufacturer_id=node.manufacturer_id or 0,
        product_type=node.product_type or 0,
        product_id=node.product_id or 0,
        firmware=node.firmware_version or "",
    )


def _as_protocol_group(group: AssociationGroup) -> zwave_protocol.AssociationGroup:
    """Return one library association group as the pure module's TypedDict."""
    return zwave_protocol.AssociationGroup(
        is_lifeline=group.is_lifeline,
        issued_commands=group.issued_commands,
        label=group.label,
        max_nodes=group.max_nodes,
        multi_channel=group.multi_channel,
        profile=group.profile,
    )


def _feature_of(groups: Mapping[str, zwave_protocol.AssociationGroup], group: str) -> Feature:
    """Return what an entry in this group carries, or report-only for an unknown group."""
    reported = groups.get(group)
    if reported is None:
        return Feature.STATUS_REPORT
    return zwave_protocol.feature_of_group(reported)


def _value_for(
    values: Mapping[str, ConfigurationValue], adapter: SettingsAdapter
) -> ConfigurationValue | None:
    """Return the configuration value one settings adapter points at.

    A bitmask adapter names a partial parameter, which the driver exposes as its own value
    with the bitmask as `property_key`, so reading and writing it touches that bit and no
    other. None means the device has not reported that parameter.
    """
    for value in values.values():
        if int(value.property_) != adapter.parameter:
            continue
        key = None if value.property_key is None else int(value.property_key)
        if key == adapter.bitmask:
            return value
    return None


def _node_id_of(handle: DeviceHandle) -> int:
    """Return the node id a Z-Wave handle names, which is the half after the home id."""
    return int(handle.protocol_id.rsplit(":", 1)[1])
