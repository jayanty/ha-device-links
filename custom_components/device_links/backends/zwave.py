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

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
from time import monotonic
from typing import TYPE_CHECKING, Final

from custom_components.device_links.backends import zwave_protocol
from custom_components.device_links.backends.base import (
    BackendDevice,
    LinkCheck,
    LinkResult,
    LinkResultStatus,
    ObservedDevice,
    SettingResult,
    SettingValue,
    SystemScope,
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
    from zwave_js_server.model.value import ConfigurationValue, Value

    from custom_components.device_links.profile_db import ProfileDatabase, ProfileEntry

_LOGGER = logging.getLogger(__name__)

# Every node on Jayant's network is on the root endpoint, and a device's own controls are
# reported there. Endpoint-addressed emitters are a Phase 2 concern; the observed state
# below already reads whatever endpoints a device reports.
_ROOT_ENDPOINT: Final = 0

# Indicator CC property 2 is the binary "is this light on" value, which is the one
# `tests/fixtures/z8_led_path.json` found writeable per button on node 36 (ids 67 to 71).
# Property 1 is the multilevel form and property 3 the on/off period, neither of which a
# leg mirroring a light's state has anything to say about.
INDICATION_PROPERTY_BINARY: Final = 2

# The device registry namespace this protocol's devices live in: the upstream integration's
# own domain, never ours. Inventing a `device_links`-namespaced identifier is precisely how
# an orphan device page gets made (Stage 0 item P2, and `rule_entity`'s module docstring).
UPSTREAM_DOMAIN: Final = "zwave_js"

# What a Z-Wave association target can be made to do by an association. The driver reports
# a per-node command class list that would narrow this per device, but the Stage 0 capture
# did not record it, so this is the set every association target in that capture supports
# rather than a claim about a device nobody has looked at. See docs/open-items.md T9.
RECEIVABLE_FEATURES: Final = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})

# The command classes an association lives in, which are the ones a deep verify refreshes
# and a subscription watches (FR-B3, FR-B4).
ASSOCIATION_CC: Final = 0x85
MULTI_CHANNEL_ASSOCIATION_CC: Final = 0x8E
_ASSOCIATION_CCS: Final = frozenset({ASSOCIATION_CC, MULTI_CHANNEL_ASSOCIATION_CC})

# How long a deep verify waits for a device to answer a refresh. Stage 0 measured an
# association add at 67 ms and a remove at 253 ms on a listening node, so five seconds is
# generous for a mesh that is answering at all, and short enough not to hang a job.
DEFAULT_DEEP_VERIFY_TIMEOUT: Final = 5.0

# Why a deep verify did not happen. A sleeping node cannot answer a refresh, and asking one
# to would burn the whole timeout to learn what its status already said.
SKIPPED_ASLEEP: Final = "asleep"

# Configuration CC, where the settings adapters point. FR-B3 watches it alongside the two
# association command classes: a parameter changed by hand is drift like any other.
CONFIGURATION_CC: Final = 0x70
_WATCHED_CCS: Final = _ASSOCIATION_CCS | {CONFIGURATION_CC}

# FR-B3's debounce window, leading edge. One refresh of one node emits an event per group,
# and the callback says only that the node is worth re-reading, so the burst is one call.
DEFAULT_DEBOUNCE_SECONDS: Final = 2.0


@dataclass(slots=True)
class _Subscription:
    """Whether one subscription is still delivering, shared by its listener and its unsubscribe.

    Unregistering the listener is not enough on its own: `EventBase.emit` iterates a copy of
    its listener list, so a callback already dispatched in the burst being delivered still
    arrives after removal. This flag is what an in-flight callback is tested against, so
    "unsubscribed" means silent from that moment and not from the next event.
    """

    live: bool = True


