"""The Zigbee2MQTT adapter: the only module that talks to a real Zigbee network.

Like `backends/zwave.py`, this is meant to be thin. Everything that can be decided without
a broker already lives in `zigbee_protocol.py`, `compiler.py` and `planner.py`, where it is
tested against the Stage 0 G1 capture; what is left here is subscribe, correlate, translate.

Three things it does that nothing else may:

- **It holds the retained bridge state.** Zigbee2MQTT publishes `bridge/devices`,
  `bridge/groups`, `bridge/info` and `bridge/state` as retained topics, so subscribing is
  the whole of the read path: there is nothing to poll and nothing to ask for.
- **It resolves a friendly name at the moment of the request** (E23). Zigbee2MQTT's request
  API addresses devices by friendly name and friendly names are renameable, so a handle
  keyed on one would break silently the first time a user tidied their names. The handle
  holds the IEEE address; the name is looked up here, per request.
- **It correlates a response to its request by `transaction`.** MQTT is fire and forget:
  nothing about a response says which request it answers except the transaction id echoed
  back, and two binds can be in flight at once.

**Every write path here is modelled, not observed.** Stage 0 item G2 was never approved, so
no bind has ever been performed on this network and nothing in the request half of this
module has met hardware. See assumption A2 in `docs/open-items.md` and issue #6. Each write
path says so again where it is.

It takes an `MqttClient` rather than reaching into Home Assistant's `mqtt` integration
itself, for the same reason `zwave.py` takes a driver: the seam is what makes the adapter
testable against `tests/fakes/zigbee.py`, and it is where a second Zigbee2MQTT instance on a
different base topic (E25) is expressed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import logging
from typing import TYPE_CHECKING, Final, Protocol, cast

from custom_components.device_links.backends import zigbee_protocol as zp
from custom_components.device_links.backends.base import BackendDevice, ObservedDevice
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    LinkTarget,
    ObservedLink,
    SettingsAdapter,
    ZigbeeFingerprint,
)

if TYPE_CHECKING:
    from custom_components.device_links.profile_db import ProfileDatabase, ZigbeeProfileEntry

_LOGGER = logging.getLogger(__name__)

# How long a deep read waits for the bridge to republish `bridge/devices` after a write.
# See `async_observed` for what this is really asking and why it is not the same question
# the Z-Wave deep verify asks.
DEFAULT_REFRESH_TIMEOUT: Final = 5.0

# How long `async_start` waits for the retained device list to arrive. A broker delivers a
# retained message immediately on subscribe, so this is a bound on "the topic is not
# retained or the bridge has never published", not on normal operation.
DEFAULT_STARTUP_TIMEOUT: Final = 10.0

# Why a deep read could not confirm anything. Carried into
# `ObservedDevice.deep_verify_skipped_reason`, which the executor turns into the `why`
# placeholder of `verify_not_confirmed`.
SKIPPED_BRIDGE_OFFLINE: Final = "bridge_offline"


class MqttClient(Protocol):
    """The two things this adapter needs from an MQTT connection, and nothing else.

    A Protocol rather than Home Assistant's `mqtt` module, so the adapter can be exercised
    against a fake bridge without a broker, and so the one place that knows how Home
    Assistant subscribes is the place that builds this.
    """

    async def async_publish(self, topic: str, payload: str) -> None:
        """Publish one message."""

    async def async_subscribe(
        self, topic: str, callback: Callable[[str, str], None]
    ) -> Callable[[], None]:
        """Subscribe to a topic filter, returning the unsubscribe callable."""


class ZigbeeBackendError(Exception):
    """The bridge cannot answer, or was asked about something it does not have.

    Raised rather than returned by the read path, exactly as `ZWaveAccessorError` is: a read
    that answered "this device holds nothing" for a device it could not see is how a planner
    comes to remove a whole network.
    """


@dataclass(slots=True)
class _State:
    """What the bridge has told us, as it last told us.

    Held as one object so that a message handler swaps a whole consistent view rather than
    updating three fields that could be read half way through.
    """

    devices: dict[str, zp.Device] = field(default_factory=dict)
    groups: dict[int, zp.Group] = field(default_factory=dict)
    online: bool = False
    coordinator_ieee: str | None = None


class ZigbeeBackend:
    """One Zigbee2MQTT instance, as the `Backend` protocol sees it.

    Constructing it does no I/O. `async_start` subscribes and waits for the retained device
    list, which is the point at which the backend knows the network.
    """

    def __init__(
        self,
        *,
        client: MqttClient,
        base_topic: str = "zigbee2mqtt",
        profiles: ProfileDatabase | None = None,
        refresh_timeout: float = DEFAULT_REFRESH_TIMEOUT,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
    ) -> None:
        """Hold what this adapter needs, and subscribe to nothing yet."""
        self._client = client
        # Never hard coded: the identifier format embeds it, and a second Zigbee2MQTT
        # instance uses a different one (E25).
        self._base = base_topic.rstrip("/")
        self._profiles = profiles
        self._refresh_timeout = refresh_timeout
        self._startup_timeout = startup_timeout

        self._state = _State()
        self._unsubscribes: list[Callable[[], None]] = []
        self._listeners: list[Callable[[str], None]] = []

        # Whether a write of ours has happened that the bridge has not yet republished
        # `bridge/devices` for. What a deep read waits on; see `async_observed`.
        self._awaiting_devices: list[asyncio.Future[None]] = []
        self._devices_stale = False

        # E26 wants a bridge going offline logged once rather than on every read.
        self._reported_offline = False

    # Lifecycle.

    async def async_start(self) -> None:
        """Subscribe to the bridge topics and wait for the retained device list.

        The four state topics are retained, so this is the whole of the read path's
        startup: a broker delivers them on subscribe and the backend knows the network
        without asking anything.
        """
        loop = asyncio.get_running_loop()
        arrived: asyncio.Future[None] = loop.create_future()
        self._awaiting_devices.append(arrived)
        for topic in (
            f"{self._base}/{zp.STATE_TOPIC}",
            f"{self._base}/{zp.GROUPS_TOPIC}",
            f"{self._base}/{zp.DEVICES_TOPIC}",
        ):
            self._unsubscribes.append(await self._client.async_subscribe(topic, self._on_message))
        try:
            async with asyncio.timeout(self._startup_timeout):
                await arrived
        except TimeoutError as err:
            self.async_stop()
            raise ZigbeeBackendError(
                f"{self._base}/{zp.DEVICES_TOPIC} did not arrive within "
                f"{self._startup_timeout}s, so this bridge has never published its devices "
                "or the topic is not retained"
            ) from err

    def async_stop(self) -> None:
        """Drop every subscription, and fail whatever was waiting on a response.

        A pending request left waiting at unload holds a coroutine that will never be
        woken, which is exactly the leak that survives a reload.
        """
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        for waiter in self._awaiting_devices:
            if not waiter.done():
                waiter.cancel()
        self._awaiting_devices.clear()

    # Messages in.

    def _on_message(self, topic: str, payload: str) -> None:
        """Take one message off the broker, defensively.

        Runs inside somebody else's dispatch, so a malformed payload must make this quiet
        rather than raise into the MQTT integration's callback loop.
        """
        relative = topic.removeprefix(f"{self._base}/")
        try:
            parsed = json.loads(payload)
        except ValueError:
            _LOGGER.debug("ignoring an unparseable payload on %s", topic)
            return
        if relative == zp.DEVICES_TOPIC:
            self._on_devices(parsed)
        elif relative == zp.GROUPS_TOPIC:
            self._on_groups(parsed)
        elif relative == zp.STATE_TOPIC:
            self._on_state(parsed)

    def _on_devices(self, parsed: object) -> None:
        """Take a new device list, and tell the coordinator which devices changed.

        A payload that yields no readable device at all is dropped rather than believed.
        There is always at least a coordinator on a Zigbee network, so an empty result means
        the message was not the device list rather than that the network is empty, and
        believing it would drift every device in the house and rewrite the lot on the next
        apply. Same reasoning as E1, one level lower down.
        """
        if not isinstance(parsed, list):
            return
        devices = _as_devices(parsed)
        if not devices:
            _LOGGER.debug(
                "%s/%s carried no readable device, so the last good list is kept",
                self._base,
                zp.DEVICES_TOPIC,
            )
            return
        changed = [
            ieee
            for ieee, device in devices.items()
            if self._state.devices.get(ieee) != device and ieee in self._state.devices
        ]
        self._state.devices = devices
        self._state.coordinator_ieee = next(
            (ieee for ieee, device in devices.items() if zp.is_coordinator(device)), None
        )
        self._devices_stale = False
        for waiter in self._awaiting_devices:
            if not waiter.done():
                waiter.set_result(None)
        self._awaiting_devices.clear()
        for ieee in changed:
            self._notify(f"{BackendId.ZIGBEE2MQTT}:{ieee}")

    def _on_groups(self, parsed: object) -> None:
        """Take a new group list.

        Every group is kept, ours and the user's alike. Reading a foreign group is how a
        colliding name is noticed (E24); it is writing to one that never happens.
        """
        if not isinstance(parsed, list):
            return
        self._state.groups = _as_groups(parsed)

    def _on_state(self, parsed: object) -> None:
        """Follow the bridge up and down, saying so once each way (E26)."""
        state = parsed.get("state") if isinstance(parsed, dict) else None
        online = state == zp.STATE_ONLINE
        if not online and not self._reported_offline:
            _LOGGER.warning(
                "the Zigbee2MQTT bridge on %s reported %s, so its devices are marked "
                "unavailable and their last known state is kept",
                self._base,
                state,
            )
            self._reported_offline = True
        elif online and self._reported_offline:
            _LOGGER.info("the Zigbee2MQTT bridge on %s is answering again", self._base)
            self._reported_offline = False
        self._state.online = online

    def _notify(self, identity: str) -> None:
        """Tell every subscriber that one device is worth re-reading."""
        for listener in list(self._listeners):
            listener(identity)

    # Reading.

    async def async_devices(self) -> list[BackendDevice]:
        """Return every device on this network that a rule could name.

        The coordinator is deliberately left out. It is the radio rather than a device: it
        offers no control a rule could start from and can act on nothing a binding could
        send, so listing it would put an item in the device picker that can do nothing. It
        still gets a handle when a binding points at it, because those bindings are real and
        are what `is_system` is about.

        Raises when the bridge is down, rather than answering with an empty list. E1: a
        backend that cannot answer is not a backend that answered "nothing", and the
        coordinator keeps every device's last known state on the strength of this raise.
        """
        self._require_online()
        return [
            BackendDevice(handle=zp.handle_of(device))
            for device in self._state.devices.values()
            if not zp.is_coordinator(device)
        ]

    async def async_capabilities(self, handle: DeviceHandle) -> DeviceCapabilities:
        """Return what this device can drive and what it can be made to do."""
        device = self._device(handle)
        warnings: list[str] = []
        controls = zp.resolve_controls(device, self._entry_of(device), warnings=warnings)
        for warning in warnings:
            _LOGGER.debug("%s: %s", handle.identity, warning)
        entry = self._entry_of(device)
        return DeviceCapabilities(
            handle=handle,
            emitters=tuple(control.emitter for control in controls),
            receivable=zp.receivable_features(device),
            # Long Range is a Z-Wave inclusion mode and has no Zigbee equivalent, so this
            # is False rather than unknown: nothing about a Zigbee device can make it true.
            is_long_range=False,
            settings=_settings_adapters(entry),
        )

    async def async_observed(self, handle: DeviceHandle, deep: bool = False) -> ObservedDevice:
        """Return the bindings really on this device now.

        `deep` asks a different question here from the one it asks on Z-Wave, and it is
        worth being exact about which. Zigbee2MQTT offers no way to re-read a device's
        binding table on demand: what `bridge/devices` carries is the bridge's own record,
        which it republishes whenever it changes. The bind itself is answered by the device
        (a ZDO Bind Response), so that record is better than a driver cache and is still not
        a fresh read of the hardware.

        So what a deep read waits for is the thing that is actually in doubt: **whether the
        bridge has republished since our last write**. How long that takes was never
        measured, because item G2 was not approved (docs/open-items.md J2), and reading a
        stale device list straight after a bind would report a link that landed as missing.
        A read that got its republish is reported as verified; one that did not is reported
        as timed out, which the executor turns into `unconfirmed` rather than into a
        failure. Neither is dressed up as the other.
        """
        device = self._device(handle)
        verified = False
        timed_out = False
        skipped: str | None = None
        if deep:
            if not self._state.online:
                skipped = SKIPPED_BRIDGE_OFFLINE
            else:
                verified = await self._await_devices()
                timed_out = not verified
                device = self._device(handle)
        return ObservedDevice(
            handle=handle,
            links=tuple(self._observed_links(handle, device)),
            settings=self._settings_of(device),
            deep_verified=verified,
            deep_verify_timed_out=timed_out,
            deep_verify_skipped_reason=skipped,
        )

    async def _await_devices(self) -> bool:
        """Wait for the bridge to republish its devices, if it owes us one.

        Nothing to wait for when no write of ours is outstanding: the retained payload we
        hold is the bridge's current view, and waiting for a message that is not coming
        would spend the whole timeout to learn what is already known.
        """
        if not self._devices_stale:
            return True
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._awaiting_devices.append(waiter)
        try:
            async with asyncio.timeout(self._refresh_timeout):
                await waiter
        except TimeoutError:
            _LOGGER.debug(
                "the bridge on %s did not republish its devices within %ss, so this read may "
                "not yet show the last write",
                self._base,
                self._refresh_timeout,
            )
            return False
        finally:
            if waiter in self._awaiting_devices:
                self._awaiting_devices.remove(waiter)
        return True

    def _observed_links(self, handle: DeviceHandle, device: zp.Device) -> list[ObservedLink]:
        """Turn one device's bindings into the links the planner diffs against.

        One binding becomes **one link per feature its cluster carries**, so a bound
        `genLevelCtrl` produces both a level-set link and a hold-to-dim link. That is what
        the binding really does, and it is what makes a rule asking for both converge: a
        binding reported under one feature only would leave the other permanently missing,
        planned as an add forever, and answered `already_present` forever.

        A binding to a **managed** group is expanded into one link per member, so that a
        one-to-many rule's per-target links match what is on the device. A binding to a
        group that is not ours is reported as a link to the group itself, because that is
        what it is and inventing per-member links for somebody else's group would be
        claiming to know what they meant by it.

        `managed_by` stays None. Only the coordinator knows which profile is active and
        which rule claims which fingerprint, and a guess here is what makes somebody else's
        binding removable.
        """
        return [
            ObservedLink(
                backend=BackendId.ZIGBEE2MQTT,
                source=handle,
                source_endpoint=binding.endpoint,
                emitter_id=self._emitter_id_of(device, binding.endpoint),
                emitter_group=binding.cluster,
                target=LinkTarget(handle=target, endpoint=endpoint),
                feature=feature,
                is_system=self._is_system(binding),
                managed_by=None,
            )
            for binding in zp.parse_bindings(device)
            for target, endpoint in self._targets_of(binding)
            for feature in sorted(zp.features_of_cluster(binding.cluster))
        ]

    def _targets_of(self, binding: zp.ParsedBinding) -> list[tuple[DeviceHandle, int | None]]:
        """Return what a binding really points at, expanding a managed group's membership."""
        if binding.group_id is None:
            return [(self._handle_of_ieee(binding.target_ieee or ""), binding.target_endpoint)]
        group = self._state.groups.get(binding.group_id)
        if group is None:
            # A binding to a group the bridge no longer lists. Reported against a handle for
            # the group rather than dropped, because the entry is on the device: a link that
            # is not reported is a link nobody can plan to remove (E24).
            return [(zp.group_handle(binding.group_id, f"group {binding.group_id}"), None)]
        if not zp.is_managed_group_name(group["friendly_name"]):
            return [(zp.group_handle(binding.group_id, group["friendly_name"]), None)]
        return [
            (self._handle_of_ieee(member["ieee_address"]), member["endpoint"])
            for member in group["members"]
        ]

    def _is_system(self, binding: zp.ParsedBinding) -> bool:
        """Say whether this binding is the bridge's own, which is never ours to remove.

        Every binding on this network today targets the coordinator, and they are what makes
        the devices report at all. Offering one for removal would invite a user to delete
        their own reporting setup, so they are system links exactly as a Z-Wave lifeline is.
        """
        return (
            binding.target_ieee is not None and binding.target_ieee == self._state.coordinator_ieee
        )

    def _emitter_id_of(self, device: zp.Device, endpoint: int) -> str:
        """Return the id of the control that drives from this endpoint.

        Resolved through the same path `async_capabilities` uses, so an observed link names
        the control a rule would name rather than a second spelling of it.
        """
        for control in zp.resolve_controls(device, self._entry_of(device)):
            if control.endpoint == endpoint:
                return control.emitter.emitter_id
        return f"ep{endpoint}"

    # Devices, groups and their identity.

    def _device(self, handle: DeviceHandle) -> zp.Device:
        """Return the device a handle names, or say which one is missing."""
        device = self._state.devices.get(handle.protocol_id)
        if device is None:
            raise ZigbeeBackendError(
                f"{handle.protocol_id} is not a device this Zigbee2MQTT bridge reports"
            )
        return device

    def _handle_of_ieee(self, ieee: str) -> DeviceHandle:
        """Return a handle for an address a binding points at.

        A binding can name a device the bridge no longer lists, and one always does on this
        network: the coordinator, which `async_devices` deliberately leaves out. Such a
        target still needs a handle, because the link it is part of is real.
        """
        device = self._state.devices.get(ieee)
        if device is None:
            return DeviceHandle(
                backend=BackendId.ZIGBEE2MQTT,
                protocol_id=ieee,
                ha_device_id="",
                fingerprint=ZigbeeFingerprint(manufacturer="", model=""),
                name_at_authoring=ieee,
            )
        return zp.handle_of(device)

    def _name_of(self, handle: DeviceHandle) -> str:
        """Return the friendly name this device answers to **right now** (E23).

        Resolved per request rather than taken off the handle, because Zigbee2MQTT's request
        API is addressed by friendly name and the name a rule was written against may be
        several renames old by the time it is applied.
        """
        return str(self._device(handle)["friendly_name"])

    def _entry_of(self, device: zp.Device) -> ZigbeeProfileEntry | None:
        """Return the curated entry for this model, or None when none claims it."""
        if self._profiles is None:
            return None
        return self._profiles.lookup_zigbee(zp.fingerprint_of(device))

    def _require_online(self) -> None:
        """Refuse to answer for a bridge that is down, rather than answering emptily."""
        if not self._state.online:
            raise ZigbeeBackendError(
                f"the Zigbee2MQTT bridge on {self._base} is offline, so its devices cannot be read"
            )

    def _settings_of(self, device: zp.Device) -> dict[str, int]:
        """Return the settings this device has reported, of the ones the profile knows.

        Empty for now: the settings a Zigbee device reports arrive on its own state topic
        rather than on `bridge/devices`, and this adapter subscribes only to the bridge
        topics. See `async_read_setting`, and docs/open-items.md T45.
        """
        return {}

    # Change subscriptions.

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """Call `callback` with a device identity whenever that device's state changes.

        No debounce, unlike the Z-Wave adapter, and for a reason rather than an omission:
        `bridge/devices` arrives as one whole message describing every device, so a change
        to any number of devices is already one message and the burst a debounce exists to
        swallow cannot happen. What is filtered instead is devices that did not change,
        because the bridge republishes the whole list whenever any part of it moves.
        """
        self._listeners.append(callback)

        def _unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return _unsubscribe

    def wake_instructions(self, handle: DeviceHandle) -> str | None:
        """Return how a user wakes this device, or None when it is always listening."""
        try:
            device = self._device(handle)
        except ZigbeeBackendError:
            return None
        entry = self._entry_of(device)
        return None if entry is None else entry.wake_instruction


