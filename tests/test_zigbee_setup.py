"""Wiring the Zigbee backend into the product: the config entry, the seam, and the sensor.

Open item T42. The adapter and its pure module were exercised from Phase 2A onwards through
`tests/fakes/zigbee.py`, and nothing in the product built one: `_async_build_backends` was
Z-Wave only, so a Zigbee rule could be compiled, planned and applied in a test and reached
nothing on a real house. This file is about the half that was missing.

Two layers, tested separately on purpose.

**The seam** (`backends/mqtt_client.py`) is checked against Home Assistant's own `mqtt`
integration with its broker mocked, because what it is for is knowing how Home Assistant
subscribes, and a fake of our own would only prove that we agree with ourselves.

**The wiring** (`__init__.py`) is checked with the fake bridge standing in for the client,
because what it is for is what gets built, what gets said, and what gets taken down again.
Putting a real broker under those tests would make them about MQTT rather than about setup.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from functools import partial
from typing import Any

from homeassistant.components.mqtt.models import ReceiveMessage
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

import custom_components.device_links as integration
from custom_components.device_links.backends.mqtt_client import (
    HomeAssistantMqttClient,
    async_mqtt_is_available,
    deliver_text,
)
from custom_components.device_links.const import DOMAIN, OPTION_ZIGBEE_BASE_TOPIC
from custom_components.device_links.models import Backend as BackendId
from tests.fakes.zigbee import FakeBridge, build_bridge_from_fixture

# --------------------------------------------------------------------------------------
# The seam: Home Assistant's mqtt integration, with its broker mocked
# --------------------------------------------------------------------------------------


async def test_the_client_is_unavailable_until_the_mqtt_integration_is_loaded(
    hass: HomeAssistant,
) -> None:
    """A house with no broker has no Zigbee2MQTT, and that is not an error."""
    assert async_mqtt_is_available(hass) is False


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_the_client_is_available_once_mqtt_is_loaded(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    assert async_mqtt_is_available(hass) is True


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_a_subscription_delivers_the_topic_and_the_text(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    """What the adapter is written against: a topic and a string, nothing else."""
    seen: list[tuple[str, str]] = []
    client = HomeAssistantMqttClient(hass)

    unsubscribe = await client.async_subscribe(
        "zigbee2mqtt/bridge/#", lambda t, p: seen.append((t, p))
    )
    async_fire_mqtt_message(hass, "zigbee2mqtt/bridge/state", '{"state":"online"}')
    await hass.async_block_till_done()

    assert seen == [("zigbee2mqtt/bridge/state", '{"state":"online"}')]

    unsubscribe()
    async_fire_mqtt_message(hass, "zigbee2mqtt/bridge/state", '{"state":"offline"}')
    await hass.async_block_till_done()

    assert len(seen) == 1, "the unsubscribe callable did not unsubscribe"


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_publishing_goes_through_the_broker_home_assistant_is_already_on(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    """Decision D2 (a)'s reasoning, one protocol along: no second connection of our own."""
    await HomeAssistantMqttClient(hass).async_publish("zigbee2mqtt/bridge/request/x", "{}")
    await hass.async_block_till_done()

    published = mqtt_mock.async_publish.call_args.args
    assert published[:2] == ("zigbee2mqtt/bridge/request/x", "{}")
    assert published[3] is False, "a request is not retained"


def test_a_payload_that_is_not_text_is_dropped_rather_than_guessed_at() -> None:
    """Home Assistant decodes UTF-8 and drops what will not decode, so this is the rest.

    Called directly, because the case is the one Home Assistant will not produce: a
    subscription asked for with no encoding, or a binary topic somebody pointed at us.
    """
    seen: list[tuple[str, str]] = []
    record = partial(_append, seen)

    deliver_text(record, _message("zigbee2mqtt/bridge/state", '{"state":"online"}'))
    deliver_text(record, _message("zigbee2mqtt/bridge/state", b"\x00\x81"))

    assert seen == [("zigbee2mqtt/bridge/state", '{"state":"online"}')]


