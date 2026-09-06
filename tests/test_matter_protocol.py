"""The pure Matter interpretation, against the real fabric wherever the real fabric answers.

`tests/fixtures/m1_matter.json` is a byte-for-byte capture of Jayant's 19 Matter nodes, so
everything about the read path here is asserted against hardware rather than against a
model. The write path is the opposite and says so: no binding and no Access Control entry
has ever been written on this fabric, so those tests pin the shape this integration produces
and prove nothing about what a device would accept (assumption A9).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.device_links.backends import matter_protocol as mp
from custom_components.device_links.models import Feature
from custom_components.device_links.profile_db import (
    MatterProfileEmitter,
    MatterProfileEntry,
    MatterProfileFingerprint,
)

FIXTURE = Path(__file__).parent / "fixtures" / "m1_matter.json"

INOVELLI = 31
EVE_ENERGY = 8
# The Eve Energy that holds two entries rather than four, which is the one with room for a
# grant. Node 8 is the tight one the Stage 0 report names, and both are used below.
SPARE_EVE = 19
AQARA_SWITCH = 30
BILRESA = 50
CONTROLLER = 112233


def captured() -> dict[int, Any]:
    """Return the M1 capture's nodes, by node id."""
    devices = json.loads(FIXTURE.read_text())["data"]["devices"]
    return {device["node_id"]: device for device in devices}


def node(node_id: int) -> Any:
    """Return one captured node."""
    return captured()[node_id]


def acl_of(node_id: int) -> tuple[mp.AclEntry, ...]:
    """Return one captured node's Access Control list as this module reads it."""
    return mp.parse_acl(node(node_id)["acl"])


def capacity_of(node_id: int) -> mp.AclCapacity:
    """Return one captured node's Access Control capacity."""
    reported: mp.AclCapacity = node(node_id)["acl_capacity"]
    return reported


LIGHT = mp.AclTarget(cluster=mp.ON_OFF_CLUSTER, endpoint=1)


# --------------------------------------------------------------------------------------
# Capabilities, read off the fabric
# --------------------------------------------------------------------------------------


def test_only_the_two_inovelli_switches_are_binding_sources() -> None:
    """The M1 headline. PRD Section 3.1 named two devices that turn out not to be.

    This is the assertion that would have to change if a firmware update ever made the
    Aqara switch or the IKEA button bindable, and it is written so that it fails loudly in
    that direction rather than quietly widening.
    """
    sources = {
        node_id: mp.derive_emitters(captured_node)
        for node_id, captured_node in captured().items()
        if mp.derive_emitters(captured_node)
    }

    assert sorted(sources) == [31, 32]
    for emitters in sources.values():
        assert [emitter.endpoint for emitter in emitters] == [2]


def test_the_ota_provider_is_never_an_emitter_wherever_it_is_advertised() -> None:
    """Cluster 41 on endpoint 0 is on 18 of the 19 nodes, and it is firmware update.

    Eighteen rather than the nineteen the Stage 0 summary rounds to: the Nest thermostat
    reports no client clusters at all. It changes nothing about the conclusion and is worth
    having exactly right, because a test written to the summary would fail on the capture.

    Both halves are checked, because the exclusion is an allowlist rather than a rule about
    endpoint 0: a node that advertised the OTA provider on a control endpoint would still
    offer nobody a firmware updater as a light switch.
    """
    every = captured().values()
    assert sum(mp.OTA_PROVIDER_CLUSTER in mp.client_clusters(one, 0) for one in every) == 18

    moved = json.loads(json.dumps(node(AQARA_SWITCH)))
    moved["endpoints"]["1"]["client_list"] = [mp.OTA_PROVIDER_CLUSTER]
    moved["endpoints"]["1"]["server_list"] = [mp.BINDING_CLUSTER]

    assert mp.derive_emitters(moved) == []
    assert not mp.emits(moved, 1, mp.OTA_PROVIDER_CLUSTER)


def test_the_root_endpoint_is_never_a_control_or_a_target() -> None:
    """Endpoint 0 administers the node. A link to it would be a link to its Access Control."""
    inovelli = node(INOVELLI)

    assert not mp.emits(inovelli, 0, mp.OTA_PROVIDER_CLUSTER)
    assert not mp.accepts(inovelli, 0, mp.ACCESS_CONTROL_CLUSTER)
    assert 0 not in [emitter.endpoint for emitter in mp.derive_emitters(inovelli)]


def test_an_endpoint_with_no_binding_cluster_is_not_offered() -> None:
    """A control with nowhere to write the link is not a control the user can pick."""
    warnings: list[str] = []
    unbindable = json.loads(json.dumps(node(INOVELLI)))
    unbindable["endpoints"]["2"]["server_list"] = [3, 29, 64, 65]

    assert mp.derive_emitters(unbindable, warnings=warnings) == []
    assert any("no Binding cluster" in warning for warning in warnings)


def test_an_endpoint_that_drives_nothing_usable_is_reported_rather_than_dropped() -> None:
    """Identify is a client cluster and is not a control, so it earns a warning and no more."""
    warnings: list[str] = []
    identify_only = json.loads(json.dumps(node(INOVELLI)))
    identify_only["endpoints"]["2"]["client_list"] = [mp.IDENTIFY_CLUSTER]

    assert mp.derive_emitters(identify_only, warnings=warnings) == []
    assert any("none of which Device Links can bind" in warning for warning in warnings)


