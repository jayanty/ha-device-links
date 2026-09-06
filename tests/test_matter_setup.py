"""Wiring the Matter backend into the product: the config entry, the option, the sensor.

The Zigbee equivalent of this file (`tests/test_zigbee_setup.py`) exists because the
adapter had been exercised for a whole phase and nothing in the product built one
(open item T42). This one is written before that can happen again.

Two layers, tested separately on purpose, exactly as they are there.

**The seam** (`backends/matter_client.py`) has its own file: it is checked against the
installed `matter` integration's own source, because what it is for is knowing how Home
Assistant holds its client, and that library is not importable in this environment.

**The wiring** (`__init__.py`) is checked here with the fake fabric standing in for the
client, because what it is for is what gets built, what gets said, and what the Matter
writes option actually reaches.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.device_links as integration
from custom_components.device_links.backends.matter_client import MatterAccessorError
from custom_components.device_links.const import DOMAIN, OPTION_MATTER_WRITES
from custom_components.device_links.models import Backend as BackendId
from tests.factories import KITCHEN_ACCENT, matter_handle
from tests.fakes.matter import COMPRESSED_FABRIC_ID, FakeMatterClient, build_fabric_from_fixture

MATTER_DOMAIN = "matter"


@pytest.fixture
def fabric() -> FakeMatterClient:
    """Jayant's Matter fabric as the M1 capture found it."""
    return build_fabric_from_fixture()


@pytest.fixture
def matter_entry(hass: HomeAssistant, fabric: FakeMatterClient) -> Iterator[MockConfigEntry]:
    """Return a loaded `matter` config entry whose adapter holds the fake fabric.

    Shaped exactly as `matter_client.async_get_client` reads it
    (`runtime_data.adapter.matter_client`), because that accessor is the one supported way
    in and a fixture that took a short cut around it would stop testing the coupling CI is
    meant to guard.

    Marked not loaded again on teardown, exactly as the `zwave_js_entry` fixture is: Home
    Assistant would otherwise try to unload this stand-in at shutdown, which means importing
    the real `matter` integration, which imports a library this environment does not have.
    """
    hass.config.components.add(MATTER_DOMAIN)
    entry = MockConfigEntry(domain=MATTER_DOMAIN, title="Matter", entry_id="matterentry")
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=fabric))
    entry.mock_state(hass, ConfigEntryState.LOADED)
    yield entry
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
def matter_devices(
    hass: HomeAssistant, fabric: FakeMatterClient, matter_entry: MockConfigEntry
) -> dict[int, dr.DeviceEntry]:
    """Register one device entry per node, with the identifier the P2 capture recorded.

    Built from the same fake fabric the adapter reads, so a test cannot pass because the
    fixture and the adapter agree on a value neither of them got from the capture.
    """
    registry = dr.async_get(hass)
    devices: dict[int, dr.DeviceEntry] = {}
    for node_id, node in fabric.nodes.items():
        instance = f"{COMPRESSED_FABRIC_ID:016X}-{node_id:016X}"
        devices[node_id] = registry.async_get_or_create(
            config_entry_id=matter_entry.entry_id,
            identifiers={(MATTER_DOMAIN, f"deviceid_{instance}-MatterNodeDevice")},
            manufacturer=node.device_info.vendorName if node.device_info else None,
            model=node.device_info.productName if node.device_info else None,
            name=node.name,
        )
    return devices


@pytest.fixture
async def matter_house(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    matter_entry: MockConfigEntry,
    matter_devices: dict[int, dr.DeviceEntry],
) -> AsyncGenerator[MockConfigEntry]:
    """Device Links set up over the fake Matter fabric, and nothing else.

    A Matter-only house, which is an ordinary house and one this integration has claimed to
    support since its config flow was written. Until Phase 3 it would have set up with no
    backends at all and retried forever.
    """
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_a_matter_only_house_sets_up(matter_house: MockConfigEntry) -> None:
    """The config flow has offered this since Phase 1 and nothing could deliver it."""
    runtime = matter_house.runtime_data

    assert set(runtime.backends) == {BackendId.MATTER}
    assert [info.upstream_domain for info in runtime.backend_info] == ["matter"]


async def test_the_matter_devices_are_read_at_setup(matter_house: MockConfigEntry) -> None:
    """A backend that is built and never read is a backend nothing uses."""
    coordinator = matter_house.runtime_data.coordinator

    assert len(coordinator.devices) == 19
    assert coordinator.backend_availability[BackendId.MATTER] is True


