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
from dataclasses import dataclass, field, replace
from itertools import count
import json
import logging
from typing import TYPE_CHECKING, Final, Protocol, cast

from custom_components.device_links.backends import zigbee_protocol as zp
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
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Diagnostic,
    Link,
    LinkTarget,
    ObservedLink,
    SettingsAdapter,
    ZigbeeFingerprint,
)

if TYPE_CHECKING:
    from custom_components.device_links.profile_db import ProfileDatabase, ZigbeeProfileEntry

_LOGGER = logging.getLogger(__name__)

# How long a request waits for the response that carries its transaction id.
#
# Deliberately under the executor's own 30 second `OPERATION_TIMEOUT_SECONDS`, and that is
# the whole reason for the number rather than a round 30. Both bound the same wait, and
# whichever fires first decides what the user is told: this one knows the request was a
# Zigbee bind that got no answer and can say so, and the executor's knows only that a
# backend did not return in time. Two 30 second timers would pick between those two
# messages at random.
DEFAULT_REQUEST_TIMEOUT: Final = 20.0

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

# What Zigbee2MQTT reports as the power source of a battery device. A bind can only be made
# while such a device is awake, so a refusal or a silence from one is a wake-up prompt
# rather than a fault (E22).
BATTERY_POWER_SOURCE: Final = "Battery"


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
class _Pending:
    """One request waiting for the response that carries its transaction id."""

    future: asyncio.Future[zp.BridgeResponse]


@dataclass(slots=True)
class _State:
    """What the bridge has told us, as it last told us.

    Held as one object so that a message handler swaps a whole consistent view rather than
    updating three fields that could be read half way through.
    """

    devices: dict[str, zp.Device] = field(default_factory=dict)
    groups: dict[int, zp.Group] = field(default_factory=dict)
    online: bool = False

    # The coordinator's address as `bridge/info` reported it, which is authoritative, and
    # as the device listing implies it, which is the fallback. Kept apart so that a listing
    # arriving without a coordinator cannot unset an address the bridge actually told us.
    reported_coordinator: str | None = None
    listed_coordinator: str | None = None

    # The Zigbee2MQTT version, as `bridge/info` last reported it. Kept live rather than read
    # once, because upgrading the add-on republishes it and never reloads this integration.
    version: str | None = None

    @property
    def coordinator_ieee(self) -> str | None:
        """Return the coordinator's address, from whichever source has one."""
        return self.reported_coordinator or self.listed_coordinator


