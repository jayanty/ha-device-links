"""Apply and Verify: the two things a user does to a whole profile at once.

They are deliberately different in kind, and the difference is the safety property. Apply
writes; Verify never does. Verify is the read-only reproduction CLAUDE.md points a
debugging session at, so it re-reads every device from the devices themselves rather than
from the driver's cache, and its only effect is that everything reporting on the observed
state becomes current.

Both are config-category buttons on the hub, because they are about the integration rather
than about any one device. A failure from either propagates: `JobRunningError` and
`RunnerShutdownError` already carry translation keys, so the user sees a translated reason
rather than a traceback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .entity import DeviceLinksEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DeviceLinksConfigEntry

_LOGGER = logging.getLogger(__name__)

# Push-updated from the coordinator, so there is nothing to serialize.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DeviceLinksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hub buttons."""
    async_add_entities([ApplyActiveProfileButton(entry), VerifyButton(entry)])


class ApplyActiveProfileButton(DeviceLinksEntity, ButtonEntity):
    """Make the devices match the active profile."""

    _attr_translation_key = "apply_active_profile"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: DeviceLinksConfigEntry) -> None:
        """Build the apply button for this entry."""
        super().__init__(entry, "apply_active_profile")

    async def async_press(self) -> None:
        """Plan the whole active profile and apply it.

        An empty plan is not an error and does not become a job: apply on a converged
        network is what somebody presses to find out that it is converged, and spending
        one of the twenty snapshot slots on it would push out the snapshots worth keeping.
        """
        plan = await self.coordinator.async_plan()
        if plan.is_empty:
            _LOGGER.info("apply pressed with nothing to do: the devices already match")
            return
        await self.runtime.runner.async_apply(plan)


class VerifyButton(DeviceLinksEntity, ButtonEntity):
    """Re-read every device from the device itself, and write nothing."""

    _attr_translation_key = "verify"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: DeviceLinksConfigEntry) -> None:
        """Build the verify button for this entry."""
        super().__init__(entry, "verify")

    async def async_press(self) -> None:
        """Refresh every device deeply, which costs radio time and never writes."""
        await self.coordinator.async_refresh(deep=True)