async def test_the_paddle_is_offered_as_a_control_end_to_end(
    matter_house: MockConfigEntry,
) -> None:
    """The whole read path, through the product rather than through the adapter alone."""
    coordinator = matter_house.runtime_data.coordinator
    capabilities = coordinator.capabilities_for(matter_handle(KITCHEN_ACCENT).identity)

    assert capabilities is not None
    (paddle,) = capabilities.emitters
    assert paddle.label == "Paddle"


async def test_the_upstream_version_comes_from_the_server(
    matter_house: MockConfigEntry,
) -> None:
    """The Matter half of "which server is this", which a remote session reads first."""
    (info,) = matter_house.runtime_data.backend_info

    assert info.upstream_version == "matter-server/1.4.0 (matter.js/0.17.9)"


async def test_the_health_sensor_reports_the_matter_backend(
    hass: HomeAssistant, matter_house: MockConfigEntry
) -> None:
    state = hass.states.get("sensor.device_links_health")

    assert state is not None
    assert state.attributes["backends"]["matter"] == {
        "available": True,
        "upstream": "matter",
        "upstream_version": "matter-server/1.4.0 (matter.js/0.17.9)",
    }


async def test_writes_are_off_until_the_option_is_turned_on(
    matter_house: MockConfigEntry,
) -> None:
    """FR-B7 and Decision D11, reached through the product rather than the constructor."""
    backend = matter_house.runtime_data.backends[BackendId.MATTER]

    assert backend._writes_enabled is False


async def test_turning_the_option_on_reaches_the_adapter(
    hass: HomeAssistant, matter_house: MockConfigEntry
) -> None:
    """Saving the option reloads the entry, which is what rebuilds the backend."""
    hass.config_entries.async_update_entry(matter_house, options={OPTION_MATTER_WRITES: True})
    await hass.async_block_till_done()

    backend = matter_house.runtime_data.backends[BackendId.MATTER]
    assert backend._writes_enabled is True


async def test_the_entities_attach_to_the_matter_integrations_own_devices(
    hass: HomeAssistant, matter_house: MockConfigEntry, matter_devices: dict[int, dr.DeviceEntry]
) -> None:
    """FR-E1: an identifier that does not match makes an orphan device, not an error."""
    registry = dr.async_get(hass)
    backend = matter_house.runtime_data.backends[BackendId.MATTER]

    identifier = backend.registry_identifier(matter_handle(KITCHEN_ACCENT))

    assert identifier is not None
    assert registry.async_get_device({identifier}) == matter_devices[KITCHEN_ACCENT]


async def test_a_house_with_no_matter_integration_builds_nothing(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Silent, because a house with no Matter fabric is an ordinary house."""
    with caplog.at_level("DEBUG", logger="custom_components.device_links"):
        built = integration._build_matter(hass, _entry(hass), None)

    assert built is None
    assert "no Matter fabric is adapted" in caplog.text


async def test_a_matter_entry_that_is_not_loaded_yet_is_skipped(
    hass: HomeAssistant, matter_entry: MockConfigEntry
) -> None:
    """`after_dependencies` does not order it before us, so this is normal on a slow start."""
    matter_entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)

    assert integration._build_matter(hass, _entry(hass), None) is None


async def test_a_matter_entry_whose_client_is_not_connected_is_skipped(
    hass: HomeAssistant, matter_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """The same situation the Z-Wave build handles: loaded, and not ready to answer."""
    matter_entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=None))

    with caplog.at_level("DEBUG", logger="custom_components.device_links"):
        built = integration._build_matter(hass, _entry(hass), None)

    assert built is None
    assert "not connected yet" in caplog.text


async def test_the_accessor_error_is_the_one_this_wiring_catches(
    hass: HomeAssistant, matter_entry: MockConfigEntry
) -> None:
    """Pins the contract between the seam and the wiring, which nothing else asserts."""
    matter_entry.runtime_data = SimpleNamespace(adapter=SimpleNamespace(matter_client=None))

    from custom_components.device_links.backends.matter_client import (  # noqa: PLC0415
        async_get_client,
    )

    with pytest.raises(MatterAccessorError):
        async_get_client(matter_entry)  # type: ignore[arg-type]


def _entry(hass: HomeAssistant) -> Any:
    """Return a Device Links config entry with no options, for the build helpers."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}-build", title="Device Links")
    entry.add_to_hass(hass)
    return entry