def test_a_caller_that_wants_no_warnings_gets_none_and_the_same_answer() -> None:
    """Every drop is reported only when somebody asked, and reporting is never the decision."""
    unbindable = json.loads(json.dumps(node(INOVELLI)))
    unbindable["endpoints"]["2"]["server_list"] = [3, 29, 64, 65]
    wrong = MatterProfileEntry(
        fingerprints=(MatterProfileFingerprint(vendor="Inovelli", product="VTM31-SN"),),
        emitters=(
            MatterProfileEmitter(
                emitter_id="ghost",
                label="Ghost",
                kind="button",
                endpoint=9,
                actions={Feature.ON_OFF: mp.ON_OFF_CLUSTER},
            ),
        ),
        wake_instruction=None,
        notes="",
    )

    assert mp.derive_emitters(unbindable) == []
    assert mp.resolve_emitters(node(INOVELLI), wrong) == mp.derive_emitters(node(INOVELLI))


def test_an_endpoint_that_drives_nothing_at_all_is_silent() -> None:
    """Most endpoints of an Inovelli drive nothing. A warning each would be noise."""
    warnings: list[str] = []
    mp.derive_emitters(node(INOVELLI), warnings=warnings)

    assert warnings == []


def test_the_paddle_carries_both_level_features_through_one_cluster() -> None:
    """LevelControl is one binding that gives the user two things, as `genLevelCtrl` is."""
    (paddle,) = mp.derive_emitters(node(INOVELLI))

    assert paddle.actions[Feature.ON_OFF] == str(mp.ON_OFF_CLUSTER)
    assert paddle.actions[Feature.LEVEL_SET] == str(mp.LEVEL_CONTROL_CLUSTER)
    assert paddle.actions[Feature.LEVEL_HOLD] == str(mp.LEVEL_CONTROL_CLUSTER)
    assert paddle.group_ids == ("6", "8")
    assert paddle.capacity == mp.BINDING_TABLE_CAPACITY
    assert paddle.supports_endpoint_targets
    assert not paddle.is_lifeline
    assert paddle.grouping == mp.GROUPING_ENDPOINT


def test_what_a_switch_can_be_made_to_do_is_read_off_its_server_clusters() -> None:
    inovelli = node(INOVELLI)

    assert mp.receivable_features(inovelli) == frozenset(
        {Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD, Feature.COLOR}
    )
    assert mp.receiving_endpoint(inovelli) == 1
    assert mp.accepts(inovelli, 1, mp.ON_OFF_CLUSTER)
    assert not mp.accepts(inovelli, 1, mp.SCENES_MANAGEMENT_CLUSTER)


def test_a_node_that_can_receive_nothing_offers_nowhere_to_land() -> None:
    """The two answers have to agree, or a link would be planned onto a device with no home."""
    button = node(BILRESA)

    assert mp.receivable_features(button) == frozenset()
    assert mp.receiving_endpoint(button) is None


def test_a_handle_keys_on_the_node_id_and_not_on_the_fabric() -> None:
    """Stage 0 item P2: the compressed fabric id changes on re-commissioning."""
    handle = mp.handle_of(node(INOVELLI))

    assert handle.protocol_id == "31"
    assert handle.identity == "matter:31"
    assert handle.fingerprint.model_key == ("Inovelli", "VTM31-SN")
    assert handle.name_at_authoring == "Kitchen Accent Lights"
    assert mp.node_id_of(handle) == 31


def test_a_node_with_no_name_still_gets_one() -> None:
    """The Nest thermostat reports an empty name, and a device picker needs something."""
    handle = mp.handle_of(node(5))

    assert handle.name_at_authoring == "Matter node 5"


def test_a_handle_that_does_not_name_a_node_is_refused_rather_than_guessed() -> None:
    handle = mp.handle_of(node(INOVELLI))
    from dataclasses import replace  # noqa: PLC0415

    assert mp.node_id_of(replace(handle, protocol_id="group:2")) is None


@pytest.mark.parametrize(
    ("cluster", "features"),
    [
        (mp.ON_OFF_CLUSTER, {Feature.ON_OFF}),
        (mp.LEVEL_CONTROL_CLUSTER, {Feature.LEVEL_SET, Feature.LEVEL_HOLD}),
        (mp.SCENES_MANAGEMENT_CLUSTER, {Feature.SCENE}),
        (mp.COLOR_CONTROL_CLUSTER, {Feature.COLOR}),
        (mp.OTA_PROVIDER_CLUSTER, set()),
    ],
)
def test_features_of_cluster_is_an_allowlist(cluster: int, features: set[Feature]) -> None:
    assert mp.features_of_cluster(cluster) == frozenset(features)


def test_an_existing_binding_on_a_cluster_we_cannot_drive_still_describes_itself() -> None:
    """A binding table half reported is a binding table nobody can plan against."""
    assert mp.features_of_binding(mp.OTA_PROVIDER_CLUSTER) == frozenset({Feature.STATUS_REPORT})
    assert mp.features_of_binding(mp.ON_OFF_CLUSTER) == frozenset({Feature.ON_OFF})


def test_cluster_for_answers_only_for_features_a_binding_can_carry() -> None:
    assert mp.cluster_for(Feature.ON_OFF) == mp.ON_OFF_CLUSTER
    assert mp.cluster_for(Feature.STATUS_REPORT) is None


def test_an_unreadable_cluster_list_reads_as_empty_rather_than_taking_the_node_down() -> None:
    """The probe records a failed read as an error record in the slot the list belongs in."""
    broken = json.loads(json.dumps(node(INOVELLI)))
    broken["endpoints"]["2"]["client_list"] = {"error": "Timeout: node did not respond"}

    assert mp.client_clusters(broken, 2) == ()
    assert mp.derive_emitters(broken) == []
    assert mp.server_clusters(broken, 3) == (3, 29, 59, 64, 65)


