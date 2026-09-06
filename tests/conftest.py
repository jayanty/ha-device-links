"""Shared fixtures for the Device Links test suite.

The Home Assistant fixtures below build the whole integration the way a user's system
does: a loaded `zwave_js` config entry holding the Stage 0 fake driver, a device registry
carrying the same device entries the P2 capture recorded, and a `device_links` entry set
up on top of both. Nothing here reaches a network, and every write lands in the fake
driver's association tables.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_links.const import DOMAIN
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    Feature,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from custom_components.device_links.storage import StoredState
from tests.factories import HOME_ID, handle
from tests.fakes.zwave import FakeDriver, build_driver_from_fixture

# The zwave_js integration's own domain, which is also the namespace of the device
# registry identifiers our rule entities have to match exactly (Stage 0 item P2).
ZWAVE_JS_DOMAIN = "zwave_js"


def extended_identifier(node_id: int, node: object) -> str:
    """Return the fingerprint-bearing zwave_js identifier for a node."""
    return f"{HOME_ID}-{node_id}-{node.manufacturer_id}:{node.product_type}:{node.product_id}"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/device_links in every test."""
    return


@pytest.fixture
def zwave_driver() -> FakeDriver:
    """Return the Stage 0 fake driver, holding Jayant's network as it was captured."""
    return build_driver_from_fixture()


@pytest.fixture
def zwave_js_entry(hass: HomeAssistant, zwave_driver: FakeDriver) -> Iterator[MockConfigEntry]:
    """Return a loaded zwave_js config entry whose client holds the fake driver.

    Shaped exactly as `zwave_accessor` reads it (`runtime_data.client.driver`), because
    that accessor is the one supported way into the driver and a fixture that took a
    short cut around it would stop testing the coupling CI is meant to guard.

    Marked not loaded again on teardown: the real `zwave_js.async_unload_entry` would
    otherwise run against this stand-in when Home Assistant shuts down, and fill the log
    with tracebacks that have nothing to do with the test that just ran.
    """
    entry = MockConfigEntry(domain=ZWAVE_JS_DOMAIN, title="Z-Wave JS", entry_id="zwavejsentry")
    entry.add_to_hass(hass)
    entry.runtime_data = SimpleNamespace(
        client=SimpleNamespace(
            driver=zwave_driver,
            version=SimpleNamespace(driver_version="15.4.0", server_version="1.44.0"),
        )
    )
    entry.mock_state(hass, ConfigEntryState.LOADED)
    yield entry
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
def zwave_js_devices(
    hass: HomeAssistant,
    zwave_driver: FakeDriver,
    zwave_js_entry: MockConfigEntry,
) -> dict[int, dr.DeviceEntry]:
    """Register one device entry per node, with the identifiers the P2 capture recorded.

    Both identifiers, exactly as captured: the short `<home id>-<node id>` form that
    entity attachment must match, and the longer fingerprint-bearing form that FR-S3 uses
    to notice a replaced device. They are built from the same fake driver the adapter
    reads, so a test cannot pass because the fixture and the adapter agree on a value
    neither of them got from the capture.
    """
    registry = dr.async_get(hass)
    devices: dict[int, dr.DeviceEntry] = {}
    for node_id, node in zwave_driver.controller.nodes.items():
        devices[node_id] = registry.async_get_or_create(
            config_entry_id=zwave_js_entry.entry_id,
            identifiers={
                (ZWAVE_JS_DOMAIN, f"{HOME_ID}-{node_id}"),
                (ZWAVE_JS_DOMAIN, extended_identifier(node_id, node)),
            },
            manufacturer=node.manufacturer,
            model=node.label,
            name=node.name,
        )
    return devices


@pytest.fixture
async def device_links_entry(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> AsyncGenerator[MockConfigEntry]:
    """Set up Device Links on top of the fake Z-Wave network, and unload it afterwards."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
def no_deployed_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the deployment reader at an empty directory, as a HACS install looks."""
    from custom_components.device_links import deployment  # noqa: PLC0415

    monkeypatch.setattr(deployment, "COMPONENT_DIR", tmp_path)


# --------------------------------------------------------------------------------------
# Profile building, shared by the entity test modules
# --------------------------------------------------------------------------------------

# The bedroom, as PRD Section 15 names it, by node id because the fixture is keyed by one.
CONTROLLER = 36  # Bedroom Scene Controller (Zooz ZEN35)
MAIN_LIGHTS = 37  # Master Bedroom Lights
LOBBY = 35  # Entrance Lobby Light

DIMMING = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})


def a_rule(  # noqa: PLR0913
    rule_id: str = "bedroom-main",
    *,
    name: str = "036 main button controls Master Bedroom Lights",
    source_node: int = CONTROLLER,
    emitter_id: str = "g2",
    target_node: int = MAIN_LIGHTS,
    enabled: bool = True,
) -> Rule:
    """Return one rule as a user would author it: one control, one target, one intent."""
    return Rule(
        id=rule_id,
        name=name,
        template=Template.REMOTE,
        backend=BackendId.ZWAVE,
        source=RuleSource(device=handle(source_node), endpoint=0, emitter_id=emitter_id),
        targets=(RuleTarget(device=handle(target_node), endpoint=None),),
        features=DIMMING,
        enabled=enabled,
    )


def a_profile(*rules: Rule, profile_id: str = "bedroom", name: str = "Bedroom") -> Profile:
    """Return a profile holding these rules."""
    return Profile(id=profile_id, name=name, rules=rules or (a_rule(),))


@callback
def activate(entry: MockConfigEntry, *profiles: Profile, active: str | None = None) -> None:
    """Make the first of these profiles active, as saving in the panel would."""
    coordinator = entry.runtime_data.coordinator
    coordinator.async_update_state(
        StoredState(
            profiles=profiles,
            active_profile_id=active or (profiles[0].id if profiles else None),
        )
    )
