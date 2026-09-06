"""Managed groups: Decision D5's one-to-many, and the guard that makes it safe to ship.

Unicast to many targets sends the command once per target, sequentially, and fills the
source's binding table, so D5 puts a one-to-many rule behind one managed Zigbee group. Every
group Device Links creates is named `dl_<rule id>`, and **a group without that prefix is
never created, never read for membership, and never deleted**: a user's own groups are not
ours to modify, and the prefix is the only thing that says which is which.

Modelled, never observed: item G2 was not approved. Assumption A2, issue #6.
"""

from __future__ import annotations

import logging

import pytest

from custom_components.device_links.backends import zigbee_protocol as zp
from custom_components.device_links.backends.base import LinkResultStatus
from custom_components.device_links.backends.zigbee2mqtt import ZigbeeBackend
from tests.factories import AUX_IEEE, LIGHT_IEEE, OLD_FIRMWARE_IEEE, SECOND_LIGHT_IEEE, profiles
from tests.fakes.zigbee import FakeBridge, build_bridge_from_fixture
from tests.test_zigbee_writes import AUX, handle, link


@pytest.fixture
def bridge() -> FakeBridge:
    return build_bridge_from_fixture()


@pytest.fixture
async def backend(bridge: FakeBridge) -> ZigbeeBackend:
    built = ZigbeeBackend(client=bridge, profiles=profiles(), request_timeout=0.2)
    await built.async_start()
    return built


def _clusters_bound(bridge: FakeBridge) -> list[tuple[str, object]]:
    return [(b["cluster"], b["target"]) for b in bridge.bindings_of(AUX, 2)]


# --------------------------------------------------------------------------------------
# One target, then a second
# --------------------------------------------------------------------------------------


