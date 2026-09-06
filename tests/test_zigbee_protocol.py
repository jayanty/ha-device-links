"""Pure Zigbee interpretation, driven by the Stage 0 G1 capture of the real bridge.

The read half of this is proven: `tests/fixtures/g1_bridge.json` is a byte-for-byte capture
of Jayant's Zigbee2MQTT 2.14.1 bridge, so every assertion about parsing is an assertion
about hardware. The request half is not: Stage 0 item G2 was never approved, so the payload
shapes below come from the Zigbee2MQTT documentation. See assumption A2 in
`docs/open-items.md` and issue #6. These tests are as wrong as the model is, deliberately,
and they get corrected together when G2 runs.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.device_links.backends import zigbee_protocol as zp
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import Emitter, Feature, ZigbeeFingerprint
from tests.factories import (
    AUX_IEEE,
    COORDINATOR_IEEE,
    LIGHT_IEEE,
    OLD_FIRMWARE_IEEE,
    zigbee_device,
    zigbee_devices,
)

# --------------------------------------------------------------------------------------
# Devices, handles and identity
# --------------------------------------------------------------------------------------


def test_every_device_in_the_capture_parses_into_a_handle() -> None:
    """A device the parser drops is a device no rule can name."""
    handles = [zp.handle_of(device) for device in zigbee_devices().values()]

    assert len(handles) == 24
    assert all(handle.backend is BackendId.ZIGBEE2MQTT for handle in handles)
    assert len({handle.identity for handle in handles}) == 24


def test_a_handle_is_keyed_on_the_ieee_address_and_not_on_the_friendly_name() -> None:
    """E23. Friendly names are renameable and a handle keyed on one breaks silently."""
    handle = zp.handle_of(zigbee_device(AUX_IEEE))

    assert handle.protocol_id == AUX_IEEE
    assert handle.identity == f"zigbee2mqtt:{AUX_IEEE}"
    assert handle.name_at_authoring == "Entrance Inside Lights Aux"
    assert handle.name_at_authoring not in handle.identity


def test_a_renamed_device_keeps_the_same_identity() -> None:
    """The whole point of E23, stated as the property that matters."""
    device = zigbee_device(AUX_IEEE)
    renamed = {**device, "friendly_name": "Front Door Aux Switch"}

    assert zp.handle_of(renamed).identity == zp.handle_of(device).identity  # type: ignore[arg-type]


def test_a_handle_carries_the_fingerprint_a_profile_is_looked_up_by() -> None:
    handle = zp.handle_of(zigbee_device(AUX_IEEE))

    assert handle.fingerprint == ZigbeeFingerprint(manufacturer="Inovelli", model="VZM31-SN")


def test_the_coordinator_has_no_definition_and_still_gets_a_fingerprint() -> None:
    """It is a device in the list, so it needs a handle; it is simply not a curated model."""
    handle = zp.handle_of(zigbee_device(COORDINATOR_IEEE))

    assert handle.fingerprint == ZigbeeFingerprint(manufacturer="", model="")
    assert zp.is_coordinator(zigbee_device(COORDINATOR_IEEE))
    assert not zp.is_coordinator(zigbee_device(AUX_IEEE))


def test_a_group_handle_is_addressable_and_is_not_an_ieee_address() -> None:
    handle = zp.group_handle(7, "dl_hallway")

    assert handle.protocol_id == "group:7"
    assert zp.group_id_of(handle) == 7
    assert zp.group_id_of(zp.handle_of(zigbee_device(AUX_IEEE))) is None


def test_a_group_handle_with_a_nonsense_id_is_not_read_as_a_group() -> None:
    """Nothing builds one, so this is about what a deserialized handle cannot smuggle in."""
    broken = replace(zp.group_handle(7, "dl_hallway"), protocol_id="group:seven")

    assert zp.group_id_of(broken) is None


# --------------------------------------------------------------------------------------
# Emitters: what a device can drive
# --------------------------------------------------------------------------------------


def test_an_endpoint_with_output_clusters_becomes_an_emitter() -> None:
    """PRD Section 3.2: VZM31-SN endpoint 2 is the paddle and endpoint 3 is the config button."""
    emitters = zp.derive_emitters(zigbee_device(AUX_IEEE))

    assert [emitter.emitter_id for emitter in emitters] == ["ep2", "ep3"]


def test_gen_on_off_maps_to_on_off() -> None:
    paddle = _emitter(AUX_IEEE, "ep2")

    assert paddle.actions[Feature.ON_OFF] == zp.GEN_ON_OFF


def test_gen_level_ctrl_maps_to_both_level_set_and_level_hold() -> None:
    """Zigbee does not separate them the way Z-Wave association groups do.

    One cluster carries Move To Level and Move/Step/Stop, so binding it gives the user
    both. Telling the compiler they are separate emitters would be inventing a distinction
    the radio does not have, and telling it only one exists would hide half of what a bind
    actually does.
    """
    paddle = _emitter(AUX_IEEE, "ep2")

    assert paddle.actions[Feature.LEVEL_SET] == zp.GEN_LEVEL_CTRL
    assert paddle.actions[Feature.LEVEL_HOLD] == zp.GEN_LEVEL_CTRL


def test_one_cluster_carrying_two_features_is_one_entry_in_the_binding_table() -> None:
    """`group_ids` is what the planner counts capacity against, so it counts clusters."""
    paddle = _emitter(AUX_IEEE, "ep2")

    assert paddle.group_ids == (zp.GEN_LEVEL_CTRL, zp.GEN_ON_OFF)
    assert len(paddle.actions) == 3


def test_an_endpoint_that_drives_nothing_bindable_is_not_offered_as_a_control() -> None:
    """Endpoint 242 drives green power and endpoint 1 drives only OTA."""
    warnings: list[str] = []

    emitters = zp.derive_emitters(zigbee_device(AUX_IEEE), warnings=warnings)

    assert not any(emitter.emitter_id in {"ep1", "ep242"} for emitter in emitters)
    assert any("genOta" in warning for warning in warnings)
    assert any("greenPower" in warning for warning in warnings)


def test_the_coordinator_offers_no_controls_at_all() -> None:
    assert zp.derive_emitters(zigbee_device(COORDINATOR_IEEE)) == []


def test_an_emitter_can_address_an_endpoint_because_every_zigbee_binding_does() -> None:
    paddle = _emitter(AUX_IEEE, "ep2")

    assert paddle.supports_endpoint_targets is True
    assert paddle.is_lifeline is False
    assert paddle.grouping == zp.GROUPING_ENDPOINT
    assert paddle.capacity == zp.BINDING_TABLE_CAPACITY


def test_an_older_firmware_reports_fewer_endpoints_and_that_is_honoured() -> None:
    """Hallway Side Lights is a VZM31-SN on software 2.00 with no endpoint 3 at all."""
    emitters = zp.derive_emitters(zigbee_device(OLD_FIRMWARE_IEEE))

    assert [emitter.emitter_id for emitter in emitters] == ["ep2"]


# --------------------------------------------------------------------------------------
# What a device can be made to do
# --------------------------------------------------------------------------------------


def test_receivable_features_come_from_the_input_clusters() -> None:
    """A link a device cannot act on is written, accepted and then does nothing forever."""
    assert zp.receivable_features(zigbee_device(LIGHT_IEEE)) == frozenset(
        {Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD, Feature.SCENE}
    )


def test_the_coordinator_receives_nothing_we_can_bind() -> None:
    assert zp.receivable_features(zigbee_device(COORDINATOR_IEEE)) == frozenset()


def test_emits_and_accepts_read_the_two_cluster_lists_the_right_way_round() -> None:
    """Binding a cluster an endpoint serves rather than drives is a binding that does nothing."""
    aux = zigbee_device(AUX_IEEE)

    assert zp.emits(aux, 2, zp.GEN_ON_OFF)
    assert not zp.accepts(aux, 2, zp.GEN_ON_OFF)
    assert zp.accepts(aux, 1, zp.GEN_ON_OFF)
    assert not zp.emits(aux, 1, zp.GEN_ON_OFF)
    assert not zp.emits(aux, 9, zp.GEN_ON_OFF), "endpoint 9 does not exist on this device"


# --------------------------------------------------------------------------------------
# Bindings already on the network
# --------------------------------------------------------------------------------------


def test_every_binding_in_the_capture_parses() -> None:
    parsed = [
        binding for device in zigbee_devices().values() for binding in zp.parse_bindings(device)
    ]

    assert parsed, "the capture has bindings and the parser found none"
    assert all(
        (binding.target_ieee is None) is not (binding.group_id is None) for binding in parsed
    )


def test_a_binding_whose_target_is_the_coordinator_is_a_system_link() -> None:
    """Every binding on this network today is one. They are the bridge's own reporting setup."""
    targets = {
        binding.target_ieee
        for device in zigbee_devices().values()
        for binding in zp.parse_bindings(device)
    }

    assert targets == {COORDINATOR_IEEE}


