"""Reading: devices, capabilities and observed state, against the fake bridge.

The read path is the proven half of Phase 2A. `tests/fixtures/g1_bridge.json` is a real
capture, and the fake bridge replays it, so what these assert about parsing and about the
starting state of Jayant's network is true of the hardware.
"""

from __future__ import annotations

import logging

import pytest

from custom_components.device_links.backends import zigbee_protocol as zp
from custom_components.device_links.backends.zigbee2mqtt import (
    SKIPPED_BRIDGE_OFFLINE,
    ZigbeeBackend,
    ZigbeeBackendError,
)
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import DeviceHandle, Feature, ZigbeeFingerprint
from tests.factories import (
    AUX_IEEE,
    COORDINATOR_IEEE,
    LIGHT_IEEE,
    OLD_FIRMWARE_IEEE,
    profiles,
)
from tests.fakes.zigbee import FakeBridge, build_bridge_from_fixture

AUX = "Entrance Inside Lights Aux"
LIGHT = "Entrance Inside Lights"


@pytest.fixture
def bridge() -> FakeBridge:
    return build_bridge_from_fixture()


@pytest.fixture
async def backend(bridge: FakeBridge) -> ZigbeeBackend:
    built = ZigbeeBackend(client=bridge, profiles=profiles())
    await built.async_start()
    return built


def _handle(ieee: str, name: str = "") -> DeviceHandle:
    """Return a handle for a captured device, by address rather than by name (E23)."""
    return DeviceHandle(
        backend=BackendId.ZIGBEE2MQTT,
        protocol_id=ieee,
        ha_device_id="",
        fingerprint=ZigbeeFingerprint(manufacturer="Inovelli", model="VZM31-SN"),
        name_at_authoring=name,
    )


# --------------------------------------------------------------------------------------
# Startup and the retained topics
# --------------------------------------------------------------------------------------


async def test_the_backend_knows_the_network_from_the_retained_topics(
    backend: ZigbeeBackend,
) -> None:
    """Nothing is asked for: the four bridge topics are retained and arrive on subscribe."""
    devices = await backend.async_devices()

    assert len(devices) == 23, "24 devices, less the coordinator"
    assert all(device.handle.backend is BackendId.ZIGBEE2MQTT for device in devices)


async def test_the_coordinator_is_not_offered_as_a_device(backend: ZigbeeBackend) -> None:
    """It is the radio. It drives no control and can act on nothing a binding sends."""
    identities = {device.handle.identity for device in await backend.async_devices()}

    assert f"zigbee2mqtt:{COORDINATOR_IEEE}" not in identities


