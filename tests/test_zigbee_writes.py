"""Writing. Every refusal is tested, because each one protects a working home.

**Nothing below has ever happened.** Stage 0 item G2 was never approved, so no Zigbee bind
has been performed on this network and every request and response shape here comes from the
Zigbee2MQTT documentation by way of `tests/fakes/zigbee.py`. Assumption A2 in
`docs/open-items.md`, issue #6. A pass here proves the adapter agrees with the model.
"""

from __future__ import annotations

import json

import pytest

from custom_components.device_links.backends import zigbee_protocol as zp
from custom_components.device_links.backends.base import LinkResultStatus
from custom_components.device_links.backends.zigbee2mqtt import ZigbeeBackend
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceHandle,
    Feature,
    Link,
    LinkTarget,
    ZigbeeFingerprint,
)
from custom_components.device_links.profile_db import load_profiles
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
    built = ZigbeeBackend(client=bridge, profiles=profiles(), request_timeout=0.2)
    await built.async_start()
    return built


def handle(ieee: str, name: str = "device") -> DeviceHandle:
    return DeviceHandle(
        backend=BackendId.ZIGBEE2MQTT,
        protocol_id=ieee,
        ha_device_id="",
        fingerprint=ZigbeeFingerprint(manufacturer="Inovelli", model="VZM31-SN"),
        name_at_authoring=name,
    )


def link(  # noqa: PLR0913
    *,
    source: str = AUX_IEEE,
    source_endpoint: int = 2,
    target: str = LIGHT_IEEE,
    target_endpoint: int | None = 1,
    feature: Feature = Feature.ON_OFF,
    cluster: str | None = None,
    rule_id: str | None = "r1",
) -> Link:
    """Return one desired Zigbee link, the unit the executor writes."""
    return Link(
        backend=BackendId.ZIGBEE2MQTT,
        source=handle(source, AUX),
        source_endpoint=source_endpoint,
        emitter_id="ep2",
        target=LinkTarget(handle=handle(target, LIGHT), endpoint=target_endpoint),
        feature=feature,
        emitter_group=cluster or zp.CLUSTER_BY_FEATURE[feature],
        rule_id=rule_id,
    )


# --------------------------------------------------------------------------------------
# The bug most likely to ship looking like it works
# --------------------------------------------------------------------------------------