class ZWaveBackend:
    """One Z-Wave network, as the `Backend` protocol sees it.

    Holds the driver and the curated profile database, and fetches nothing until it is
    asked: constructing this is not an I/O operation, so a config entry can build one
    before the mesh is interesting.
    """

    def __init__(
        self,
        *,
        driver: Driver,
        profiles: ProfileDatabase | None,
        deep_verify_timeout: float = DEFAULT_DEEP_VERIFY_TIMEOUT,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    ) -> None:
        """Hold what this adapter needs, and read nothing yet."""
        self._driver = driver
        self._profiles = profiles
        self._deep_verify_timeout = deep_verify_timeout
        self._debounce_seconds = debounce_seconds

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
        """Return what is really on this device now.

        A shallow read is the driver's cache, which is right about our own writes (Stage 0
        confirmed it reflects them immediately) and can be behind on somebody else's.
        `deep` asks the device itself, which costs radio time and a bounded wait, so it is
        opt-in per request and is what the executor does after an apply.
        """
        node = self._node(handle)
        verified = False
        timed_out = False
        skipped: str | None = None
        if deep:
            if _is_asleep(node):
                skipped = SKIPPED_ASLEEP
            else:
                verified = await self._await_refresh(node)
                timed_out = not verified
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
            deep_verified=verified,
            deep_verify_timed_out=timed_out,
            deep_verify_skipped_reason=skipped,
        )

    async def _await_refresh(self, node: Node) -> bool:
        """Refresh the association command classes and wait for the device to answer.

        FR-B4 describes deep verify as refresh, then read. Stage 0 item Z3 found
        `async_refresh_cc_values` sends `wait_for_result=False` and returns in 0 ms: it is
        fire and forget, so a read issued straight afterwards returns the same cache it
        would have returned anyway. Implemented literally, FR-B4 produces a verify that
        always agrees with itself, which is worse than no verify because it looks like
        assurance. So: subscribe first, so a fast device cannot answer before anyone is
        listening; then refresh; then wait for the value-updated event the answer produces.

        Returns whether the device answered. What that answer is worth has one honest
        limit, and callers have to know it. The event is emitted when a refreshed value
        lands, and a real driver may not emit one when the value it read back is unchanged,
        which was never measured (Stage 0 item Z5 was not run: docs/open-items.md J4 and
        T10, issue #8). On real hardware, then, a timeout means "the device did not report
        its associations to us in time", not "the device is wrong", and the common case
        where nothing was stale may produce one. That is why this returns a fact rather
        than raising, why the caller gets `deep_verified` and `deep_verify_timed_out` as
        separate things, and why this logs at debug: a warning that fires routinely is a
        warning users learn to ignore, and it would devalue the one that matters.
        """
        answered: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        def _on_value_updated(event: Mapping[str, object]) -> None:
            if _command_class_of(event) in _ASSOCIATION_CCS and not answered.done():
                answered.set_result(None)

        unsubscribe = node.on("value updated", _on_value_updated)
        try:
            # Imported inside the function, not at module scope: see the module docstring.
            from zwave_js_server.const import CommandClass  # noqa: PLC0415

            for command_class in (
                CommandClass.ASSOCIATION,
                CommandClass.MULTI_CHANNEL_ASSOCIATION,
            ):
                await node.async_refresh_cc_values(command_class)
            async with asyncio.timeout(self._deep_verify_timeout):
                await answered
        except TimeoutError:
            _LOGGER.debug(
                "node %s did not report its associations within %ss, so this read is the "
                "driver cache rather than a confirmation",
                node.node_id,
                self._deep_verify_timeout,
            )
            return False
        finally:
            unsubscribe()
        return True

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

    # Settings.

    async def async_read_setting(self, handle: DeviceHandle, capability: str) -> SettingValue:
        """Read one named setting off the device.

        The parameter and bitmask come back with the value, so a diagnostic can say which
        parameter was read without resolving the adapter a second time. A value of None
        means the device has not reported that parameter, which is not the same as zero.

        Raises `ZWaveAccessorError` when this model has no such setting, because a read
        has no shape to report a refusal in and inventing a value would be worse. The
        write path answers the same question with a `SettingResult`, which does.
        """
        node = self._node(handle)
        adapter = self._adapter_of(node, capability)
        value = _value_for(node.get_configuration_values(), adapter)
        return SettingValue(
            capability=capability,
            parameter=adapter.parameter,
            bitmask=adapter.bitmask,
            value=value.value if value is not None and isinstance(value.value, int) else None,
        )

    async def async_write_setting(
        self, handle: DeviceHandle, capability: str, value: int
    ) -> SettingResult:
        """Write one named setting to the device and read it back.

        Only the value the named capability points at is written. A bitmask adapter names
        a partial parameter, which the driver exposes as its own value, so writing it
        touches that bit and leaves the rest of the parameter alone: Decision D4's
        parameter 19 on a ZEN35 is never written by a rule that asked about parameter 35.

        PRD Section 8.4 requires the read-back, and the read-back is what decides the
        result. A device that accepts a write and ignores it is a real failure mode, and
        reporting it as success is how a rule comes to look applied and do nothing.
        """
        node = self._node(handle)
        try:
            adapter = self._adapter_of(node, capability)
        except ZWaveAccessorError:
            return SettingResult(
                ok=False,
                reason=Diagnostic(
                    "settings_not_available",
                    {"device": handle.name_at_authoring, "setting": capability},
                ),
            )
        target = _value_for(node.get_configuration_values(), adapter)
        if target is None:
            return SettingResult(
                ok=False,
                reason=Diagnostic(
                    "setting_not_reported",
                    {"device": handle.name_at_authoring, "setting": capability},
                ),
            )
        try:
            await node.async_set_value(target, value)
        # The caller asked for one setting and needs one answer about it.
        except Exception as err:
            _LOGGER.debug("write of %s on node %s failed: %s", capability, node.node_id, err)
            return SettingResult(
                ok=False,
                reason=Diagnostic(
                    "setting_write_failed",
                    {"device": handle.name_at_authoring, "setting": capability},
                ),
            )
        read_back = await self.async_read_setting(handle, capability)
        if read_back.value == value:
            return SettingResult(ok=True, read_back=read_back.value)
        return SettingResult(
            ok=False,
            read_back=read_back.value,
            reason=Diagnostic(
                "setting_not_applied",
                {"device": handle.name_at_authoring, "setting": capability},
            ),
        )

    # Button indications, which only a hybrid leg of kind (c) ever asks about.

    async def async_read_indication(self, handle: DeviceHandle, emitter_id: str) -> bool | None:
        """Return whether this button's own LED is lit, or None when nothing can say.

        Indicator CC rather than the LED-mode configuration parameters, and Stage 0 is why:
        `tests/fixtures/z8_led_path.json` measured both at 33 ms and found that an indicator
        set does not write device NVM. A leg mirroring a light would otherwise put a flash
        write on a finite-endurance device every time that light changed.
        """
        value = await self._indication_value(handle, emitter_id)
        return None if value is None or value.value is None else bool(value.value)

    async def async_write_indication(
        self, handle: DeviceHandle, emitter_id: str, lit: bool
    ) -> bool:
        """Light or unlight this button's own LED, and say whether the write went out."""
        value = await self._indication_value(handle, emitter_id)
        if value is None:
            return False
        try:
            await self._node(handle).async_set_value(value, lit)
        # One leg firing. What a caller does with a failure is count it, not raise it at a
        # user who is standing in a room pressing a button.
        except Exception as err:
            _LOGGER.debug(
                "the indication for %s on %s was not written: %s", emitter_id, handle.identity, err
            )
            return False
        return True

    async def _indication_value(self, handle: DeviceHandle, emitter_id: str) -> Value | None:
        """Return the node value that is this control's own indicator, or None.

        The emitter is resolved through `async_capabilities` rather than by reading the
        curated entry directly, and that is not a detail: a curated emitter that covers
        exactly the groups a derived one covered keeps the **derived** id, so the entry
        calls this control `button_2` while every rule in the profile calls it `g7`. Asking
        the same path the rest of the integration asks is the only way the two agree.

        Two ways to get None, both of them real: nothing says which indicator belongs to
        this control (which is most models, because nothing discoverable says so), or the
        device has not reported that indicator at all.
        """
        # Imported inside the function, not at module scope: see the module docstring.
        from zwave_js_server.const import CommandClass  # noqa: PLC0415

        node = self._node(handle)
        capabilities = await self.async_capabilities(handle)
        indicator_id = next(
            (
                emitter.indicator_id
                for emitter in capabilities.emitters
                if emitter.emitter_id == emitter_id
            ),
            None,
        )
        if indicator_id is None:
            return None
        for value in node.values.values():
            if (
                int(value.command_class) == CommandClass.INDICATOR
                and _as_int(value.property_) == indicator_id
                and _as_int(value.property_key) == INDICATION_PROPERTY_BINARY
            ):
                return value
        return None

    def _adapter_of(self, node: Node, capability: str) -> SettingsAdapter:
        """Return where this named setting lives on this model, or say it does not."""
        entry = self._entry_of(node)
        adapter = None if entry is None else entry.settings.get(capability)
        if adapter is None:
            raise ZWaveAccessorError(
                f"node {node.node_id} has no {capability} setting in the profile database"
            )
        return adapter

    # Change subscriptions.

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """Call `callback` with a device identity whenever that device's state changes.

        FR-B3: observed state follows the driver's value-updated events for Association
        (0x85), Multi Channel Association (0x8E) and Configuration (0x70), rather than
        polling. The callback says only which device is worth re-reading, so one refresh
        emitting an event per group is one call: the debounce is leading edge, delivering
        the first event about a device at once and swallowing the burst behind it, because
        a drift that is reported two seconds late is a drift the user watches happen.

        The returned callable removes every listener it registered, and closes the door
        behind it: `EventBase.emit` iterates a copy of its listener list, so a callback
        already dispatched in the burst being delivered would still arrive after removal.
        At a config entry unload that is a callback reaching a coordinator that has already
        torn itself down, which is the leak that survives a reload and confuses everyone.

        Nodes included after this call are not watched. Re-subscribing on node added is the
        coordinator's job, because it is the thing that knows a device appeared.

        NOTE: whether a real driver emits these for a change made outside Home Assistant is
        Stage 0 item Z5, which was never run: see docs/open-items.md J4 and issue #8. The
        event shape here is modelled from the library, not observed on that path.
        """
        subscription = _Subscription()
        listener = self._listener(callback, subscription)
        listeners = [
            node.on("value updated", listener) for node in self._driver.controller.nodes.values()
        ]

        def _unsubscribe() -> None:
            subscription.live = False
            for remove in listeners:
                remove()

        return _unsubscribe

    def _listener(
        self, callback: Callable[[str], None], subscription: _Subscription
    ) -> Callable[[Mapping[str, object]], None]:
        """Return the listener that turns one node event into at most one callback.

        One listener for the whole subscription, so the debounce window is shared across
        the nodes it watches and an unsubscribe silences all of them at once.
        """
        last_seen: dict[str, float] = {}

        def _listen(event: Mapping[str, object]) -> None:
            if not subscription.live:
                return
            if _command_class_of(event) not in _WATCHED_CCS:
                return
            node_id = _node_id_of_event(event)
            if node_id is None:
                return
            identity = f"{BackendId.ZWAVE}:{self._protocol_id(node_id)}"
            now = monotonic()
            if identity in last_seen and now - last_seen[identity] < self._debounce_seconds:
                return
            last_seen[identity] = now
            callback(identity)

        return _listen

    def wake_instructions(self, handle: DeviceHandle) -> str | None:
        """Return how a user wakes this device, or None when it is always listening."""
        entry = self._entry_of(self._node(handle))
        return None if entry is None else entry.wake_instruction

    def system_scope(self) -> SystemScope:
        """Report that a Z-Wave lifeline group is reserved whole rather than entry by entry.

        An association group has one purpose, so the group is the unit and not the entry.

        A Z-Wave group holding the controller is the lifeline, and nothing else may ever go
        into it: the group is the unit, not the entry in it. `_local_refusal` says the same
        thing one layer lower down for the write itself.
        """
        return SystemScope.SLOT

    def registry_identifier(self, handle: DeviceHandle) -> tuple[str, str] | None:
        """Return the `zwave_js` device registry identifier for this node.

        The short `<home id>-<node id>` form, which is what `zwave_js`'s own
        `helpers.get_device_id` builds and what Stage 0 item P2 captured off the real
        registry. The longer fingerprint-bearing form is deliberately not used: it changes
        when a node is replaced by a different model, which is the signal FR-S3 wants and
        the last thing an attachment lookup should depend on.

        A handle whose address is not `<home id>:<node id>` gets None rather than a guess.
        Nothing this adapter builds is shaped any other way, so reaching that means a
        handle arrived from a file somebody edited, and a near miss here makes an orphan
        device rather than an error (see `rule_entity`).
        """
        home_id, separator, node_id = handle.protocol_id.partition(":")
        if not separator or not home_id or not node_id:
            return None
        return (UPSTREAM_DOMAIN, f"{home_id}-{node_id}")

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


def _command_class_of(event: Mapping[str, object]) -> int | None:
    """Return the command class of the value a node event is about, if it is about one.

    The event payload is a plain dict the library fills in, so it is read defensively:
    an event shape that changes upstream must make a subscription go quiet, not throw
    inside somebody else's emit loop, where `EventBase.emit` would swallow it.
    """
    command_class = getattr(event.get("value"), "command_class", None)
    return None if command_class is None else int(command_class)


def _node_id_of_event(event: Mapping[str, object]) -> int | None:
    """Return the node a driver event is about, or None when it does not say.

    `Node.receive_event` puts the node object into every event it emits. Read defensively
    all the same: this runs inside somebody else's emit loop, where a raised exception is
    caught and logged as an error nobody asked for.
    """
    node_id = getattr(event.get("node"), "node_id", None)
    return None if node_id is None else int(node_id)


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


def _as_int(value: object) -> int | None:
    """Return this property or property key as a number, or None when it is not one.

    The driver types both as `int | str | None`, and the strings it uses are names rather
    than digits, so anything unparseable is simply not the indicator being looked for.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return None


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