def test_a_boolean_is_not_a_cluster_id() -> None:
    """JSON true parses to a Python bool, which is an int, and would read as cluster 1."""
    odd = json.loads(json.dumps(node(INOVELLI)))
    odd["endpoints"]["2"]["client_list"] = [True, 6]

    assert mp.client_clusters(odd, 2) == (6,)


def test_an_endpoint_the_node_does_not_report_answers_with_nothing() -> None:
    inovelli = node(INOVELLI)

    assert mp.client_clusters(inovelli, 99) == ()
    assert mp.server_clusters(inovelli, 99) == ()
    assert not mp.has_binding_cluster(inovelli, 99)


def test_endpoint_ids_ignore_a_key_that_is_not_a_number() -> None:
    odd = json.loads(json.dumps(node(EVE_ENERGY)))
    odd["endpoints"]["parent"] = {"client_list": [], "server_list": []}

    assert mp.endpoint_ids(odd) == (0, 1, 2)


def test_attribute_paths_are_built_in_one_place() -> None:
    """The read path and the write path must never disagree about a device's address."""
    assert mp.attribute_path(2, 29, 2) == "2/29/2"
    assert mp.client_list_path(2) == "2/29/2"
    assert mp.server_list_path(0) == "0/29/1"
    assert mp.binding_path(2) == "2/30/0"
    assert mp.ACL_PATH == "0/31/0"
    assert mp.ACL_ENTRIES_PER_FABRIC_PATH == "0/31/4"
    assert mp.ACL_SUBJECTS_PER_ENTRY_PATH == "0/31/2"
    assert mp.ACL_TARGETS_PER_ENTRY_PATH == "0/31/3"


# --------------------------------------------------------------------------------------
# Curated entries
# --------------------------------------------------------------------------------------


def _curated(**overrides: Any) -> MatterProfileEntry:
    """Return a curated entry for the Inovelli paddle, with fields a test wants changed."""
    emitter = MatterProfileEmitter(
        emitter_id="paddle",
        label="Paddle",
        kind="paddle",
        endpoint=2,
        actions={
            Feature.ON_OFF: mp.ON_OFF_CLUSTER,
            Feature.LEVEL_SET: mp.LEVEL_CONTROL_CLUSTER,
            Feature.LEVEL_HOLD: mp.LEVEL_CONTROL_CLUSTER,
        },
        **overrides,
    )
    return MatterProfileEntry(
        fingerprints=(MatterProfileFingerprint(vendor="Inovelli", product="VTM31-SN"),),
        emitters=(emitter,),
        wake_instruction=None,
        notes="",
    )


def test_a_curated_entry_relabels_a_control_without_renaming_it() -> None:
    """A rule written against `ep2` must not break when a profile entry is contributed."""
    (paddle,) = mp.resolve_emitters(node(INOVELLI), _curated())

    assert paddle.emitter_id == "ep2"
    assert paddle.label == "Paddle"
    assert paddle.grouping == mp.GROUPING_PROFILE_DB
    assert paddle.actions[Feature.ON_OFF] == "6"


def test_a_curated_emitter_that_contradicts_the_node_is_dropped_with_a_reason() -> None:
    warnings: list[str] = []
    entry = _curated()
    wrong = MatterProfileEmitter(
        emitter_id="ghost",
        label="Ghost",
        kind="button",
        endpoint=9,
        actions={Feature.ON_OFF: mp.ON_OFF_CLUSTER},
    )

    resolved = mp.resolve_emitters(
        node(INOVELLI),
        MatterProfileEntry(
            fingerprints=entry.fingerprints,
            emitters=(*entry.emitters, wrong),
            wake_instruction=None,
            notes="",
        ),
        warnings=warnings,
    )

    assert [emitter.emitter_id for emitter in resolved] == ["ep2"]
    assert any("which this node does not report" in warning for warning in warnings)


@pytest.mark.parametrize(
    ("endpoint", "actions", "expected"),
    [
        (1, {Feature.ON_OFF: mp.ON_OFF_CLUSTER}, "which that endpoint does not drive"),
        (2, {Feature.SCENE: mp.ON_OFF_CLUSTER}, "which cannot carry it"),
    ],
)
def test_every_kind_of_contradiction_is_named(
    endpoint: int, actions: dict[Feature, int], expected: str
) -> None:
    warnings: list[str] = []
    entry = MatterProfileEntry(
        fingerprints=(MatterProfileFingerprint(vendor="Inovelli", product="VTM31-SN"),),
        emitters=(
            MatterProfileEmitter(
                emitter_id="x", label="X", kind="button", endpoint=endpoint, actions=actions
            ),
        ),
        wake_instruction=None,
        notes="",
    )

    resolved = mp.resolve_emitters(node(INOVELLI), entry, warnings=warnings)

    assert [emitter.emitter_id for emitter in resolved] == ["ep2"]
    assert any(expected in warning for warning in warnings)


def test_a_curated_emitter_on_an_endpoint_with_no_binding_cluster_is_dropped() -> None:
    warnings: list[str] = []
    unbindable = json.loads(json.dumps(node(INOVELLI)))
    unbindable["endpoints"]["2"]["server_list"] = [3, 29, 64, 65]

    resolved = mp.resolve_emitters(unbindable, _curated(), warnings=warnings)

    assert resolved == []
    assert any("serves no Binding cluster" in warning for warning in warnings)


