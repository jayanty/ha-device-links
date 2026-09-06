"""The fake bridge is what the whole Zigbee write path is proved against, so prove it first.

Everything below the read tests describes behaviour nobody has observed: Stage 0 item G2 was
never approved. Assumption A2 in `docs/open-items.md`, issue #6. These tests are as wrong as
the model is, on purpose, and they are corrected together with it when G2 runs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from custom_components.device_links.backends import zigbee_protocol as zp
from tests.factories import AUX_IEEE, COORDINATOR_IEEE, LIGHT_IEEE
from tests.fakes.zigbee import FakeBridge, build_bridge_from_fixture

AUX = "Entrance Inside Lights Aux"
LIGHT = "Entrance Inside Lights"
KITCHEN = "Kitchen Lights"


@pytest.fixture
def bridge() -> FakeBridge:
    return build_bridge_from_fixture()


class Recorder:
    """Collects what the bridge published, so a test can read it back."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, Any]] = []

    def __call__(self, topic: str, payload: str) -> None:
        self.messages.append((topic, json.loads(payload)))

    def last(self, suffix: str) -> Any:
        """Return the most recent payload published on a topic ending in this."""
        for topic, payload in reversed(self.messages):
            if topic.endswith(suffix):
                return payload
        raise AssertionError(f"nothing was published on a topic ending {suffix!r}")

    def count(self, suffix: str) -> int:
        return sum(1 for topic, _ in self.messages if topic.endswith(suffix))


async def _subscribed(bridge: FakeBridge, topic: str = "zigbee2mqtt/#") -> Recorder:
    recorder = Recorder()
    await bridge.async_subscribe(topic, recorder)
    return recorder


# --------------------------------------------------------------------------------------
# The read half, which the G1 capture proves
# --------------------------------------------------------------------------------------


async def test_subscribing_delivers_the_retained_topics_at_once(bridge: FakeBridge) -> None:
    """The bridge topics are retained, so a real broker does exactly this on subscribe."""
    recorder = await _subscribed(bridge)

    assert len(recorder.last("bridge/devices")) == 24
    assert recorder.last("bridge/groups") == []
    assert recorder.last("bridge/state") == {"state": "online"}
    assert recorder.last("bridge/info")["version"] == "2.14.1"


async def test_a_subscription_only_gets_what_its_filter_matches(bridge: FakeBridge) -> None:
    recorder = await _subscribed(bridge, "zigbee2mqtt/bridge/devices")

    assert recorder.count("bridge/devices") == 1
    assert recorder.count("bridge/groups") == 0


async def test_unsubscribing_stops_delivery(bridge: FakeBridge) -> None:
    recorder = Recorder()
    unsubscribe = await bridge.async_subscribe("zigbee2mqtt/#", recorder)
    before = len(recorder.messages)

    unsubscribe()
    bridge.go_offline()

    assert len(recorder.messages) == before


async def test_the_capture_starts_with_every_binding_on_the_coordinator(
    bridge: FakeBridge,
) -> None:
    """The recorded starting state, and the reason a system-link classifier is needed."""
    bindings = bridge.bindings_of(AUX, 1)

    assert bindings
    assert all(binding["target"]["ieee_address"] == COORDINATOR_IEEE for binding in bindings)
    assert bridge.groups == []


async def test_a_rename_changes_the_name_and_not_the_address(bridge: FakeBridge) -> None:
    """E23, from the bridge's side: the IEEE address is what survives."""
    bridge.rename(AUX_IEEE, "Front Door Aux")

    assert bridge.device_named("Front Door Aux")["ieee_address"] == AUX_IEEE


# --------------------------------------------------------------------------------------
# The write half. Modelled, never observed: assumption A2, issue #6.
# --------------------------------------------------------------------------------------