def _append(seen: list[tuple[str, str]], topic: str, payload: str) -> None:
    """Record one delivered message, as a callback the adapter would pass."""
    seen.append((topic, payload))


def _message(topic: str, payload: str | bytes) -> ReceiveMessage:
    """Return one `ReceiveMessage` as Home Assistant hands it to a subscriber."""
    return ReceiveMessage(
        topic=topic,
        payload=payload,
        qos=0,
        retain=True,
        subscribed_topic=topic,
        timestamp=0.0,
    )


# --------------------------------------------------------------------------------------
# The wiring: what setup builds, and what unload takes away
# --------------------------------------------------------------------------------------


@pytest.fixture
def bridge() -> FakeBridge:
    """Jayant's Zigbee network as the G1 capture found it, on the default base topic."""
    return build_bridge_from_fixture()


@pytest.fixture
def zigbee2mqtt(
    monkeypatch: pytest.MonkeyPatch, bridge: FakeBridge
) -> Callable[[FakeBridge], None]:
    """Make setup believe MQTT is loaded, and hand the adapter the fake bridge.

    The seam is what this replaces, and it is the seam that has its own tests above. What
    is under test here is everything on this side of it.
    """
    holder = {"bridge": bridge}
    monkeypatch.setattr(integration, "async_mqtt_is_available", lambda hass: True)
    monkeypatch.setattr(integration, "HomeAssistantMqttClient", lambda hass: holder["bridge"])

    def _serve(replacement: FakeBridge) -> None:
        holder["bridge"] = replacement

    return _serve