async def test_one_target_is_a_plain_binding_and_makes_no_group(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """D5 is about one-to-many. A rule with one target does not need a group, and a group
    per rule would fill a user's Zigbee2MQTT with entries that buy them nothing.
    """
    result = await backend.async_add_link(link(target=LIGHT_IEEE))

    assert result.status is LinkResultStatus.APPLIED
    assert bridge.groups == []
    assert _clusters_bound(bridge)[-1][1]["type"] == "endpoint"  # type: ignore[index]


async def test_a_second_target_creates_the_managed_group_for_that_rule(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    await backend.async_add_link(link(target=LIGHT_IEEE, rule_id="hallway"))

    result = await backend.async_add_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.APPLIED
    group = bridge.group_named("dl_hallway")
    assert group is not None
    assert group["members"] == [{"ieee_address": SECOND_LIGHT_IEEE, "endpoint": 1}]
    assert {b["target"]["type"] for b in bridge.bindings_of(AUX, 2)} == {"endpoint", "group"}


async def test_a_third_target_joins_the_same_group(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    group = bridge.group_named("dl_hallway")
    assert group is not None
    assert [member["ieee_address"] for member in group["members"]] == [
        SECOND_LIGHT_IEEE,
        OLD_FIRMWARE_IEEE,
    ]
    assert len(bridge.bindings_of(AUX, 2)) == 3, "one reporting, one unicast, one group"


async def test_the_group_binding_is_written_once_per_cluster(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A rule asking for on/off and dimming binds two clusters to the same group."""
    for feature in (zp.Feature.ON_OFF, zp.Feature.LEVEL_SET):
        await backend.async_add_link(link(target=LIGHT_IEEE, feature=feature, rule_id="hall"))
        await backend.async_add_link(
            link(target=SECOND_LIGHT_IEEE, feature=feature, rule_id="hall")
        )

    to_group = [b for b in bridge.bindings_of(AUX, 2) if b["target"]["type"] == "group"]
    assert sorted(b["cluster"] for b in to_group) == [zp.GEN_LEVEL_CTRL, zp.GEN_ON_OFF]
    assert len(bridge.group_named("dl_hall")["members"]) == 1  # type: ignore[index]


async def test_everything_the_rule_asked_for_reads_back(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The whole point: a group binding must expand back into the links that asked for it."""
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    observed = await backend.async_observed(handle(AUX_IEEE, AUX))
    reached = {
        connection.target.handle.protocol_id
        for connection in observed.links
        if connection.source_endpoint == 2 and not connection.is_system
    }

    assert reached == {LIGHT_IEEE, SECOND_LIGHT_IEEE}


async def test_applying_the_same_links_again_writes_nothing(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))
    before = bridge.write_count

    results = [
        await backend.async_add_link(link(target=target, rule_id="hallway"))
        for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE)
    ]

    assert all(result.status is LinkResultStatus.ALREADY_PRESENT for result in results)
    assert bridge.write_count == before


# --------------------------------------------------------------------------------------
# Taking targets away
# --------------------------------------------------------------------------------------


async def test_removing_a_grouped_target_takes_it_out_of_the_group(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    result = await backend.async_remove_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.APPLIED
    group = bridge.group_named("dl_hallway")
    assert group is not None
    assert [member["ieee_address"] for member in group["members"]] == [OLD_FIRMWARE_IEEE]


async def test_the_group_goes_when_its_last_member_does(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Nothing is left behind on the bridge for a rule that no longer drives anything."""
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    await backend.async_remove_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert bridge.group_named("dl_hallway") is None
    assert [b["target"]["type"] for b in bridge.bindings_of(AUX, 2)] == ["endpoint", "endpoint"]


async def test_removing_every_link_of_a_rule_leaves_the_bridge_as_it_was(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    before = list(bridge.bindings_of(AUX, 2))
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_remove_link(link(target=target, rule_id="hallway"))

    assert bridge.bindings_of(AUX, 2) == before
    assert bridge.groups == []


# --------------------------------------------------------------------------------------
# A group that is not ours
# --------------------------------------------------------------------------------------


async def test_a_group_without_the_prefix_is_never_touched(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The guard that makes this feature safe to ship. The fake bridge would allow it."""
    bridge.add_group("kitchen", 5, [{"ieee_address": LIGHT_IEEE, "endpoint": 1}])
    before = bridge.write_count

    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    assert bridge.group_named("kitchen") == {
        "id": 5,
        "friendly_name": "kitchen",
        "members": [{"ieee_address": LIGHT_IEEE, "endpoint": 1}],
    }
    assert bridge.write_count > before, "the rule was applied; only the foreign group is untouched"


async def test_a_link_pointing_at_a_foreign_group_is_refused(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A rule cannot be made to drive somebody else's group either."""
    bridge.add_group("kitchen", 5)
    before = bridge.write_count

    result = await backend.async_add_link(
        link(target="group:5", target_endpoint=None, rule_id=None)
    )

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_foreign_group"
    assert bridge.write_count == before


async def test_the_payload_builders_refuse_a_foreign_group_whatever_the_adapter_does() -> None:
    """Defence in depth: the guard is in the pure module too, where nothing can route round it."""
    with pytest.raises(zp.ForeignGroupError):
        zp.group_remove_payload(friendly_name="kitchen", transaction="t")


async def test_reusing_a_managed_group_this_session_did_not_create_says_so(
    backend: ZigbeeBackend, bridge: FakeBridge, caplog: pytest.LogCaptureFixture
) -> None:
    """E24. A `dl_` name is ours by the only test there is, so it is adopted, not duplicated.

    Adopted rather than taken over: only the member this link names is added, so whatever
    else is in it is left exactly as it is.
    """
    bridge.add_group("dl_hallway", 6, [{"ieee_address": OLD_FIRMWARE_IEEE, "endpoint": 1}])

    with caplog.at_level(logging.WARNING):
        await backend.async_add_link(link(target=LIGHT_IEEE, rule_id="hallway"))
        await backend.async_add_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    group = bridge.group_named("dl_hallway")
    assert group is not None
    assert [member["ieee_address"] for member in group["members"]] == [
        OLD_FIRMWARE_IEEE,
        SECOND_LIGHT_IEEE,
    ]
    assert any("dl_hallway" in record.getMessage() for record in caplog.records)


async def test_a_managed_group_that_has_disappeared_is_recreated_on_apply(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """E24. Somebody deleted it in Zigbee2MQTT; the next apply puts it back."""
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))
    bridge.groups.clear()
    bridge._republish(zp.GROUPS_TOPIC)

    result = await backend.async_add_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.APPLIED
    group = bridge.group_named("dl_hallway")
    assert group is not None
    assert [member["ieee_address"] for member in group["members"]] == [SECOND_LIGHT_IEEE]


# --------------------------------------------------------------------------------------
# The lifecycle a rule's deletion does not reach
# --------------------------------------------------------------------------------------


async def test_a_managed_group_can_be_dropped_by_rule_id(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """What answers "a rule was deleted while Home Assistant was down".

    Nothing in core calls this yet: the `Backend` protocol writes one link at a time and
    never sees the rule, so nothing below it can know that a rule has stopped existing.
    See docs/open-items.md T41.
    """
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    assert await backend.async_drop_managed_group("hallway") is True

    assert bridge.group_named("dl_hallway") is None
    assert [b["target"]["type"] for b in bridge.bindings_of(AUX, 2)] == ["endpoint", "endpoint"]


async def test_dropping_a_group_that_is_not_there_is_not_an_error(
    backend: ZigbeeBackend,
) -> None:
    assert await backend.async_drop_managed_group("never_existed") is False


async def test_the_groups_a_rule_owns_can_be_listed(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """So whoever does know which rules exist can find the ones that no longer do."""
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))
    bridge.add_group("kitchen", 9)

    assert backend.managed_group_rule_ids() == frozenset({"hallway"})


# --------------------------------------------------------------------------------------
# When a group operation goes wrong
# --------------------------------------------------------------------------------------


async def test_a_group_request_that_is_refused_is_a_failed_link(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    await backend.async_add_link(link(target=LIGHT_IEEE, rule_id="hallway"))
    bridge.silent = True

    result = await backend.async_add_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_group_failed"


async def test_a_failed_membership_change_does_not_leave_the_link_looking_applied(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A group that exists and does not hold the target is a link that does nothing."""
    await backend.async_add_link(link(target=LIGHT_IEEE, rule_id="hallway"))
    bridge.add_group("dl_hallway", 7)
    bridge.silent = True

    result = await backend.async_add_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.FAILED


async def test_a_group_that_vanishes_between_the_plan_and_the_write_is_nothing_to_do(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Somebody deleted it in Zigbee2MQTT while the apply was running.

    There is nothing on the device answering to this link any more, and nothing went wrong,
    so it is `already_present` in the sense that matters: the removal has happened.
    """
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))
    bridge.groups.clear()
    bridge._republish(zp.GROUPS_TOPIC)

    result = await backend.async_remove_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.ALREADY_PRESENT


async def test_the_group_a_link_already_names_is_not_wrapped_in_another_one(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """A link whose target is a group is written as it stands, rule or no rule."""
    bridge.add_group("dl_hall", 3, [{"ieee_address": LIGHT_IEEE, "endpoint": 1}])

    result = await backend.async_add_link(
        link(target="group:3", target_endpoint=None, rule_id="hallway")
    )

    assert result.status is LinkResultStatus.APPLIED
    assert bridge.group_named("dl_hallway") is None


async def test_a_group_the_bridge_accepts_and_then_does_not_list_is_a_failure(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Answered, and still not there. Nothing is reported as applied on the strength of a
    response alone when the thing it was about cannot be found afterwards.
    """
    await backend.async_add_link(link(target=LIGHT_IEEE, rule_id="hallway"))

    def _delete_it_again(topic: str, payload: str) -> None:
        bridge.groups.clear()
        bridge._republish(zp.GROUPS_TOPIC)

    await bridge.async_subscribe("zigbee2mqtt/bridge/response/group/add", _delete_it_again)

    result = await backend.async_add_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_group_failed"


async def test_the_adapter_guard_refuses_a_foreign_group_by_name(
    backend: ZigbeeBackend,
) -> None:
    """Redundant with the payload builders on purpose: both would have to fail."""
    with pytest.raises(zp.ForeignGroupError):
        await backend._remove_group("kitchen")


async def test_a_link_naming_a_group_that_is_gone_by_the_time_it_is_written_is_refused(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Between `_absolute_refusal` saying the group is there and the request being built,
    somebody deleted it in Zigbee2MQTT. Refused rather than sent to a name that means
    nothing.
    """
    bridge.add_group("dl_hall", 3)

    def _delete_it(topic: str, payload: str) -> None:
        bridge.groups.clear()
        bridge._republish(zp.GROUPS_TOPIC)

    await bridge.async_subscribe("zigbee2mqtt/bridge/response/group/members/add", _delete_it)
    await backend.async_add_link(link(target=LIGHT_IEEE, rule_id="hall"))

    result = await backend.async_add_link(link(target=SECOND_LIGHT_IEEE, rule_id="hall"))

    assert result.status is LinkResultStatus.FAILED


async def test_a_control_bound_to_a_group_that_does_not_hold_the_target_is_not_removable_there(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Two managed groups on one cluster, and only one of them holds what is being removed."""
    bridge.add_group("dl_other", 8, [{"ieee_address": OLD_FIRMWARE_IEEE, "endpoint": 1}])
    bridge.add_binding(AUX, 2, zp.GEN_ON_OFF, {"type": "group", "id": 8})
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    result = await backend.async_remove_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.APPLIED
    assert bridge.group_named("dl_other") is not None
    assert bridge.group_named("dl_hallway") is None


async def test_a_membership_removal_the_bridge_will_not_answer_is_a_failed_link(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """Half a removal is worse than none: the group would still drive what the rule dropped."""
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))
    bridge.silent = True

    result = await backend.async_remove_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_group_failed"


async def test_a_group_deletion_the_bridge_will_not_answer_is_a_failed_link(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The last member came out and the group did not, so the link is not done."""
    for target in (LIGHT_IEEE, SECOND_LIGHT_IEEE):
        await backend.async_add_link(link(target=target, rule_id="hallway"))

    def _swallow(topic: str, payload: str) -> None:
        bridge.silent = True

    await bridge.async_subscribe("zigbee2mqtt/bridge/response/group/members/remove", _swallow)

    result = await backend.async_remove_link(link(target=SECOND_LIGHT_IEEE, rule_id="hallway"))

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "zigbee_group_failed"


async def test_a_binding_to_a_foreign_group_is_not_a_membership_this_rule_can_remove(
    backend: ZigbeeBackend, bridge: FakeBridge
) -> None:
    """The control drives a group that is not ours, and the target is not in it either.

    Nothing here is removable through a group: what makes the link present is the plain
    binding, and that is what comes off.
    """
    bridge.add_group("kitchen", 5, [{"ieee_address": LIGHT_IEEE, "endpoint": 1}])
    bridge.add_binding(AUX, 2, zp.GEN_ON_OFF, {"type": "group", "id": 5})
    await backend.async_add_link(link(target=LIGHT_IEEE, rule_id=None))

    result = await backend.async_remove_link(link(target=LIGHT_IEEE, rule_id=None))

    assert result.status is LinkResultStatus.APPLIED
    assert bridge.group_named("kitchen") == {
        "id": 5,
        "friendly_name": "kitchen",
        "members": [{"ieee_address": LIGHT_IEEE, "endpoint": 1}],
    }