def _as_devices(parsed: Sequence[object]) -> dict[str, zp.Device]:
    """Narrow the `bridge/devices` payload into the shape the pure module reads.

    This is the boundary between untrusted JSON off a broker and the TypedDicts everything
    downstream is written against, so it is where the keys those types require are actually
    checked. An entry missing one is dropped rather than repaired: a device with no address
    or no endpoints cannot be addressed, and inventing the missing half would put a device
    in the picker that no request could name.
    """
    devices: dict[str, zp.Device] = {}
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        if not _has_all(raw, ("ieee_address", "friendly_name", "type", "endpoints")):
            continue
        device = cast("zp.Device", raw)
        devices[device["ieee_address"]] = device
    return devices


def _as_groups(parsed: Sequence[object]) -> dict[int, zp.Group]:
    """Narrow the `bridge/groups` payload the same way."""
    groups: dict[int, zp.Group] = {}
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        if not _has_all(raw, ("id", "friendly_name", "members")):
            continue
        group = cast("zp.Group", raw)
        groups[int(group["id"])] = group
    return groups


def _has_all(raw: Mapping[str, object], keys: Sequence[str]) -> bool:
    """Say whether a payload carries every key the type it is about to become requires."""
    return all(key in raw for key in keys)


def _settings_adapters(entry: ZigbeeProfileEntry | None) -> dict[str, SettingsAdapter]:
    """Return a Zigbee entry's settings in the protocol-neutral shape the compiler reads.

    `parameter` is 0 and `bitmask` is None, because a Zigbee setting is addressed by name
    and there is no number to report. Reporting a plausible-looking number would be worse
    than reporting none: a diagnostic would then name a parameter nobody could look up.
    """
    if entry is None:
        return {}
    return {
        capability: SettingsAdapter(parameter=0, bitmask=None, values=adapter.values)
        for capability, adapter in entry.settings.items()
    }


__all__ = ["MqttClient", "ZigbeeBackend", "ZigbeeBackendError"]