@pytest.fixture
async def both_backends(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zigbee2mqtt: Callable[[FakeBridge], None],
) -> AsyncGenerator[MockConfigEntry]:
    """Device Links set up over the fake Z-Wave network and the fake Zigbee bridge."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_both_backends_are_built_when_both_upstreams_are_there(
    both_backends: MockConfigEntry,
) -> None:
    """T42: `_async_build_backends` built Z-Wave only, so nothing in the product was Zigbee."""
    runtime = both_backends.runtime_data

    assert set(runtime.backends) == {BackendId.ZWAVE, BackendId.ZIGBEE2MQTT}
    assert {info.backend_id: info.upstream_domain for info in runtime.backend_info} == {
        BackendId.ZWAVE: "zwave_js",
        BackendId.ZIGBEE2MQTT: "mqtt",
    }


async def test_the_zigbee_devices_are_read_at_setup(both_backends: MockConfigEntry) -> None:
    """A backend that is built and never read is a backend nothing uses."""
    coordinator = both_backends.runtime_data.coordinator

    assert any(handle.backend is BackendId.ZIGBEE2MQTT for handle in coordinator.devices.values())
    assert coordinator.backend_availability[BackendId.ZIGBEE2MQTT] is True


async def test_the_upstream_version_comes_from_bridge_info(
    both_backends: MockConfigEntry,
) -> None:
    """The Zigbee half of "which Z-Wave JS is this", which is what a health read asks first."""
    info = next(
        info
        for info in both_backends.runtime_data.backend_info
        if info.backend_id is BackendId.ZIGBEE2MQTT
    )

    assert info.upstream_version == "2.14.1"


async def test_the_upstream_version_follows_an_upgraded_add_on(
    hass: HomeAssistant, both_backends: MockConfigEntry, bridge: FakeBridge
) -> None:
    """Zigbee2MQTT is an add-on, so upgrading it republishes `bridge/info` and reloads nothing.

    A version snapshotted at setup would be quoted in an issue report long after it stopped
    being true, which is why this one is read rather than remembered.
    """
    info = next(
        info
        for info in both_backends.runtime_data.backend_info
        if info.backend_id is BackendId.ZIGBEE2MQTT
    )
    bridge.upgrade("2.15.0")
    await hass.async_block_till_done()

    assert info.upstream_version == "2.15.0"


async def test_the_health_sensor_reports_both_backends(
    hass: HomeAssistant, both_backends: MockConfigEntry
) -> None:
    """PRD Section 17.1: this is the one entity a remote session reads first."""
    state = hass.states.get("sensor.device_links_health")

    assert state is not None
    backends = state.attributes["backends"]
    assert set(backends) == {"zwave", "zigbee2mqtt"}
    assert backends["zigbee2mqtt"] == {
        "available": True,
        "upstream": "mqtt",
        "upstream_version": "2.14.1",
    }


async def test_the_diagnostics_report_both_backends(
    hass: HomeAssistant, both_backends: MockConfigEntry
) -> None:
    from custom_components.device_links.diagnostics import (  # noqa: PLC0415
        async_get_config_entry_diagnostics,
    )

    dump = await async_get_config_entry_diagnostics(hass, both_backends)

    assert [entry["backend"] for entry in dump["backends"]] == ["zwave", "zigbee2mqtt"]
    assert dump["backends"][1]["upstream_version"] == "2.14.1"


async def test_a_bridge_that_goes_offline_makes_that_backend_unavailable(
    hass: HomeAssistant,
    both_backends: MockConfigEntry,
    bridge: FakeBridge,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """E26, from the top: the bridge going down is said once, and once on the way back."""
    coordinator = both_backends.runtime_data.coordinator
    bridge.go_offline()
    await coordinator.async_refresh()

    assert coordinator.backend_availability == {
        BackendId.ZWAVE: True,
        BackendId.ZIGBEE2MQTT: False,
    }
    assert caplog.text.count("the Zigbee2MQTT bridge on zigbee2mqtt reported offline") == 1

    bridge.come_back()
    await coordinator.async_refresh()

    assert coordinator.backend_availability[BackendId.ZIGBEE2MQTT] is True
    assert caplog.text.count("the Zigbee2MQTT bridge on zigbee2mqtt is answering again") == 1


async def test_unloading_the_entry_drops_the_bridge_subscriptions(
    hass: HomeAssistant, both_backends: MockConfigEntry, bridge: FakeBridge
) -> None:
    """A subscription that outlives an unload fires against a dead entry and survives a reload."""
    assert bridge._subscriptions, "the backend never subscribed"

    assert await hass.config_entries.async_unload(both_backends.entry_id) is True
    await hass.async_block_till_done()

    assert bridge._subscriptions == []


async def test_a_second_instance_is_chosen_by_its_base_topic(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zigbee2mqtt: Callable[[FakeBridge], None],
) -> None:
    """E25: the base topic is the whole of a Zigbee2MQTT instance's address."""
    zigbee2mqtt(build_bridge_from_fixture(base_topic="zigbee2mqtt_upstairs"))
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Device Links",
        options={OPTION_ZIGBEE_BASE_TOPIC: "zigbee2mqtt_upstairs"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert BackendId.ZIGBEE2MQTT in entry.runtime_data.backends

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_wrong_base_topic_leaves_the_rest_of_the_integration_working(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zigbee2mqtt: Callable[[FakeBridge], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broker with nothing on this topic is said once and is not a failure.

    The Z-Wave half of the house keeps working, which is the whole reason this is a warning
    rather than a `ConfigEntryNotReady`: somebody with an MQTT broker for something else
    entirely would otherwise have Device Links retrying for ever over a bridge they do not own.
    """
    zigbee2mqtt(build_bridge_from_fixture(base_topic="somewhere_else"))
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert set(entry.runtime_data.backends) == {BackendId.ZWAVE}
    assert "no Zigbee2MQTT bridge answered on the base topic 'zigbee2mqtt'" in caplog.text

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_zwave_only_house_never_looks_for_a_bridge(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The setup an existing user has: no mqtt integration, and nothing said about one.

    Deliberately the shared fixture rather than a local one, so this is the same entry every
    other Z-Wave test in the suite sets up.
    """
    assert set(device_links_entry.runtime_data.backends) == {BackendId.ZWAVE}
    assert [info.backend_id for info in device_links_entry.runtime_data.backend_info] == [
        BackendId.ZWAVE
    ]
    assert "Zigbee2MQTT" not in caplog.text
