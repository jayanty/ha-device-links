"""The active profile select, and the one thing it must not do.

Decision D10 makes exactly one profile active, which is what makes a select the right
control: it is a radio button over the whole configuration, not a set of toggles.

**Selecting does not apply.** A select box is a control people try in order to find out
what it does, and this one names sets of associations across a whole house. If picking one
wrote to the devices, the way a user discovers what "Away" means is by having it happen to
them, at whatever time of day they were curious, with no dialog and nothing to cancel. So
selecting activates the profile and opens a plan (FR-E1), which is a read-only description
of the work the switch implies, and applying it is a separate, deliberate act. Auto-apply
exists as an option because somebody may genuinely want it, and it is off unless they say
so. That option is read here and nowhere else on purpose: the panel and the WebSocket
command behind it always show the plan first (Decision D18), and this is the one control
that has nowhere to show one.

Options are profile names rather than ids, because a name is what the user wrote and an id
is what the panel generated. Nothing enforces that two profiles have different names, so a
duplicate name reaches the first profile that carries it; that is a naming problem the
panel can prevent, and it is better than showing a list of slugs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, OPTION_AUTO_APPLY_ON_PROFILE_SWITCH
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
    """Set up the active profile select."""
    async_add_entities([ActiveProfileSelect(entry)])


class ActiveProfileSelect(DeviceLinksEntity, SelectEntity):
    """Which of the stored profiles is the one in force."""

    _attr_translation_key = "active_profile"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: DeviceLinksConfigEntry) -> None:
        """Build the profile select for this entry."""
        super().__init__(entry, "active_profile")

    @property
    def options(self) -> list[str]:
        """Return the stored profiles by name, in a stable order."""
        return sorted(profile.name for profile in self.coordinator.state.profiles)

    @property
    def current_option(self) -> str | None:
        """Return the active profile's name, or None when none is active."""
        profile = self.coordinator.active_profile
        return None if profile is None else profile.name

    async def async_select_option(self, option: str) -> None:
        """Activate this profile and open a plan, without writing to anything."""
        profile = next(
            (
                candidate
                for candidate in self.coordinator.state.profiles
                if candidate.name == option
            ),
            None,
        )
        if profile is None:
            # The list a user picked from can be older than the profiles are: one may have
            # been renamed or deleted in the panel since the page was opened.
            raise ServiceValidationError(
                f"no profile is named {option!r}",
                translation_domain=DOMAIN,
                translation_key="unknown_profile",
                translation_placeholders={"profile": option},
            )
        self.coordinator.async_activate_profile(profile.id)
        self.runtime.pending_plan = await self.coordinator.async_plan()
        _LOGGER.info(
            "profile %s is active; its plan holds %s change(s) and nothing has been written",
            profile.id,
            len(self.runtime.pending_plan.items),
        )
        if self._entry.options.get(OPTION_AUTO_APPLY_ON_PROFILE_SWITCH, False):
            await self.runtime.runner.async_apply(self.runtime.pending_plan)