async def _bind(  # noqa: PLR0913
    bridge: FakeBridge,
    *,
    clusters: list[str],
    transaction: str = "t1",
    source: str = AUX,
    source_endpoint: int = 2,
    target: str = LIGHT,
    target_endpoint: int | None = 1,
    unbind: bool = False,
) -> None:
    request = zp.BindRequest(
        source_name=source,
        source_endpoint=source_endpoint,
        target=target,
        target_endpoint=target_endpoint,
        clusters=tuple(clusters),
        transaction=transaction,
    )
    payload = zp.unbind_payload(request) if unbind else zp.bind_payload(request)
    topic = zp.UNBIND_REQUEST if unbind else zp.BIND_REQUEST
    await bridge.async_publish(f"zigbee2mqtt/{topic}", json.dumps(payload))


async def test_a_bind_updates_bridge_devices_and_republishes_it(bridge: FakeBridge) -> None:
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL])

    assert [binding["cluster"] for binding in bridge.bindings_of(AUX, 2)] == [
        "manuSpecificInovelli",
        zp.GEN_ON_OFF,
        zp.GEN_LEVEL_CTRL,
    ]
    published = recorder.last("bridge/devices")
    aux = next(device for device in published if device["friendly_name"] == AUX)
    assert len(aux["endpoints"]["2"]["bindings"]) == 3


async def test_an_unbind_removes_exactly_what_it_names(bridge: FakeBridge) -> None:
    await _bind(bridge, clusters=[zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL])

    await _bind(bridge, clusters=[zp.GEN_LEVEL_CTRL], unbind=True)

    assert [binding["cluster"] for binding in bridge.bindings_of(AUX, 2)] == [
        "manuSpecificInovelli",
        zp.GEN_ON_OFF,
    ]


async def test_a_response_carries_the_transaction_it_was_asked_with(bridge: FakeBridge) -> None:
    """Correlation is by transaction and by nothing else: MQTT does not order responses."""
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF], transaction="abc123")

    assert recorder.last("response/device/bind")["transaction"] == "abc123"


async def test_two_requests_answered_out_of_order_are_still_tellable_apart(
    bridge: FakeBridge,
) -> None:
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF], transaction="first")
    await _bind(bridge, clusters=[zp.GEN_LEVEL_CTRL], transaction="second", target=KITCHEN)

    transactions = [
        payload["transaction"]
        for topic, payload in recorder.messages
        if topic.endswith("response/device/bind")
    ]
    assert transactions == ["first", "second"]


async def test_a_partial_failure_reports_status_ok(bridge: FakeBridge) -> None:
    """The documented behaviour that makes the naive check wrong.

    One cluster of two failing is `status: "ok"` with that cluster in `failed`. A caller
    that reads `status` alone believes the whole bind landed.
    """
    bridge.fail_clusters = {zp.GEN_LEVEL_CTRL}
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL])

    response = recorder.last("response/device/bind")
    assert response["status"] == "ok"
    assert response["data"]["failed"] == [zp.GEN_LEVEL_CTRL]
    assert [b["cluster"] for b in bridge.bindings_of(AUX, 2)] == [
        "manuSpecificInovelli",
        zp.GEN_ON_OFF,
    ], "the cluster that failed must not be on the device"


async def test_every_cluster_failing_reports_status_error(bridge: FakeBridge) -> None:
    bridge.fail_clusters = {zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL}
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL])

    response = recorder.last("response/device/bind")
    assert response["status"] == "error"
    assert response["error"]
    assert response["data"]["failed"] == [zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL]


async def test_a_cluster_the_source_does_not_drive_fails(bridge: FakeBridge) -> None:
    """Endpoint 1 is the load and drives only OTA, so nothing binds from it."""
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF], source_endpoint=1)

    assert recorder.last("response/device/bind")["status"] == "error"


async def test_a_request_can_get_no_response_at_all(bridge: FakeBridge) -> None:
    """A restarted add-on, a lost message, or a bridge that simply never answered."""
    bridge.silent = True
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF])

    assert recorder.count("response/device/bind") == 0
    assert bridge.write_count == 1, "the request really was sent; only the answer is missing"


async def test_a_device_that_is_not_listening_refuses(bridge: FakeBridge) -> None:
    """What a sleeping battery source produces (E22)."""
    bridge.unresponsive = {AUX_IEEE}
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF])

    response = recorder.last("response/device/bind")
    assert response["status"] == "error"
    assert "did not respond" in response["error"]
    assert bridge.bindings_of(AUX, 2) == [
        {
            "cluster": "manuSpecificInovelli",
            "target": {"type": "endpoint", "ieee_address": COORDINATOR_IEEE, "endpoint": 1},
        }
    ]