def test_a_curated_emitter_that_names_a_new_control_keeps_its_own_id() -> None:
    """An entry describing a control the generic derivation missed is not renamed."""
    entry = MatterProfileEntry(
        fingerprints=(MatterProfileFingerprint(vendor="Inovelli", product="VTM31-SN"),),
        emitters=(
            MatterProfileEmitter(
                emitter_id="paddle",
                label="Paddle",
                kind="paddle",
                endpoint=2,
                actions={Feature.ON_OFF: mp.ON_OFF_CLUSTER},
            ),
        ),
        wake_instruction=None,
        notes="",
    )

    (paddle,) = mp.resolve_emitters(node(INOVELLI), entry)

    assert paddle.emitter_id == "paddle"
    assert paddle.group_ids == ("6",)


def test_no_entry_at_all_leaves_the_generic_derivation_standing() -> None:
    assert mp.resolve_emitters(node(INOVELLI), None) == mp.derive_emitters(node(INOVELLI))


# --------------------------------------------------------------------------------------
# Access Control, read
# --------------------------------------------------------------------------------------


def test_the_controllers_own_entry_is_read_as_administer() -> None:
    """The entry CLAUDE.md Section 3 rule 4 puts beside a lifeline."""
    ours = [entry for entry in acl_of(INOVELLI) if not entry.is_redacted]

    assert len(ours) == 1
    assert ours[0].is_administer
    assert ours[0].privilege == mp.PRIVILEGE_ADMINISTER
    assert ours[0].auth_mode == mp.AUTH_MODE_CASE
    assert ours[0].subjects == (CONTROLLER,)
    assert ours[0].targets == ()


def test_another_fabrics_entries_are_read_as_redacted_rather_than_as_empty() -> None:
    """Three of the four entries on this switch belong to fabrics that did not let us read."""
    entries = acl_of(INOVELLI)

    assert [entry.is_redacted for entry in entries] == [True, False, True, True]
    assert [entry.fabric_index for entry in entries] == [1, 2, 3, 3]


def test_the_fabric_this_controller_reads_under_is_derived_from_what_it_can_read() -> None:
    """It is a different index on different nodes, so it cannot be a constant."""
    assert mp.our_fabric_index(acl_of(INOVELLI)) == 2
    assert mp.our_fabric_index(acl_of(EVE_ENERGY)) == 3


def test_a_list_with_nothing_readable_in_it_names_no_fabric() -> None:
    """Which makes every write refuse, because there is nothing to write under."""
    assert mp.our_fabric_index(()) is None
    assert mp.parse_acl({"error": "Timeout"}) == ()


def test_two_readable_fabrics_are_refused_rather_than_resolved() -> None:
    """A read this function's assumption does not hold for must not be guessed at."""
    entries = (
        mp.grant_entry(1, LIGHT, fabric_index=2),
        mp.grant_entry(1, LIGHT, fabric_index=3),
    )

    assert mp.our_fabric_index(entries) is None


def test_the_fabrics_own_and_foreign_entries_are_told_apart() -> None:
    entries = acl_of(EVE_ENERGY)

    assert len(mp.entries_of_fabric(entries, 3)) == 1
    assert len(mp.foreign_entries(entries, 3)) == 3


def test_an_administer_entry_covers_a_target_it_does_not_name() -> None:
    """A whole-node grant really does grant this, so a second entry would be redundant."""
    (administer,) = mp.entries_of_fabric(acl_of(INOVELLI), 2)

    assert administer.grants(CONTROLLER, LIGHT)
    assert not administer.grants(999, LIGHT)


def test_a_view_only_entry_does_not_grant_operate() -> None:
    entry = mp.AclEntry(
        privilege=mp.PRIVILEGE_VIEW,
        auth_mode=mp.AUTH_MODE_CASE,
        subjects=(7,),
        targets=(LIGHT,),
        fabric_index=2,
    )

    assert not entry.grants(7, LIGHT)


def test_a_redacted_entry_grants_nothing_we_can_see() -> None:
    (foreign, *_rest) = acl_of(INOVELLI)

    assert not foreign.grants(CONTROLLER, LIGHT)
    assert not foreign.is_managed_grant(LIGHT)


def test_a_targeted_entry_is_read_back_as_the_target_it_names() -> None:
    """Nothing on the fabric has one yet, so this reads back what a write of ours produces."""
    written = mp.acl_payload((mp.grant_entry(31, LIGHT, fabric_index=2),))
    with_index = [{**written[0], str(mp.ACL_TAG_FABRIC_INDEX): 2}]

    (parsed,) = mp.parse_acl(json.loads(json.dumps(with_index)))

    assert parsed.targets == (LIGHT,)
    assert parsed.subjects == (31,)
    assert parsed.is_managed_grant(LIGHT)


def test_a_target_that_is_not_a_mapping_is_not_a_target() -> None:
    entries = mp.parse_acl([{"1": 3, "2": 2, "3": [31], "4": ["nonsense"]}])

    assert entries[0].targets == ()


def test_a_target_naming_a_cluster_and_an_endpoint_is_the_narrowest_grant() -> None:
    assert LIGHT.is_targeted
    assert not mp.AclTarget().is_targeted


# --------------------------------------------------------------------------------------
# Access Control, written. Modelled, never observed: assumption A9.
# --------------------------------------------------------------------------------------


def test_a_grant_is_appended_when_the_list_has_room() -> None:
    outcome = mp.grant_for(
        acl_of(SPARE_EVE), subject=31, target=LIGHT, capacity=capacity_of(SPARE_EVE)
    )

    assert outcome.refusal is None
    assert outcome.changed
    assert outcome.entries is not None
    assert len(outcome.entries) == 2
    granted = outcome.entries[-1]
    assert granted.privilege == mp.PRIVILEGE_OPERATE
    assert granted.auth_mode == mp.AUTH_MODE_CASE
    assert granted.subjects == (31,)
    assert granted.targets == (LIGHT,)
    assert granted.fabric_index == 2


