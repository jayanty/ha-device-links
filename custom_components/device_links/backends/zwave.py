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
from custom_components.device_links.backends.base import (
    BackendDevice,
    LinkCheck,
    LinkResult,
    LinkResultStatus,
    ObservedDevice,
)
from custom_components.device_links.backends.zwave_accessor import ZWaveAccessorError
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Diagnostic,
    Feature,
    Link,
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

    # Writing, and the refusals that come before it.

    async def async_check_link(self, link: Link) -> LinkCheck:
        """Say whether this link could be written, without writing it.

        The same refusals as `async_add_link` up to but not including the write, so the
        plan dialog can show what apply would say rather than a hopeful guess.
        """
        try:
            node = self._node(link.source)
            groups = await self._groups(node)
            refusal = _local_refusal(link, groups.get(link.source_endpoint, {}))
            if refusal is None:
                refusal = await self._driver_refusal(node, link)
        # A failure to ask is an answer the caller can act on, not a traceback.
        except Exception as err:
            _LOGGER.debug("check of %s failed: %s", link.fingerprint, err)
            return LinkCheck(ok=False, reason=Diagnostic("check_failed", _about(link)))
        if refusal is not None:
            return LinkCheck(ok=False, reason=refusal)
        return LinkCheck(ok=True)

    async def async_add_link(self, link: Link) -> LinkResult:
        """Write one link to the device, or explain why it was not written.

        The order of the refusals is the safety rule, and it is this and no other:

        1. The lifeline, because it is never ours to write whatever else is true, and
           asking any later question first could answer instead of it.
        2. Self-association, for the same reason: it can never be right, so nothing about
           the device's current state can make it right.
        3. Already present, which is where a state-dependent answer belongs. It sits after
           the two absolute refusals so that neither can be masked by "it is already
           there", and before the check so that a link the device already holds is never
           reported as blocked: a check can start refusing something that was written
           months ago (a security class changed, a node was re-included), and answering
           BLOCKED for an entry that exists would make a plan that can never converge.
        4. The driver's own check, which costs a radio round trip and so goes last of the
           questions. Anything but OK, including a value this version has never heard of,
           refuses.
        5. The write.
        """
        return await self._write(link, adding=True)

    async def async_remove_link(self, link: Link) -> LinkResult:
        """Remove one link from the device, or explain why it was not removed.

        The same shape as the add without the driver check, which asks whether an
        association may be created and has nothing to say about taking one off. Not
        present is `ALREADY_PRESENT`: there is nothing to do, and nothing went wrong.
        """
        return await self._write(link, adding=False)

    async def _write(self, link: Link, *, adding: bool) -> LinkResult:
        """Add or remove one association, refusing in the documented order."""
        controller = self._driver.controller
        try:
            node = self._node(link.source)
            groups = await self._groups(node)
            refusal = _local_refusal(link, groups.get(link.source_endpoint, {}))
            if refusal is not None:
                return LinkResult(status=LinkResultStatus.BLOCKED, reason=refusal)

            source = self._address(node.node_id, link.source_endpoint)
            target = self._address(_node_id_of(link.target.handle), link.target.endpoint)
            group = int(link.emitter_group)
            present = _is_present(await controller.async_get_associations(source), group, target)
            # An add of what is there and a removal of what is not are both nothing to do,
            # and neither is worth a radio round trip on a mesh that is carrying traffic.
            if present is adding:
                return LinkResult(status=LinkResultStatus.ALREADY_PRESENT)

            if adding:
                refusal = await self._driver_refusal(node, link)
                if refusal is not None:
                    return LinkResult(status=LinkResultStatus.BLOCKED, reason=refusal)

            # A sleeping node cannot answer now, so the write is queued rather than
            # waited on. NOTE: modelled from the library signature, not observed. Stage 0
            # item Z4 was never approved, so what really happens to a queued write, and
            # which event reports it landing, is unproven. See docs/open-items.md J1 and
            # issue #5. Nothing that passes against the fake driver is evidence about it.
            asleep = _is_asleep(node)
            write = (
                controller.async_add_associations
                if adding
                else controller.async_remove_associations
            )
            # `force` is never passed, here or anywhere (CLAUDE.md Section 3 rule 6): it
            # skips the driver's own safety checks, which are the ones step 4 asked.
            await write(source, group, [target], wait_for_result=not asleep)
        # The executor asks one link at a time and needs a result for every one.
        except Exception as err:
            _LOGGER.debug("write of %s failed: %s", link.fingerprint, err)
            return LinkResult(
                status=LinkResultStatus.FAILED,
                reason=Diagnostic("link_write_failed", _about(link)),
                raw_error=str(err),
            )
        else:
            if asleep:
                return LinkResult(status=LinkResultStatus.PENDING_WAKEUP)
            return LinkResult(status=LinkResultStatus.APPLIED)

    async def _driver_refusal(self, node: Node, link: Link) -> Diagnostic | None:
        """Ask the driver whether this association may be written, and translate its answer.

        `AssociationCheckResult.OK` is 1, so the answer is compared to it explicitly:
        a truthiness test would read every refusal as permission (Stage 0 item Z3).
        """
        answer = await self._driver.controller.async_check_association(
            self._address(node.node_id, link.source_endpoint),
            int(link.emitter_group),
            self._address(_node_id_of(link.target.handle), link.target.endpoint),
        )
        reason = zwave_protocol.blocked_reason_for(int(answer))
        if reason is None:
            return None
        return Diagnostic(reason.translation_key, {**_about(link), **reason.placeholders})

    def _address(self, node_id: int, endpoint: int | None) -> AssociationAddress:
        """Return one end of an association, as the driver addresses it.

        Stage 0 recorded that the controller is the first positional argument on 0.73.0;
        constructing it the other way round raises `TypeError`.
        """
        # Imported inside the function, not at module scope: see the module docstring.
        from zwave_js_server.model.association import AssociationAddress  # noqa: PLC0415

        return AssociationAddress(self._driver.controller, node_id=node_id, endpoint=endpoint)

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


