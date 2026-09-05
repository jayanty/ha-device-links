"""The Device Links integration.

Phase 1 adds the sidebar panel, the backends, the rule entities, and the services. Until
then this sets up and unloads cleanly and does nothing else, which is deliberate: the
manifest declares config_flow, so Home Assistant offers the integration in the Add
Integration list, and an entry that cannot set up would surface as "Error setting up
entry" rather than as "not built yet".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

__all__ = ["DOMAIN", "DeviceLinksRuntimeData", "async_setup_entry", "async_unload_entry"]


@dataclass
class DeviceLinksRuntimeData:
    """Everything the integration keeps for the lifetime of its config entry.

    Quality-scale rule runtime-data: state lives here rather than in hass.data, and the
    entry is typed as DeviceLinksConfigEntry so mypy checks access to it. Phase 1 fills
    this with the coordinator, the backends, and the job runner.
    """

    backends: dict[str, object] = field(default_factory=dict)


type DeviceLinksConfigEntry = ConfigEntry[DeviceLinksRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> bool:
    """Set up Device Links from a config entry."""
    entry.runtime_data = DeviceLinksRuntimeData()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> bool:
    """Unload a config entry.

    Phase 1 removes event subscriptions, unregisters the panel, and cancels running jobs
    here. There is nothing to tear down yet, so this only has to succeed.
    """
    return True