async def test_a_request_naming_a_device_that_does_not_exist_is_refused(
    bridge: FakeBridge,
) -> None:
    recorder = await _subscribed(bridge)

    await _bind(bridge, clusters=[zp.GEN_ON_OFF], target="Nowhere")

    assert "does not exist" in recorder.last("response/device/bind")["error"]


# --------------------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------------------


async def _group_request(bridge: FakeBridge, topic: str, payload: dict[str, Any]) -> None:
    await bridge.async_publish(f"zigbee2mqtt/{topic}", json.dumps(payload))


async def test_creating_a_group_allocates_an_id_and_republishes_the_groups(
    bridge: FakeBridge,
) -> None:
    recorder = await _subscribed(bridge)

    await _group_request(
        bridge, zp.GROUP_ADD_REQUEST, zp.group_add_payload(friendly_name="dl_r1", transaction="t")
    )

    assert recorder.last("response/group/add")["data"]["id"] == 1
    assert recorder.last("bridge/groups") == [{"id": 1, "friendly_name": "dl_r1", "members": []}]


async def test_members_can_be_added_and_removed(bridge: FakeBridge) -> None:
    await _group_request(
        bridge, zp.GROUP_ADD_REQUEST, zp.group_add_payload(friendly_name="dl_r1", transaction="t")
    )
    member = zp.group_member_payload(
        friendly_name="dl_r1", device_name=LIGHT, endpoint=1, transaction="t"
    )

    await _group_request(bridge, zp.GROUP_MEMBER_ADD_REQUEST, member)
    added = bridge.group_named("dl_r1")

    await _group_request(bridge, zp.GROUP_MEMBER_REMOVE_REQUEST, member)

    assert added is not None
    assert added["members"] == []
    assert bridge.group_named("dl_r1") == {"id": 1, "friendly_name": "dl_r1", "members": []}


async def test_a_group_can_be_bound_to_and_the_binding_names_the_group(
    bridge: FakeBridge,
) -> None:
    await _group_request(
        bridge, zp.GROUP_ADD_REQUEST, zp.group_add_payload(friendly_name="dl_r1", transaction="t")
    )

    await _bind(bridge, clusters=[zp.GEN_ON_OFF], target="dl_r1", target_endpoint=None)

    assert bridge.bindings_of(AUX, 2)[-1]["target"] == {"type": "group", "id": 1}


async def test_deleting_a_group_drops_the_bindings_that_pointed_at_it(
    bridge: FakeBridge,
) -> None:
    await _group_request(
        bridge, zp.GROUP_ADD_REQUEST, zp.group_add_payload(friendly_name="dl_r1", transaction="t")
    )
    await _bind(bridge, clusters=[zp.GEN_ON_OFF], target="dl_r1", target_endpoint=None)

    await _group_request(
        bridge,
        zp.GROUP_REMOVE_REQUEST,
        zp.group_remove_payload(friendly_name="dl_r1", transaction="t"),
    )

    assert bridge.group_named("dl_r1") is None
    assert [b["cluster"] for b in bridge.bindings_of(AUX, 2)] == ["manuSpecificInovelli"]


async def test_the_fake_will_modify_a_group_with_no_managed_prefix(bridge: FakeBridge) -> None:
    """Deliberate. A real bridge would, and a fake that refused would make our guard untested.

    The refusal that matters is `zigbee_protocol.ForeignGroupError` and the adapter's own
    check. This asserts that nothing here is quietly doing that work for them.
    """
    recorder = await _subscribed(bridge)

    await _group_request(
        bridge, zp.GROUP_ADD_REQUEST, {"friendly_name": "kitchen", "transaction": "t"}
    )

    assert recorder.last("response/group/add")["status"] == "ok"
    assert bridge.group_named("kitchen") is not None