def test_a_group_target_parses_as_a_group_rather_than_as_an_endpoint() -> None:
    """No group exists on this network yet, so this is the shape the capture confirmed."""
    device = {
        "ieee_address": AUX_IEEE,
        "friendly_name": "Entrance Inside Lights Aux",
        "type": "Router",
        "endpoints": {
            "2": {
                "bindings": [{"cluster": "genOnOff", "target": {"type": "group", "id": 12}}],
                "clusters": {"input": [], "output": ["genOnOff"]},
            }
        },
    }

    [binding] = zp.parse_bindings(device)  # type: ignore[arg-type]

    assert binding.group_id == 12
    assert binding.target_ieee is None
    assert binding.target_endpoint is None


def test_a_target_shape_this_version_does_not_know_is_dropped_rather_than_guessed() -> None:
    device = {
        "ieee_address": AUX_IEEE,
        "friendly_name": "Aux",
        "type": "Router",
        "endpoints": {
            "2": {
                "bindings": [{"cluster": "genOnOff", "target": {"type": "something_new"}}],
                "clusters": {"input": [], "output": ["genOnOff"]},
            }
        },
    }

    assert zp.parse_bindings(device) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Requests. Modelled from the documentation, never observed: assumption A2, issue #6.
# --------------------------------------------------------------------------------------