def test_the_administer_entry_is_carried_through_a_grant_untouched() -> None:
    """Everything in the written list that was there before, plus one thing."""
    before = acl_of(SPARE_EVE)
    outcome = mp.grant_for(before, subject=31, target=LIGHT, capacity=capacity_of(SPARE_EVE))

    assert outcome.entries is not None
    assert mp.entries_of_fabric(before, 2)[0] in outcome.entries


def test_an_inovelli_switch_is_already_a_full_target_on_this_fabric() -> None:
    """Read off the capture rather than constructed: E28 is live on real hardware here.

    Both Inovelli switches report 4 entries per fabric and already hold 4, so a rule
    pointing at one as a **target** is refused today whatever else is true. As a source they
    are fine, because a source needs no grant of its own.
    """
    outcome = mp.grant_for(
        acl_of(INOVELLI), subject=32, target=LIGHT, capacity=capacity_of(INOVELLI)
    )

    assert outcome.refusal is mp.AclRefusal.ENTRIES_FULL
    assert (outcome.used, outcome.capacity) == (4, 4)


def test_a_grant_that_is_already_there_writes_nothing() -> None:
    """The second apply of a rule must not fill a list that has two slots free."""
    existing = (*acl_of(SPARE_EVE), mp.grant_entry(31, LIGHT, fabric_index=2))

    outcome = mp.grant_for(existing, subject=31, target=LIGHT, capacity=capacity_of(SPARE_EVE))

    assert not outcome.changed
    assert outcome.refusal is None


def test_a_second_control_merges_into_the_entry_the_first_one_made() -> None:
    """The load-bearing case. Eve Energy has 2 entries free and 10 subjects per entry."""
    existing = (*acl_of(EVE_ENERGY), mp.grant_entry(31, LIGHT, fabric_index=3))

    outcome = mp.grant_for(existing, subject=32, target=LIGHT, capacity=capacity_of(EVE_ENERGY))

    assert outcome.changed
    assert outcome.entries is not None
    assert len(outcome.entries) == 2
    assert outcome.entries[-1].subjects == (31, 32)


def test_a_merge_never_grants_more_than_a_separate_entry_would_have() -> None:
    """Why merging into an entry nothing labels as ours is safe: the target is identical."""
    existing = (*acl_of(EVE_ENERGY), mp.grant_entry(31, LIGHT, fabric_index=3))

    outcome = mp.grant_for(existing, subject=32, target=LIGHT, capacity=capacity_of(EVE_ENERGY))

    assert outcome.entries is not None
    assert all(entry.targets in ((), (LIGHT,)) for entry in outcome.entries)
    assert not any(entry.grants(999, LIGHT) for entry in outcome.entries)


def test_an_entry_for_another_target_is_not_merged_into() -> None:
    other = mp.AclTarget(cluster=mp.LEVEL_CONTROL_CLUSTER, endpoint=1)
    existing = (*acl_of(EVE_ENERGY), mp.grant_entry(31, other, fabric_index=3))

    outcome = mp.grant_for(existing, subject=32, target=LIGHT, capacity=capacity_of(EVE_ENERGY))

    assert outcome.entries is not None
    assert len(outcome.entries) == 3


def test_a_full_list_refuses_and_carries_the_numbers_the_message_needs() -> None:
    """E27 wants the user told how full it is, so the refusal carries both numbers."""
    capacity = mp.AclCapacity(entries_per_fabric=4, subjects_per_entry=4, targets_per_entry=3)

    outcome = mp.grant_for(acl_of(EVE_ENERGY), subject=31, target=LIGHT, capacity=capacity)

    assert outcome.refusal is mp.AclRefusal.ENTRIES_FULL
    assert outcome.entries is None
    assert (outcome.used, outcome.capacity) == (4, 4)


def test_a_full_entry_on_a_full_list_says_so_rather_than_blaming_the_list() -> None:
    """Told apart because the two have different answers: free a slot, or use fewer controls."""
    capacity = mp.AclCapacity(entries_per_fabric=2, subjects_per_entry=1, targets_per_entry=3)
    existing = (
        mp.AclEntry(mp.PRIVILEGE_ADMINISTER, mp.AUTH_MODE_CASE, (CONTROLLER,), (), 2),
        mp.grant_entry(31, LIGHT, fabric_index=2),
    )

    outcome = mp.grant_for(existing, subject=32, target=LIGHT, capacity=capacity)

    assert outcome.refusal is mp.AclRefusal.SUBJECTS_FULL


def test_a_full_entry_with_room_to_append_takes_the_second_entry() -> None:
    capacity = mp.AclCapacity(entries_per_fabric=6, subjects_per_entry=1, targets_per_entry=3)
    existing = (
        mp.AclEntry(mp.PRIVILEGE_ADMINISTER, mp.AUTH_MODE_CASE, (CONTROLLER,), (), 2),
        mp.grant_entry(31, LIGHT, fabric_index=2),
    )

    outcome = mp.grant_for(existing, subject=32, target=LIGHT, capacity=capacity)

    assert outcome.refusal is None
    assert outcome.entries is not None
    assert len(outcome.entries) == 3


def test_a_device_that_cannot_express_a_targeted_grant_is_refused_not_widened() -> None:
    """PRD Section 10: Operate on the specific cluster and endpoint, or nothing."""
    capacity = mp.AclCapacity(entries_per_fabric=6, subjects_per_entry=4, targets_per_entry=0)

    outcome = mp.grant_for(acl_of(EVE_ENERGY), subject=31, target=LIGHT, capacity=capacity)

    assert outcome.refusal is mp.AclRefusal.NO_TARGETED_ENTRIES


