"""What every Device Links entity has in common: a device, a subscription, availability.

The **hub** is a service device named "Device Links", and everything that is about the
integration rather than about a piece of the house goes on it: health, drift, the active
profile, the buttons. Rule entities go somewhere else entirely, onto the user's own
device entry; `rule_entity.py` is where that lives, because attaching to a device
somebody else created has a failure mode of its own that deserves its own module.

Subscription is explicit rather than through `async_on_remove`, because
`entity-event-setup` is about a listener outliving its entity and the clearest way to
show that it does not is to unsubscribe in the method named after the moment it must
happen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, INTEGRATION_TITLE

if TYPE_CHECKING:
    from . import DeviceLinksConfigEntry, DeviceLinksRuntimeData
    from .coordinator import DeviceLinksCoordinator


@callback
def async_hub_device_info(entry: DeviceLinksConfigEntry) -> DeviceInfo:
    """Return the integration's own service device.

    Keyed by the config entry id rather than by the domain, so a second entry (which the
    config flow refuses today) could never collide with the first one's device.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=INTEGRATION_TITLE,
        manufacturer=INTEGRATION_TITLE,
        entry_type=DeviceEntryType.SERVICE,
    )


class DeviceLinksEntity(Entity):
    """The base every Device Links entity shares.

    Push-updated: the coordinator calls back when anything changes, so nothing polls and
    `should_poll` is false. Availability follows the backends rather than the entry,
    because an entry that is loaded while nothing answers is exactly the state a user has
    to be able to see (quality-scale rule entity-unavailable).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: DeviceLinksConfigEntry, key: str) -> None:
        """Hold the entry's runtime and claim a unique id derived from the entry."""
        self._entry = entry
        self.runtime: DeviceLinksRuntimeData = entry.runtime_data
        self.coordinator: DeviceLinksCoordinator = entry.runtime_data.coordinator
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = async_hub_device_info(entry)
        self._unsubscribe: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        """Start listening to the coordinator (quality-scale rule entity-event-setup)."""
        self._unsubscribe = self.coordinator.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening, so no callback outlives this entity."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def _handle_update(self) -> None:
        """Write this entity's state again, because something it displays changed."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Say whether anything can be read right now."""
        return self.coordinator.available