async def test_a_second_group_with_the_same_name_is_refused_by_the_bridge(
    bridge: FakeBridge,
) -> None:
    bridge.add_group("dl_r1", 4)
    recorder = await _subscribed(bridge)

    await _group_request(
        bridge, zp.GROUP_ADD_REQUEST, zp.group_add_payload(friendly_name="dl_r1", transaction="t")
    )

    assert "already exists" in recorder.last("response/group/add")["error"]


async def test_a_membership_change_on_a_group_that_is_gone_is_refused(
    bridge: FakeBridge,
) -> None:
    recorder = await _subscribed(bridge)

    await _group_request(
        bridge,
        zp.GROUP_MEMBER_ADD_REQUEST,
        zp.group_member_payload(
            friendly_name="dl_gone", device_name=LIGHT, endpoint=1, transaction="t"
        ),
    )

    assert "does not exist" in recorder.last("response/group/members/add")["error"]


async def test_a_membership_change_naming_an_unknown_device_is_refused(
    bridge: FakeBridge,
) -> None:
    bridge.add_group("dl_r1", 1)
    recorder = await _subscribed(bridge)

    await _group_request(
        bridge,
        zp.GROUP_MEMBER_ADD_REQUEST,
        zp.group_member_payload(
            friendly_name="dl_r1", device_name="Nowhere", endpoint=1, transaction="t"
        ),
    )

    assert "does not exist" in recorder.last("response/group/members/add")["error"]


async def test_removing_a_group_that_does_not_exist_is_refused(bridge: FakeBridge) -> None:
    recorder = await _subscribed(bridge)

    await _group_request(
        bridge,
        zp.GROUP_REMOVE_REQUEST,
        zp.group_remove_payload(friendly_name="dl_gone", transaction="t"),
    )

    assert "does not exist" in recorder.last("response/group/remove")["error"]


# --------------------------------------------------------------------------------------
# Bridge lifecycle
# --------------------------------------------------------------------------------------


async def test_the_bridge_can_go_offline_and_come_back(bridge: FakeBridge) -> None:
    """E26: a Zigbee2MQTT restart, and the retained re-read that follows it."""
    recorder = await _subscribed(bridge)

    bridge.go_offline()
    assert recorder.last("bridge/state") == {"state": "offline"}

    bridge.come_back()
    assert recorder.last("bridge/state") == {"state": "online"}
    assert recorder.count("bridge/devices") == 2


async def test_a_request_topic_the_bridge_does_not_know_goes_unanswered(
    bridge: FakeBridge,
) -> None:
    """Which is what a timeout is made of, and better than answering the wrong thing."""
    recorder = await _subscribed(bridge)

    await bridge.async_publish("zigbee2mqtt/bridge/request/device/invented", "{}")

    assert recorder.count("response") == 0
    assert bridge.request_count == 1


async def test_power_source_can_be_changed_because_no_bindable_battery_device_exists(
    bridge: FakeBridge,
) -> None:
    """The four Aqara sensors are battery but drive no bindable cluster, so E22 needs this."""
    bridge.set_power_source(AUX_IEEE, "Battery")

    assert bridge.device_named(AUX)["power_source"] == "Battery"


async def test_the_fixture_devices_are_copied_rather_than_shared(bridge: FakeBridge) -> None:
    """Two bridges in one session must not write into each other, or into the fixture."""
    other = build_bridge_from_fixture()
    await _bind(bridge, clusters=[zp.GEN_ON_OFF])

    assert len(bridge.bindings_of(AUX, 2)) == 2
    assert len(other.bindings_of(AUX, 2)) == 1


async def test_a_bridge_can_be_built_from_devices_a_test_made_up() -> None:
    made_up: list[Any] = [
        {
            "ieee_address": LIGHT_IEEE,
            "friendly_name": "Invented",
            "type": "Router",
            "endpoints": {"1": {"bindings": [], "clusters": {"input": [], "output": []}}},
        }
    ]

    made = FakeBridge(devices=made_up, base_topic="zigbee2mqtt2")
    recorder = await _subscribed(made, "zigbee2mqtt2/#")

    assert len(recorder.last("bridge/devices")) == 1
