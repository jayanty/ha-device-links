"""Hybrid legs: the three pieces of intent no radio can carry, executed by Home Assistant.

PRD Section 6.7 and Decision D3. A rule compiles into legs. Native legs are association
entries and binding table rows: they are written into the devices and keep working when
Home Assistant is off. Three intents contain one piece that no radio can express, and for
those the integration becomes the missing wire.

**The whole of this module is the exception to local-first, so it is fenced three ways.**
A global option that is off by default, a per-rule opt-in on top of it, and the words
"HA-executed" on every screen that shows a leg. None of those is decoration: a leg stops
working the moment Home Assistant stops, while the native legs of the same rule carry on,
and a user who does not know which half is which cannot reason about their own house.

**A leg dies with its rule, by construction rather than by remembering to.** This manager
owns no list of its own that anything else may add to. It subscribes to the coordinator,
which fires whenever the stored state changes, recomputes the whole set of legs that should
exist from the active profile, and starts and stops the difference. Disabling a rule,
switching profiles, editing a rule, deleting one and unloading the entry all go through that
one path, so there is no fourth case somebody can add without it being handled. `async_setup`
takes the coordinator subscription and Home Assistant's own started event, and both are
released by `async_shutdown`, which the config entry calls on unload.

**What a leg does when its own action fails.** A native link either applies or it does not,
and the plan dialog says which. A leg fires at three in the morning with nobody watching, so
there is nowhere to report into: it counts. Every leg counts what it fired and what failed
on the rule's own status sensor (`hybrid_fired`, `hybrid_errors`, `hybrid_last_fired`), the
Health sensor aggregates the counts, each failure is one warning in the log naming the leg,
and a failure **rate** above a threshold raises a Repairs issue, which is the surface a user
meets without going looking. One failed press does not: a light that was mid-reboot is not a
fault, and an issue that appears for one is one nobody reads twice.

**Kind (c) writes Indicator CC, never the LED-mode parameters.** Stage 0 measured both at
33 ms and found that an indicator set does not touch device NVM
(`tests/fixtures/z8_led_path.json`), and a leg mirroring a light's state changes as often as
that light does. The write hygiene FR-H2 asks for is here rather than in the adapter:
deduplicate on the value, coalesce a burst, and never write the same device more than once a
second, because each set is a radio frame and a dimming light would otherwise emit one frame
per level.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any, Final

from homeassistant.const import ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_STARTED, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .models import Backend as BackendId
from .models import HybridKind, HybridLeg
from .rule_entity import async_upstream_device

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from homeassistant.helpers.event import EventStateChangedData

    from . import DeviceLinksConfigEntry
    from .coordinator import DeviceLinksCoordinator

_LOGGER = logging.getLogger(__name__)

# The bus event Home Assistant fires for a Z-Wave value notification, which is how a scene
# button press reaches us over the lifeline (FR-H3: no association traffic is listened to,
# and the controller is not added to anybody's group). Spelled here rather than imported
# from `zwave_js`, because importing another integration's constants is a coupling that
# breaks on their refactor rather than on ours.
ZWAVE_VALUE_NOTIFICATION: Final = "zwave_js_value_notification"

# Central Scene, and the notification values that mean a button was pressed. Held down and
# released are deliberately not here: a leg that fired on every stage of a long press would
# fire three times for one gesture.
CENTRAL_SCENE_COMMAND_CLASS: Final = 91
PRESSED_VALUES: Final = frozenset({"KeyPressed", "KeyPressed2x", "KeyPressed3x"})

# FR-H2's numbers. The timeout and the single retry bound how long one firing can take; the
# debounce is leading edge for a press, so the light responds at once and the repeats behind
# it are swallowed rather than queued.
CALL_TIMEOUT_SECONDS: Final = 10.0
PRESS_DEBOUNCE_SECONDS: Final = 0.5

# Write hygiene for kind (c): at most one indication write per second per leg, with the
# latest wanted value coalesced into the write that does happen, so a dimming light produces
# one frame rather than one per level.
INDICATION_MIN_INTERVAL_SECONDS: Final = 1.0

# The domains a leg will act on when it is handed a device. Everything else attached to a
# switch (its power meter, its config buttons, its own scene events) is not a load, and
# calling `turn_off` on a device's diagnostic sensors is how a leg comes to log an error a
# second for a house that is behaving perfectly.
LOAD_DOMAINS: Final = frozenset({"light", "switch", "fan"})

# What each press-triggered kind does when it fires. Kind (b) is off and only off, because
# the intent it exists for is UC4's "off all, including this device's own load", which is
# what the checkbox says: a leg that toggled would be a different feature wearing the same
# tick box.
_PRESS_SERVICE: Final[Mapping[HybridKind, str]] = {
    HybridKind.ON_ONLY: "turn_on",
    HybridKind.OFF_ONLY: "turn_off",
    HybridKind.SELF_LOAD: "turn_off",
}


@dataclass(slots=True)
class LegStatus:
    """What one rule's legs have done, as the status sensor reports it (FR-H2)."""

    legs: int = 0
    fired: int = 0
    errors: int = 0
    last_fired: str | None = None

    def as_attributes(self) -> dict[str, Any]:
        """Return this as the attributes of a rule's status sensor."""
        return {
            "hybrid_legs": self.legs,
            "hybrid_fired": self.fired,
            "hybrid_errors": self.errors,
            "hybrid_last_fired": self.last_fired,
        }