class ZigbeeBackend:
    """One Zigbee2MQTT instance, as the `Backend` protocol sees it.

    Constructing it does no I/O. `async_start` subscribes and waits for the retained device
    list, which is the point at which the backend knows the network.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        client: MqttClient,
        base_topic: str = "zigbee2mqtt",
        profiles: ProfileDatabase | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        refresh_timeout: float = DEFAULT_REFRESH_TIMEOUT,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
    ) -> None:
        """Hold what this adapter needs, and subscribe to nothing yet."""
        self._client = client
        # Never hard coded: the identifier format embeds it, and a second Zigbee2MQTT
        # instance uses a different one (E25).
        self._base = base_topic.rstrip("/")
        self._profiles = profiles
        self._request_timeout = request_timeout
        self._refresh_timeout = refresh_timeout
        self._startup_timeout = startup_timeout

        self._state = _State()
        self._pending: dict[str, _Pending] = {}
        self._unsubscribes: list[Callable[[], None]] = []
        self._listeners: list[Callable[[str], None]] = []
        self._transactions = count(1)

        # Managed groups this backend has created or already adopted, so E24's warning about
        # using a group somebody else made is said once and never about one of our own.
        self._created: set[str] = set()

        # Whoever is waiting for the retained device list to arrive, which is only ever
        # `async_start`: it has to be the device list specifically, because a backend that
        # came up on the strength of the group list would come up knowing no devices.
        self._awaiting_devices: list[asyncio.Future[None]] = []

        # Whether a write of ours has happened that the bridge has not yet republished
        # anything for. What a deep read waits on; see `async_observed`. **Either** retained
        # topic answers it, because either can be what a write of ours changed: a bind
        # republishes `bridge/devices` and a membership change republishes `bridge/groups`,
        # and a managed group's membership is half of what an observed link is made of.
        self._awaiting_state: list[asyncio.Future[None]] = []
        self._state_stale = False

        # E26 wants a bridge going offline logged once rather than on every read.
        self._reported_offline = False

    # Lifecycle.

    async def async_start(self) -> None:
        """Subscribe to the bridge topics and wait for the retained device list.

        The four state topics are retained, so this is the whole of the read path's
        startup: a broker delivers them on subscribe and the backend knows the network
        without asking anything. The response topics are subscribed to first, so a response
        can never arrive before there is something listening for it.

        **Nothing is left subscribed by a start that did not finish.** A broker that accepts
        two subscriptions and refuses the third leaves the two behind for the life of the
        process otherwise, and a caller that treats a failed start as "no backend" has no
        object left to stop.
        """
        loop = asyncio.get_running_loop()
        arrived: asyncio.Future[None] = loop.create_future()
        self._awaiting_devices.append(arrived)
        try:
            for topic in (
                f"{self._base}/bridge/response/#",
                f"{self._base}/{zp.STATE_TOPIC}",
                f"{self._base}/{zp.INFO_TOPIC}",
                f"{self._base}/{zp.GROUPS_TOPIC}",
                f"{self._base}/{zp.DEVICES_TOPIC}",
            ):
                self._unsubscribes.append(
                    await self._client.async_subscribe(topic, self._on_message)
                )
            async with asyncio.timeout(self._startup_timeout):
                await arrived
        except TimeoutError as err:
            self.async_stop()
            raise ZigbeeBackendError(
                f"{self._base}/{zp.DEVICES_TOPIC} did not arrive within "
                f"{self._startup_timeout}s, so this bridge has never published its devices "
                "or the topic is not retained"
            ) from err
        except BaseException:
            # Whatever an MQTT client raises when it will not take a subscription, plus a
            # cancellation from a config entry setup being abandoned. Re-raised rather than
            # translated: the caller decides what a broker that would not answer means.
            self.async_stop()
            raise

    def async_stop(self) -> None:
        """Drop every subscription, and fail whatever was waiting on a response.

        A pending request left waiting at unload holds a coroutine that will never be
        woken, which is exactly the leak that survives a reload.
        """
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()
        for waiting in (self._awaiting_devices, self._awaiting_state):
            for waiter in waiting:
                if not waiter.done():
                    waiter.cancel()
            waiting.clear()

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
        elif relative == zp.INFO_TOPIC:
            self._on_info(parsed)
        elif relative == zp.STATE_TOPIC:
            self._on_state(parsed)
        elif relative.startswith("bridge/response/"):
            self._on_response(parsed)

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
        listed = next((ieee for ieee, device in devices.items() if zp.is_coordinator(device)), None)
        if listed is None and self._state.coordinator_ieee is None:
            # The one classification that must not fail open. Without a coordinator address
            # every reporting binding on the network stops being a system link and is
            # offered to the user as something they could remove, which is the thing that
            # makes their devices report at all.
            _LOGGER.warning(
                "no coordinator is reported on %s, so bindings to it cannot be told apart "
                "from a user's own and are reported as unmanaged rather than as system links",
                self._base,
            )
        self._state.listed_coordinator = listed
        self._state_arrived(self._awaiting_devices)
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
        self._state_arrived([])

    def _on_info(self, parsed: object) -> None:
        """Take the bridge's own description of itself, for the coordinator's address.

        The authoritative source: `bridge/info` names the coordinator outright, where the
        device listing only implies it through a `type` string that is Zigbee2MQTT's to
        change. Read but never required, because a bridge that has not published it yet
        still has a device listing to fall back on.
        """
        if not isinstance(parsed, dict):
            return
        address = zp.coordinator_address(parsed)
        if address is not None:
            self._state.reported_coordinator = address
        version = zp.bridge_version(parsed)
        if version is not None:
            self._state.version = version

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

    def _on_response(self, parsed: object) -> None:
        """Hand a response to whatever asked for it, matching on the transaction id.

        MQTT is fire and forget and responses are not ordered, so the echoed transaction is
        the only thing that says which request a response answers. A response for a
        transaction nobody is waiting on is dropped: it belongs to another client of the
        same broker, or to a request of ours that has already timed out.
        """
        if not isinstance(parsed, dict):
            return
        response = zp.parse_response(parsed)
        if response.transaction is None:
            return
        pending = self._pending.pop(response.transaction, None)
        if pending is not None and not pending.future.done():
            pending.future.set_result(response)

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
        emitters = zp.resolve_emitters(device, self._entry_of(device), warnings=warnings)
        for warning in warnings:
            _LOGGER.debug("%s: %s", handle.identity, warning)
        entry = self._entry_of(device)
        return DeviceCapabilities(
            handle=handle,
            emitters=tuple(emitters),
            receivable=zp.receivable_features(device),
            # Long Range is a Z-Wave inclusion mode and has no Zigbee equivalent, so this
            # is False rather than unknown: nothing about a Zigbee device can make it true.
            is_long_range=False,
            settings=_settings_adapters(entry),
            # A Zigbee binding always names a target endpoint, so a link that reaches this
            # device has to have one even where nobody was asked which. See T48.
            receiving_endpoint=zp.receiving_endpoint(device),
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
                verified = await self._await_state()
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

    def _state_arrived(self, also: list[asyncio.Future[None]]) -> None:
        """Note that the bridge has republished, and wake whatever was waiting for it."""
        self._state_stale = False
        for waiting in (self._awaiting_state, also):
            for waiter in waiting:
                if not waiter.done():
                    waiter.set_result(None)
            waiting.clear()

    async def _await_state(self) -> bool:
        """Wait for the bridge to republish, if it owes us a republish.

        Nothing to wait for when no write of ours is outstanding: the retained payload we
        hold is the bridge's current view, and waiting for a message that is not coming
        would spend the whole timeout to learn what is already known.

        A wait that times out lowers the flag on its way out, which is the difference
        between one slow read and every read afterwards being slow. What the flag means is
        "we are still expecting a republish", and once we have stopped expecting it we are
        not: the next read's claim is only ever that this is the bridge's current view, and
        after giving up that is as true as it will get. Reporting the read that waited as
        unconfirmed is the whole of what is owed to the user.
        """
        if not self._state_stale:
            return True
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._awaiting_state.append(waiter)
        try:
            async with asyncio.timeout(self._refresh_timeout):
                await waiter
        except TimeoutError:
            _LOGGER.debug(
                "the bridge on %s did not republish within %ss, so this read may not yet "
                "show the last write",
                self._base,
                self._refresh_timeout,
            )
            self._state_stale = False
            return False
        finally:
            if waiter in self._awaiting_state:
                self._awaiting_state.remove(waiter)
        return True

    def _observed_links(self, handle: DeviceHandle, device: zp.Device) -> list[ObservedLink]:
        """Turn one device's bindings into the links the planner diffs against.

        One binding becomes **one link per feature its cluster carries**, so a bound
        `genLevelCtrl` produces both a level-set link and a hold-to-dim link, and a binding
        on a cluster Device Links cannot drive still produces one link that reports rather
        than controls, so a device's binding table is described whole. That is what
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
            for feature in sorted(zp.features_of_binding(binding.cluster))
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
        if not zp.is_managed_group_name(group["friendly_name"]) or not group["members"]:
            # A group that is not ours, or one of ours with nothing in it. Either way there
            # is no membership to expand, and the entry is still on the device: a binding
            # that produces no link at all is device state nothing in the product can see,
            # list as unmanaged, or plan to remove (E24).
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
        for emitter in zp.resolve_emitters(device, self._entry_of(device)):
            if emitter.endpoint == endpoint:
                return emitter.emitter_id
        return f"ep{endpoint}"

    # Writing, and the refusals that come before it.
    #
    # NOTE: everything from here to the end of this section is modelled from the
    # Zigbee2MQTT documentation and has never been performed against hardware. Stage 0
    # item G2 was never approved, so no Zigbee bind has ever been made on this network:
    # the request shapes, the response shapes and the failure modes are all taken from
    # the documentation, and `tests/fakes/zigbee.py` is the model they are proved against
    # rather than evidence about the bridge. See assumption A2 in docs/open-items.md and
    # issue #6. When G2 runs, this is what gets corrected.

    async def async_check_link(self, link: Link) -> LinkCheck:
        """Say whether this link could be written, without writing it.

        Zigbee has no equivalent of the Z-Wave driver's `checkAssociation`: there is no
        request that asks the bridge whether a bind would be allowed. So a check here is
        everything that can be answered from what the bridge already publishes, which turns
        out to be most of it and costs nothing at all: the coordinator's address, every
        device the bridge knows, and every endpoint's input and output clusters are all in
        the retained `bridge/devices` payload.

        The panel's blocked-with-reason experience is therefore not worse for Zigbee than
        for Z-Wave. It is arguably better: the Z-Wave check spends a radio round trip and
        can still be answered by a mesh that is busy, and this one is a lookup.

        What it deliberately does not answer is whether the link is already there. A check
        says whether a write could be made, and an existing binding does not change that.
        """
        refusal = self._refusal(link, adding=True)
        if refusal is not None:
            return LinkCheck(ok=False, reason=refusal)
        return LinkCheck(ok=True)

    async def async_add_link(self, link: Link) -> LinkResult:
        """Bind one cluster, or explain why it was not bound.

        The order of the refusals is the safety rule, and it is this and no other:

        1. A coordinator binding, because it is never ours to write whatever else is true.
           This is Zigbee's lifeline: those bindings are Zigbee2MQTT's own reporting setup,
           and every binding on this network today is one.
        2. A self-binding, for the same reason: it can never be what the user meant, so
           nothing about the bridge's current state can make it right.
        3. A target endpoint that is not named. A Zigbee binding always names one, so a
           link that does not is not a link that can be expressed.
        4. The bridge being offline, which is not about this link at all but means nothing
           can be written now.
        5. A device or group the bridge does not report.
        6. Already present, which is where a state-dependent answer belongs. After the
           absolute refusals so neither can be masked by "it is already there", and before
           the capability checks so that an entry which exists is never reported as blocked:
           a firmware upgrade can change what a device says it drives, and answering BLOCKED
           for an entry that is on the device makes a plan that can never converge.
        7. Whether the source really drives the cluster and the target really serves it.
           Only when adding: a check about writing has nothing to say about taking an entry
           off, and refusing there would strand a binding nobody could remove.
        8. The request.

        NOTE: modelled from the Zigbee2MQTT documentation, never observed. Assumption A2,
        issue #6.
        """
        return await self._write(link, adding=True)

    async def async_remove_link(self, link: Link) -> LinkResult:
        """Unbind one cluster, or explain why it was not unbound.

        The same shape as the add, without step 7. Not present is `ALREADY_PRESENT`: there
        is nothing to do and nothing went wrong.

        **Unbinding removes the attribute reporting Zigbee2MQTT configured on that cluster**
        unless `skip_disable_reporting` is set (CLAUDE.md Section 10). Device Links does not
        set it, so what happens is what the bridge would do on its own rather than a quiet
        divergence, and the plan says so before a user confirms it.

        NOTE: modelled from the Zigbee2MQTT documentation, never observed. Assumption A2,
        issue #6.
        """
        return await self._write(link, adding=False)

    async def _write(self, link: Link, *, adding: bool) -> LinkResult:
        """Bind or unbind one cluster, refusing in the documented order.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        refusal = self._absolute_refusal(link)
        if refusal is not None:
            return LinkResult(status=LinkResultStatus.BLOCKED, reason=refusal)
        # Nothing below re-checks that the source and the target exist, because the refusal
        # above did: it is the step that answers `zigbee_unknown_device`, and a second
        # answer to the same question here would be a branch no test could reach and no
        # reader could trust.
        present = self._is_present(link)
        if present is adding:
            return LinkResult(status=LinkResultStatus.ALREADY_PRESENT)
        if not adding:
            return await self._unbind(link)
        refusal = self._capability_refusal(link)
        if refusal is not None:
            return LinkResult(status=LinkResultStatus.BLOCKED, reason=refusal)
        return await self._bind(link)

    # Managed groups (Decision D5).
    #
    # Unicast to several targets sends the command once per target, sequentially, and fills
    # the source's binding table, so a one-to-many rule goes through one managed Zigbee
    # group instead. Three rules decide the shape of everything below:
    #
    # 1. **A group is created only when a control already drives something else.** The first
    #    target of a rule is a plain binding, because a group per rule would fill a user's
    #    Zigbee2MQTT with entries that buy them nothing, and unicast to one target is the
    #    better write anyway.
    # 2. **Nothing that is already on the device is moved into a group.** The obvious design
    #    is to migrate the first target into the group when the second arrives, and it is
    #    wrong: this adapter cannot tell a binding a rule of ours wrote from one the user
    #    made by hand in Zigbee2MQTT years ago (ownership lives in the coordinator, by
    #    fingerprint), so migrating would eventually swallow somebody's own binding and
    #    delete it when the rule went. So the first target stays a plain binding and the
    #    rest go through the group: two binding table entries for any number of targets,
    #    and never a write to an entry that might not be ours.
    # 3. **A group without the `dl_` prefix is never created, never read for membership and
    #    never deleted.** The prefix is the only thing that says which groups are ours, and
    #    `zigbee_protocol` raises `ForeignGroupError` from the payload builders themselves,
    #    so nothing here can route around it.
    #
    # What is missing, and is not missing by accident: nothing drives the lifecycle of a
    # group whose rule was deleted while Home Assistant was down. The `Backend` protocol
    # writes one link at a time and never sees a rule, so this layer cannot know a rule has
    # stopped existing. `async_drop_managed_group` and `managed_group_rule_ids` are the two
    # halves of the answer for whoever does know; wiring them up is a deliberate decision
    # about the protocol rather than a quiet special case. See docs/open-items.md T41.

    async def _bind(self, link: Link) -> LinkResult:
        """Write one binding, through this rule's managed group when the rule needs one."""
        group_name = self._group_for(link)
        if group_name is None:
            return await self._request_binding(link, adding=True)
        return await self._bind_through_group(link, group_name)

    async def _unbind(self, link: Link) -> LinkResult:
        """Take one binding off, whether it is a plain binding or a group membership."""
        if zp.group_id_of(link.target.handle) is not None or self._plain_binding(link) is not None:
            # A link that names a group is one binding and comes off as one, membership
            # untouched: what it asked for was the group, so the group is what goes. A link
            # that names a device and has a plain binding comes off the same way.
            return await self._request_binding(link, adding=False)
        group = self._group_holding(link)
        if group is None:
            # `_write` reached here because something on the device answers to this link,
            # and neither a plain binding nor a group membership does. Presence and removal
            # ask that question two different ways (fingerprints over the observed links,
            # and the bindings themselves), so a disagreement between them lands here.
            #
            # Reported rather than asserted, and this was an `assert` until a review pointed
            # out that whole-dict comparison of a group member made the two disagree the
            # moment Zigbee2MQTT added a field to one. An adapter that raises breaks the
            # `Backend` contract and takes the rest of the job's report with it, which is a
            # worse answer to a disagreement than one failed link.
            _LOGGER.debug(
                "%s reads as present and matches neither a plain binding nor a group",
                link.fingerprint,
            )
            return LinkResult(
                status=LinkResultStatus.FAILED,
                reason=Diagnostic("zigbee_bind_failed", _binding_placeholders(link)),
            )
        return await self._unbind_through_group(link, group)

    def _group_for(self, link: Link) -> str | None:
        """Return the managed group this link should go through, or None for a plain bind.

        None when the link has no rule (a raw service call owns no group), when it already
        names a group as its target, or when this control drives nothing else yet.
        """
        if link.rule_id is None or zp.group_id_of(link.target.handle) is not None:
            return None
        name = zp.managed_group_name(link.rule_id)
        if self._group_binding(link, name) is not None:
            return name
        return name if self._peer_bindings(link) else None

    async def _bind_through_group(self, link: Link, name: str) -> LinkResult:
        """Put this link's target into the rule's group, and bind the group if it is not.

        The order matters: the member goes in before the group is bound, so a failure
        half way leaves a group that drives nothing rather than a group binding that drives
        an empty group. The first is inert; the second is a control that does nothing and
        looks connected.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        group_id = await self._ensure_group(name)
        if group_id is None:
            return self._group_failure(link, name)
        member = self._member_payload(link, name)
        if member is None or not await self._group_request(zp.GROUP_MEMBER_ADD_REQUEST, member):
            return self._group_failure(link, name)
        if self._group_binding(link, name) is not None:
            return LinkResult(status=LinkResultStatus.APPLIED)
        return await self._request_binding(_to_group(link, group_id, name), adding=True)

    async def _unbind_through_group(self, link: Link, group: zp.Group) -> LinkResult:
        """Take this link's target out of the rule's group, and drop the group when it empties.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        name = str(group["friendly_name"])
        member = self._member_payload(link, name)
        if member is None or not await self._group_request(zp.GROUP_MEMBER_REMOVE_REQUEST, member):
            return self._group_failure(link, name)
        remaining = self._state.groups.get(int(group["id"]))
        if remaining is not None and remaining["members"]:
            return LinkResult(status=LinkResultStatus.APPLIED)
        if not await self._remove_group(name):
            return self._group_failure(link, name)
        return LinkResult(status=LinkResultStatus.APPLIED)

    def _member_payload(self, link: Link, name: str) -> dict[str, object] | None:
        """Return the request that puts this link's target in or out of a managed group.

        None when the link names no target endpoint. `_absolute_refusal` has already
        refused one of those, so this cannot happen from `_write`; what it must not do if
        it ever can is choose an endpoint, because a guessed endpoint is a binding to
        something the user did not ask for and the rest of this module refuses to guess.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        if link.target.endpoint is None:
            return None
        target = self._device(link.target.handle)
        return zp.group_member_payload(
            friendly_name=name,
            device_name=str(target["friendly_name"]),
            endpoint=link.target.endpoint,
            transaction=self._next_transaction(),
        )

    async def _ensure_group(self, name: str) -> int | None:
        """Return this managed group's id, creating it if the bridge does not have it.

        E24: a managed group somebody deleted in Zigbee2MQTT is put back on the next apply.
        A group with this name that we did not create is **adopted rather than taken over**:
        the `dl_` prefix is the only thing that says a group is ours, so a name carrying it
        is ours by the only test there is, and what is said about it is a warning rather
        than a refusal. Nothing about its existing membership is disturbed, here or
        anywhere: only the one member a link names is ever added or removed.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        _refuse_foreign(name)
        existing = self._group_named(name)
        if existing is not None:
            if name not in self._created:
                self._created.add(name)
                _LOGGER.warning(
                    "the Zigbee group %s already existed on %s and was not created by this "
                    "session, so it is being used as it is: its other members are left alone",
                    name,
                    self._base,
                )
            return int(existing["id"])
        created = await self._create_group(name)
        if created is None:
            return None
        self._created.add(name)
        return created

    async def _create_group(self, name: str) -> int | None:
        """Create one managed group and return the id the bridge allocated, or None.

        The id comes out of the response rather than from `bridge/groups` afterwards. Which
        of the two arrives first was never measured, because item G2 was not approved, and
        reading the id from the retained topic would report a group that was created as a
        failure whenever the answer beat the republish.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        _refuse_foreign(name)
        response = await self._request(
            zp.GROUP_ADD_REQUEST,
            zp.group_add_payload(friendly_name=name, transaction=self._next_transaction()),
        )
        self._state_stale = True
        if response is None or not response.succeeded:
            _LOGGER.debug("the group %s was not created: %s", name, response)
            return None
        if response.group_id is not None:
            return response.group_id
        made = self._group_named(name)
        return None if made is None else int(made["id"])

    async def _remove_group(self, name: str) -> bool:
        """Delete one managed group, and say whether the bridge accepted it.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        _refuse_foreign(name)
        self._created.discard(name)
        return await self._group_request(
            zp.GROUP_REMOVE_REQUEST,
            zp.group_remove_payload(friendly_name=name, transaction=self._next_transaction()),
        )

    async def async_drop_managed_group(self, rule_id: str) -> bool:
        """Delete the managed group belonging to one rule, and say whether there was one.

        The answer to "a rule was deleted while Home Assistant was down". Deleting the group
        drops every binding that pointed at it, which is what makes it a whole answer rather
        than half of one.

        Nothing in core calls this: the `Backend` protocol writes one link at a time and
        never sees a rule, so this layer cannot know a rule has stopped existing. It is here
        so that whoever does know has something to call. See docs/open-items.md T41.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        name = zp.managed_group_name(rule_id)
        if self._group_named(name) is None:
            return False
        self._state_stale = True
        return await self._remove_group(name)

    def managed_group_rule_ids(self) -> frozenset[str]:
        """Return the rule ids the managed groups on this bridge belong to.

        Groups without the `dl_` prefix are not listed, because they are not ours and
        knowing about them is the first step to acting on them.
        """
        return frozenset(
            str(group["friendly_name"]).removeprefix(zp.MANAGED_GROUP_PREFIX)
            for group in self._state.groups.values()
            if zp.is_managed_group_name(str(group["friendly_name"]))
        )

    async def _group_request(self, topic: str, payload: Mapping[str, object]) -> bool:
        """Send one group request and say whether the bridge carried it out.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        self._state_stale = True
        response = await self._request(topic, payload)
        if response is None or not response.succeeded:
            _LOGGER.debug("group request on %s was not carried out: %s", topic, response)
            return False
        return True

    def _group_failure(self, link: Link, name: str) -> LinkResult:
        """Report a link that could not be written because its group could not be managed."""
        return LinkResult(
            status=LinkResultStatus.FAILED,
            reason=Diagnostic(
                "zigbee_group_failed", {**_binding_placeholders(link), "group": name}
            ),
        )

    def _group_named(self, name: str) -> zp.Group | None:
        """Return one group by friendly name, or None when the bridge does not list it."""
        return next(
            (group for group in self._state.groups.values() if str(group["friendly_name"]) == name),
            None,
        )

    def _bindings_from(self, link: Link) -> list[zp.ParsedBinding]:
        """Return every binding written from this link's source endpoint and cluster."""
        source = self._device(link.source)
        return [
            binding
            for binding in zp.parse_bindings(source)
            if binding.endpoint == link.source_endpoint and binding.cluster == link.emitter_group
        ]

    def _peer_bindings(self, link: Link) -> list[zp.ParsedBinding]:
        """Return the plain bindings this control already drives, the bridge's own aside.

        The coordinator bindings are Zigbee2MQTT's reporting setup rather than anything a
        user asked for, so a control whose only other binding is one of those is a control
        that drives nothing and needs no group.
        """
        return [
            binding
            for binding in self._bindings_from(link)
            if binding.group_id is None and binding.target_ieee != self._state.coordinator_ieee
        ]

    def _plain_binding(self, link: Link) -> zp.ParsedBinding | None:
        """Return the plain binding that expresses this link, if there is one."""
        return next(
            (
                binding
                for binding in self._bindings_from(link)
                if binding.target_ieee == link.target.handle.protocol_id
                and binding.target_endpoint == link.target.endpoint
            ),
            None,
        )

    def _group_binding(self, link: Link, name: str) -> zp.ParsedBinding | None:
        """Return this control's binding to the named managed group, if there is one."""
        group = self._group_named(name)
        if group is None:
            return None
        return next(
            (
                binding
                for binding in self._bindings_from(link)
                if binding.group_id == int(group["id"])
            ),
            None,
        )

    def _group_holding(self, link: Link) -> zp.Group | None:
        """Return the managed group this control is bound to that holds this link's target."""
        member = (link.target.handle.protocol_id, link.target.endpoint)
        for binding in self._bindings_from(link):
            if binding.group_id is None:
                continue
            group = self._state.groups.get(binding.group_id)
            if group is None or not zp.is_managed_group_name(str(group["friendly_name"])):
                continue
            if any(_member_of(entry) == member for entry in group["members"]):
                return group
        return None

    async def _request_binding(self, link: Link, *, adding: bool) -> LinkResult:
        """Send one bind or unbind and turn the answer into a result.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        request = self._bind_request(link)
        payload = zp.bind_payload(request) if adding else zp.unbind_payload(request)
        topic = zp.BIND_REQUEST if adding else zp.UNBIND_REQUEST
        # Set before publishing rather than after, because the bridge republishes
        # `bridge/devices` before it answers: a flag raised afterwards would be raised
        # after the message that lowers it and would never come down.
        self._state_stale = True
        response = await self._request(topic, payload)
        if response is None:
            return self._no_response(link)
        if response.succeeded:
            return LinkResult(status=LinkResultStatus.APPLIED)
        if response.partly_failed:
            # The whole reason `BridgeResponse.succeeded` exists. `status` is `error` only
            # when every cluster failed, so a cluster named in `failed` under `status: "ok"`
            # is a bind that did not happen and would otherwise be reported as applied.
            return self._cluster_failure(link, response)
        # Anything else, `status: "error"` and any answer this version does not recognise
        # alike, is a failure. Failing closed on an unknown status matters as much here as
        # it does for the Z-Wave check result: nothing is written on an answer we cannot read.
        return self._bind_error(link, response)

    def _no_response(self, link: Link) -> LinkResult:
        """Report a request that got no answer, without claiming to know what happened.

        MQTT is fire and forget, so silence has several causes: the bridge is down, the
        device was not listening, or the response was lost. None of them is "the binding
        was not made", and saying so would be a claim nobody can support.

        There is no `LinkResultStatus` for "we do not know", and inventing a sixth member
        would change what every consumer of a job summary switches on, so this is `FAILED`
        with a reason that says exactly what is and is not known. The job's own re-read is
        what settles it: if the bind did land, the next plan is empty. A battery source
        gets `PENDING_WAKEUP` instead, because for one of those silence has a likely cause
        and an action attached to it (E22).
        """
        if self._is_battery(link.source):
            return self._pending_wakeup(link)
        return LinkResult(
            status=LinkResultStatus.FAILED,
            reason=Diagnostic(
                "zigbee_no_response",
                {**_binding_placeholders(link), "seconds": str(self._request_timeout)},
            ),
        )

    def _cluster_failure(self, link: Link, response: zp.BridgeResponse) -> LinkResult:
        """Report the clusters that did not bind, by name."""
        self._settle_stale(response)
        return LinkResult(
            status=LinkResultStatus.FAILED,
            reason=Diagnostic(
                "zigbee_clusters_failed",
                {**_binding_placeholders(link), "clusters": ", ".join(response.failed)},
            ),
            raw_error=response.error,
        )

    def _bind_error(self, link: Link, response: zp.BridgeResponse) -> LinkResult:
        """Report a request the bridge refused outright."""
        self._settle_stale(response)
        if self._is_battery(link.source):
            return self._pending_wakeup(link)
        return LinkResult(
            status=LinkResultStatus.FAILED,
            reason=Diagnostic("zigbee_bind_failed", _binding_placeholders(link)),
            raw_error=response.error,
        )

    def _pending_wakeup(self, link: Link) -> LinkResult:
        """Report a battery source that was not listening (E22).

        Not a failure and not a success: the write has not happened and nothing has gone
        wrong. `pending_wakeup` is what the rest of the system already means by that, and
        the Repairs issue built on it is what asks this adapter for the wake instruction.
        """
        return LinkResult(
            status=LinkResultStatus.PENDING_WAKEUP,
            reason=Diagnostic("zigbee_wake_the_device", _binding_placeholders(link)),
        )

    def _settle_stale(self, response: zp.BridgeResponse) -> None:
        """Lower the stale flag when the bridge has said it changed nothing.

        A bridge that answered and wrote nothing has nothing to republish, so a later deep
        read must not spend its whole timeout waiting for a message that is not coming. A
        request that got no answer at all leaves the flag up, deliberately: that is the case
        where the write may have landed and the read really should wait, once.
        """
        if not response.written:
            self._state_stale = False

    async def _request(self, topic: str, payload: Mapping[str, object]) -> zp.BridgeResponse | None:
        """Publish one request and wait for the response carrying its transaction id.

        Registered before publishing, not after: the bridge can answer immediately, and a
        waiter set up afterwards would miss the answer to its own request and time out.

        None means "no answer", and both ways of getting there mean the same thing to the
        caller: the response never came, or the broker would not take the request. A
        `CancelledError` is different and is left to propagate, because the only thing that
        raises one here is `async_stop` during a config entry unload, and reporting a
        teardown as a link that failed would put a fault in the job log for a shutdown.

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        transaction = str(payload["transaction"])
        future: asyncio.Future[zp.BridgeResponse] = asyncio.get_running_loop().create_future()
        self._pending[transaction] = _Pending(future)
        try:
            await self._client.async_publish(f"{self._base}/{topic}", json.dumps(payload))
            async with asyncio.timeout(self._request_timeout):
                return await future
        except TimeoutError:
            _LOGGER.debug(
                "no response to %s on %s within %ss, so whether it was carried out is unknown",
                transaction,
                topic,
                self._request_timeout,
            )
            return None
        except asyncio.CancelledError:
            raise
        except Exception as err:  # an MQTT client may raise anything its broker raises
            _LOGGER.debug("publishing %s on %s failed: %s", transaction, topic, err)
            return None
        finally:
            self._pending.pop(transaction, None)

    def _bind_request(self, link: Link) -> zp.BindRequest:
        """Return the request that expresses this link, addressed as the bridge expects.

        Exactly one cluster, and never the "all supported clusters" form Zigbee2MQTT falls
        back to when `clusters` is absent: on an Inovelli switch that would also bind
        `manuSpecificInovelli` and the metering clusters, which no rule ever asked for.

        Both ends are named by the friendly name they answer to now, resolved here rather
        than taken off the handle (E23).

        NOTE: modelled, never observed. Assumption A2, issue #6.
        """
        return zp.BindRequest(
            source_name=self._name_of(link.source),
            source_endpoint=link.source_endpoint,
            target=self._target_name(link),
            target_endpoint=link.target.endpoint,
            clusters=(link.emitter_group,),
            transaction=self._next_transaction(),
        )

    def _next_transaction(self) -> str:
        """Return an id no other in-flight request of this backend is using."""
        return f"dl-{next(self._transactions)}"

    def _target_name(self, link: Link) -> str:
        """Return what the request calls this link's target: a device name or a group name.

        A device is looked up, because its friendly name is renameable and the handle keeps
        only the address (E23). A group falls back to the name on the handle when the bridge
        no longer lists it, which happens when somebody deletes a managed group while an
        apply is running: the request then goes out naming a group that is not there, the
        bridge refuses it, and the link is reported as failed. That is a better answer than
        raising, which would take the whole result with it, and better than inventing a
        different target.
        """
        group_id = zp.group_id_of(link.target.handle)
        if group_id is None:
            return self._name_of(link.target.handle)
        group = self._state.groups.get(group_id)
        if group is None:
            return link.target.handle.name_at_authoring
        return str(group["friendly_name"])

    def _absolute_refusal(self, link: Link) -> Diagnostic | None:
        """Return why this link may never be written, whatever the bridge currently says."""
        if link.target.handle.protocol_id == self._state.coordinator_ieee:
            return Diagnostic("zigbee_coordinator_binding_protected", _binding_placeholders(link))
        if link.source.identity == link.target.handle.identity:
            return Diagnostic("zigbee_self_binding", _binding_placeholders(link))
        if zp.group_id_of(link.target.handle) is None and link.target.endpoint is None:
            return Diagnostic("zigbee_target_endpoint_required", _binding_placeholders(link))
        if not self._state.online:
            return Diagnostic(
                "zigbee_bridge_offline", {**_binding_placeholders(link), "topic": self._base}
            )
        return self._addressing_refusal(link)

    def _addressing_refusal(self, link: Link) -> Diagnostic | None:
        """Return why this link names something the bridge does not have."""
        group_id = zp.group_id_of(link.target.handle)
        if group_id is not None:
            group = self._state.groups.get(group_id)
            if group is None:
                return Diagnostic("zigbee_unknown_device", _binding_placeholders(link))
            if not zp.is_managed_group_name(str(group["friendly_name"])):
                return Diagnostic("zigbee_foreign_group", _binding_placeholders(link))
        try:
            self._device(link.source)
            if group_id is None:
                self._device(link.target.handle)
        except ZigbeeBackendError:
            return Diagnostic("zigbee_unknown_device", _binding_placeholders(link))
        return None

    def _capability_refusal(self, link: Link) -> Diagnostic | None:
        """Return why this bind would not do anything, asked before it is spent.

        A binding whose source endpoint does not drive the cluster sends nothing, and one
        whose target endpoint does not serve it is accepted and dead forever. Neither shows
        up on the device afterwards as anything but a binding that is present and useless,
        which is the worst outcome available: it looks applied.
        """
        source = self._device(link.source)
        if not zp.emits(source, link.source_endpoint, link.emitter_group):
            return Diagnostic("zigbee_source_cannot_send", _binding_placeholders(link))
        if zp.group_id_of(link.target.handle) is not None:
            # A group has no clusters of its own, so there is nothing here to ask it. What
            # its members can act on is not checked anywhere: the compiler checked it for
            # each target when it produced the per-target links, and a group is only ever
            # reached through those. Nothing produces a link that names a group directly
            # today, and a future one would need this asking the members.
            return None
        target = self._device(link.target.handle)
        if link.target.endpoint is None or not zp.accepts(
            target, link.target.endpoint, link.emitter_group
        ):
            return Diagnostic("zigbee_target_cannot_receive", _binding_placeholders(link))
        return None

    def _refusal(self, link: Link, *, adding: bool) -> Diagnostic | None:
        """Return every refusal that does not depend on what is already on the device."""
        refusal = self._absolute_refusal(link)
        if refusal is not None or not adding:
            return refusal
        return self._capability_refusal(link)

    def _is_present(self, link: Link) -> bool:
        """Say whether this exact link is already on the device.

        Compared by fingerprint against the observed links, so it asks the same question
        the planner asked and gets the same answer: a managed group's expansion counts as
        the per-target links it stands for, and a level binding counts for both the
        features it carries.
        """
        group_id = zp.group_id_of(link.target.handle)
        if group_id is not None:
            # A link that names a group cannot be compared against the observed links,
            # because those expand a managed group into the members it stands for and so
            # never carry the group's own address. What answers it is the binding itself.
            return any(binding.group_id == group_id for binding in self._bindings_from(link))
        source = self._device(link.source)
        return any(
            observed.fingerprint == link.fingerprint
            for observed in self._observed_links(link.source, source)
        )

    def _is_battery(self, handle: DeviceHandle) -> bool:
        """Say whether this device is battery powered, which changes what silence means."""
        try:
            device = self._device(handle)
        except ZigbeeBackendError:
            return False
        return str(device.get("power_source", "")).startswith(BATTERY_POWER_SOURCE)

    # Settings.

    async def async_read_setting(self, handle: DeviceHandle, capability: str) -> SettingValue:
        """Read one named setting off the device, as far as this adapter can see it.

        `value` is None, always, and that is a fact rather than a gap being papered over:
        a Zigbee device's settings arrive on its **own** state topic, and this adapter
        subscribes to the bridge topics only. None means "the device has not told us",
        which is exactly true and is not the same as zero.

        Raises for a setting the curated entry does not name, which is the same contract
        the Z-Wave adapter has: a read has no shape to report a refusal in, and inventing
        a value would be worse. See docs/open-items.md T45.
        """
        entry = self._entry_of(self._device(handle))
        if entry is None or capability not in entry.settings:
            raise ZigbeeBackendError(
                f"{handle.protocol_id} has no {capability} setting in the profile database"
            )
        return SettingValue(capability=capability, parameter=0, bitmask=None, value=None)

    async def async_write_setting(
        self, handle: DeviceHandle, capability: str, value: int
    ) -> SettingResult:
        """Refuse to write a Zigbee device setting, and say why rather than pretending.

        Refused rather than attempted, deliberately, and this is the one place in Phase 2A
        where a modelled write is **not** built. The bind path is modelled on one unproven
        thing (the request and response shapes, assumption A2). A settings write would be
        built on two: those, plus the property names and payload labels in the curated
        entries, which come from Zigbee2MQTT's converters and could not be checked against
        the G1 capture at all, because the capture trimmed `definition.exposes` out. A write
        proved only against a fake that embodies both guesses would demonstrate nothing
        except that the two guesses agree with each other.

        Nothing can reach this today in any case: `compiler.py` produces a setting write
        only for `mirror_hub_commands`, which is a Z-Wave concept, and the executor cannot
        carry out a `set_param` item at all (docs/open-items.md T16). The adapters are still
        shipped in the profile entries, so the data is captured and the work is queued
        rather than lost. See docs/open-items.md T45.
        """
        entry = self._entry_of(self._device(handle))
        if entry is None or capability not in entry.settings:
            return SettingResult(
                ok=False,
                reason=Diagnostic(
                    "settings_not_available",
                    {"device": handle.name_at_authoring, "setting": capability},
                ),
            )
        return SettingResult(
            ok=False,
            reason=Diagnostic(
                "zigbee_settings_not_written",
                {"device": handle.name_at_authoring, "setting": capability},
            ),
        )

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

        A device that has just joined the network is not announced, for the same reason the
        Z-Wave adapter does not announce a newly included node: the callback carries an
        identity, and the coordinator drops one it has never read. Noticing a new device is
        the coordinator's job, because it is the thing that keeps the device list.
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

    def bridge_version(self) -> str | None:
        """Return the Zigbee2MQTT version this bridge last reported on `bridge/info`.

        The Zigbee half of `zwave_accessor.async_get_server_version`, and read live rather
        than snapshotted at setup: Zigbee2MQTT is an add-on rather than a Home Assistant
        integration, so upgrading it republishes `bridge/info` and reloads nothing of ours.
        """
        return self._state.version

    def system_scope(self) -> SystemScope:
        """Report that a Zigbee coordinator binding reserves itself and not its cluster.

        An endpoint's cluster is a table of independent bindings, not a slot with one purpose.

        The bridge's reporting bindings sit beside a user's own on the same endpoint and the
        same cluster, and on a button or a remote they sit on exactly the cluster a rule
        binds from. Reading one of them as "this cluster is the bridge's" refused every rule
        from such a device with no way out (docs/open-items.md T49). What is still never
        ours is the binding itself, which `_absolute_refusal` refuses on its own account.
        """
        return SystemScope.ENTRY