async def test_a_handle_is_the_ieee_address_and_survives_a_rename(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """E23. The identity must not move when a user tidies their names up."""
    before = {device.handle.identity for device in await backend.async_devices()}

    bridge.rename(AUX_IEEE, "Front Door Aux")

    assert {device.handle.identity for device in await backend.async_devices()} == before


async def test_startup_gives_up_when_the_device_list_never_arrives() -> None:
    """A topic that is not retained leaves the backend with no network and no explanation."""
    bridge = FakeBridge(devices=[])
    bridge.devices = []
    backend = ZigbeeBackend(client=_SilentClient(bridge), startup_timeout=0.01)

    with pytest.raises(ZigbeeBackendError, match="did not arrive"):
        await backend.async_start()


class _SilentClient:
    """A broker that accepts a subscription and delivers nothing, retained or not."""

    def __init__(self, bridge: FakeBridge) -> None:
        self.bridge = bridge

    async def async_publish(self, topic: str, payload: str) -> None:
        await self.bridge.async_publish(topic, payload)

    async def async_subscribe(self, topic: str, callback: object) -> object:
        return lambda: None


# --------------------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------------------


async def test_capabilities_offer_the_paddle_and_the_config_button(
    backend: ZigbeeBackend,
) -> None:
    capabilities = await backend.async_capabilities(_handle(AUX_IEEE))

    assert [emitter.emitter_id for emitter in capabilities.emitters] == ["ep2", "ep3"]


async def test_one_cluster_carries_both_level_features(backend: ZigbeeBackend) -> None:
    """The compiler must see that Zigbee cannot separate them, not be told a story."""
    capabilities = await backend.async_capabilities(_handle(AUX_IEEE))
    paddle = capabilities.emitters[0]

    assert paddle.actions[Feature.LEVEL_SET] == paddle.actions[Feature.LEVEL_HOLD]


async def test_capabilities_report_what_the_device_can_be_made_to_do(
    backend: ZigbeeBackend,
) -> None:
    capabilities = await backend.async_capabilities(_handle(LIGHT_IEEE))

    assert Feature.ON_OFF in capabilities.receivable
    assert Feature.LEVEL_SET in capabilities.receivable
    assert capabilities.is_long_range is False


async def test_a_device_this_bridge_does_not_report_is_refused_by_name(
    backend: ZigbeeBackend,
) -> None:
    """An empty answer for a missing device reads as a device with nothing on it."""
    with pytest.raises(ZigbeeBackendError, match="0x00"):
        await backend.async_capabilities(_handle("0x0011223344556677"))


async def test_an_older_firmware_gets_the_controls_it_really_has(
    backend: ZigbeeBackend,
) -> None:
    """Two VZM31-SN switches in the capture have no endpoint 3 and still get a paddle."""
    capabilities = await backend.async_capabilities(_handle(OLD_FIRMWARE_IEEE))

    assert [emitter.emitter_id for emitter in capabilities.emitters] == ["ep2"]


async def test_with_no_profile_database_the_derivation_still_answers(
    bridge: FakeBridge,
) -> None:
    backend = ZigbeeBackend(client=bridge, profiles=None)
    await backend.async_start()

    capabilities = await backend.async_capabilities(_handle(AUX_IEEE))

    assert [emitter.grouping for emitter in capabilities.emitters] == ["endpoint", "endpoint"]
    assert capabilities.settings == {}


# --------------------------------------------------------------------------------------
# Observed state
# --------------------------------------------------------------------------------------


async def test_every_binding_in_the_capture_is_a_system_link(backend: ZigbeeBackend) -> None:
    """They are Zigbee2MQTT's own reporting setup, and never ours to remove."""
    observed = await backend.async_observed(_handle(AUX_IEEE))

    assert observed.links
    assert all(link.is_system for link in observed.links)
    assert all(link.managed_by is None for link in observed.links)


async def test_a_bound_level_cluster_reads_back_as_two_links(
    backend: ZigbeeBackend,
) -> None:
    """One binding, two features, because the binding really carries both.

    Reporting it under one feature only would leave the other permanently missing from
    every plan: proposed as an add, answered `already_present`, and proposed again.
    """
    observed = await backend.async_observed(_handle(AUX_IEEE))
    level = [link for link in observed.links if link.emitter_group == zp.GEN_LEVEL_CTRL]

    assert {link.feature for link in level} == {Feature.LEVEL_SET, Feature.LEVEL_HOLD}


async def test_an_observed_link_names_the_control_a_rule_would_name(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The paddle is `ep2` on both sides, so a desired link and an observed one agree.

    The reporting bindings the bridge made are all on endpoint 1, which drives only OTA and
    is therefore no control at all. Those keep the plain `ep1` spelling, which is honest:
    they are entries on an endpoint, not the work of a button somebody could press.
    """
    bridge.add_binding(
        AUX, 2, zp.GEN_ON_OFF, {"type": "endpoint", "ieee_address": LIGHT_IEEE, "endpoint": 1}
    )

    observed = await backend.async_observed(_handle(AUX_IEEE))

    assert {link.emitter_id for link in observed.links} == {"ep1", "ep2"}
    assert [link.emitter_id for link in observed.links if link.source_endpoint == 2] == ["ep2"]


async def test_a_binding_to_a_device_the_bridge_does_not_list_still_produces_a_link(
    backend: ZigbeeBackend,
) -> None:
    """Every binding on this network points at the coordinator, which is not in the listing."""
    observed = await backend.async_observed(_handle(AUX_IEEE))

    assert {link.target.handle.protocol_id for link in observed.links} == {COORDINATOR_IEEE}


async def test_a_shallow_read_never_claims_to_have_been_confirmed(
    backend: ZigbeeBackend,
) -> None:
    observed = await backend.async_observed(_handle(AUX_IEEE))

    assert observed.deep_verified is False
    assert observed.deep_verify_timed_out is False
    assert observed.deep_verify_skipped_reason is None


async def test_a_deep_read_with_nothing_outstanding_is_confirmed(
    backend: ZigbeeBackend,
) -> None:
    """The retained payload we hold is the bridge's current view when it owes us nothing."""
    observed = await backend.async_observed(_handle(AUX_IEEE), deep=True)

    assert observed.deep_verified is True
    assert observed.deep_verify_timed_out is False


async def test_a_deep_read_while_the_bridge_is_offline_says_so_rather_than_confirming(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    bridge.go_offline()

    observed = await backend.async_observed(_handle(AUX_IEEE), deep=True)

    assert observed.deep_verified is False
    assert observed.deep_verify_skipped_reason == SKIPPED_BRIDGE_OFFLINE


# --------------------------------------------------------------------------------------
# Groups seen on the read path
# --------------------------------------------------------------------------------------


async def test_a_binding_to_a_foreign_group_is_reported_as_a_link_to_that_group(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """It is what it is. Inventing per-member links would claim to know what a user meant."""
    bridge.add_group("kitchen", 3, [{"ieee_address": LIGHT_IEEE, "endpoint": 1}])
    _bind_to_group(bridge, 3)

    observed = await backend.async_observed(_handle(AUX_IEEE))
    to_group = [link for link in observed.links if link.source_endpoint == 2]

    assert [link.target.handle.protocol_id for link in to_group] == ["group:3"]
    assert to_group[0].target.handle.name_at_authoring == "kitchen"


async def test_a_binding_to_a_managed_group_is_expanded_into_its_members(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """So a one-to-many rule's per-target links match what is really on the device."""
    bridge.add_group(
        "dl_r1",
        4,
        [
            {"ieee_address": LIGHT_IEEE, "endpoint": 1},
            {"ieee_address": OLD_FIRMWARE_IEEE, "endpoint": 1},
        ],
    )
    _bind_to_group(bridge, 4)

    observed = await backend.async_observed(_handle(AUX_IEEE))
    to_members = [link for link in observed.links if link.source_endpoint == 2]

    assert {link.target.handle.protocol_id for link in to_members} == {
        LIGHT_IEEE,
        OLD_FIRMWARE_IEEE,
    }
    assert all(link.target.endpoint == 1 for link in to_members)


async def test_a_binding_to_a_group_that_is_gone_is_still_reported(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A link nobody can see is a link nobody can plan to remove (E24)."""
    _bind_to_group(bridge, 9)

    observed = await backend.async_observed(_handle(AUX_IEEE))

    assert any(link.target.handle.protocol_id == "group:9" for link in observed.links)


def _bind_to_group(bridge: FakeBridge, group_id: int) -> None:
    """Put a group binding on the aux switch's paddle without going through a request."""
    bridge.add_binding(AUX, 2, zp.GEN_ON_OFF, {"type": "group", "id": group_id})


# --------------------------------------------------------------------------------------
# The bridge going away
# --------------------------------------------------------------------------------------


async def test_an_offline_bridge_refuses_to_list_rather_than_answering_nothing(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """E1 and E26. An empty answer would drift the whole network and rewrite it on apply."""
    bridge.go_offline()

    with pytest.raises(ZigbeeBackendError, match="offline"):
        await backend.async_devices()


async def test_the_bridge_going_offline_is_logged_once(
    backend: ZigbeeBackend, bridge: FakeBridge, caplog: pytest.LogCaptureFixture
) -> None:
    """E26. A warning that repeats is a warning users learn to scroll past."""
    with caplog.at_level(logging.WARNING):
        bridge.go_offline()
        bridge.go_offline()

    offline = [r for r in caplog.records if "reported offline" in r.getMessage()]
    assert len(offline) == 1


async def test_coming_back_is_said_once_too(
    backend: ZigbeeBackend, bridge: FakeBridge, caplog: pytest.LogCaptureFixture
) -> None:
    bridge.go_offline()
    with caplog.at_level(logging.INFO):
        bridge.come_back()

    assert any("answering again" in record.getMessage() for record in caplog.records)
    assert await backend.async_devices()


# --------------------------------------------------------------------------------------
# Change subscriptions
# --------------------------------------------------------------------------------------


async def test_a_subscriber_hears_about_a_device_that_changed(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    bridge.rename(AUX_IEEE, "Front Door Aux")

    assert seen == [f"zigbee2mqtt:{AUX_IEEE}"]
    unsubscribe()


async def test_a_subscriber_hears_nothing_about_devices_that_did_not_change(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The bridge republishes the whole list whenever any part of it moves."""
    seen: list[str] = []
    backend.subscribe(seen.append)

    bridge.rename(AUX_IEEE, "Front Door Aux")

    assert len(seen) == 1, "23 other devices were in the same message and none of them moved"


async def test_unsubscribing_stops_the_callbacks(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A listener that outlives its config entry fires at a coordinator that is gone."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)
    unsubscribe()

    bridge.rename(AUX_IEEE, "Front Door Aux")

    assert seen == []


async def test_stopping_drops_every_subscription(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    seen: list[str] = []
    backend.subscribe(seen.append)

    backend.async_stop()
    bridge.rename(AUX_IEEE, "Front Door Aux")

    assert seen == []


# --------------------------------------------------------------------------------------
# Payloads that make no sense
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    ["not json", '"a string"', "{}", '[{"no": "address"}]'],
)
async def test_a_payload_that_makes_no_sense_leaves_the_last_good_one_standing(
    backend: ZigbeeBackend, bridge: FakeBridge, payload: str
) -> None:
    """It arrives off a broker. A handler that raised would take the subscription with it."""
    before = len(await backend.async_devices())

    bridge._deliver("zigbee2mqtt/bridge/devices", payload)

    assert len(await backend.async_devices()) == before


async def test_a_nonsense_groups_payload_is_ignored_too(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    bridge.add_group("dl_r1", 1)

    bridge._deliver("zigbee2mqtt/bridge/groups", '{"not": "a list"}')
    bridge._deliver("zigbee2mqtt/bridge/groups", '[{"id": 1}]')

    observed = await backend.async_observed(_handle(AUX_IEEE))
    assert observed.links


async def test_a_state_payload_that_is_not_an_object_reads_as_offline(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Failing closed: a bridge whose state cannot be read is not a bridge known to be up."""
    bridge._deliver("zigbee2mqtt/bridge/state", '"online"')

    with pytest.raises(ZigbeeBackendError, match="offline"):
        await backend.async_devices()


# --------------------------------------------------------------------------------------
# Base topic
# --------------------------------------------------------------------------------------


async def test_the_base_topic_is_not_hard_coded() -> None:
    """E25. A second Zigbee2MQTT instance uses a different one, and identifiers embed it."""
    bridge = FakeBridge(base_topic="zigbee2mqtt_upstairs")
    backend = ZigbeeBackend(client=bridge, base_topic="zigbee2mqtt_upstairs")

    await backend.async_start()

    assert len(await backend.async_devices()) == 23


async def test_wake_instructions_come_from_the_curated_entry(
    backend: ZigbeeBackend,
) -> None:
    """None today: no Zigbee model in the capture is battery powered and bindable."""
    assert backend.wake_instructions(_handle(AUX_IEEE)) is None
    assert backend.wake_instructions(_handle("0x0011223344556677")) is None
