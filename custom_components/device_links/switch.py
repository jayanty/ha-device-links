"""The rule switch: one control per rule, on the device the rule starts from.

Decision D7 makes this switch physical. Off does not mute a rule, it takes the
associations off the device; on puts them back. That is the behaviour a user asked for and
it is also why every toggle goes through the shared rate limiter rather than straight to
the runner: association tables live in NVM with a finite write endurance, and an
automation toggling this in a loop would spend it (E35).

**What the switch position means, and what it deliberately does not.** It is the rule's
enabled state, which is the thing this control sets. It is not a claim that the links are
on the device, because a rule can be enabled and drifted, and there is no honest way for
one boolean to say both. Reporting `off` for a drifted rule would say the user turned it
off, which is false and would make an automation reading this act on a decision nobody
took; reporting `on` and saying nothing else would claim the house is wired the way the
rule asks. So the position follows the rule and the attributes carry the truth about the
devices: `status` is the rule state, and `links_total` against `links_in_sync` says "three
of four", which is the pair somebody can act on. Drift is additionally its own `problem`
binary sensor at the hub, which is what an alert should be built on.

When nothing can read the rule's devices the switch goes unavailable instead of picking a
position, because "we cannot say" is a state Home Assistant already has.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant

from .rule_entity import RuleEntity, RuleEntityKind, async_track_rule_entities

if TYPE_CHECKING:
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DeviceLinksConfigEntry
    from .models import Rule

# Push-updated from the coordinator, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceLinksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one switch per rule of the active profile."""
    async_track_rule_entities(
        hass,
        entry,
        async_add_entities,
        RuleEntityKind(platform=Platform.SWITCH, key_prefix="rule", factory=RuleSwitch),
    )


class RuleSwitch(RuleEntity, SwitchEntity):
    """Enable or disable one rule, which adds or removes its links."""

    _attr_translation_key = "rule_switch"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: DeviceLinksConfigEntry, rule: Rule, device: dr.DeviceEntry) -> None:
        """Build the switch for one rule, attached to that rule's source device."""
        super().__init__(entry, rule, device, key_prefix="rule")

    @property
    def is_on(self) -> bool:
        """Return whether the rule is enabled, or what the user last asked for.

        A deferred toggle shows the requested state rather than the applied one. The
        alternative snaps the switch back under the user's finger, and what a person does
        next is press it again, which is the burst the rate limiter exists to survive.
        `rate_limited` is what tells them why nothing has happened yet.
        """
        requested = self.runtime.toggles.requested_state(self.rule.id)
        if requested is not None:
            return requested
        # Read from the coordinator rather than from the rule this entity was built with:
        # `enabled` is exactly the field a toggle changes, so the snapshot would report
        # the state it had when the entity was created for as long as it lived.
        return self.coordinator.is_rule_enabled(self.rule.id, default=self.rule.enabled)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return what the position cannot say: what is really on the devices."""
        total, in_sync = self.coordinator.rule_link_counts(self.rule.id)
        profile = self.coordinator.active_profile
        return {
            "status": str(self.rule_state),
            "links_total": total,
            "links_in_sync": in_sync,
            "profile": None if profile is None else profile.name,
            "rate_limited": self.runtime.toggles.is_rate_limited(self.rule.id),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the rule and write its links, subject to the rate limit."""
        await self.runtime.toggles.async_request(self.rule.id, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the rule and take its links off the devices, subject to the rate limit."""
        await self.runtime.toggles.async_request(self.rule.id, enabled=False)