def test_a_node_whose_fabric_cannot_be_identified_is_never_written_to() -> None:
    outcome = mp.grant_for((), subject=31, target=LIGHT, capacity=capacity_of(EVE_ENERGY))

    assert outcome.refusal is mp.AclRefusal.FABRIC_UNKNOWN
    assert outcome.entries is None


def test_revoking_takes_one_subject_off_and_leaves_the_others() -> None:
    existing = (
        *acl_of(EVE_ENERGY),
        mp.AclEntry(mp.PRIVILEGE_OPERATE, mp.AUTH_MODE_CASE, (31, 32), (LIGHT,), 3),
    )

    outcome = mp.revoke_for(existing, subject=31, target=LIGHT)

    assert outcome.changed
    assert outcome.entries is not None
    assert outcome.entries[-1].subjects == (32,)


def test_revoking_the_last_subject_removes_the_entry_rather_than_emptying_it() -> None:
    """An Access Control entry with no subjects grants every node on the fabric."""
    existing = (*acl_of(EVE_ENERGY), mp.grant_entry(31, LIGHT, fabric_index=3))

    outcome = mp.revoke_for(existing, subject=31, target=LIGHT)

    assert outcome.entries is not None
    assert len(outcome.entries) == 1
    assert outcome.entries[0].is_administer


def test_revoking_leaves_a_grant_this_integration_did_not_write_alone() -> None:
    """A whole-node Operate entry covers the target and is somebody else's arrangement."""
    foreign = mp.AclEntry(mp.PRIVILEGE_OPERATE, mp.AUTH_MODE_CASE, (31,), (), 3)
    existing = (*acl_of(EVE_ENERGY), foreign)

    outcome = mp.revoke_for(existing, subject=31, target=LIGHT)

    assert not outcome.changed
    assert outcome.entries is not None
    assert foreign in outcome.entries


def test_revoking_from_a_node_whose_fabric_is_unknown_is_refused() -> None:
    outcome = mp.revoke_for((), subject=31, target=LIGHT)

    assert outcome.refusal is mp.AclRefusal.FABRIC_UNKNOWN


def test_nothing_can_build_a_list_that_drops_an_administer_entry() -> None:
    """The guard every path goes through, so no caller can route around it."""
    administer = mp.AclEntry(mp.PRIVILEGE_ADMINISTER, mp.AUTH_MODE_CASE, (CONTROLLER,), (), 2)

    with pytest.raises(mp.AclError, match="Administer"):
        mp._checked((administer,), ())


def test_nothing_can_build_a_list_that_alters_an_administer_entry() -> None:
    administer = mp.AclEntry(mp.PRIVILEGE_ADMINISTER, mp.AUTH_MODE_CASE, (CONTROLLER,), (), 2)
    widened = mp.AclEntry(mp.PRIVILEGE_ADMINISTER, mp.AUTH_MODE_CASE, (CONTROLLER, 9), (), 2)

    with pytest.raises(mp.AclError, match="Administer"):
        mp._checked((administer,), (widened,))


def test_an_acl_payload_is_keyed_by_tlv_tag() -> None:
    """PRD Section 8.6: the current server serializes a struct by tag, not by field name."""
    payload = mp.acl_payload((mp.grant_entry(31, LIGHT, fabric_index=2),))

    assert payload == [
        {
            "1": mp.PRIVILEGE_OPERATE,
            "2": mp.AUTH_MODE_CASE,
            "3": [31],
            "4": [{"0": 6, "1": 1, "2": None}],
        }
    ]


def test_a_whole_node_grant_serializes_its_targets_as_null() -> None:
    """Which is what the fabric reported for the controller's own entry."""
    entry = mp.AclEntry(mp.PRIVILEGE_ADMINISTER, mp.AUTH_MODE_CASE, (CONTROLLER,), (), 2)

    assert mp.acl_payload((entry,))[0]["4"] is None


def test_the_fabric_index_is_never_written() -> None:
    """The node assigns it from the session the write arrived on."""
    payload = mp.acl_payload((mp.grant_entry(31, LIGHT, fabric_index=2),))

    assert str(mp.ACL_TAG_FABRIC_INDEX) not in payload[0]


def test_another_fabrics_entry_can_never_be_written_back() -> None:
    (foreign, *_rest) = acl_of(INOVELLI)

    with pytest.raises(mp.AclError, match="another fabric"):
        mp.acl_payload((foreign,))


# --------------------------------------------------------------------------------------
# Bindings, and the receipt that makes E27 structural
# --------------------------------------------------------------------------------------

WANTED = mp.BindingEntry(node=8, endpoint=1, cluster=mp.ON_OFF_CLUSTER)


def receipt(**overrides: Any) -> mp.GrantReceipt:
    """Return a receipt for letting node 31 operate the light on node 8."""
    fields: dict[str, Any] = {
        "node_id": 8,
        "subject": 31,
        "target": LIGHT,
        "confirmed": (mp.grant_entry(31, LIGHT, fabric_index=3),),
    }
    fields.update(overrides)
    return mp.GrantReceipt(**fields)


def test_both_inovelli_binding_lists_are_empty_on_the_fabric() -> None:
    """The read half, against hardware: nothing has ever been bound here."""
    assert mp.parse_bindings(node(INOVELLI), 2) == ()
    assert mp.parse_bindings(node(INOVELLI), 1) == ()