def _member_of(entry: zp.GroupMember) -> tuple[str, int]:
    """Return one group member as the pair that identifies it, and nothing else.

    Whole-dict equality is what this replaced, and it was wrong in a way that only shows up
    on somebody else's bridge: Zigbee2MQTT is free to add a field to a member entry, and one
    extra key would make this stop matching the link that put the member there. Two things
    identify a member of a Zigbee group, and they are the same two `_is_present` compares.
    """
    return (str(entry["ieee_address"]), int(entry["endpoint"]))


def _to_group(link: Link, group_id: int, friendly_name: str) -> Link:
    """Return the same link with its target replaced by the managed group standing for it.

    What actually reaches the bridge for a one-to-many rule: the binding names the group,
    and the group holds the targets. The link's identity is untouched, because this copy
    exists only to build one request.
    """
    return replace(
        link,
        target=LinkTarget(handle=zp.group_handle(group_id, friendly_name), endpoint=None),
    )


def _refuse_foreign(name: str) -> None:
    """Refuse to act on a group Device Links did not create.

    Deliberately redundant with the same check inside `zigbee_protocol`'s payload builders.
    The two protect the same thing from different directions, and the cost of the second is
    one line: a group without the prefix is somebody's own work, and the whole feature is
    only safe to ship because nothing can reach one.
    """
    if not zp.is_managed_group_name(name):
        raise zp.ForeignGroupError(f"{name!r} is not a group Device Links created")


def _binding_placeholders(link: Link) -> dict[str, str]:
    """Return the placeholders every message about a Zigbee binding needs to be actionable.

    `cluster` rather than `group`, because that is what a Zigbee link is written to and a
    message that called it a group would be describing Z-Wave. `tests/test_translations.py`
    knows this helper by name, so a message using one of these three is checked against
    what is really supplied wherever it is raised.
    """
    return {
        "device": link.source.name_at_authoring,
        "cluster": link.emitter_group,
        "target": link.target.handle.name_at_authoring,
    }


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
