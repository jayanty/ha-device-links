"""The fake fabric is what the whole Matter write path is proved against, so prove it first.

The read tests below check that the fake serves what the M1 capture recorded, which is
evidence about real hardware. Everything from the write tests down describes behaviour
nobody has observed: nothing has ever been written to a Matter device from this project.
Assumption A9 in `docs/open-items.md`. Those tests are as wrong as the model is, on purpose,
and they are corrected together with it when a write is finally attempted.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.device_links.backends import matter_protocol as mp
from tests.fakes.matter import (
    CONTROLLER_NODE_ID,
    FakeMatterClient,
    FakeMatterError,
    build_fabric_from_fixture,
)

INOVELLI = 31
EVE_ENERGY = 8
SPARE_EVE = 19
LIGHT = mp.AclTarget(cluster=mp.ON_OFF_CLUSTER, endpoint=1)


@pytest.fixture
def fabric() -> FakeMatterClient:
    return build_fabric_from_fixture()


# --------------------------------------------------------------------------------------
# What the capture recorded, served as the fabric served it
# --------------------------------------------------------------------------------------


def test_the_fabric_holds_the_nineteen_nodes_that_were_captured(
    fabric: FakeMatterClient,
) -> None:
    nodes = {node.node_id: node for node in fabric.get_nodes()}

    assert len(nodes) == 19
    assert nodes[INOVELLI].name == "Kitchen Accent Lights"
    assert nodes[INOVELLI].device_info is not None
    assert nodes[INOVELLI].device_info.vendorName == "Inovelli"
    assert nodes[INOVELLI].device_info.productName == "VTM31-SN"
    assert all(node.available for node in nodes.values())


async def test_a_read_answers_with_a_mapping_keyed_by_the_path(
    fabric: FakeMatterClient,
) -> None:
    """The single most consequential shape in this backend, and Stage 0 was caught by it.

    Reading the mapping as the value turns every list into "not a list", which reads as a
    device with no clusters rather than as an error.
    """
    answer = await fabric.read_attribute(INOVELLI, mp.client_list_path(2))

    assert answer == {"2/29/2": [3, 6, 8]}


async def test_the_access_control_list_comes_back_keyed_by_tlv_tag(
    fabric: FakeMatterClient,
) -> None:
    """PRD Section 8.6, confirmed by the capture: a struct is tagged, not named."""
    answer = await fabric.read_attribute(INOVELLI, mp.ACL_PATH)

    assert answer[mp.ACL_PATH][1] == {
        "1": mp.PRIVILEGE_ADMINISTER,
        "2": mp.AUTH_MODE_CASE,
        "254": 2,
        "3": [CONTROLLER_NODE_ID],
        "4": None,
    }


async def test_another_fabrics_entries_come_back_redacted(fabric: FakeMatterClient) -> None:
    """Three of the four entries on the Inovelli carry a fabric index and nothing else."""
    entries = fabric.acl_of(INOVELLI)

    assert [entry.is_redacted for entry in entries] == [True, False, True, True]


def test_the_fabric_index_is_different_on_different_nodes(fabric: FakeMatterClient) -> None:
    """Which is why nothing anywhere may treat it as a constant."""
    assert fabric.fabric_index(INOVELLI) == 2
    assert fabric.fabric_index(EVE_ENERGY) == 3


def test_only_endpoints_with_a_binding_cluster_have_a_binding_list(
    fabric: FakeMatterClient,
) -> None:
    """Which on this fabric is endpoint 2 of the two Inovelli switches, and nothing else."""
    with_bindings = {
        node_id: [
            path for path in held if path.endswith(f"/{mp.BINDING_CLUSTER}/{mp.BINDING_ATTRIBUTE}")
        ]
        for node_id, held in fabric.attributes.items()
    }

    assert {node_id for node_id, paths in with_bindings.items() if paths} == {31, 32}
    assert fabric.bindings_of(INOVELLI, 2) == []


async def test_a_node_that_is_not_answering_raises(fabric: FakeMatterClient) -> None:
    """E29. The adapter must never let one of these escape as an unhandled exception."""
    fabric.unresponsive.add(INOVELLI)

    with pytest.raises(FakeMatterError, match="did not respond"):
        await fabric.read_attribute(INOVELLI, mp.client_list_path(2))


async def test_an_attribute_the_node_does_not_have_raises(fabric: FakeMatterClient) -> None:
    with pytest.raises(FakeMatterError, match="has no attribute"):
        await fabric.read_attribute(INOVELLI, mp.binding_path(1))


def test_a_node_can_be_taken_off_the_fabric_and_marked_unreachable(
    fabric: FakeMatterClient,
) -> None:
    fabric.go_offline(EVE_ENERGY)
    fabric.remove_node(SPARE_EVE)

    assert not fabric.nodes[EVE_ENERGY].available
    assert SPARE_EVE not in {node.node_id for node in fabric.get_nodes()}


# --------------------------------------------------------------------------------------
# Writes. Modelled, never observed: assumption A9.
# --------------------------------------------------------------------------------------


async def test_a_write_changes_what_the_next_read_answers(fabric: FakeMatterClient) -> None:
    entry = {"1": 8, "3": 1, "4": mp.ON_OFF_CLUSTER}

    await fabric.write_attribute(INOVELLI, mp.binding_path(2), [entry])

    assert fabric.bindings_of(INOVELLI, 2) == [entry]
    assert fabric.writes == [(INOVELLI, mp.binding_path(2), [entry])]


async def test_a_rejected_write_raises_and_changes_nothing(fabric: FakeMatterClient) -> None:
    fabric.reject_writes.add(mp.binding_path(2))

    with pytest.raises(FakeMatterError, match="rejected a write"):
        await fabric.write_attribute(INOVELLI, mp.binding_path(2), [{"1": 8}])

    assert fabric.bindings_of(INOVELLI, 2) == []


async def test_a_silent_write_is_accepted_and_ignored(fabric: FakeMatterClient) -> None:
    """The case a read-back exists for: the device said yes and did nothing."""
    fabric.silent.add(mp.binding_path(2))

    await fabric.write_attribute(INOVELLI, mp.binding_path(2), [{"1": 8}])

    assert fabric.bindings_of(INOVELLI, 2) == []
    assert fabric.write_count == 1


async def test_an_access_control_write_is_scoped_to_this_fabric(
    fabric: FakeMatterClient,
) -> None:
    """The specification's behaviour: our entries are replaced, other fabrics' are not."""
    grant = mp.acl_payload((mp.grant_entry(32, LIGHT, fabric_index=2),))

    await fabric.write_attribute(INOVELLI, mp.ACL_PATH, grant)

    entries = fabric.acl_of(INOVELLI)
    assert len(mp.foreign_entries(entries, 2)) == 3
    assert [entry.subjects for entry in mp.entries_of_fabric(entries, 2)] == [(32,)]


async def test_a_written_entry_is_stamped_with_the_fabric_it_arrived_on(
    fabric: FakeMatterClient,
) -> None:
    """The node assigns the fabric index, which is why a write never sends one."""
    grant = mp.acl_payload((mp.grant_entry(32, LIGHT, fabric_index=99),))

    await fabric.write_attribute(INOVELLI, mp.ACL_PATH, grant)

    (ours,) = mp.entries_of_fabric(fabric.acl_of(INOVELLI), 2)
    assert ours.fabric_index == 2


async def test_a_server_that_replaced_every_fabrics_entries_can_be_reproduced(
    fabric: FakeMatterClient,
) -> None:
    """Never observed and catastrophic, which is why the adapter checks for it every time."""
    fabric.unscoped_acl_writes = True
    grant = mp.acl_payload((mp.grant_entry(32, LIGHT, fabric_index=2),))

    await fabric.write_attribute(INOVELLI, mp.ACL_PATH, grant)

    assert mp.foreign_entries(fabric.acl_of(INOVELLI), 2) == ()


async def test_a_write_that_loses_the_administer_entry_can_be_reproduced(
    fabric: FakeMatterClient,
) -> None:
    """The other catastrophe: the controller locked out of its own device."""
    fabric.drops_administer = True
    before = mp.entries_of_fabric(fabric.acl_of(INOVELLI), 2)
    keep = mp.acl_payload((*before, mp.grant_entry(32, LIGHT, fabric_index=2)))

    await fabric.write_attribute(INOVELLI, mp.ACL_PATH, keep)

    assert not any(entry.is_administer for entry in fabric.acl_of(INOVELLI))


async def test_the_fake_writes_whatever_it_is_given(fabric: FakeMatterClient) -> None:
    """It protects nobody, on purpose. A real device would not, and the adapter's own
    refusal is what makes this safe to ship, so the fake must not stand in for it.
    """
    await fabric.write_attribute(INOVELLI, mp.ACL_PATH, [])

    assert mp.entries_of_fabric(fabric.acl_of(INOVELLI), 2) == ()


async def test_a_write_to_a_node_that_is_not_answering_raises(
    fabric: FakeMatterClient,
) -> None:
    fabric.unresponsive.add(INOVELLI)

    with pytest.raises(FakeMatterError):
        await fabric.write_attribute(INOVELLI, mp.binding_path(2), [])


# --------------------------------------------------------------------------------------
# Subscriptions, and the knobs a test uses to set a fabric up
# --------------------------------------------------------------------------------------


def test_a_subscription_receives_events_and_can_be_removed(fabric: FakeMatterClient) -> None:
    seen: list[tuple[Any, Any]] = []

    remove = fabric.subscribe_events(callback=lambda event, data: seen.append((event, data)))
    fabric.notify("attribute_updated", {"node_id": INOVELLI})
    remove()
    fabric.notify("attribute_updated", {"node_id": INOVELLI})

    assert seen == [("attribute_updated", {"node_id": INOVELLI})]
    assert fabric.subscription_count == 0


def test_an_event_filter_keeps_out_what_it_names(fabric: FakeMatterClient) -> None:
    seen: list[Any] = []

    fabric.subscribe_events(
        callback=lambda event, data: seen.append(data), event_filter="node_removed"
    )
    fabric.notify("attribute_updated", {"node_id": INOVELLI})

    assert seen == []


def test_a_test_can_change_what_a_node_says_it_can_hold(fabric: FakeMatterClient) -> None:
    """The fabric holds no node with a full Access Control list of a shape worth testing."""
    fabric.set_capacity(EVE_ENERGY, entries_per_fabric=2, subjects_per_entry=1)

    assert fabric.attributes[EVE_ENERGY][mp.ACL_ENTRIES_PER_FABRIC_PATH] == 2
    assert fabric.attributes[EVE_ENERGY][mp.ACL_SUBJECTS_PER_ENTRY_PATH] == 1


def test_a_test_can_put_somebody_elses_entries_on_a_node(fabric: FakeMatterClient) -> None:
    fabric.set_acl(EVE_ENERGY, [{"1": 5, "2": 2, "3": [CONTROLLER_NODE_ID], "254": 3}])
    fabric.add_binding(INOVELLI, 2, {"2": 4})

    assert len(fabric.acl_of(EVE_ENERGY)) == 1
    assert fabric.bindings_of(INOVELLI, 2) == [{"2": 4}]


def test_a_fabric_that_has_not_said_what_it_is_answers_with_nothing() -> None:
    """`server_info` is None until the client has connected, and the adapter says so."""
    client = FakeMatterClient(server_info=None)

    assert client.server_info is None
    assert client.get_nodes() == []