def test_a_binding_list_is_read_by_tlv_tag_whichever_way_the_keys_are_spelled() -> None:
    """Integers from the client, strings from anything that has been through JSON."""
    from_client = json.loads(json.dumps(node(INOVELLI)))
    from_client["bindings"]["2"] = [{1: 8, 3: 1, 4: 6}]
    from_json = json.loads(json.dumps(node(INOVELLI)))
    from_json["bindings"]["2"] = [{"1": 8, "3": 1, "4": 6}]

    assert mp.parse_bindings(from_client, 2) == (WANTED,)
    assert mp.parse_bindings(from_json, 2) == (WANTED,)


def test_an_entry_this_version_does_not_understand_still_takes_up_a_slot() -> None:
    """A list of three reported as two is a list whose capacity is counted short."""
    odd = json.loads(json.dumps(node(INOVELLI)))
    odd["bindings"]["2"] = [{"2": 4}, {"99": 1}]

    parsed = mp.parse_bindings(odd, 2)

    assert len(parsed) == 2
    assert parsed[0].group == 4
    assert not parsed[0].is_unicast
    assert parsed[1] == mp.BindingEntry()


def test_an_unreadable_binding_list_reads_as_empty() -> None:
    broken = json.loads(json.dumps(node(INOVELLI)))
    broken["bindings"]["2"] = {"error": "Timeout"}

    assert mp.parse_bindings(broken, 2) == ()
    assert mp.parse_bindings(broken, 7) == ()


def test_a_binding_is_appended_to_what_is_already_there() -> None:
    """FR-B7: never drop an entry this integration did not write."""
    theirs = mp.BindingEntry(group=4)

    written = mp.binding_for((theirs,), wanted=WANTED, source_node_id=31, receipt=receipt())

    assert written == (theirs, WANTED)


def test_a_binding_that_is_already_there_is_not_written_again() -> None:
    assert mp.binding_for((WANTED,), wanted=WANTED, source_node_id=31, receipt=receipt()) is None


def test_no_binding_can_be_built_without_a_confirmed_grant() -> None:
    """E27 made structural: there is no other function that adds a binding entry."""
    with pytest.raises(mp.GrantNotConfirmedError, match="does not report a grant"):
        mp.GrantReceipt(node_id=8, subject=31, target=LIGHT, confirmed=acl_of(EVE_ENERGY))


def test_a_receipt_for_another_target_cannot_be_reused() -> None:
    """A perfectly good receipt, for endpoint 1, offered for a binding to endpoint 2."""
    with pytest.raises(mp.GrantNotConfirmedError, match="is not the one"):
        mp.binding_for(
            (),
            wanted=mp.BindingEntry(node=8, endpoint=2, cluster=mp.ON_OFF_CLUSTER),
            source_node_id=31,
            receipt=receipt(),
        )


def test_a_receipt_for_another_node_cannot_be_reused() -> None:
    """The grant was written on node 8 and the binding points at node 19."""
    with pytest.raises(mp.GrantNotConfirmedError, match="is not the one"):
        mp.binding_for(
            (),
            wanted=mp.BindingEntry(node=19, endpoint=1, cluster=mp.ON_OFF_CLUSTER),
            source_node_id=31,
            receipt=receipt(),
        )


def test_a_receipt_for_another_source_cannot_be_reused() -> None:
    with pytest.raises(mp.GrantNotConfirmedError, match="is not the one"):
        mp.binding_for((), wanted=WANTED, source_node_id=32, receipt=receipt())


def test_a_binding_this_integration_would_never_write_is_refused_outright() -> None:
    with pytest.raises(mp.AclError, match="always names a node"):
        mp.binding_for((), wanted=mp.BindingEntry(group=4), source_node_id=31, receipt=receipt())


def test_confirming_a_grant_reads_the_list_back_and_finds_it() -> None:
    before = acl_of(EVE_ENERGY)
    after = (*before, mp.grant_entry(31, LIGHT, fabric_index=3))

    confirmed = mp.confirm_grant(node_id=8, subject=31, target=LIGHT, before=before, after=after)

    assert confirmed.covers(node_id=8, subject=31, target=LIGHT)


def test_a_write_that_lost_the_administer_entry_stops_the_binding() -> None:
    """The controller has just been locked out. Nothing else may be written after that."""
    before = acl_of(EVE_ENERGY)
    after = (mp.grant_entry(31, LIGHT, fabric_index=3),)

    with pytest.raises(mp.GrantNotConfirmedError, match="Administer"):
        mp.confirm_grant(node_id=8, subject=31, target=LIGHT, before=before, after=after)


def test_a_write_that_was_not_fabric_scoped_stops_the_binding() -> None:
    """If a write ever replaced the whole list, this is what notices, at the write that did it."""
    before = acl_of(EVE_ENERGY)
    after = (
        mp.entries_of_fabric(before, 3)[0],
        mp.grant_entry(31, LIGHT, fabric_index=3),
    )

    with pytest.raises(mp.GrantNotConfirmedError, match="not scoped to this fabric"):
        mp.confirm_grant(node_id=8, subject=31, target=LIGHT, before=before, after=after)


def test_a_read_back_this_controller_is_not_in_stops_the_binding() -> None:
    before = acl_of(EVE_ENERGY)

    with pytest.raises(mp.GrantNotConfirmedError, match="cannot find itself"):
        mp.confirm_grant(node_id=8, subject=31, target=LIGHT, before=before, after=())


def test_removing_a_binding_needs_no_receipt() -> None:
    """The grant is narrowed afterwards, so a failure leaves a permission and not a refusal."""
    assert mp.binding_without((WANTED,), wanted=WANTED) == ()
    assert mp.binding_without((), wanted=WANTED) is None


def test_a_binding_payload_is_keyed_by_tlv_tag() -> None:
    payload = mp.binding_payload((WANTED, mp.BindingEntry(group=4)))

    assert payload == [{"1": 8, "3": 1, "4": 6}, {"2": 4}]


