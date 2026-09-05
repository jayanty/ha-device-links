"""Setup and unload must both succeed cleanly.

The manifest declares config_flow, so Home Assistant lists Device Links in Add
Integration. An entry that cannot set up would show a user "Error setting up entry",
which reads as broken rather than as not built yet. These tests exist so that stays true
as Phase 1 adds real work to both functions.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_links import DeviceLinksRuntimeData
from custom_components.device_links.const import DOMAIN


async def _add_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setting_up_the_entry_succeeds(hass: HomeAssistant) -> None:
    """The failure this guards against is a user seeing 'Error setting up entry'."""
    entry = await _add_entry(hass)

    assert entry.state is ConfigEntryState.LOADED, (
        f"entry did not load: {entry.state}. Home Assistant calls async_setup_entry "
        "unconditionally for a config_flow integration, so it must exist and succeed."
    )


async def test_runtime_data_is_attached_and_typed(hass: HomeAssistant) -> None:
    """Quality-scale rule runtime-data: state lives on the entry, not in hass.data."""
    entry = await _add_entry(hass)

    assert isinstance(entry.runtime_data, DeviceLinksRuntimeData)
    assert hass.data.get(DOMAIN) is None, "state belongs on runtime_data, not hass.data"


async def test_unloading_the_entry_succeeds(hass: HomeAssistant) -> None:
    entry = await _add_entry(hass)

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_the_entry_can_be_reloaded(hass: HomeAssistant) -> None:
    """Reload is setup and unload back to back, and is how a user recovers from trouble."""
    entry = await _add_entry(hass)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, DeviceLinksRuntimeData)