@dataclass(slots=True)
class _Running:
    """One leg that is currently listening, and everything it has to let go of."""

    leg: HybridLeg
    unsubscribes: list[CALLBACK_TYPE] = field(default_factory=list)
    # Leading-edge debounce for a press, and the coalescing state for an indication.
    last_fired_at: float | None = None
    wanted: bool | None = None
    written_at: float | None = None
    timer: CALLBACK_TYPE | None = None

    def stop(self) -> None:
        """Release every listener and timer this leg holds, once."""
        for unsubscribe in self.unsubscribes:
            unsubscribe()
        self.unsubscribes.clear()
        if self.timer is not None:
            self.timer()
            self.timer = None


class HybridLegs:
    """Registers, fires and retires every HA-executed leg of the active profile."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DeviceLinksConfigEntry,
        coordinator: DeviceLinksCoordinator,
        *,
        allowed: bool,
    ) -> None:
        """Hold what a leg needs, and register nothing until `async_setup` runs.

        `allowed` is the global option (FR-H1). It is a constructor argument rather than a
        lookup because changing an option reloads the config entry, so it cannot change
        under a running manager, and a manager that re-read it would be answering a question
        that cannot be asked.
        """
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._allowed = allowed
        self._running: dict[str, _Running] = {}
        self._status: dict[str, LegStatus] = {}
        self._unsubscribes: list[CALLBACK_TYPE] = []
        # What each button's indicator read before this integration first wrote to it, so
        # turning a leg off puts the light back where its owner left it (FR-H2).
        self._original: dict[str, bool] = {}

    # Lifecycle.

    @callback
    def async_setup(self) -> None:
        """Start following the active profile, and re-sync once Home Assistant is up.

        Two triggers, because they answer different questions. The coordinator says the
        rules changed; the started event says the entities a leg acts on now exist, which
        they may not during setup, and a leg registered against an entity that is not there
        yet would watch a state that never arrives.
        """
        self._unsubscribes.append(self._coordinator.async_add_listener(self._async_resync))
        self._unsubscribes.append(
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._async_started)
        )
        self._async_resync()

    @callback
    def async_shutdown(self) -> None:
        """Stop every leg, and deliberately restore nothing.

        Unload is Home Assistant going away, and a restore would be a radio write nobody
        asked for at the worst possible moment: mid-shutdown, against a mesh, with no user
        watching and no plan behind it. A leg that is retired while the integration is
        running does restore, because that is somebody turning it off; see `_async_resync`.

        Dropping the two subscriptions first is what makes this final: nothing can call
        `_async_resync` afterwards, so nothing can put back what the loop below takes down.
        """
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()
        for running in list(self._running.values()):
            running.stop()
        self._running.clear()

    @callback
    def _async_started(self, _event: Event) -> None:
        """Re-register once Home Assistant is running and the entities exist."""
        self._async_resync()

    # What should be running.

    @callback
    def _async_resync(self) -> None:
        """Start every leg that should exist, stop every leg that should not.

        The whole set is recomputed rather than patched. A rule disabled, a profile
        switched, a rule edited and a rule deleted are four different events with one
        answer, and computing the answer in one place is what makes it impossible to add a
        fifth that forgets to stop anything.

        There is deliberately no "are we shutting down" guard here. What stops this running
        after an unload is that `async_shutdown` drops the two subscriptions that call it,
        and a guard for a caller that cannot exist would be a branch no test could reach,
        which is a worse kind of protection than none.
        """
        wanted = {leg.identity: leg for leg in self._wanted_legs()}
        for identity in sorted(set(self._running) - set(wanted)):
            self._retire(self._running.pop(identity))
        for identity, leg in sorted(wanted.items()):
            if identity not in self._running:
                self._running[identity] = self._start(leg)
        self._recount()

    def _wanted_legs(self) -> list[HybridLeg]:
        """Return every leg the active profile's enabled rules ask for.

        Nothing at all while the global option is off, which is what makes that option
        mean something: a rule may carry the opt-in and be stored and exported with it, and
        until somebody turns hybrid legs on for this Home Assistant, no listener exists.
        """
        profile = self._coordinator.active_profile
        if not self._allowed or profile is None:
            return []
        legs: list[HybridLeg] = []
        for rule in profile.rules:
            compiled = self._coordinator.compiled_for(rule.id)
            if rule.enabled and compiled is not None:
                legs.extend(compiled.hybrid_legs)
        return legs

    def _recount(self) -> None:
        """Refresh the per-rule leg counts, keeping what each rule has already fired."""
        counts: dict[str, int] = {}
        for running in self._running.values():
            counts[running.leg.rule_id] = counts.get(running.leg.rule_id, 0) + 1
        for rule_id in set(self._status) | set(counts):
            self._status.setdefault(rule_id, LegStatus()).legs = counts.get(rule_id, 0)

    # Registration.

    def _start(self, leg: HybridLeg) -> _Running:
        """Register the listeners one leg needs, and say so at INFO.

        At INFO because this is the moment Home Assistant takes on a job the radio was
        doing, and a log that does not record it leaves the user's house doing something
        no line anywhere explains.
        """
        running = _Running(leg=leg)
        if leg.kind is HybridKind.BUTTON_LED:
            self._watch_target(running)
        else:
            self._watch_presses(running)
        _LOGGER.info(
            "hybrid leg %s is now executed by Home Assistant for rule %s, and stops working "
            "while Home Assistant does",
            leg.identity,
            leg.rule_id,
        )
        return running

    def _retire(self, running: _Running) -> None:
        """Stop one leg, and put back what it changed.

        Only kind (c) changed anything that outlives it: a press leg leaves nothing behind,
        and a button LED it drove would otherwise stay wherever the last light state left
        it, which is a light nobody can now explain and nothing will ever change again.
        """
        running.stop()
        leg = running.leg
        if leg.kind is HybridKind.BUTTON_LED:
            original = self._original.pop(leg.identity, None)
            if original is not None:
                self._hass.async_create_task(
                    self._async_write_indication(leg, original), eager_start=False
                )
        _LOGGER.info("hybrid leg %s is no longer executed by Home Assistant", leg.identity)

    def _watch_presses(self, running: _Running) -> None:
        """Listen for the press this leg acts on, over the lifeline and nothing else.

        FR-H3: Central Scene notifications already reach Home Assistant for every press on
        every device this matters for, so nothing is added to an association group and no
        association traffic is listened to. A protocol with no press we can hear is refused
        at compile time rather than listened for here, which is why this only ever sees
        Z-Wave: a Zigbee emitter carries no scene number, so no leg of these kinds compiles.
        """
        leg = running.leg
        if leg.source.backend is not BackendId.ZWAVE:  # pragma: no cover
            # Unreachable today and kept anyway: no leg of these kinds compiles on another
            # protocol, because only a Z-Wave emitter can carry a scene number. What makes
            # it worth a branch is Phase 3, where a Matter emitter could carry one and this
            # would otherwise register a `zwave_js` listener for a Matter button.
            _LOGGER.warning(
                "hybrid leg %s asks for a button press on the %s backend, which has no press "
                "this integration can hear, so the leg does nothing",
                leg.identity,
                leg.source.backend,
            )
            return
        device = async_upstream_device(self._hass, self._entry, leg.source)
        if device is None:
            _LOGGER.warning(
                "hybrid leg %s names a device Home Assistant has no record of, so the press "
                "it waits for can never be recognised",
                leg.identity,
            )
            return
        device_id = device.id

        @callback
        def _on_notification(event: Event[Mapping[str, Any]]) -> None:
            if _is_press(event.data, device_id=device_id, scene_id=leg.scene_id):
                self._fire_press(running)

        running.unsubscribes.append(
            self._hass.bus.async_listen(ZWAVE_VALUE_NOTIFICATION, _on_notification)
        )

    def _watch_target(self, running: _Running) -> None:
        """Follow the light this leg mirrors, and light the button to match right away.

        The immediate write matters as much as the following: a leg registered at start-up
        against a light that has been on for six hours would otherwise leave the button dark
        until somebody touched that light, which reads as a leg that does not work.
        """
        leg = running.leg
        entities = self._entities_of(leg.target.handle.identity)
        if not entities:
            _LOGGER.warning(
                "hybrid leg %s watches a device with nothing Home Assistant can read a state "
                "from, so the button LED will not follow it",
                leg.identity,
            )
            return

        @callback
        def _on_state(_event: Event[EventStateChangedData]) -> None:
            self._want_indication(running, self._is_on(entities))

        running.unsubscribes.append(async_track_state_change_event(self._hass, entities, _on_state))
        self._want_indication(running, self._is_on(entities))

    # Firing.

    @callback
    def _fire_press(self, running: _Running) -> None:
        """Act on one press, swallowing the burst of identical events behind it.

        Leading edge on purpose. A trailing debounce would put half a second between a
        person pressing a button and their light responding, which is the difference
        between a feature and a fault report.
        """
        now = monotonic()
        if running.last_fired_at is not None and now - running.last_fired_at < (
            PRESS_DEBOUNCE_SECONDS
        ):
            return
        running.last_fired_at = now
        leg = running.leg
        identity = (
            leg.source.identity if leg.kind is HybridKind.SELF_LOAD else leg.target.handle.identity
        )
        entities = self._entities_of(identity)
        if not entities:
            self._note_error(leg, "there is nothing Home Assistant can act on")
            return
        self._hass.async_create_task(
            self._async_call(leg, _PRESS_SERVICE[leg.kind], entities), eager_start=False
        )

    @callback
    def _want_indication(self, running: _Running, lit: bool) -> None:
        """Record the value this button's LED should show, and write it at most once a second.

        Deduplication first: a light ramping from 10% to 90% emits a state change per step
        and every one of them means the same thing to a binary indicator. Then coalescing:
        a value that arrives inside the rate limit is remembered and written when the limit
        expires, so the last state is never the one that was dropped.
        """
        if running.wanted == lit:
            return
        running.wanted = lit
        if running.timer is not None:
            return
        now = monotonic()
        wait = 0.0
        if running.written_at is not None:
            wait = max(0.0, INDICATION_MIN_INTERVAL_SECONDS - (now - running.written_at))
        if wait == 0.0:
            self._write_indication_now(running)
            return

        @callback
        def _later(_now: Any) -> None:
            running.timer = None
            self._write_indication_now(running)

        running.timer = async_call_later(self._hass, wait, _later)

    def _write_indication_now(self, running: _Running) -> None:
        """Send the value that is currently wanted, whatever arrived while we waited."""
        lit = running.wanted
        if lit is None:  # pragma: no cover
            # Unreachable: nothing arms the timer or calls this before a value is wanted.
            # It is here because the field is genuinely `bool | None` and a write of None
            # would be a write of False, which is a light somebody did not ask to go out.
            return
        running.written_at = monotonic()
        self._hass.async_create_task(
            self._async_write_indication(running.leg, lit, count=True), eager_start=False
        )

    async def _async_write_indication(
        self, leg: HybridLeg, lit: bool, *, count: bool = False
    ) -> None:
        """Write one button indication, recording what was there before the first time.

        The read happens once per leg, before the first write, which is what makes turning
        the leg off restorable. A device that will not say what its indicator holds gets no
        recorded value and no restore, which is reported as nothing rather than as a guess:
        writing a default back would be this integration deciding what somebody's button
        looked like before it arrived.
        """
        backend = self._coordinator.backend_for(leg.source)
        if backend is None:  # pragma: no cover
            # Unreachable while a leg only exists for a device a loaded backend listed.
            # Kept because the coordinator's answer is genuinely optional and a leg that
            # silently did nothing would be worse than one that counts a failure.
            self._note_error(leg, "its backend is not loaded")
            return
        try:
            if leg.identity not in self._original:
                before = await backend.async_read_indication(leg.source, leg.emitter_id)
                if before is not None:
                    self._original[leg.identity] = before
            written = await backend.async_write_indication(leg.source, leg.emitter_id, lit)
        # An adapter raises whatever its client raises, and a leg firing has nowhere to
        # report into but its own counters.
        except Exception:
            _LOGGER.warning(
                "hybrid leg %s could not write the button indication", leg.identity, exc_info=True
            )
            self._count(leg, ok=False)
            return
        if not written:
            self._note_error(leg, "the device did not take the button indication")
            return
        if count:
            self._count(leg, ok=True)

    async def _async_call(self, leg: HybridLeg, service: str, entities: Sequence[str]) -> None:
        """Make one service call, with a timeout and exactly one retry (FR-H2).

        One retry rather than a backoff loop: a leg is a person pressing a button, and a
        command that has not landed after two tries has missed the moment it was for.
        """
        last: Exception | None = None
        for _attempt in (1, 2):
            try:
                async with asyncio.timeout(CALL_TIMEOUT_SECONDS):
                    await self._hass.services.async_call(
                        "homeassistant", service, {ATTR_ENTITY_ID: list(entities)}, blocking=True
                    )
            # A service call raises whatever the integration behind it raises, and this is
            # the retry: what it must not do is escape into a bus callback.
            except Exception as err:
                last = err
                continue
            self._count(leg, ok=True)
            return
        _LOGGER.warning(
            "hybrid leg %s could not call homeassistant.%s on %s: %s",
            leg.identity,
            service,
            ", ".join(entities),
            last,
        )
        self._count(leg, ok=False)

    # Counting, which is the only report a leg firing at 3am can make.

    def _note_error(self, leg: HybridLeg, why: str) -> None:
        """Count one failure and say once, at warning level, what could not be done."""
        _LOGGER.warning("hybrid leg %s did not fire because %s", leg.identity, why)
        self._count(leg, ok=False)

    def _count(self, leg: HybridLeg, *, ok: bool) -> None:
        """Record one firing on the rule that owns the leg, and tell the entities."""
        status = self._status.setdefault(leg.rule_id, LegStatus())
        status.fired += 1
        if not ok:
            status.errors += 1
        status.last_fired = dt_util.utcnow().isoformat()
        self._coordinator.async_update_listeners()

    def status_for(self, rule_id: str) -> LegStatus:
        """Return what one rule's legs have done, which is zeroes when it has none."""
        return self._status.get(rule_id, LegStatus())

    @property
    def totals(self) -> LegStatus:
        """Return every rule's legs added together, for the Health sensor."""
        total = LegStatus(legs=len(self._running))
        for status in self._status.values():
            total.fired += status.fired
            total.errors += status.errors
            if status.last_fired is not None and (
                total.last_fired is None or status.last_fired > total.last_fired
            ):
                total.last_fired = status.last_fired
        return total

    @property
    def allowed(self) -> bool:
        """Say whether the global option that lets a leg exist at all is on (FR-H1)."""
        return self._allowed

    @property
    def running(self) -> tuple[HybridLeg, ...]:
        """Return every leg currently listening, for diagnostics and the panel."""
        return tuple(running.leg for running in self._running.values())

    # Entities.

    def _entities_of(self, identity: str) -> tuple[str, ...]:
        """Return the load entities of the device this identity names.

        Two filters, and the second is the one that matters. The domain filter keeps out a
        switch's power sensor and its own scene events. The entity-category filter keeps out
        the ones that are in a load's domain and are not a load: a Zooz switch exposes its
        smart bulb mode as a config `switch`, and a leg that turned somebody's device
        configuration off every time they pressed a scene button would be a far stranger
        fault than the one it was written to fix.
        """
        handle = self._coordinator.handle_for(identity)
        device = None if handle is None else async_upstream_device(self._hass, self._entry, handle)
        if device is None:
            return ()
        registry = er.async_get(self._hass)
        return tuple(
            sorted(
                entry.entity_id
                for entry in er.async_entries_for_device(registry, device.id)
                if entry.domain in LOAD_DOMAINS
                and entry.entity_category is None
                and not entry.disabled
            )
        )

    def _is_on(self, entities: Sequence[str]) -> bool:
        """Say whether any of these entities is on, which is what a button LED shows.

        Any rather than all: a button that lights when the room is lit is what a user reads
        it as, and a device with two loads of which one is on is a lit room. Unavailable and
        unknown read as off, which is the honest answer for an indicator with two states: a
        light nobody can see is not a light anybody would call lit.
        """
        return any(
            (state := self._hass.states.get(entity_id)) is not None and state.state == STATE_ON
            for entity_id in entities
        )


@callback
def _is_press(data: Mapping[str, Any], *, device_id: str, scene_id: int | None) -> bool:
    """Say whether this value notification is the press one leg is waiting for.

    Three things have to agree, and the scene number is the one that matters: a filter on
    the device alone would fire every leg on a five-button controller whichever button was
    pressed, which is the failure this whole design refuses to risk. The scene number is
    read from `property_key` and falls back to `property_key_name`, because zwave-js reports
    the first as a number and the second as its zero-padded name and which one arrives has
    changed between versions.
    """
    if scene_id is None or data.get("device_id") != device_id:
        return False
    if int(data.get("command_class", 0) or 0) != CENTRAL_SCENE_COMMAND_CLASS:
        return False
    if str(data.get("value")) not in PRESSED_VALUES:
        return False
    for field_name in ("property_key", "property_key_name"):
        try:
            if int(data[field_name]) == scene_id:
                return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


__all__ = ["HybridLegs", "LegStatus"]