# --------------------------------------------------------------------------------------
# The properties that matter more than any single case
# --------------------------------------------------------------------------------------

# Every shape of Access Control list this integration can meet, small enough to enumerate
# exhaustively: another fabric's redacted entry and the controller's own Administer entry are
# always there, and the sixth is what somebody else may have left behind.
_STARTS = (
    (),
    (mp.grant_entry(31, LIGHT, 2),),
    (mp.grant_entry(31, mp.AclTarget(cluster=8, endpoint=1), 2),),
    (mp.AclEntry(mp.PRIVILEGE_OPERATE, mp.AUTH_MODE_CASE, (31, 32), (LIGHT,), 2),),
    (mp.AclEntry(mp.PRIVILEGE_OPERATE, mp.AUTH_MODE_CASE, (31,), (), 2),),
    (mp.AclEntry(mp.PRIVILEGE_MANAGE, mp.AUTH_MODE_CASE, (31,), (LIGHT,), 2),),
)
_FOREIGN = mp.AclEntry(None, None, (), (), 1)
_ADMIN = mp.AclEntry(mp.PRIVILEGE_ADMINISTER, mp.AUTH_MODE_CASE, (CONTROLLER,), (), 2)
_SUBJECTS = (31, 32, 99, CONTROLLER)
_TARGETS = (
    LIGHT,
    mp.AclTarget(cluster=8, endpoint=1),
    mp.AclTarget(cluster=6, endpoint=2),
)
_CAPACITIES = tuple(
    mp.AclCapacity(
        entries_per_fabric=entries, subjects_per_entry=subjects, targets_per_entry=targets
    )
    for entries in (1, 2, 4, 6)
    for subjects in (1, 2, 4)
    for targets in (0, 1, 3)
)


def _what_is_granted(entries: tuple[mp.AclEntry, ...]) -> set[tuple[int, mp.AclTarget]]:
    """Return every (subject, target) pair this list lets through, of the ones we ask about."""
    return {
        (subject, target)
        for subject in _SUBJECTS
        for target in _TARGETS
        if any(entry.grants(subject, target) for entry in entries)
    }


def _every_case() -> list[tuple[tuple[mp.AclEntry, ...], int, mp.AclTarget, mp.AclCapacity]]:
    """Return every combination of list, subject, target and capacity worth trying."""
    return [
        ((_FOREIGN, _ADMIN, *start), subject, target, capacity)
        for start in _STARTS
        for subject in _SUBJECTS
        for target in _TARGETS
        for capacity in _CAPACITIES
    ]


def test_a_grant_never_widens_access_beyond_the_one_thing_it_was_asked_for() -> None:
    """The property the whole merge design rests on, over every case it can meet.

    Merging a subject into an entry somebody else may have written is only safe because the
    entry grants exactly the target being asked for, so the result can never let anything
    through that a separate entry of ours would not have. That is an argument, and this is
    the check: across 2592 combinations of starting list, subject, target and reported
    capacity, the only pair any outcome adds is the pair that was asked for.
    """
    for existing, subject, target, capacity in _every_case():
        outcome = mp.grant_for(existing, subject=subject, target=target, capacity=capacity)
        if outcome.entries is None:
            continue
        widened = _what_is_granted(outcome.entries) - _what_is_granted(existing)
        assert widened <= {(subject, target)}, (
            f"granting {subject} on {target} to {existing} also let through {widened}"
        )


def test_no_outcome_ever_loses_the_controllers_own_entry() -> None:
    """CLAUDE.md Section 3 rule 4, over the same space. A grant and a revocation both."""
    for existing, subject, target, capacity in _every_case():
        for outcome in (
            mp.grant_for(existing, subject=subject, target=target, capacity=capacity),
            mp.revoke_for(existing, subject=subject, target=target),
        ):
            if outcome.entries is None:
                continue
            assert any(entry.is_administer for entry in outcome.entries), (
                f"{subject} on {target} against {existing} lost the Administer entry"
            )


def test_no_outcome_ever_leaves_an_entry_with_no_subjects() -> None:
    """An Access Control entry with an empty subject list grants every node on the fabric.

    So the dangerous direction of a revocation is not failing to remove a subject: it is
    removing the last one and leaving the entry behind, which turns taking access away into
    the widest grant on the device.
    """
    for existing, subject, target, capacity in _every_case():
        for outcome in (
            mp.grant_for(existing, subject=subject, target=target, capacity=capacity),
            mp.revoke_for(existing, subject=subject, target=target),
        ):
            if outcome.entries is None:
                continue
            assert not [
                entry for entry in outcome.entries if not entry.subjects and not entry.is_redacted
            ], f"{subject} on {target} against {existing} left an entry granting everybody"


def test_a_revocation_never_widens_access_at_all() -> None:
    """Taking a link away has no pair it is allowed to add, unlike a grant."""
    for existing, subject, target, _capacity in _every_case():
        outcome = mp.revoke_for(existing, subject=subject, target=target)
        if outcome.entries is None:
            continue
        assert not _what_is_granted(outcome.entries) - _what_is_granted(existing)


def test_a_written_list_never_carries_another_fabrics_entry() -> None:
    """Every outcome has to be writable, and a redacted entry cannot be written back."""
    for existing, subject, target, capacity in _every_case():
        for outcome in (
            mp.grant_for(existing, subject=subject, target=target, capacity=capacity),
            mp.revoke_for(existing, subject=subject, target=target),
        ):
            if outcome.entries is None:
                continue
            mp.acl_payload(outcome.entries)
