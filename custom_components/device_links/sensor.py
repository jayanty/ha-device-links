"""The sensors: health, the active profile's aggregate state, and what is waiting.

The Health sensor earns the length of this module. PRD Section 17.1 makes it the one
entity read first when something is wrong on a system nobody can attach a debugger to, so
it has two properties the others do not.

**It never goes unavailable.** Every other entity here disappears when no backend
answers, which is honest: nothing can be said about a house nobody can see. If this one
did the same, the state that says the backends are down would itself be `unavailable`,
and the first thing a remote session reads would tell it nothing. So it stays available
and says `error`, which is the answer somebody needs at that moment.

**A missing `.deployed` file reports `ok`.** That file is written by the dev deploy tool
and a HACS install has none. Treating its absence as a fault would make every normal
install look broken on the one read that decides where an investigation goes next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant

from .coordinator import RuleState
from .entity import DeviceLinksEntity
from .rule_entity import RuleEntity, RuleEntityKind, async_track_rule_entities

if TYPE_CHECKING:
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DeviceLinksConfigEntry
    from .models import Rule

# Entities here are pushed to by the coordinator rather than polled, so there is nothing
# for Home Assistant to serialize (quality-scale rule parallel-updates).
PARALLEL_UPDATES = 0

# What the Health sensor can say. `degraded` is the useful one: it means the integration
# is running and something it depends on is not, which is the state that explains why a
# rule is not being applied without claiming the integration itself has failed.
HEALTH_OK: Final = "ok"
HEALTH_DEGRADED: Final = "degraded"
HEALTH_ERROR: Final = "error"
HEALTH_STATES: Final = (HEALTH_OK, HEALTH_DEGRADED, HEALTH_ERROR)

# The rule states a status sensor can report, in the order PRD Section 6.6 lists them.
# `applying` is the executor's, and the coordinator never invents it: it is added here
# because a rule that is mid-job is neither in sync nor drifted and saying either would
# be wrong for as long as the job runs.
RULE_STATES: Final = (
    str(RuleState.IN_SYNC),
    str(RuleState.DRIFT),
    str(RuleState.PENDING),
    "applying",
    str(RuleState.BLOCKED),
    str(RuleState.DISABLED),
    str(RuleState.UNKNOWN),
)

# Worst first. An aggregate that reported the best of what it saw would say `in_sync` for
# a profile with one blocked rule in it, which is the report that stops anybody looking.
_AGGREGATION_ORDER: Final = (
    RuleState.BLOCKED,
    RuleState.DRIFT,
    RuleState.PENDING,
    RuleState.UNKNOWN,
    RuleState.DISABLED,
    RuleState.IN_SYNC,
)

# A job status that is not this one means the last apply did not do everything it set out
# to, which is a reason to say `degraded` rather than `ok`.
_JOB_COMPLETED: Final = "completed"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceLinksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub sensors, and one status sensor per rule of the active profile."""
    async_add_entities(
        [
            DeviceLinksHealthSensor(entry),
            ActiveProfileStatusSensor(entry),
            PendingLinksSensor(entry),
        ]
    )
    async_track_rule_entities(
        hass,
        entry,
        async_add_entities,
        RuleEntityKind(
            platform=Platform.SENSOR, key_prefix="rule_status", factory=RuleStatusSensor
        ),
    )