def _local_refusal(
    link: Link, groups: Mapping[str, zwave_protocol.AssociationGroup]
) -> Diagnostic | None:
    """Return why this link may not be written at all, without asking the driver.

    Both refusals are absolute, so they are answered here rather than paid for at the
    radio. A lifeline is how a device reports to Home Assistant at all, and a device
    cannot be in its own association group (`Forbidden_SelfAssociation`): the driver would
    refuse that too, but a round trip to be told what we already know is a round trip a
    busy mesh does not have.
    """
    if zwave_protocol.is_lifeline_group(groups, link.emitter_group):
        return Diagnostic("lifeline_is_protected", _about(link))
    if link.source.identity == link.target.handle.identity:
        return Diagnostic("self_association", _about(link))
    return None


def _is_present(
    associations: Mapping[int, list[AssociationAddress]], group: int, target: AssociationAddress
) -> bool:
    """Say whether this exact target is already in this group.

    Endpoint included, and not normalised: an address with no endpoint is a node
    association and one with endpoint 0 is a multi channel association to the root. They
    are written with different command classes and are genuinely different entries.
    """
    return any(
        (address.node_id, address.endpoint) == (target.node_id, target.endpoint)
        for address in associations.get(group, [])
    )


def _about(link: Link) -> dict[str, str]:
    """Return the placeholders every message about a link needs to be actionable."""
    return {
        "device": link.source.name_at_authoring,
        "group": link.emitter_group,
        "target": link.target.handle.name_at_authoring,
    }


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


def _is_asleep(node: Node) -> bool:
    """Say whether this node is asleep, which changes what a write to it means."""
    # Imported inside the function, not at module scope: see the module docstring.
    from zwave_js_server.const import NodeStatus  # noqa: PLC0415

    return node.status == NodeStatus.ASLEEP


def _node_id_of(handle: DeviceHandle) -> int:
    """Return the node id a Z-Wave handle names, which is the half after the home id."""
    return int(handle.protocol_id.rsplit(":", 1)[1])
