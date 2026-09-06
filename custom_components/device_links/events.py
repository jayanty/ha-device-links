"""The three bus events automations are built on, and the one rule they all follow.

FR-E2 names them: `device_links_job_finished`, `device_links_drift_detected` and
`device_links_pending_wakeup`. They are the scriptable half of this integration, so what
they carry is an interface: an automation somebody wrote a year ago reads these payloads.

**Everything in a payload is plain JSON.** Not "is JSON-serializable by luck", but built
from strings, numbers, lists and dicts on purpose. A `StrEnum` survives `json.dumps` and a
`Diagnostic` does not, and the difference shows up when somebody's automation fires at
half past six in the morning rather than when the code was written. So enums are stringified
here and nothing else crosses.

**Drift fires on the edge, not on the state.** The coordinator re-resolves on every read,
which is every couple of seconds while a device is chatty, and an event per resolve would
notify on a loop for as long as a link stayed missing. That is how a user learns to filter
out the alert that matters (E4). So this holds the set of rules already reported and fires
only for what has newly gone wrong, and forgets a rule once it is in sync again so the next
failure is reported.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .const import EVENT_DRIFT_DETECTED, EVENT_JOB_FINISHED, EVENT_PENDING_WAKEUP
from .coordinator import RuleState
from .executor import LinkOutcome
from .rule_entity import async_upstream_device

if TYPE_CHECKING:
    from . import DeviceLinksConfigEntry
    from .coordinator import DeviceLinksCoordinator
    from .executor import JobReport


class DeviceLinksEventBridge:
    """Turns what the coordinator and the runner know into events on the bus."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DeviceLinksConfigEntry,
        coordinator: DeviceLinksCoordinator,
    ) -> None:
        """Hold what an event needs. Nothing is subscribed until `async_setup` runs."""
        self._hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._reported_drift: set[str] = set()
        self._unsubscribe: CALLBACK_TYPE | None = None

    @callback
    def async_setup(self) -> None:
        """Start watching for drift."""
        self._unsubscribe = self._coordinator.async_add_listener(self._async_check_drift)

    @callback
    def async_shutdown(self) -> None:
        """Stop watching, so nothing fires after the config entry has gone."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def async_job_finished(self, report: JobReport) -> None:
        """Fire the events one finished apply produces.

        Called by the runner for every job, whatever started it, so a service call, a
        button and a WebSocket command all produce the same event. Putting this on the
        runner rather than on each caller is what makes that true by construction.
        """
        outcomes: Counter[str] = Counter(str(result.outcome) for result in report.results)
        rule_ids = sorted(
            {
                rule_id
                for result in report.results
                if (rule_id := self._coordinator.owner_of(result.fingerprint)) is not None
            }
        )
        self._hass.bus.async_fire(
            EVENT_JOB_FINISHED,
            {
                "job_id": report.id,
                "scope": report.scope,
                "status": str(report.status),
                "created_at": report.created_at,
                "total": len(report.results),
                "results": dict(outcomes),
                "rule_ids": rule_ids,
            },
        )
        for result in report.results:
            if result.outcome is LinkOutcome.PENDING_WAKEUP:
                self._async_fire_pending_wakeup(result.fingerprint, result.device_identity)

    @callback
    def _async_fire_pending_wakeup(self, fingerprint: str, device_identity: str) -> None:
        """Say that a write is queued at a device that has to be woken up (E5).

        Both device references are carried: the protocol identity, which is stable and is
        what the rest of this integration keys on, and the Home Assistant device id, which
        is what a notification needs to link somebody to the device page with the wake
        instruction on it. The second can be None on a device Home Assistant does not have
        a registry entry for, which is a real state rather than an error.
        """
        handle = self._coordinator.handle_for(device_identity)
        device = None if handle is None else async_upstream_device(self._hass, self._entry, handle)
        self._hass.bus.async_fire(
            EVENT_PENDING_WAKEUP,
            {
                "rule_id": self._coordinator.owner_of(fingerprint),
                "fingerprint": fingerprint,
                "device_identity": device_identity,
                "device_id": None if device is None else device.id,
            },
        )

    @callback
    def _async_check_drift(self) -> None:
        """Fire for rules that have newly drifted, and forget the ones that recovered."""
        states = self._coordinator.drift_state()
        drifted = {rule_id for rule_id, state in states.items() if state is RuleState.DRIFT}
        newly = sorted(drifted - self._reported_drift)
        self._reported_drift = drifted
        if not newly:
            return
        profile = self._coordinator.active_profile
        payload: dict[str, Any] = {
            "profile_id": None if profile is None else profile.id,
            "rule_ids": newly,
        }
        self._hass.bus.async_fire(EVENT_DRIFT_DETECTED, payload)