class DeviceLinksHealthSensor(DeviceLinksEntity, SensorEntity):
    """One cheap entity that summarizes everything, for the person who cannot see more."""

    _attr_translation_key = "health"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, entry: DeviceLinksConfigEntry) -> None:
        """Build the health sensor for this entry."""
        super().__init__(entry, "health")
        self._attr_options = list(HEALTH_STATES)

    @property
    def available(self) -> bool:
        """Always available, deliberately: see this module's docstring."""
        return True

    @property
    def native_value(self) -> str:
        """Return `ok`, `degraded` or `error`, in that order of badness.

        `error` is "nothing can be read", because at that point no other entity here is
        saying anything true. `degraded` is "something is impaired": a backend that is
        down while another is up, or a last apply that did not finish cleanly. Drift is
        deliberately not folded in: a drifted link is the house disagreeing with the
        profile, which the drift sensor is for, and reporting the integration as unwell
        because a user unplugged a lamp would make this state mean nothing.
        """
        availability = self.coordinator.backend_availability
        if not any(availability.values()):
            return HEALTH_ERROR
        if not all(availability.values()) or self._last_job_status not in (None, _JOB_COMPLETED):
            return HEALTH_DEGRADED
        return HEALTH_OK

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return everything a remote debugging session asks for after the state."""
        deployment = self.runtime.deployment
        jobs = self.coordinator.state.jobs
        return {
            "version": self.runtime.version,
            "commit": None if deployment is None else deployment.commit,
            "branch": None if deployment is None else deployment.branch,
            "deployed_at": None if deployment is None else deployment.deployed_at,
            "backends": {
                str(backend.backend_id): {
                    "available": self.coordinator.backend_availability.get(
                        backend.backend_id, False
                    ),
                    "upstream": backend.upstream_domain,
                    "upstream_version": backend.upstream_version,
                }
                for backend in self.runtime.backend_info
            },
            "jobs": {
                "total": len(jobs),
                "last_status": self._last_job_status,
                "last_at": jobs[-1].created_at if jobs else None,
            },
            "last_error": self.coordinator.last_error,
            # PRD Section 6.6 asks the Health sensor for the hybrid-leg counters, and this
            # is the one place a remote session can see that Home Assistant is standing in
            # for a wire somewhere in this house, and how often it has failed to.
            "hybrid": {
                "allowed": self.runtime.hybrid.allowed,
                **self.runtime.hybrid.totals.as_attributes(),
            },
        }

    @property
    def _last_job_status(self) -> str | None:
        """Return how the most recent apply ended, or None when none has run."""
        jobs = self.coordinator.state.jobs
        return jobs[-1].status if jobs else None


class ActiveProfileStatusSensor(DeviceLinksEntity, SensorEntity):
    """What the active profile's rules add up to, worst state first."""

    _attr_translation_key = "active_profile_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, entry: DeviceLinksConfigEntry) -> None:
        """Build the active profile status sensor for this entry."""
        super().__init__(entry, "active_profile_status")
        self._attr_options = list(RULE_STATES)

    @property
    def native_value(self) -> str:
        """Return the worst state any rule of the active profile is in.

        A job in flight wins over everything, for the same reason it does on a per-rule
        sensor: what is on the devices is mid-change, and calling that in sync or drifted
        is a statement about a state that has not settled.

        No profile and no rules both read `unknown` rather than `in_sync`: an empty
        profile has not converged on anything, and saying it has would be a claim about a
        house nobody has described yet.
        """
        if self.runtime.runner.active_rule_ids:
            return "applying"
        states = list(self.coordinator.drift_state().values())
        if not states:
            return str(RuleState.UNKNOWN)
        return str(next(state for state in _AGGREGATION_ORDER if state in states))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the profile this is about and how its rules break down."""
        states = self.coordinator.drift_state()
        profile = self.coordinator.active_profile
        return {
            "profile": None if profile is None else profile.name,
            "profile_id": None if profile is None else profile.id,
            "rules": len(states),
            "by_state": {
                str(state): sum(1 for value in states.values() if value is state)
                for state in _AGGREGATION_ORDER
                if any(value is state for value in states.values())
            },
        }


class PendingLinksSensor(DeviceLinksEntity, SensorEntity):
    """How many links a job queued at a device that was asleep (E5).

    Disabled by default because on a network with no battery controllers it reads zero
    forever, and an entity that is always zero is a state row per restart and a line in
    every dashboard picker for nothing.
    """

    _attr_translation_key = "pending_links"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: DeviceLinksConfigEntry) -> None:
        """Build the pending links sensor for this entry."""
        super().__init__(entry, "pending_links")

    @property
    def native_value(self) -> int:
        """Return how many links are still waiting for a device to wake up."""
        return len(self.coordinator.pending_link_fingerprints())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return which links they are, so the count can be acted on rather than watched."""
        return {"fingerprints": sorted(self.coordinator.pending_link_fingerprints())}


class RuleStatusSensor(RuleEntity, SensorEntity):
    """What one rule's links are doing, on that rule's own device page.

    Disabled by default: a house with forty rules would otherwise carry forty extra state
    rows, forty recorder streams and forty entries in every entity picker, to say what the
    rule switch already says in an attribute. It is here for the person who wants to graph
    one rule or trigger on it, which is worth enabling one entity by hand for.
    """

    _attr_translation_key = "rule_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, entry: DeviceLinksConfigEntry, rule: Rule, device: dr.DeviceEntry) -> None:
        """Build the status sensor for one rule, attached to that rule's source device."""
        super().__init__(entry, rule, device, key_prefix="rule_status")
        self._attr_options = list(RULE_STATES)

    @property
    def native_value(self) -> str:
        """Return the rule's state, with `applying` taking precedence while a job runs.

        A rule that is being written is neither in sync nor drifted: what is on the device
        is mid-change, and reporting either would be a statement about a state that has
        not settled. The coordinator never invents `applying`, because it cannot see the
        runner, so this is where the two are put together.
        """
        if self.rule.id in self.runtime.runner.active_rule_ids:
            return "applying"
        return str(self.rule_state)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the counts that make a drifted rule actionable rather than alarming."""
        total, in_sync = self.coordinator.rule_link_counts(self.rule.id)
        return {
            "links_total": total,
            "links_in_sync": in_sync,
            "rule_id": self.rule.id,
            # FR-H2. Zeroes for a rule with no HA-executed leg, which is most of them, and
            # a count that only moves when Home Assistant did something a radio could not.
            **self.runtime.hybrid.status_for(self.rule.id).as_attributes(),
        }