def test_a_bind_payload_names_its_clusters_explicitly() -> None:
    """Leaving `clusters` out binds every supported cluster, which is never what a rule asked."""
    payload = zp.bind_payload(
        zp.BindRequest(
            source_name="Entrance Inside Lights Aux",
            source_endpoint=2,
            target="Entrance Inside Lights",
            target_endpoint=1,
            clusters=(zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL),
            transaction="dl-1",
        )
    )

    assert payload == {
        "from": "Entrance Inside Lights Aux",
        "from_endpoint": 2,
        "to": "Entrance Inside Lights",
        "to_endpoint": 1,
        "clusters": ["genOnOff", "genLevelCtrl"],
        "transaction": "dl-1",
    }


def test_a_bind_payload_with_no_clusters_is_refused_rather_than_sent() -> None:
    """An empty list would be sent as "bind everything" by a bridge that ignores it."""
    with pytest.raises(ValueError, match="at least one cluster"):
        zp.bind_payload(_request(clusters=()))


def test_a_group_target_omits_the_target_endpoint() -> None:
    payload = zp.bind_payload(_request(target="dl_hallway", target_endpoint=None))

    assert "to_endpoint" not in payload
    assert payload["to"] == "dl_hallway"


def test_every_payload_carries_a_transaction() -> None:
    """MQTT is fire and forget: without one, a response cannot be matched to its request."""
    built = [
        zp.bind_payload(_request(transaction="t1")),
        zp.unbind_payload(_request(transaction="t2")),
        zp.group_add_payload(friendly_name="dl_x", transaction="t3"),
        zp.group_remove_payload(friendly_name="dl_x", transaction="t4"),
        zp.group_member_payload(
            friendly_name="dl_x", device_name="b", endpoint=1, transaction="t5"
        ),
    ]

    assert [payload["transaction"] for payload in built] == ["t1", "t2", "t3", "t4", "t5"]


def test_an_unbind_leaves_reporting_alone_only_when_it_is_asked_to() -> None:
    """Unbinding removes the attribute reporting Zigbee2MQTT configured (CLAUDE.md 10)."""
    default = zp.unbind_payload(_request())
    asked = zp.unbind_payload(_request(), skip_disable_reporting=True)

    assert "skip_disable_reporting" not in default, "the bridge's own default is to disable it"
    assert asked["skip_disable_reporting"] is True


def _group_request(name: str, which: str) -> dict[str, object]:
    """Build one of the three group requests, so all three can be checked the same way."""
    if which == "add":
        return zp.group_add_payload(friendly_name=name, transaction="t")
    if which == "remove":
        return zp.group_remove_payload(friendly_name=name, transaction="t")
    return zp.group_member_payload(friendly_name=name, device_name="b", endpoint=1, transaction="t")


@pytest.mark.parametrize("which", ["add", "remove", "member"])
def test_no_group_request_can_be_built_for_a_group_we_did_not_create(which: str) -> None:
    """A user's own group is not ours to modify, and the guard is in the payload builder.

    In the pure module rather than only in the adapter, so that every request that could
    reach the bridge passes through it and nothing above can route around it.
    """
    with pytest.raises(zp.ForeignGroupError, match="dl_"):
        _group_request("kitchen", which)

    assert _group_request("dl_kitchen", which)["transaction"] == "t"


