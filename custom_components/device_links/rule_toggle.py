"""The one place a rule is enabled or disabled, and the rate limit that guards a radio.

A rule switch physically adds and removes associations (Decision D7), and a Z-Wave
association table lives in the device's non-volatile memory, which has a finite write
endurance. An automation that toggles a rule in a loop is therefore not merely noisy: it
spends a hardware budget somebody paid for and cannot top up. E35 and FR-E1 answer that
with a rate limit of one executed toggle per rule per 30 seconds, with a burst coalesced
into whatever state the caller last asked for.

**The limiter is not on the entity, deliberately.** A rule can be enabled from the switch,
from `device_links.set_rule_enabled`, and from the panel's WebSocket command, and those
last two are what an automation would actually use. A limiter that lived on the switch
would be bypassed by exactly the callers that make the failure possible, so it lives here,
on the config entry's runtime data, and every surface calls it. It is not in the
coordinator either, for a structural reason worth keeping: the coordinator knows nothing
about the job runner and must not, since the runner depends on it. This module is where
the two meet, and it is the only place they do.

**Leading edge, trailing coalesce.** The first request is executed at once, because a
switch that did nothing for thirty seconds is a switch a user presses again. Everything
that arrives during the cooldown is remembered as one pending state, and when the cooldown
ends that state is executed unless it is already what was executed. So a burst that ends
where it started costs one write, and a burst that ends somewhere else costs two: one now
and one when it is allowed.
"""

from __future__ import annotations

from functools import partial
import logging
from typing import TYPE_CHECKING, Final

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .coordinator import DeviceLinksCoordinator, PlanScope
from .executor import JobRunner, JobRunningError, RunnerShutdownError

if TYPE_CHECKING:
    from datetime import datetime

_LOGGER = logging.getLogger(__name__)

# E35 and FR-E1: at most one executed toggle per rule per 30 seconds.
TOGGLE_MIN_INTERVAL_SECONDS: Final = 30.0


class RuleToggleLimiter:
    """Enables and disables rules, at most one write per rule per interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DeviceLinksCoordinator,
        runner: JobRunner,
        *,
        min_interval_seconds: float = TOGGLE_MIN_INTERVAL_SECONDS,
    ) -> None:
        """Hold what a toggle needs. Nothing is scheduled until something is requested."""
        self._hass = hass
        self._coordinator = coordinator
        self._runner = runner
        self._min_interval = min_interval_seconds

        # rule id -> the cooldown timer that is running for it.
        self._cooldowns: dict[str, CALLBACK_TYPE] = {}
        # rule id -> the state a caller asked for during a cooldown and has not got yet.
        self._pending: dict[str, bool] = {}
        # rule id -> the state the last executed toggle carried, so a coalesced burst that
        # ends where it started can be recognised and cost nothing.
        self._executed: dict[str, bool] = {}
        # Whether the config entry is going away. A cooldown callback that was already
        # dispatched when shutdown ran finishes after it, and would otherwise start a fresh
        # timer that nothing is left to cancel: the entry is gone, so it fires at a
        # discarded coordinator and survives a reload, which is the leak this module's
        # docstring rules out.
        self._shut_down = False

    async def async_request(self, rule_id: str, *, enabled: bool) -> None:
        """Ask for a rule to be enabled or disabled, subject to the rate limit."""
        if self._shut_down:
            _LOGGER.debug("rule %s was toggled while unloading, so nothing was done", rule_id)
            return
        if rule_id in self._cooldowns:
            self._pending[rule_id] = enabled
            _LOGGER.debug(
                "rule %s was toggled inside the %ss rate limit window, so the request is "
                "coalesced and applied when the window closes",
                rule_id,
                self._min_interval,
            )
            self._coordinator.async_update_listeners()
            return
        await self._async_execute(rule_id, enabled)
        self._start_cooldown(rule_id)

    @callback
    def is_rate_limited(self, rule_id: str) -> bool:
        """Say whether this rule has a request waiting for the window to close."""
        return rule_id in self._pending

    @callback
    def requested_state(self, rule_id: str) -> bool | None:
        """Return the state last asked for and not yet executed, or None when there is none.

        What a switch shows while a toggle is deferred. Showing the applied state instead
        would snap the switch back under the user's finger, and the next thing they do is
        press it again, which is the burst this class exists to survive.
        """
        return self._pending.get(rule_id)

    @callback
    def async_shutdown(self) -> None:
        """Cancel every pending toggle, because the entry is going away.

        A timer that outlives the config entry fires at a runner that has been shut down
        and a store that is being discarded, and it survives a reload.
        """
        self._shut_down = True
        for cancel in self._cooldowns.values():
            cancel()
        self._cooldowns.clear()
        self._pending.clear()

    async def _async_execute(self, rule_id: str, enabled: bool) -> None:
        """Record the intent, then apply exactly that rule's work and nothing else."""
        self._executed[rule_id] = enabled
        if not self._coordinator.async_set_rule_enabled(rule_id, enabled):
            _LOGGER.debug("no rule %s in the active profile, so nothing was toggled", rule_id)
            return
        scope = PlanScope(rule_ids=frozenset({rule_id}))
        plan = await self._coordinator.async_plan(scope)
        if plan.is_empty:
            return
        try:
            await self._runner.async_apply(plan, scope=scope)
        except (JobRunningError, RunnerShutdownError):
            # The intent is stored and the links are not written, which is what the rule's
            # status sensor already calls `pending` or `drift`. Raising here would only
            # move the problem to a caller that has no better answer than pressing Apply,
            # which is exactly what the user can do from the state they can now see.
            _LOGGER.warning(
                "rule %s was toggled to %s but its links could not be written now, so it "
                "reports as not applied until the next apply",
                rule_id,
                "enabled" if enabled else "disabled",
                exc_info=True,
            )

    def _start_cooldown(self, rule_id: str) -> None:
        """Start the window during which further toggles of this rule only coalesce."""
        if self._shut_down:
            return
        self._cooldowns[rule_id] = async_call_later(
            self._hass, self._min_interval, partial(self._async_cooldown_elapsed, rule_id)
        )

    async def _async_cooldown_elapsed(self, rule_id: str, _now: datetime) -> None:
        """Apply whatever was asked for during the window, unless it is already true."""
        self._cooldowns.pop(rule_id, None)
        pending = self._pending.pop(rule_id, None)
        if pending is None or pending == self._executed.get(rule_id):
            self._coordinator.async_update_listeners()
            return
        await self._async_execute(rule_id, pending)
        self._start_cooldown(rule_id)
        self._coordinator.async_update_listeners()
