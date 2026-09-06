"""The coordinator: what the devices hold, whose links those are, and what is unknown.

Everything above this module asks it three questions: what is on the devices, what should
be, and which of what is on them is ours. The third one is the dangerous one.

**Ownership is by recorded fingerprint, and is never inferred from shape.** The planner
removes exactly what `managed_by` claims and nothing else, so the moment ownership becomes
a guess ("this is in a group a rule uses, so it is probably ours"), the next apply deletes
an association somebody made by hand in Z-Wave JS UI two years ago, with no warning and no
undo. So the active profile is compiled, the resulting links are indexed by fingerprint,
and `managed_by` is set on an exact match of the whole fingerprint or not at all. The
Z-Wave adapter deliberately leaves `managed_by` as None for exactly this reason: only this
layer knows which profile is active.

Two consequences of that rule are worth stating, because they look inconsistent until you
see what each protects:

- **A disabled rule still owns its links.** Its rule is still in the profile, so it is
  still compiled (with `enabled` forced on) for the ownership index, while contributing
  nothing to the desired state. Its links are therefore owned, no longer wanted, and so
  planned for removal, which is what disabling is meant to do (FR-R5). If disabling made
  them unmanaged, they could never be removed by default, and the integration would report
  them forever: the user would have to go and delete by hand exactly what they asked it to
  take off.
- **A deleted rule owns nothing.** It is not in the profile, so nothing compiles its
  fingerprints, so its links become unmanaged and are reported rather than removed
  (Decision D9). The intent behind them is gone, and quietly removing links on the strength
  of a rule that no longer exists is the one thing worse than leaving them.

**A backend that cannot answer is not a backend that answered "nothing".** If a dropped
WebSocket or a restarted add-on produced an empty device, every link in the house would
show as drifted and the next apply would try to rewrite the entire network. So a read that
fails marks the device unavailable and keeps the cache exactly as it was, and an
unavailable device is left out of planning entirely: nothing is added to it and nothing is
removed from it while we cannot see it (E1).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
import logging
from typing import Final

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from custom_components.device_links.backends.base import Backend, ObservedDevice
from custom_components.device_links.compiler import CompiledRule, compile_rule
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Link,
    ObservedLink,
    Plan,
    PlanItem,
    Profile,
    Rule,
)
from custom_components.device_links.planner import build_plan
from custom_components.device_links.storage import DeviceLinksStore, StoredState

_LOGGER = logging.getLogger(__name__)

# One refresh of a device emits an event per group it touched, and a user watching a light
# not respond is watching in seconds rather than in milliseconds. Two seconds coalesces a
# burst into one read and leaves G3's 30 second drift budget almost entirely unspent.
REFRESH_DEBOUNCE_SECONDS: Final = 2.0


class RuleState(StrEnum):
    """What one rule's links are doing, as far as the coordinator can honestly say.

    A subset of the states PRD Section 6.6 lists for the rule status sensor. `applying`
    belongs to the executor and is not invented here. `blocked` is here because the
    compiler produces it: a rule whose every leg was refused compiles to nothing, and a
    rule with nothing to write must not be reported as in sync with what it did not write.

    `UNKNOWN` and `DRIFT` are deliberately far apart. Drift is a fault, and reporting one
    because a node was asleep or a backend was restarting is how a user learns to ignore
    the alert that matters (E4).
    """

    IN_SYNC = "in_sync"
    DRIFT = "drift"
    PENDING = "pending"
    BLOCKED = "blocked"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PlanScope:
    """Which part of the network a plan is about. Empty means all of it.

    A scope selects devices first, because one device is one radio conversation and one
    device's group is what a capacity check is about: the diff is computed over whole
    devices so that another rule's links on the same device are seen, counted against the
    group's capacity, and never proposed for removal. Only then are the resulting items
    narrowed to the rules the scope names, so applying one rule does exactly that rule's
    work and nothing else.
    """

    rule_ids: frozenset[str] = frozenset()
    device_identities: frozenset[str] = frozenset()


class DeviceLinksCoordinator:
    """The observed-state cache, the ownership index, and what may be planned from them."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        backends: Mapping[BackendId, Backend],
        store: DeviceLinksStore,
        refresh_debounce_seconds: float = REFRESH_DEBOUNCE_SECONDS,
    ) -> None:
        """Hold what the coordinator needs, and read nothing yet."""
        self._hass = hass
        self._backends = dict(backends)
        self._store = store
        self._debounce_seconds = refresh_debounce_seconds

        self._state = StoredState()
        self._handles: dict[str, DeviceHandle] = {}
        self._capabilities: dict[str, DeviceCapabilities] = {}
        self._observed: dict[str, ObservedDevice] = {}
        self._unavailable: set[str] = set()

        # Ownership, rebuilt from the active profile on every resolve. `_owners` is the
        # whole of it: fingerprint to the rule that claims it, and nothing else is ever
        # consulted to decide whether a link is ours.
        self._compiled: dict[str, CompiledRule] = {}
        self._owners: dict[str, str] = {}
        self._desired: list[Link] = []

        self._unsubscribes: list[CALLBACK_TYPE] = []
        self._pending: set[str] = set()
        self._flush_handle: CALLBACK_TYPE | None = None

        # Whether each backend answered the last time it was asked, and what went wrong
        # the last time something did not. Both are read by the Health sensor, which is
        # the first entity anybody looks at when a system nobody can debug goes quiet.
        # They start at "answering": nothing has failed yet, and reporting an outage
        # before the first read would make a healthy start look like a fault.
        self._backend_available: dict[BackendId, bool] = dict.fromkeys(self._backends, True)
        self._last_error: dict[str, str] | None = None

        # Entities, which are pushed to rather than polled (quality-scale rule
        # parallel-updates). Held here rather than on the entities so that an entity that
        # forgot to unsubscribe is visible as a count rather than as a leak nobody finds.
        self._listeners: list[CALLBACK_TYPE] = []

        # Devices somebody else is in the middle of a conversation with, counted so that
        # two holders of the same device release it only when both have let go.
        self._held: Counter[str] = Counter()

    # Lifecycle.

    async def async_setup(self) -> None:
        """Load what was stored, read every device, and start following changes.

        A `StorageSchemaError` from the load is deliberately not caught here: E18 wants the
        integration up and read-only with a Repairs issue rather than silently empty, and
        which of those it is is a decision for the layer that owns the config entry.
        """
        self._state = await self._store.async_load()
        await self.async_refresh()
        for backend in self._backends.values():
            self._unsubscribes.append(backend.subscribe(self._device_changed))

    async def async_shutdown(self) -> None:
        """Stop following changes, and stop any refresh that was about to happen.

        A listener that outlives a config entry unload fires at a coordinator that has
        already torn itself down, survives a reload, and is the leak nobody finds.
        """
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        self._cancel_flush()

    # Telling the entities.

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call this back whenever anything an entity displays may have changed.

        Returns the unsubscribe callable, which an entity calls from
        `async_will_remove_from_hass` (quality-scale rule entity-event-setup). A listener
        that outlives its entity fires at an object Home Assistant has already torn down
        and survives a reload, which is the leak nobody finds; `listener_count` exists so
        a test can see one rather than waiting for the second reload to.
        """
        self._listeners.append(update_callback)

        @callback
        def _remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove

    @property
    def listener_count(self) -> int:
        """Return how many entities are currently subscribed."""
        return len(self._listeners)

    @callback
    def async_update_listeners(self) -> None:
        """Tell every subscribed entity to write its state again."""
        for update_callback in list(self._listeners):
            update_callback()

    # What is known.

    @property
    def state(self) -> StoredState:
        """Return everything that is stored, as it currently stands."""
        return self._state

    @property
    def active_profile(self) -> Profile | None:
        """Return the one active profile (Decision D10), or None when there is none."""
        return self._state.active_profile

    def observed_for(self, handle: DeviceHandle) -> ObservedDevice | None:
        """Return what this device holds, or None when nothing has ever been read from it.

        None rather than an empty device: "we have not read this" and "this device holds
        nothing" are different answers, and a caller that cannot tell them apart is one
        that will eventually plan to write a whole network from scratch.

        What comes back is the last thing the device said, which is not the same as what it
        holds now: while a device is unavailable this is deliberately kept and served, so
        the UI can still show what is there. Ask `is_available` before treating it as
        current, and note that nothing unavailable is ever planned for.
        """
        return self._observed.get(handle.identity)

    def is_available(self, identity: str) -> bool:
        """Say whether this device answered the last time it was asked."""
        return identity in self._observed and identity not in self._unavailable

    @property
    def available(self) -> bool:
        """Say whether anything at all can be read right now.

        One backend answering is enough: the Zigbee half of a house being unreachable does
        not make the Z-Wave half unknowable, and taking every entity away because one
        protocol dropped would hide the state that is still true.
        """
        return any(self._backend_available.values())

    @property
    def backend_availability(self) -> Mapping[BackendId, bool]:
        """Return whether each backend answered the last time it was asked."""
        return dict(self._backend_available)

    @property
    def last_error(self) -> Mapping[str, str] | None:
        """Return what last went wrong reading a device, without any network identifier.

        The backend and the exception type, and no message: this is a state attribute,
        which is world-readable, ends up in the recorder, and gets screenshotted into
        issue reports. The full text is in the log, which is where a person triaging one
        of these is already looking.
        """
        return None if self._last_error is None else dict(self._last_error)

    def pending_link_fingerprints(self) -> frozenset[str]:
        """Return the links whose last job left them queued at a sleeping node (E5).

        The latest job to mention a fingerprint is the one that counts: a later apply that
        landed answers an earlier one that was queued. What this cannot see is a node that
        woke up and took the write without a job of ours running, which is why the count
        is described as what the last job left rather than as what is on the devices.
        """
        latest: dict[str, bool] = {}
        for job in self._state.jobs:
            for result in job.results:
                latest[result.fingerprint] = result.status == "pending_wakeup"
        return frozenset(fingerprint for fingerprint, waiting in latest.items() if waiting)

    def backend_for(self, handle: DeviceHandle) -> Backend | None:
        """Return the adapter that speaks this device's protocol, if it is loaded."""
        return self._backends.get(handle.backend)

    @property
    def devices(self) -> Mapping[str, DeviceHandle]:
        """Return every device any backend has listed, by identity.

        What the WebSocket API lists and what diagnostics dumps. A device that has stopped
        answering is still here, because it is still on the network: ask `is_available`
        before treating what is cached about it as current.
        """
        return dict(self._handles)

    def capabilities_for(self, identity: str) -> DeviceCapabilities | None:
        """Return what this device can do, as it was last read, or None if never read."""
        return self._capabilities.get(identity)

    @property
    def capabilities(self) -> Mapping[str, DeviceCapabilities]:
        """Return what every device that has been read can do, by identity.

        A copy, because this is what the compiler and the swap flow are handed and neither
        may end up holding a view of a cache that moves under them mid-decision.
        """
        return dict(self._capabilities)

    def compiled_for(self, rule_id: str) -> CompiledRule | None:
        """Return what one rule of the active profile compiled to, disabled or not."""
        return self._compiled.get(rule_id)

    def compile_rule(self, rule: Rule) -> CompiledRule:
        """Compile a rule against the devices as they are now, storing nothing.

        What `rules/validate` answers with: a rule the user is still editing, checked
        against real capabilities, without it having to exist in a profile first.
        """
        return compile_rule(rule, self._capabilities)

    # What is stored, and what that means for ownership.

    @callback
    def async_update_state(self, state: StoredState) -> None:
        """Take new stored state, persist it, and resolve ownership again.

        This is how the coordinator is told that ownership may have changed: a rule added,
        edited, disabled or deleted, or a different profile activated. Nothing is re-read
        from a radio, because nothing about the devices changed: what changed is which
        fingerprints the profile claims.
        """
        self._state = state
        self._store.async_schedule_save(state)
        self._resolve_ownership()

    @callback
    def async_activate_profile(self, profile_id: str) -> bool:
        """Make one stored profile the active one, and say whether it exists.

        Nothing is written to a device: activating changes which rules are wanted, and
        making the devices match that is an apply, which the user asks for separately
        (FR-E1). Decision D10 is why this is a single id rather than a set.
        """
        if not any(profile.id == profile_id for profile in self._state.profiles):
            return False
        self.async_update_state(replace(self._state, active_profile_id=profile_id))
        return True

    def handle_for(self, identity: str) -> DeviceHandle | None:
        """Return the handle of a device this coordinator has seen, by its identity."""
        return self._handles.get(identity)

    def owner_of(self, fingerprint: str) -> str | None:
        """Return the rule of the active profile that claims this link, if any."""
        return self._owners.get(fingerprint)

    def is_rule_enabled(self, rule_id: str, *, default: bool) -> bool:
        """Say whether this rule of the active profile is enabled, as it stands now.

        `default` answers for a rule that is not in the active profile, which a rule
        entity briefly is while it is being torn down: its rule left the profile and Home
        Assistant has not finished removing it yet. Its own last-known value is the only
        honest answer in that window, and inventing one would make a switch flip under a
        user's eyes on its way out.
        """
        profile = self.active_profile
        if profile is None:
            return default
        return next((rule.enabled for rule in profile.rules if rule.id == rule_id), default)

    @callback
    def async_set_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        """Enable or disable one rule of the active profile, and say whether it exists.

        Only the stored intent changes here: nothing is written to a device, because
        disabling a rule is what makes its links unwanted and removing them is an apply
        like any other (FR-R5). The two are deliberately separate so a caller can decide
        the intent without a radio conversation, and so the ownership index is already
        right when the plan is built.

        False means no rule of the active profile has that id, which is a caller error
        rather than something to raise about here: the layers above turn it into a
        translated `ServiceValidationError`.
        """
        profile = self.active_profile
        if profile is None or not any(rule.id == rule_id for rule in profile.rules):
            return False
        updated = replace(
            profile,
            rules=tuple(
                rule.with_enabled(enabled) if rule.id == rule_id else rule for rule in profile.rules
            ),
        )
        self.async_update_state(
            replace(
                self._state,
                profiles=tuple(
                    updated if candidate.id == profile.id else candidate
                    for candidate in self._state.profiles
                ),
            )
        )
        return True

    @callback
    def async_note_applied(self, rule_ids: Iterable[str]) -> None:
        """Record that these rules have been applied successfully at least once.

        Drift is "different from desired after the last successful apply" (FR-A5), so a
        rule that has never been applied is pending rather than drifted: nothing has moved
        away from anything yet. This is persisted because a restart does not un-apply
        anything, and a restart that reset every rule to pending would stop reporting drift
        exactly when a user is most likely to be looking for it.
        """
        applied = self._state.applied_rule_ids | frozenset(rule_ids)
        if applied != self._state.applied_rule_ids:
            self.async_update_state(replace(self._state, applied_rule_ids=applied))

    # Reading.

    async def async_relist(self) -> None:
        """Ask every backend which devices are on its network, and take the answer whole.

        The only path that can notice a device has **left**. A per-device read cannot: it
        asks about a device we already know of, so a node that has been excluded reads as
        one that did not answer. Asking for the listing again is what tells "unreachable"
        from "gone", which is what E19 and the swap flow (FR-S3) are decided on.

        Deliberately not on a timer. It re-reads every device on the network, so a schedule
        would be radio traffic for a question whose answer changes when a person changes it;
        `async_setup` asks it once, and an unscoped Verify asks it again, which is the
        surface somebody uses precisely when they think the picture is out of date.
        """
        await self.async_refresh()

    async def async_refresh(
        self, handle: DeviceHandle | None = None, *, deep: bool = False
    ) -> ObservedDevice | None:
        """Re-read one device, or every device, and resolve ownership over the result.

        `deep` asks the devices themselves rather than the driver's cache, which costs
        radio time: it is what the executor does after an apply, not what a subscription
        callback does.

        A single-device refresh hands back what it read, so a caller that has to reason
        about the answer holds it rather than fetching it out of the cache again. The two
        are the same object today, because nothing can run between the store and this
        return, but "nothing can run in between" is a property of code somebody will
        change: a verify that consumes its own read cannot be undone by a later write into
        the cache, whatever else ends up running there. None means the device did not
        answer, and what was cached before is still cached.
        """
        if handle is None:
            await self._read_all(deep=deep)
            self._resolve_ownership()
            return None
        read = await self._read_device(handle, deep=deep)
        self._resolve_ownership()
        return None if read is None else self._observed.get(handle.identity)

    async def _read_all(self, *, deep: bool) -> None:
        """Read every device of every backend, one backend's failure at a time."""
        for backend_id, backend in self._backends.items():
            try:
                devices = await backend.async_devices()
            except Exception as error:  # an adapter may raise anything its client raises
                self._note_backend_lost(backend_id, error)
                self._mark_backend_unavailable(backend_id)
                continue
            self._note_backend_answering(backend_id)
            for device in devices:
                self._handles[device.handle.identity] = device.handle
                await self._read_device(device.handle, deep=deep)
            self._forget_unlisted(backend_id, {device.handle.identity for device in devices})

    def _forget_unlisted(self, backend_id: BackendId, listed: set[str]) -> None:
        """Drop what this backend no longer lists, so a removed device stops being current.

        A device that has left the network is not the same as one that did not answer, and
        this is the only place the difference is visible: the backend answered, with a list
        that no longer has it in. Keeping it would leave a device that is physically gone
        reading as merely unavailable for the life of the process, and FR-S3 (which offers
        a swap when a device rules reference disappears) could never fire while Home
        Assistant kept running.

        **An empty listing never prunes.** Zigbee2MQTT republishes `bridge/devices` while it
        restarts, and a momentarily empty list would otherwise take every Zigbee device off
        this network at once, which is a mass event nobody caused. A backend that has
        listed devices before and lists none now is treated as one that did not really
        answer: the cache stands and the next listing settles it.

        What is dropped is only the cache. The stored rules are untouched, so a rule
        naming the device still exists and still says what the user wanted; it simply reads
        as `unknown` rather than as `drift`, which is what E4 asks for.
        """
        known = {
            identity for identity, handle in self._handles.items() if handle.backend is backend_id
        }
        gone = known - listed
        if not listed or not gone:
            return
        _LOGGER.info(
            "the %s backend no longer lists %s, so what was cached about them is dropped",
            backend_id,
            ", ".join(sorted(gone)),
        )
        for identity in gone:
            self._handles.pop(identity, None)
            self._capabilities.pop(identity, None)
            self._observed.pop(identity, None)
            self._unavailable.discard(identity)

    async def _read_device(self, handle: DeviceHandle, *, deep: bool) -> ObservedDevice | None:
        """Read one device, keeping what is cached when it does not answer.

        Returns what was read, or None when there was no answer and the cache was left as
        it was, so a caller can tell "this is what the device said" from "the device said
        nothing" without asking a second question.
        """
        backend = self._backends.get(handle.backend)
        if backend is None:
            return None
        try:
            capabilities = await backend.async_capabilities(handle)
            observed = await backend.async_observed(handle, deep)
        except Exception as error:  # an adapter may raise anything its client raises
            # Logged once per device rather than once per refresh: a node that has been
            # unreachable for a week would otherwise fill the log with the same line every
            # two seconds, and a line that appears that often is one nobody reads
            # (quality-scale rule log-when-unavailable).
            if handle.identity not in self._unavailable:
                _LOGGER.warning(
                    "%s did not answer, so its last known state is kept and it is marked "
                    "unavailable rather than empty",
                    handle.identity,
                    exc_info=True,
                )
            self._note_error(str(handle.backend), error)
            self._unavailable.add(handle.identity)
            return None
        self._handles[handle.identity] = handle
        self._capabilities[handle.identity] = capabilities
        self._observed[handle.identity] = observed
        self._unavailable.discard(handle.identity)
        return observed

    def _note_backend_lost(self, backend_id: BackendId, error: Exception) -> None:
        """Record that a backend stopped answering, and say so exactly once.

        Once, because the alternative is one warning per refresh for as long as the
        add-on is down, and a log line that repeats every two seconds is one a user
        scrolls past on the way to the one that matters (quality-scale rule
        log-when-unavailable). The recovery below is logged once for the same reason and
        at INFO, because coming back is not a fault.
        """
        self._note_error(str(backend_id), error)
        if self._backend_available.get(backend_id, True):
            _LOGGER.warning(
                "the %s backend stopped answering, so its devices are marked unavailable "
                "and their last known state is kept",
                backend_id,
                exc_info=error,
            )
        self._backend_available[backend_id] = False

    def _note_backend_answering(self, backend_id: BackendId) -> None:
        """Record that a backend answered, and say so once if it had stopped."""
        if not self._backend_available.get(backend_id, True):
            _LOGGER.info("the %s backend is answering again", backend_id)
        self._backend_available[backend_id] = True

    def _note_error(self, backend_id: str, error: Exception) -> None:
        """Keep what last went wrong, without keeping anything that identifies a network."""
        self._last_error = {"backend": backend_id, "error": type(error).__name__}

    def _mark_backend_unavailable(self, backend_id: BackendId) -> None:
        """Mark every device of a backend that has stopped answering, keeping the cache.

        This is the whole of E1 in two lines: the connection dropped, so the devices are
        unavailable, so nothing is planned for them. What they held is still what they
        held; we have simply stopped being able to see it.
        """
        self._unavailable.update(
            identity for identity, handle in self._handles.items() if handle.backend is backend_id
        )

    # Ownership.

    def _resolve_ownership(self) -> None:
        """Compile the active profile and stamp ownership onto the cache.

        Compiled once here, for every rule in the profile, rather than per device: the
        answer must be the same for every device, and compiling per device is how two
        devices end up disagreeing about who owns a link between them.
        """
        self._compiled, self._owners, self._desired = self._compile_active_profile()
        for identity, device in self._observed.items():
            self._observed[identity] = replace(
                device, links=tuple(self._owned(link) for link in device.links)
            )
        # Every path that changes what an entity would say ends here: a read, a stored
        # state change, a debounced refresh. Notifying from one place rather than from
        # three is what makes "the entity is stale" impossible to introduce by adding a
        # fourth.
        self.async_update_listeners()

    def _compile_active_profile(
        self,
    ) -> tuple[dict[str, CompiledRule], dict[str, str], list[Link]]:
        """Return what each rule compiles to, who owns what, and what is wanted.

        Every rule is compiled with `enabled` forced on, because ownership is about what a
        rule claims and a disabled rule still claims what it wrote. Only enabled rules
        contribute to the desired state, which is what makes a disabled rule's links owned,
        unwanted, and therefore removable.

        The compilation is kept rather than thrown away, because drift asks the same
        question again for every rule and compiling twice is how two answers about the same
        rule end up disagreeing.
        """
        compiled: dict[str, CompiledRule] = {}
        owners: dict[str, str] = {}
        desired: list[Link] = []
        profile = self.active_profile
        if profile is None:
            return compiled, owners, desired
        for rule in profile.rules:
            compiled[rule.id] = compile_rule(rule.with_enabled(True), self._capabilities)
            for link in compiled[rule.id].links:
                # First claim wins. Two rules asking for the same write are one entry on
                # the device, and an entry with two owners is an entry whose removal
                # depends on which rule was looked at first.
                owners.setdefault(link.fingerprint, rule.id)
            if rule.enabled:
                desired.extend(compiled[rule.id].links)
        return compiled, owners, desired

    def _owned(self, link: ObservedLink) -> ObservedLink:
        """Return this observed link with its owner resolved, and never with a guess.

        A system link is answered before the index is consulted at all, so no ownership
        record and no accident of compilation can make a lifeline look removable. This is
        deliberately redundant with the planner's own guard: the two protect the same thing
        from different directions, and the cost of the second one is one line.
        """
        if link.is_system:
            return replace(link, rule_id=None, managed_by=None)
        owner = self._owners.get(link.fingerprint)
        return replace(link, rule_id=owner, managed_by=owner)

    # Planning.

    async def async_plan(
        self,
        scope: PlanScope | None = None,
        *,
        remove_unmanaged: frozenset[str] = frozenset(),
        desired: Sequence[Link] | None = None,
    ) -> Plan:
        """Return what would happen if this scope were applied, from what was last read.

        Deliberately built from the cache rather than refreshing first: the caller decides
        when a read is worth the radio time, and a plan whose token was computed from state
        the caller never saw is a plan they cannot reason about. The executor refreshes and
        then plans.

        `desired` answers "what would happen if *this* were what the profile wanted", which
        is what a device swap and a snapshot rollback both need: both propose a state that
        is not stored yet, and both must be previewable in full before anything is written.
        **Ownership is deliberately not overridden with it.** `managed_by` is a record of
        what Device Links put on a device, not of what somebody now wants there, so the
        stored profile keeps claiming its links and they are correctly planned for removal
        when the proposed state no longer wants them. Overriding both halves would make a
        proposal that claims links it never wrote, which is how a preview comes to offer to
        delete somebody else's associations.
        """
        identities = self.identities_in_scope(scope)
        observed: list[ObservedLink] = []
        for identity in sorted(identities):
            observed.extend(self._observed[identity].links)
        wanted = self._desired if desired is None else desired
        plan = build_plan(
            desired=[link for link in wanted if link.source.identity in identities],
            observed=observed,
            capabilities=self._capabilities,
            remove_unmanaged=remove_unmanaged,
        )
        return self._narrowed_to_rules(plan, scope, remove_unmanaged)

    def _narrowed_to_rules(
        self, plan: Plan, scope: PlanScope | None, remove_unmanaged: frozenset[str]
    ) -> Plan:
        """Return the plan with only the work the scope's rules asked for.

        The diff behind this was computed over whole devices, which is what makes it safe:
        another rule's links were seen, so they were counted against group capacity and
        were never mistaken for something nobody wants. What is dropped here is only the
        work that belongs to a rule the user did not select, so "apply this rule" applies
        that rule. What is reported (`unmanaged`, `unchanged_count`) is left as it was
        found, because a report about a device is about the whole device.
        """
        if scope is None or not scope.rule_ids:
            return plan
        return replace(
            plan,
            items=tuple(
                item
                for item in plan.items
                if self._is_wanted(item, scope.rule_ids, remove_unmanaged)
            ),
        )

    @staticmethod
    def _is_wanted(item: PlanItem, rule_ids: frozenset[str], selected: frozenset[str]) -> bool:
        """Say whether one plan item is work the scoped rules asked for.

        An observed link carries the owner this coordinator resolved, and a desired one
        carries the rule that compiled it, in the same field, so one question answers both.
        A link nobody owns is only ever in a plan because the user selected it by
        fingerprint, and that selection is not something a rule scope should discard.
        """
        if item.link is None:
            return True
        if item.link.rule_id is None:
            return item.link.fingerprint in selected
        return item.link.rule_id in rule_ids

    def identities_in_scope(self, scope: PlanScope | None) -> set[str]:
        """Return the devices this plan may touch, which never includes an unreadable one.

        A device we cannot read is left out of both halves: its desired links are not added
        and its observed links are not diffed. Including one half without the other is
        exactly the mass-deletion (or mass-rewrite) failure this module exists to prevent.
        """
        identities = {identity for identity in self._observed if self.is_available(identity)}
        if scope is None:
            return identities
        if scope.device_identities:
            identities &= scope.device_identities
        if scope.rule_ids:
            identities &= {
                link.source.identity
                for rule_id in scope.rule_ids
                for link in self._links_of(rule_id)
            }
        return identities

    def _links_of(self, rule_id: str) -> tuple[Link, ...]:
        """Return what one rule of the active profile compiles to, disabled or not."""
        compiled = self._compiled.get(rule_id)
        return () if compiled is None else compiled.links

    # Drift.

    def drift_state(self) -> Mapping[str, RuleState]:
        """Return what each rule of the active profile is doing, by rule id."""
        profile = self.active_profile
        if profile is None:
            return {}
        return {rule.id: self._rule_state(rule) for rule in profile.rules}

    def rule_link_counts(self, rule_id: str) -> tuple[int, int]:
        """Return how many links this rule wants, and how many are really on the devices.

        "3 of 4" is what makes a drifted rule actionable: it says the fault is one link
        rather than the whole rule, which is the difference between checking one group and
        re-including a device.
        """
        wanted = self._links_of(rule_id)
        present = self._present
        return len(wanted), sum(1 for link in wanted if link.fingerprint in present)

    def _rule_state(self, rule: Rule) -> RuleState:
        """Return one rule's state, asking the questions in the order that keeps it honest.

        Disabled first, because a disabled rule is not drifting, it is off. Then whether
        every device it names can be seen at all, because a state that cannot be observed
        is unknown and not wrong (E4). Then whether it compiles to anything at all, because
        a rule whose every leg was refused has nothing to be in sync with and saying
        `in_sync` about it would be the most misleading answer available. Then whether it
        has ever been applied, because nothing can have drifted from an apply that never
        happened. Only then is a missing link a fault.
        """
        if not rule.enabled:
            return RuleState.DISABLED
        devices = {rule.source.device.identity} | {
            target.device.identity for target in rule.targets
        }
        if any(not self.is_available(identity) for identity in devices):
            return RuleState.UNKNOWN
        wanted = self._links_of(rule.id)
        if not wanted:
            return RuleState.BLOCKED
        if all(link.fingerprint in self._present for link in wanted):
            return RuleState.IN_SYNC
        if rule.id not in self._state.applied_rule_ids:
            return RuleState.PENDING
        return RuleState.DRIFT

    @property
    def _present(self) -> set[str]:
        """Return the fingerprint of every link every readable device currently holds."""
        return {
            link.fingerprint
            for identity, device in self._observed.items()
            if self.is_available(identity)
            for link in device.links
        }

    # Following changes.

    @callback
    def async_hold_refresh(self, identities: Iterable[str]) -> CALLBACK_TYPE:
        """Suspend event-driven re-reads of these devices until the caller lets go.

        A job writing to a node is a conversation with that node, and our own writes are
        exactly what makes the driver emit the value-updated events this coordinator
        follows. Without a hold, a job's first write arms a refresh that fires in the
        middle of the same job: a second radio conversation with a node that is already
        in one (which is the timeout that looks like broken hardware), and a write into
        the cache the job is reasoning from, from a read that was taken before the job
        finished writing. Neither is drift, and neither is anything the user did.

        Only the debounced, event-driven path is held. An explicit `async_refresh` is not,
        because the holder is the thing doing the reading: holding its own reads would
        deadlock the verify this exists to protect. Events are not dropped either, they
        are deferred: what changed stays pending and is read once the hold is released, so
        a change made by somebody else during a job is still noticed afterwards.

        The returned callable releases the hold and is safe to call once; call it from a
        `finally`, because a hold that outlives its job stops drift detection for good.
        """
        held = tuple(identities)
        self._held.update(held)
        released = False

        def _release() -> None:
            nonlocal released
            if released:
                return
            released = True
            for identity in held:
                self._held[identity] -= 1
                if self._held[identity] <= 0:
                    del self._held[identity]
            self._arm_flush()

        return _release

    @callback
    def _device_changed(self, identity: str) -> None:
        """Note that a device is worth re-reading, and read it once the burst is over.

        Trailing edge: the burst is what a single refresh of one device produces, and
        reading in the middle of one is reading a half-updated cache. The wait is bounded
        and short, so a drift a user is watching happen is still reported while they are
        still watching.
        """
        self._pending.add(identity)
        self._arm_flush()

    def _arm_flush(self) -> None:
        """Schedule the trailing-edge read, unless there is nothing it could read yet.

        A device under a hold does not arm anything: its event stays pending and the timer
        is armed by the release instead, so a held burst costs no wake-ups rather than one
        every debounce window for as long as the hold lasts.
        """
        if self._flush_handle is not None:
            return
        if any(identity not in self._held for identity in self._pending):
            self._flush_handle = async_call_later(
                self._hass, self._debounce_seconds, self._flush_pending
            )

    async def _flush_pending(self, _now: datetime) -> None:
        """Re-read every device that changed while the debounce was running.

        A device that has been put on hold since the timer was armed keeps its place in
        the pending set rather than being read now: the read would reach a node somebody
        else is mid-conversation with, which is the one thing this cache must never do.
        """
        self._flush_handle = None
        held = {identity for identity in self._pending if identity in self._held}
        pending, self._pending = self._pending - held, held
        for identity in sorted(pending):
            handle = self._handles.get(identity)
            if handle is not None:
                await self._read_device(handle, deep=False)
        self._resolve_ownership()

    def _cancel_flush(self) -> None:
        """Drop a refresh that was scheduled and is no longer wanted."""
        if self._flush_handle is not None:
            self._flush_handle()
            self._flush_handle = None
        self._pending.clear()