def test_the_managed_prefix_is_what_makes_a_group_ours() -> None:
    assert zp.is_managed_group_name("dl_bedroom")
    assert not zp.is_managed_group_name("bedroom")
    assert not zp.is_managed_group_name("my_dl_group")
    assert zp.managed_group_name("bedroom") == "dl_bedroom"


def test_clusters_for_names_each_cluster_once_however_many_features_asked_for_it() -> None:
    """On/off plus both level features is two binds, not three."""
    assert zp.clusters_for([Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD]) == (
        zp.GEN_LEVEL_CTRL,
        zp.GEN_ON_OFF,
    )
    assert zp.clusters_for([Feature.STATUS_REPORT]) == ()


# --------------------------------------------------------------------------------------
# Responses. This is the one most likely to ship a bug that looks like it works.
# --------------------------------------------------------------------------------------


def test_ok_with_an_empty_failed_list_is_success() -> None:
    response = zp.parse_response(
        {
            "data": {"from": "a", "to": "b", "clusters": ["genOnOff"], "failed": []},
            "status": "ok",
            "transaction": "t1",
        }
    )

    assert response.succeeded
    assert not response.partly_failed
    assert response.written == ("genOnOff",)
    assert response.transaction == "t1"


def test_ok_with_a_non_empty_failed_list_is_not_success() -> None:
    """The single most likely way to ship a bug that looks like it works.

    Zigbee2MQTT reports `status: "error"` only when every cluster failed. A bind where
    `genOnOff` landed and `genLevelCtrl` did not comes back as `ok`, so a check on `status`
    alone reports the link as applied: the user gets a paddle that turns the light on and
    cannot dim it, and the panel says everything is fine.
    """
    response = zp.parse_response(
        {
            "data": {
                "from": "a",
                "to": "b",
                "clusters": ["genOnOff", "genLevelCtrl"],
                "failed": ["genLevelCtrl"],
            },
            "status": "ok",
            "transaction": "t1",
        }
    )

    assert response.status == "ok"
    assert not response.succeeded, "a partial failure must never read as success"
    assert response.partly_failed
    assert response.failed == ("genLevelCtrl",)
    assert response.written == ("genOnOff",)


def test_error_carries_the_error_text() -> None:
    response = zp.parse_response(
        {
            "data": {"from": "a", "to": "b", "clusters": ["genOnOff"], "failed": ["genOnOff"]},
            "status": "error",
            "error": "Failed to bind (Status 'NO_ENTRY')",
            "transaction": "t9",
        }
    )

    assert not response.succeeded
    assert response.error == "Failed to bind (Status 'NO_ENTRY')"
    assert response.written == ()


def test_a_response_that_makes_no_sense_is_read_as_a_failure_rather_than_raising() -> None:
    """It arrives off a broker. A parser that throws takes the subscription with it."""
    response = zp.parse_response({"status": 7, "data": "not an object"})

    assert response.status == ""
    assert not response.succeeded
    assert response.failed == ()
    assert response.transaction is None


def test_a_transaction_reported_inside_data_is_still_found() -> None:
    """Zigbee2MQTT echoes the request body into `data`, so it can turn up in either place."""
    response = zp.parse_response(
        {"status": "ok", "data": {"clusters": [], "failed": [], "transaction": "t4"}}
    )

    assert response.transaction == "t4"


def test_a_failed_list_with_something_that_is_not_a_cluster_name_is_ignored() -> None:
    response = zp.parse_response(
        {"status": "ok", "data": {"clusters": ["genOnOff"], "failed": [17, None]}}
    )

    assert response.succeeded


def _request(**overrides: object) -> zp.BindRequest:
    """Return a bind request, with only the part a test is about spelled out."""
    fields: dict[str, object] = {
        "source_name": "Entrance Inside Lights Aux",
        "source_endpoint": 2,
        "target": "Entrance Inside Lights",
        "target_endpoint": 1,
        "clusters": (zp.GEN_ON_OFF,),
        "transaction": "t",
    }
    return zp.BindRequest(**{**fields, **overrides})  # type: ignore[arg-type]


def _emitter(ieee: str, emitter_id: str) -> Emitter:
    """Return one derived emitter of a captured device by id."""
    emitters = zp.derive_emitters(zigbee_device(ieee))
    return next(emitter for emitter in emitters if emitter.emitter_id == emitter_id)
