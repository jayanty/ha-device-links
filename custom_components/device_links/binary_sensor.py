"""The drift sensor: one problem sensor for "the house no longer matches the profile".

Drift is a fault and is worth an automation, which is why it is a `problem` binary sensor
rather than a state on the profile sensor: `problem` is the device class Home Assistant's
own alerting understands, so a user can send themselves a notification without writing a
template.

What it deliberately does not turn on for is a device nobody can read. That is `unknown`
in the coordinator and it stays out of here, because a battery remote asleep or an add-on
restarting is not drift, and an alert that fires for both is one a user turns off (E4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .coordinator import RuleState
from .entity import DeviceLinksEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DeviceLinksConfigEntry

# Push-updated from the coordinator, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceLinksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub binary sensors."""
    async_add_entities([DriftBinarySensor(entry)])


class DriftBinarySensor(DeviceLinksEntity, BinarySensorEntity):
    """On when any rule of the active profile has drifted from what was applied."""

    _attr_translation_key = "drift"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: DeviceLinksConfigEntry) -> None:
        """Build the drift sensor for this entry."""
        super().__init__(entry, "drift")

    @property
    def is_on(self) -> bool:
        """Say whether anything that was applied is no longer on its device."""
        return any(state is RuleState.DRIFT for state in self.coordinator.drift_state().values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Name the rules that drifted, so the alert can be acted on from itself."""
        return {
            "drifted_rules": sorted(
                rule_id
                for rule_id, state in self.coordinator.drift_state().items()
                if state is RuleState.DRIFT
            )
        }
