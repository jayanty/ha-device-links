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

from collections.abc import Iterable, Mapping
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

    # Lifecycle.

    async def async_setup(self) -> None:
        """Load what was stored, read every device, and start following changes."""
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

    def backend_for(self, handle: DeviceHandle) -> Backend | None:
        """Return the adapter that speaks this device's protocol, if it is loaded."""
        return self._backends.get(handle.backend)

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

    async def async_refresh(
        self, handle: DeviceHandle | None = None, *, deep: bool = False
    ) -> None:
        """Re-read one device, or every device, and resolve ownership over the result.

        `deep` asks the devices themselves rather than the driver's cache, which costs
        radio time: it is what the executor does after an apply, not what a subscription
        callback does.
        """
        if handle is None:
            await self._read_all(deep=deep)
        else:
            await self._read_device(handle, deep=deep)
        self._resolve_ownership()

    async def _read_all(self, *, deep: bool) -> None:
        """Read every device of every backend, one backend's failure at a time."""
        for backend_id, backend in self._backends.items():
            try:
                devices = await backend.async_devices()
            except Exception:
                _LOGGER.warning(
                    "the %s backend did not answer, so its devices are marked unavailable "
                    "and their last known state is kept",
                    backend_id,
                    exc_info=True,
                )
                self._mark_backend_unavailable(backend_id)
                continue
            for device in devices:
                self._handles[device.handle.identity] = device.handle
                await self._read_device(device.handle, deep=deep)

    async def _read_device(self, handle: DeviceHandle, *, deep: bool) -> None:
        """Read one device, keeping what is cached when it does not answer."""
        backend = self._backends.get(handle.backend)
        if backend is None:
            return
        try:
            capabilities = await backend.async_capabilities(handle)
            observed = await backend.async_observed(handle, deep)
        except Exception:  # an adapter may raise anything its client raises
            _LOGGER.warning(
                "%s did not answer, so its last known state is kept and it is marked "
                "unavailable rather than empty",
                handle.identity,
                exc_info=True,
            )
            self._unavailable.add(handle.identity)
            return
        self._handles[handle.identity] = handle
        self._capabilities[handle.identity] = capabilities
        self._observed[handle.identity] = observed
        self._unavailable.discard(handle.identity)

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
    ) -> Plan:
        """Return what would happen if this scope were applied, from what was last read.

        Deliberately built from the cache rather than refreshing first: the caller decides
        when a read is worth the radio time, and a plan whose token was computed from state
        the caller never saw is a plan they cannot reason about. The executor refreshes and
        then plans.
        """
        identities = self._identities_in_scope(scope)
        observed: list[ObservedLink] = []
        for identity in sorted(identities):
            observed.extend(self._observed[identity].links)
        plan = build_plan(
            desired=[link for link in self._desired if link.source.identity in identities],
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

    def _identities_in_scope(self, scope: PlanScope | None) -> set[str]:
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
    def _device_changed(self, identity: str) -> None:
        """Note that a device is worth re-reading, and read it once the burst is over.

        Trailing edge: the burst is what a single refresh of one device produces, and
        reading in the middle of one is reading a half-updated cache. The wait is bounded
        and short, so a drift a user is watching happen is still reported while they are
        still watching.
        """
        self._pending.add(identity)
        if self._flush_handle is None:
            self._flush_handle = async_call_later(
                self._hass, self._debounce_seconds, self._flush_pending
            )

    async def _flush_pending(self, _now: datetime) -> None:
        """Re-read every device that changed while the debounce was running."""
        self._flush_handle = None
        pending, self._pending = self._pending, set()
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
