"""Setup and unload, and the judgment call about what "not ready" means here.

`after_dependencies` asks Home Assistant to load `zwave_js` before this integration if it
is going to load it at all, and does not order it otherwise. So being set up before the
Z-Wave driver exists is a normal event on a slow start, not a fault, and the only correct
answer to it is `ConfigEntryNotReady`: Home Assistant retries with a backoff and the entry
comes up by itself. The alternative, setting up with no backends, produces an integration
that says it is loaded, shows every device unavailable, and never recovers on its own.

The same code path covers a user who removed Z-Wave JS, which never becomes ready. That
shows as "Retrying setup", which is an honest description of an integration that adapts
protocol integrations and has none to adapt, and Task 6's Repairs issue (E1) is what turns
it into an explanation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_links import DeviceLinksRuntimeData
from custom_components.device_links.const import DOMAIN
from custom_components.device_links.models import Backend as BackendId


async def _add_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setting_up_the_entry_succeeds(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """The failure this guards against is a user seeing 'Error setting up entry'."""
    assert device_links_entry.state is ConfigEntryState.LOADED, (
        f"entry did not load: {device_links_entry.state}"
    )


async def test_runtime_data_is_attached_and_typed(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Quality-scale rule runtime-data: state lives on the entry, not in hass.data."""
    runtime = device_links_entry.runtime_data

    assert isinstance(runtime, DeviceLinksRuntimeData)
    assert BackendId.ZWAVE in runtime.backends
    assert hass.data.get(DOMAIN) is None, "state belongs on runtime_data, not hass.data"


async def test_setup_is_retried_when_no_upstream_integration_has_loaded(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Not ready, not failed: `after_dependencies` does not order zwave_js before us.

    A retry is what makes a slow Z-Wave JS start recover by itself. Coming up loaded with
    no backends would look fine, report every device unavailable forever, and need a
    manual reload nobody would know to do.
    """
    entry = await _add_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_is_retried_when_zwave_js_is_loaded_but_not_connected(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A loaded entry whose client has no driver yet is the same temporary situation."""
    zwave_js_entry = MockConfigEntry(domain="zwave_js", title="Z-Wave JS")
    zwave_js_entry.add_to_hass(hass)
    zwave_js_entry.runtime_data = SimpleNamespace(client=SimpleNamespace(driver=None, version=None))
    zwave_js_entry.mock_state(hass, ConfigEntryState.LOADED)

    entry = await _add_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_zwave_js_entry_that_has_not_loaded_yet_is_skipped(
    hass: HomeAssistant, hass_storage: dict[str, Any], zwave_driver: Any
) -> None:
    """A Z-Wave entry still starting must not stop the loaded one from being used.

    Registered first on purpose: a loop that took the first entry it saw rather than the
    first loaded one would pass this test if the order were the other way round.
    """
    starting = MockConfigEntry(domain="zwave_js", title="Z-Wave JS (starting)")
    starting.add_to_hass(hass)
    starting.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    loaded = MockConfigEntry(domain="zwave_js", title="Z-Wave JS")
    loaded.add_to_hass(hass)
    loaded.runtime_data = SimpleNamespace(client=SimpleNamespace(driver=zwave_driver, version=None))
    loaded.mock_state(hass, ConfigEntryState.LOADED)

    entry = await _add_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert BackendId.ZWAVE in entry.runtime_data.backends


async def test_unloading_the_entry_succeeds_and_leaves_nothing_running(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Unload is the mirror of setup: no listener, no timer and no job left behind."""
    runtime = device_links_entry.runtime_data

    assert await hass.config_entries.async_unload(device_links_entry.entry_id) is True
    await hass.async_block_till_done()

    assert device_links_entry.state is ConfigEntryState.NOT_LOADED
    assert runtime.coordinator.listener_count == 0


async def test_the_entry_can_be_reloaded(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Reload is setup and unload back to back, and is how a user recovers from trouble."""
    await hass.config_entries.async_reload(device_links_entry.entry_id)
    await hass.async_block_till_done()

    assert device_links_entry.state is ConfigEntryState.LOADED
    assert isinstance(device_links_entry.runtime_data, DeviceLinksRuntimeData)


async def test_an_unreadable_stored_file_fails_setup_rather_than_starting_empty(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """E18: coming up empty would let the next save overwrite what could not be read.

    Read-only mode and the Repairs issue E18 asks for are Task 6's. What cannot wait is
    not starting with an empty profile list on top of a file full of somebody's work.
    """
    hass_storage["device_links.profiles"] = {
        "version": 1,
        "minor_version": 1,
        "key": "device_links.profiles",
        "data": {"profiles": [{"this": "is not a profile"}]},
    }

    entry = await _add_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert hass_storage["device_links.profiles"]["data"] == {
        "profiles": [{"this": "is not a profile"}]
    }, "the file that could not be read was written over"


async def test_a_profile_database_that_cannot_be_read_does_not_stop_setup(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without curated profiles every device falls back to its own groups, which is fine."""
    import custom_components.device_links as integration  # noqa: PLC0415

    def unreadable(*args: object, **kwargs: object) -> dict[str, str]:
        raise ValueError("zooz.json is not valid JSON")

    monkeypatch.setattr(integration, "load_profiles", unreadable)

    entry = await _add_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.profiles is None
    assert "fall back to the association groups" in caplog.text


async def test_nothing_is_torn_down_when_a_platform_refuses_to_unload(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed unload leaves live entities, which must not be holding a dead runner."""

    async def refuse(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", refuse)
    runtime = device_links_entry.runtime_data

    from custom_components.device_links import async_unload_entry  # noqa: PLC0415

    assert await async_unload_entry(hass, device_links_entry) is False
    assert runtime.coordinator.listener_count > 0, "the coordinator was torn down anyway"

    # Put the platform back before the fixture unloads for real. An entry that cannot
    # unload keeps everything it registered, timers included, which is the point of the
    # assertion above and would otherwise leave one behind for the next test to trip on.
    monkeypatch.undo()


async def test_a_platform_that_fails_to_set_up_leaves_nothing_subscribed(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Home Assistant does not unload an entry that never loaded, so setup has to.

    By the time the platforms are forwarded, every backend is already subscribed and the
    coordinator's debounced refresh is armed. A failure past that point would otherwise
    leave both running for the life of the process, and the next reload would add a second
    set on top.
    """

    async def refuse(*args: object, **kwargs: object) -> None:
        raise HomeAssistantError("the switch platform would not load")

    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", refuse)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not hass.states.async_entity_ids("sensor"), "entities survived a failed setup"
    # The subscription is one "value updated" listener per node on the driver, so this is
    # the state the leak would be visible in: nothing left listening to the radio.
    assert not [
        node
        for node in zwave_driver.controller.nodes.values()
        if node._listeners.get("value updated")
    ], "a backend subscription outlived a setup that failed"