async def test_a_partial_cluster_failure_is_never_reported_as_applied(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Zigbee2MQTT reports `status: "error"` only when **every** cluster failed.

    A response that says `ok` and lists a cluster in `failed` is a bind that did not happen
    for that cluster. Reading `status` alone reports the link as applied, and the user gets
    a paddle that turns the light on and cannot dim it while the panel says everything is
    fine. This is the single most likely way to ship a Zigbee bug that looks like it works.
    """
    bridge.fail_clusters = {zp.GEN_LEVEL_CTRL}
    bridge.ok_despite_total_failure = True

    result = await backend.async_add_link(link(feature=Feature.LEVEL_SET))

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_clusters_failed"
    assert zp.GEN_LEVEL_CTRL in result.reason.placeholders["clusters"]


async def test_a_partial_failure_names_the_clusters_that_did_not_bind(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A bare "it failed" is not actionable; "genLevelCtrl did not bind" is."""
    bridge.fail_clusters = {zp.GEN_LEVEL_CTRL}
    bridge.ok_despite_total_failure = True

    result = await backend.async_add_link(link(feature=Feature.LEVEL_HOLD))

    assert result.reason is not None
    assert result.reason.placeholders["clusters"] == zp.GEN_LEVEL_CTRL


async def test_a_link_that_really_did_bind_is_applied(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.APPLIED
    assert [b["cluster"] for b in bridge.bindings_of(AUX, 2)][-1] == zp.GEN_ON_OFF


async def test_a_total_failure_carries_the_bridge_error_text(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """PRD Section 9: the raw text is for the person filing the bug, not the primary message."""
    bridge.fail_clusters = {zp.GEN_ON_OFF}

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_bind_failed"
    assert result.raw_error is not None
    assert "no cluster could be written" in result.raw_error


# --------------------------------------------------------------------------------------
# Only the clusters the rule asked for
# --------------------------------------------------------------------------------------


async def test_a_bind_names_exactly_one_cluster_and_never_all_supported(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Omitting `clusters` binds everything the device supports, which no rule ever asked."""
    await backend.async_add_link(link())

    topic, body = bridge.requests[-1]
    assert topic == zp.BIND_REQUEST
    assert body["clusters"] == [zp.GEN_ON_OFF]


async def test_the_request_is_addressed_by_the_name_the_device_answers_to_now(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """E23. The handle holds the address; the name is resolved at the moment of the request."""
    bridge.rename(AUX_IEEE, "Front Door Aux")
    bridge.rename(LIGHT_IEEE, "Front Door Light")

    await backend.async_add_link(link())

    _, body = bridge.requests[-1]
    assert body["from"] == "Front Door Aux"
    assert body["to"] == "Front Door Light"


async def test_both_level_features_write_the_one_cluster_that_carries_them(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """There is no way to bind one without the other, so the second is already present."""
    first = await backend.async_add_link(link(feature=Feature.LEVEL_SET))
    second = await backend.async_add_link(link(feature=Feature.LEVEL_HOLD))

    assert first.status is LinkResultStatus.APPLIED
    assert second.status is LinkResultStatus.ALREADY_PRESENT
    assert [b["cluster"] for b in bridge.bindings_of(AUX, 2)].count(zp.GEN_LEVEL_CTRL) == 1


# --------------------------------------------------------------------------------------
# Refusals, each of which protects something
# --------------------------------------------------------------------------------------


async def test_a_binding_to_the_coordinator_is_refused_even_when_asked_directly(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Defence in depth, exactly as the Z-Wave lifeline gets.

    Every binding on this network is a coordinator binding: they are Zigbee2MQTT's own
    reporting setup, and removing one stops the device reporting to Home Assistant at all.
    The planner will not ask, but a service call could.
    """
    before = bridge.write_count

    result = await backend.async_remove_link(
        link(source_endpoint=1, target=COORDINATOR_IEEE, target_endpoint=1)
    )

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_coordinator_binding_protected"
    assert bridge.write_count == before, "a coordinator unbind reached the bridge"


async def test_adding_a_binding_to_the_coordinator_is_refused_too(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The bridge's reporting setup is ours to read, never ours to write."""
    before = bridge.write_count

    result = await backend.async_add_link(link(target=COORDINATOR_IEEE))

    assert result.status is LinkResultStatus.BLOCKED
    assert bridge.write_count == before


async def test_a_self_binding_is_refused_before_any_request(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """`Link` refuses to build one, so this is what a deserialized or service-call one meets."""
    self_link = link()
    # Past `Link.__post_init__`, which refuses to build one, to what a deserialized link or
    # a raw service call could hand the adapter. Defence in depth means the adapter refuses
    # on its own account and not because something upstream already did.
    object.__setattr__(self_link, "target", LinkTarget(handle=handle(AUX_IEEE, AUX), endpoint=1))
    before = bridge.write_count

    result = await backend.async_add_link(self_link)

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_self_binding"
    assert bridge.write_count == before


async def test_a_link_with_no_target_endpoint_is_refused_rather_than_guessed(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A Zigbee binding always names an endpoint. There is no device-wide form.

    Choosing one on the user's behalf would read back as the endpoint chosen and never
    match a link that asked for "the whole device", so the plan would propose the same add
    forever. A refusal that says what to do is better than a plan that cannot converge.
    """
    before = bridge.write_count

    result = await backend.async_add_link(link(target_endpoint=None))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_target_endpoint_required"
    assert bridge.write_count == before


async def test_a_source_endpoint_that_does_not_drive_the_cluster_is_refused(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Endpoint 1 is the load and drives only OTA: binding from it would do nothing."""
    result = await backend.async_add_link(link(source_endpoint=1))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_source_cannot_send"


async def test_a_target_endpoint_that_cannot_serve_the_cluster_is_refused(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A binding the target cannot act on is accepted by the radio and dead forever."""
    result = await backend.async_add_link(link(target_endpoint=2))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_target_cannot_receive"


async def test_a_device_the_bridge_does_not_report_is_refused_with_its_address(
    backend: ZigbeeBackend,
) -> None:
    result = await backend.async_add_link(link(target="0x0011223344556677"))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_unknown_device"


async def test_a_write_while_the_bridge_is_offline_is_refused(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    bridge.go_offline()
    before = bridge.write_count

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_bridge_offline"
    assert bridge.write_count == before


# --------------------------------------------------------------------------------------
# Nothing to do
# --------------------------------------------------------------------------------------


async def test_adding_a_binding_that_is_already_there_sends_nothing(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """E12. A redundant request is airtime spent to learn what is already known."""
    await backend.async_add_link(link())
    before = bridge.write_count

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert bridge.write_count == before


async def test_removing_a_binding_that_is_not_there_sends_nothing(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    before = bridge.write_count

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert bridge.write_count == before


async def test_removing_a_binding_that_is_there_removes_it(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    await backend.async_add_link(link())

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.APPLIED
    assert zp.GEN_ON_OFF not in [b["cluster"] for b in bridge.bindings_of(AUX, 2)]


async def test_a_removal_is_not_refused_by_a_check_about_writing(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The order of the refusals matters: a check that would refuse an add has nothing to
    say about taking an entry off, and refusing there would make a plan that never converges.
    """
    bridge.add_binding(
        AUX, 3, zp.GEN_ON_OFF, {"type": "endpoint", "ieee_address": LIGHT_IEEE, "endpoint": 1}
    )
    bridge.device_named(AUX)["endpoints"]["3"]["clusters"]["output"] = []

    result = await backend.async_remove_link(link(source_endpoint=3))

    assert result.status is LinkResultStatus.APPLIED


# --------------------------------------------------------------------------------------
# What "we do not know" looks like
# --------------------------------------------------------------------------------------


async def test_a_request_with_no_response_is_reported_as_not_knowing(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """MQTT is fire and forget, so silence has several causes and none of them is "no".

    The status has to be one of the five the executor handles, and there is no "unknown",
    so this is `FAILED`. What it must not do is say the bind did not happen: the message
    says the bridge did not answer and that whether the binding was made is unknown, and
    the re-read that follows the job is what settles it.
    """
    bridge.silent = True

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_no_response"
    assert result.reason.placeholders["seconds"] == "0.2"


async def test_a_response_for_somebody_else_does_not_answer_this_request(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Correlation is by transaction. Two binds can be in flight at once."""
    bridge.silent = True
    bridge._deliver(
        "zigbee2mqtt/bridge/response/device/bind",
        '{"status": "ok", "data": {"clusters": [], "failed": []}, "transaction": "not-ours"}',
    )

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_no_response"


async def test_two_requests_in_flight_get_their_own_answers(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Every request carries its own transaction, and no two share one."""
    await backend.async_add_link(link())
    await backend.async_add_link(link(target=OLD_FIRMWARE_IEEE))

    transactions = [body["transaction"] for _, body in bridge.requests]
    assert len(set(transactions)) == len(transactions)


# --------------------------------------------------------------------------------------
# A source that is not listening (E22)
# --------------------------------------------------------------------------------------


async def test_a_battery_source_that_refuses_is_pending_rather_than_failed(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """E22. A battery device has to be awake when the request is made.

    It is not a failure and it is not a success: the write has not happened and nothing has
    gone wrong. `pending_wakeup` is the outcome the rest of the system already has for
    exactly that, and the Repairs issue that follows it asks the backend for the wake
    instruction.
    """
    bridge.set_power_source(AUX_IEEE, "Battery")
    bridge.unresponsive = {AUX_IEEE}

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.PENDING_WAKEUP
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_wake_the_device"


async def test_a_battery_source_that_never_answers_is_pending_too(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    bridge.set_power_source(AUX_IEEE, "Battery")
    bridge.silent = True

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.PENDING_WAKEUP


async def test_a_mains_source_that_refuses_is_a_failure_and_not_a_wake_up_prompt(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A prompt to wake a switch that is wired into the wall would be nonsense."""
    bridge.unresponsive = {AUX_IEEE}

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED


# --------------------------------------------------------------------------------------
# Checking without writing
# --------------------------------------------------------------------------------------


async def test_a_check_passes_for_a_link_that_could_be_written(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    check = await backend.async_check_link(link())

    assert check.ok
    assert bridge.write_count == 0, "a check must not write"


@pytest.mark.parametrize(
    ("built", "key"),
    [
        (lambda: link(target=COORDINATOR_IEEE), "zigbee_coordinator_binding_protected"),
        (lambda: link(target_endpoint=None), "zigbee_target_endpoint_required"),
        (lambda: link(source_endpoint=1), "zigbee_source_cannot_send"),
        (lambda: link(target_endpoint=2), "zigbee_target_cannot_receive"),
        (lambda: link(target="0x0011223344556677"), "zigbee_unknown_device"),
    ],
)
async def test_a_check_refuses_everything_an_add_would_refuse(
    backend: ZigbeeBackend, bridge: FakeBridge, built: object, key: str
) -> None:
    """Zigbee has no driver-side check, so a check is what can be answered without a radio.

    That turns out to be most of it, and all of it for free: the bridge already publishes
    every endpoint's clusters and every device it knows. The plan dialog can therefore say
    what apply would say without spending a request, which is more than the Z-Wave check
    manages and not less.
    """
    check = await backend.async_check_link(built())  # type: ignore[operator]

    assert not check.ok
    assert check.reason is not None
    assert check.reason.translation_key == key
    assert bridge.write_count == 0


async def test_a_check_on_an_offline_bridge_refuses(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    bridge.go_offline()

    check = await backend.async_check_link(link())

    assert not check.ok
    assert check.reason is not None
    assert check.reason.translation_key == "zigbee_bridge_offline"


async def test_a_check_says_nothing_about_whether_the_link_is_already_there(
    backend: ZigbeeBackend,
) -> None:
    """A check answers "could this be written", which an existing binding does not change."""
    await backend.async_add_link(link())

    assert (await backend.async_check_link(link())).ok


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


def _with_settings(bridge: FakeBridge) -> ZigbeeBackend:
    """Return a backend whose profile database names a setting for this model.

    Built here rather than leaning on a shipped file, so these say something about the
    adapter rather than about whichever entries happen to ship.
    """
    document = {
        "devices": [
            {
                "backend": "zigbee2mqtt",
                "model": "VZM31-SN",
                "manufacturer": "Inovelli",
                "fingerprints": [{"vendor": "Inovelli", "model": "VZM31-SN"}],
                "emitters": [
                    {
                        "emitter_id": "paddle",
                        "label": "Paddle",
                        "kind": "paddle",
                        "endpoint": 2,
                        "actions": {"on_off": "genOnOff"},
                    }
                ],
                "settings": {
                    "smart_bulb_mode": {
                        "property": "smartBulbMode",
                        "values": {"off": 0, "on": 1},
                        "payloads": {"off": "Disabled", "on": "Enabled"},
                    }
                },
            }
        ]
    }
    return ZigbeeBackend(client=bridge, profiles=load_profiles({"t.json": json.dumps(document)}))


async def test_a_setting_the_profile_knows_reads_as_not_reported(
    bridge: FakeBridge,
) -> None:
    """The value lives on the device's own state topic, which this adapter does not read.

    None means "the device has not told us", which is exactly true and is different from
    zero. See docs/open-items.md T45.
    """
    backend = _with_settings(bridge)
    await backend.async_start()

    value = await backend.async_read_setting(handle(AUX_IEEE, AUX), "smart_bulb_mode")

    assert value.capability == "smart_bulb_mode"
    assert value.value is None
    assert value.parameter == 0, "a Zigbee setting is addressed by name, not by number"


async def test_a_setting_no_profile_entry_knows_is_refused_by_name(
    backend: ZigbeeBackend,
) -> None:
    with pytest.raises(Exception, match="invented_setting"):
        await backend.async_read_setting(handle(AUX_IEEE, AUX), "invented_setting")


async def test_writing_a_setting_says_plainly_that_it_is_not_written_yet(
    bridge: FakeBridge,
) -> None:
    """Refused rather than attempted, and the message says which.

    The property names in the profile entries come from Zigbee2MQTT's converters and could
    not be validated against the G1 capture, which trimmed `definition.exposes`. Writing on
    that basis, through a `set` round trip nobody has observed either, would be two
    unverified models stacked. See docs/open-items.md T45.
    """
    backend = _with_settings(bridge)
    await backend.async_start()

    result = await backend.async_write_setting(handle(AUX_IEEE, AUX), "smart_bulb_mode", 1)

    assert not result.ok
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_settings_not_written"
    assert bridge.write_count == 0


async def test_writing_a_setting_no_entry_knows_says_that_instead(
    backend: ZigbeeBackend,
) -> None:
    result = await backend.async_write_setting(handle(AUX_IEEE, AUX), "invented", 1)

    assert not result.ok
    assert result.reason is not None
    assert result.reason.translation_key == "settings_not_available"


# --------------------------------------------------------------------------------------
# The paths only a broken bridge or a hand-built link reaches
# --------------------------------------------------------------------------------------


async def test_a_link_whose_source_the_bridge_forgot_is_refused_rather_than_written(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The device was removed from the network between the plan and the apply."""
    bridge.devices = [d for d in bridge.devices if d["ieee_address"] != AUX_IEEE]
    bridge._republish(zp.DEVICES_TOPIC)

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_unknown_device"


async def test_a_link_pointing_at_a_group_the_bridge_does_not_report_is_refused(
    backend: ZigbeeBackend,
) -> None:
    result = await backend.async_add_link(
        link(target="group:12", target_endpoint=None, rule_id=None)
    )

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_unknown_device"


async def test_a_link_pointing_at_a_managed_group_is_written_as_it_stands(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A group has no clusters of its own, so what its members can act on is not asked here."""
    bridge.add_group("dl_hall", 3, [{"ieee_address": LIGHT_IEEE, "endpoint": 1}])

    result = await backend.async_add_link(
        link(target="group:3", target_endpoint=None, rule_id=None)
    )

    assert result.status is LinkResultStatus.APPLIED
    assert bridge.bindings_of(AUX, 2)[-1]["target"] == {"type": "group", "id": 3}


async def test_a_battery_device_the_bridge_forgot_is_not_reported_as_asleep(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """`_is_battery` has to answer for a device it cannot see, and the answer is no."""
    bridge.silent = True
    bridge.devices = [
        d if d["ieee_address"] != AUX_IEEE else {**d, "power_source": None} for d in bridge.devices
    ]
    bridge._republish(zp.DEVICES_TOPIC)

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED


async def test_a_binding_to_a_device_the_bridge_has_forgotten_still_reads_back(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The entry is on the device, so it has to be reportable, whoever it points at.

    A link nobody can see is a link nobody can plan to remove, so a target the bridge no
    longer lists gets a handle carrying its address and nothing else.
    """
    bridge.add_binding(
        AUX,
        2,
        zp.GEN_ON_OFF,
        {"type": "endpoint", "ieee_address": "0x00158d0001aabbcc", "endpoint": 1},
    )

    observed = await backend.async_observed(handle(AUX_IEEE, AUX))
    orphan = next(
        item for item in observed.links if item.target.handle.protocol_id.startswith("0x0015")
    )

    assert orphan.target.handle.name_at_authoring == "0x00158d0001aabbcc"
    assert not orphan.is_system


async def test_a_source_the_bridge_forgot_is_not_treated_as_a_battery_device(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """`_is_battery` is asked after a failure, when the device may already be gone.

    A wake-up prompt for a device that is no longer on the network would be an instruction
    nobody can follow, so an unknown device is not a battery one.
    """
    assert backend._is_battery(handle("0x0011223344556677")) is False
