"""The Matter write path: the access grant, the binding, and the order they happen in.

**Nothing here is proved against hardware.** No Matter binding and no Access Control entry
has ever been written by this project, so every one of these tests says that the adapter
agrees with `tests/fakes/matter.py`, which is a model built from the Matter specification and
from the shape the Stage 0 M1 reads came back in. That is assumption A9 in
`docs/open-items.md`, and this file is corrected together with the fake when a write is
finally attempted against a real device.

Two things it does check that are not about agreement with a model, and that are the reason
this path is safe to ship behind a flag:

- **The ordering is structural.** A binding cannot be written without a receipt, and a
  receipt cannot exist without an Access Control list read back from the device that carries
  the grant. Every refusal in the grant leaves the source device untouched, and that is
  asserted by counting what reached the fabric rather than by reading a status.
- **The Administer entry is untouchable.** Every path that could drop the controller's own
  grant is refused, whether the refusal comes from the merge or from the read-back.
"""

from __future__ import annotations

import pytest

from custom_components.device_links.backends import matter_protocol as mp
from custom_components.device_links.backends.base import LinkResultStatus
from custom_components.device_links.backends.matter import MatterBackend
from custom_components.device_links.models import Feature, Link
from tests.factories import (
    KITCHEN_ACCENT,
    KITCHEN_PENDANTS,
    SPARE_EVE,
    TIGHT_EVE,
    matter_handle,
    matter_link,
)
from tests.fakes.matter import CONTROLLER_NODE_ID, FakeMatterClient, build_fabric_from_fixture

# The link every test here starts from: the Inovelli paddle on endpoint 2 driving the Eve
# Energy's load on endpoint 1 over OnOff. The spare Eve is the target rather than the tight
# one because it has room for a grant; the tight one is used where fullness is the point.
LIGHT = mp.AclTarget(cluster=mp.ON_OFF_CLUSTER, endpoint=1)


@pytest.fixture
def fabric() -> FakeMatterClient:
    return build_fabric_from_fixture()


@pytest.fixture
def backend(fabric: FakeMatterClient) -> MatterBackend:
    return MatterBackend(client=fabric, writes_enabled=True)


def link(target: int = SPARE_EVE, **overrides: object) -> Link:
    """Return the link under test, with whatever a test wants changed."""
    return matter_link(KITCHEN_ACCENT, target, **overrides)  # type: ignore[arg-type]


def acl_writes(fabric: FakeMatterClient) -> list[object]:
    """Return every Access Control list this test wrote, in order."""
    return [value for _, path, value in fabric.writes if path == mp.ACL_PATH]


def binding_writes(fabric: FakeMatterClient) -> list[object]:
    """Return every Binding list this test wrote, in order."""
    return [value for _, path, value in fabric.writes if path.endswith(f"/{mp.BINDING_CLUSTER}/0")]


# --------------------------------------------------------------------------------------
# The flag, which is the whole of FR-B7
# --------------------------------------------------------------------------------------


async def test_writes_are_off_unless_somebody_turned_them_on(fabric: FakeMatterClient) -> None:
    """FR-B7 and Decision D11. The default is off in the adapter as well as in the options."""
    backend = MatterBackend(client=fabric)

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_writes_disabled"
    assert fabric.write_count == 0


async def test_a_removal_is_refused_by_the_flag_as_well(fabric: FakeMatterClient) -> None:
    """A flag that stopped adds and allowed removals would still be writing to devices."""
    backend = MatterBackend(client=fabric)

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert fabric.write_count == 0


async def test_a_check_says_the_flag_is_why_before_anything_is_planned(
    fabric: FakeMatterClient,
) -> None:
    backend = MatterBackend(client=fabric)

    check = await backend.async_check_link(link())

    assert not check.ok
    assert check.reason is not None
    assert check.reason.translation_key == "matter_writes_disabled"


async def test_reading_works_whether_or_not_writing_does(fabric: FakeMatterClient) -> None:
    """The option is about writing. Hiding the devices would protect nobody."""
    backend = MatterBackend(client=fabric)

    devices = await backend.async_devices()
    capabilities = await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert len(devices) == 19
    assert len(capabilities.emitters) == 1


# --------------------------------------------------------------------------------------
# A binding that works, and the grant it is built on
# --------------------------------------------------------------------------------------


async def test_a_binding_writes_the_access_grant_first_and_then_the_binding(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """E27, in the order it happens. Two writes, and the access one is first."""
    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.APPLIED
    assert [path for _, path, _ in fabric.writes] == [mp.ACL_PATH, mp.binding_path(2)]


async def test_the_grant_is_operate_on_the_one_cluster_and_endpoint(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """PRD Section 10: least privilege, never Administer, targeted where the device allows."""
    await backend.async_add_link(link())

    granted = [
        entry
        for entry in fabric.acl_of(SPARE_EVE)
        if entry.subjects == (KITCHEN_ACCENT,) and not entry.is_redacted
    ]
    (grant,) = granted
    assert grant.privilege == mp.PRIVILEGE_OPERATE
    assert grant.auth_mode == mp.AUTH_MODE_CASE
    assert grant.targets == (mp.AclTarget(cluster=mp.ON_OFF_CLUSTER, endpoint=1),)


async def test_the_binding_names_the_target_node_endpoint_and_cluster(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    await backend.async_add_link(link())

    assert fabric.bindings_of(KITCHEN_ACCENT, 2) == [
        {"1": SPARE_EVE, "3": 1, "4": mp.ON_OFF_CLUSTER}
    ]


async def test_the_administer_entry_survives_a_grant(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """CLAUDE.md Section 3 rule 4: the controller's own entry is never ours to touch."""
    before = [entry for entry in fabric.acl_of(SPARE_EVE) if entry.is_administer]

    await backend.async_add_link(link())

    after = [entry for entry in fabric.acl_of(SPARE_EVE) if entry.is_administer]
    assert before == after
    assert before != []


async def test_another_fabrics_entries_survive_a_grant(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A write of ours must change this fabric's entries and nobody else's."""
    before = mp.foreign_entries(fabric.acl_of(SPARE_EVE), 2)

    await backend.async_add_link(link())

    assert mp.foreign_entries(fabric.acl_of(SPARE_EVE), 2) == before


async def test_a_binding_that_is_already_there_writes_nothing(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The second apply of a rule must not spend a write or an Access Control entry."""
    await backend.async_add_link(link())
    fabric.writes.clear()

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert fabric.write_count == 0


async def test_a_second_control_merges_into_the_grant_the_first_one_made(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The load-bearing case: two entries of headroom is not enough for a grant each."""
    await backend.async_add_link(link())
    await backend.async_add_link(matter_link(KITCHEN_PENDANTS, SPARE_EVE))

    ours = mp.entries_of_fabric(fabric.acl_of(SPARE_EVE), 2)
    grants = [entry for entry in ours if not entry.is_administer]
    assert len(grants) == 1
    assert grants[0].subjects == (KITCHEN_ACCENT, KITCHEN_PENDANTS)


async def test_two_features_of_one_cluster_share_one_binding_and_one_grant(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Binding LevelControl is one entry that carries both, exactly as on Zigbee.

    The other Inovelli is the target, because it is the only device on this fabric that
    serves LevelControl at all: an Eve Energy is a plug and its endpoint 1 serves OnOff and
    nothing dimmable. Its access list is full at 4 of 4, which is a real refusal and not the
    one this test is about, so it is widened first.
    """
    fabric.set_capacity(KITCHEN_PENDANTS, entries_per_fabric=6)
    dim = matter_link(KITCHEN_ACCENT, KITCHEN_PENDANTS, cluster=8, feature=Feature.LEVEL_SET)
    hold = matter_link(KITCHEN_ACCENT, KITCHEN_PENDANTS, cluster=8, feature=Feature.LEVEL_HOLD)

    assert (await backend.async_add_link(dim)).status is LinkResultStatus.APPLIED
    result = await backend.async_add_link(hold)

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert len(fabric.bindings_of(KITCHEN_ACCENT, 2)) == 1


async def test_a_binding_somebody_else_wrote_is_carried_through_untouched(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """FR-B7: never drop an entry this integration did not create."""
    theirs = {"2": 4}
    fabric.add_binding(KITCHEN_ACCENT, 2, theirs)

    await backend.async_add_link(link())

    assert theirs in fabric.bindings_of(KITCHEN_ACCENT, 2)


# --------------------------------------------------------------------------------------
# E27: a rejected grant leaves no partial state
# --------------------------------------------------------------------------------------


async def test_a_full_access_list_blocks_the_link_and_writes_nothing(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """E27 and E28 on real numbers: both Inovelli switches hold 4 of 4 already."""
    result = await backend.async_add_link(matter_link(KITCHEN_ACCENT, KITCHEN_PENDANTS))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_acl_full"
    assert result.reason.placeholders["used"] == "4"
    assert result.reason.placeholders["capacity"] == "4"
    assert fabric.write_count == 0


async def test_a_grant_that_cannot_be_written_leaves_the_source_untouched(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The whole of E27: no binding follows a grant that did not happen."""
    fabric.reject_writes.add(mp.ACL_PATH)

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert binding_writes(fabric) == []
    assert fabric.bindings_of(KITCHEN_ACCENT, 2) == []


async def test_a_grant_the_device_accepted_and_ignored_stops_the_binding(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The read-back is what catches this. The write succeeded and nothing changed."""
    fabric.silent.add(mp.ACL_PATH)

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_grant_not_confirmed"
    assert binding_writes(fabric) == []


async def test_a_write_that_locked_the_controller_out_stops_the_binding(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Never observed and catastrophic, so it is checked on every single write."""
    fabric.drops_administer = True

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_grant_not_confirmed"
    assert result.raw_error is not None
    assert "Administer" in result.raw_error
    assert binding_writes(fabric) == []


async def test_a_write_that_was_not_scoped_to_this_fabric_stops_the_binding(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """If a server ever replaced the whole list, this is what notices, at the write itself."""
    fabric.unscoped_acl_writes = True

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.raw_error is not None
    assert "other fabrics" in result.raw_error
    assert binding_writes(fabric) == []


async def test_a_node_whose_access_list_cannot_be_read_is_never_written_to(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """No fabric index means nothing can be written under one."""
    fabric.set_acl(SPARE_EVE, [{"254": 1}])

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_acl_unreadable"
    assert fabric.write_count == 0


async def test_a_device_that_cannot_express_a_targeted_grant_is_refused(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Never widened to a whole-node grant: PRD Section 10 says the narrowest or nothing."""
    fabric.set_capacity(SPARE_EVE, targets_per_entry=0)

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_acl_not_targetable"
    assert fabric.write_count == 0


async def test_a_full_grant_on_a_full_list_says_which_of_the_two_it_is(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The two have different answers, so they are different messages."""
    fabric.set_capacity(SPARE_EVE, entries_per_fabric=3, subjects_per_entry=1)
    await backend.async_add_link(link())

    result = await backend.async_add_link(matter_link(KITCHEN_PENDANTS, SPARE_EVE))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_acl_subjects_full"


async def test_a_capacity_that_could_not_be_read_refuses_rather_than_guessing(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Zero refuses. A device whose limit is unknown is one to leave alone."""
    fabric.attributes[SPARE_EVE][mp.ACL_ENTRIES_PER_FABRIC_PATH] = None

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_acl_full"
    assert fabric.write_count == 0


# --------------------------------------------------------------------------------------
# The binding write, and what happens when it does not take
# --------------------------------------------------------------------------------------


async def test_a_binding_the_device_accepted_and_ignored_is_reported_as_failed(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """It looks applied, which is the worst outcome available, so the read-back decides."""
    fabric.silent.add(mp.binding_path(2))

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_binding_not_confirmed"


async def test_a_binding_write_the_device_refused_is_reported_with_its_own_words(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    fabric.reject_writes.add(mp.binding_path(2))

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_write_failed"
    assert result.raw_error is not None
    assert "FakeMatterError" in result.raw_error


async def test_a_full_binding_list_is_blocked_before_anything_is_granted(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """E28. Nothing is written to the target for a link that cannot land on the source."""
    for index in range(mp.BINDING_TABLE_CAPACITY):
        fabric.add_binding(KITCHEN_ACCENT, 2, {"1": 100 + index, "3": 1, "4": 6})

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_binding_full"
    assert fabric.write_count == 0


# --------------------------------------------------------------------------------------
# Refusals that never reach the fabric
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("built", "key"),
    [
        (
            lambda: matter_link(KITCHEN_ACCENT, SPARE_EVE, target_endpoint=None),
            "matter_target_endpoint_required",
        ),
        # Endpoint 1 is the load: it serves no Binding cluster, so there is nowhere on it
        # to keep a link whatever it drives.
        (lambda: matter_link(KITCHEN_ACCENT, SPARE_EVE, endpoint=1), "matter_no_binding_cluster"),
        # Endpoint 2 is the paddle and does serve one, and it does not drive scenes.
        (
            lambda: matter_link(KITCHEN_ACCENT, SPARE_EVE, cluster=98, feature=Feature.SCENE),
            "matter_source_cannot_send",
        ),
        # An Eve Energy is a plug: its endpoint 1 serves OnOff and nothing dimmable, so a
        # LevelControl binding to it would be accepted and dead forever.
        (
            lambda: matter_link(KITCHEN_ACCENT, SPARE_EVE, cluster=8, feature=Feature.LEVEL_SET),
            "matter_target_cannot_receive",
        ),
        # The root endpoint administers the node and acts on nothing.
        (
            lambda: matter_link(KITCHEN_ACCENT, SPARE_EVE, target_endpoint=0),
            "matter_target_cannot_receive",
        ),
    ],
)
async def test_a_link_that_could_not_work_is_blocked_before_it_is_spent(
    backend: MatterBackend, fabric: FakeMatterClient, built: object, key: str
) -> None:
    result = await backend.async_add_link(built())  # type: ignore[operator]

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == key
    assert fabric.write_count == 0


async def test_a_self_binding_is_refused_whatever_else_is_true(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """`Link` refuses to build one, so this is what a deserialized or service-call one meets."""
    # Past `Link.__post_init__`, which refuses to build one, to what a deserialized link or
    # a raw service call could hand the adapter. Defence in depth means the adapter refuses
    # on its own account and not because something upstream already did.
    from custom_components.device_links.models import LinkTarget  # noqa: PLC0415

    built = link()
    object.__setattr__(
        built, "target", LinkTarget(handle=matter_handle(KITCHEN_ACCENT), endpoint=1)
    )

    result = await backend.async_add_link(built)

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_self_binding"
    assert fabric.write_count == 0


async def test_a_group_target_is_refused_and_says_why(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A Matter group needs keys handed out at commissioning time. That is not a link."""
    from dataclasses import replace  # noqa: PLC0415

    from custom_components.device_links.models import LinkTarget  # noqa: PLC0415

    built = replace(link(), target=LinkTarget(handle=mp.group_handle(4), endpoint=None))

    result = await backend.async_add_link(built)

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_group_target"
    assert fabric.write_count == 0


async def test_a_link_whose_group_is_not_a_cluster_id_is_refused(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A rule written for another protocol reads this way, and can be imported."""
    from dataclasses import replace  # noqa: PLC0415

    built = replace(link(), emitter_group="genOnOff")

    result = await backend.async_add_link(built)

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_unknown_cluster"
    assert fabric.write_count == 0


async def test_a_node_that_has_left_the_fabric_is_blocked(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    built = link()
    fabric.remove_node(SPARE_EVE)

    result = await backend.async_add_link(built)

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_unknown_device"
    assert fabric.write_count == 0


async def test_a_node_that_is_asleep_is_pending_rather_than_failed(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """E29: nothing has gone wrong, and the write is worth trying again when it is back."""
    fabric.go_offline(SPARE_EVE)

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.PENDING_WAKEUP
    assert result.reason is not None
    assert result.reason.translation_key == "matter_node_offline"
    assert fabric.write_count == 0


async def test_a_source_endpoint_with_no_binding_cluster_is_refused(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """There is nowhere on the device to keep the entry, so it can never be written."""
    fabric.attributes[KITCHEN_ACCENT][mp.server_list_path(2)] = [3, 29, 64, 65]
    fabric.attributes[KITCHEN_ACCENT][mp.client_list_path(2)] = [3, 6, 8]

    result = await backend.async_add_link(link())

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_no_binding_cluster"
    assert fabric.write_count == 0


async def test_a_check_passes_for_a_link_that_would_work(backend: MatterBackend) -> None:
    check = await backend.async_check_link(link())

    assert check.ok
    assert check.reason is None


async def test_a_check_of_a_removal_asks_less_than_a_check_of_an_add(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A refusal about writing has nothing to say about taking an entry off."""
    fabric.attributes[KITCHEN_ACCENT][mp.client_list_path(2)] = [3]

    check = await backend.async_check_link(link())

    assert not check.ok
    assert check.reason is not None
    assert check.reason.translation_key == "matter_source_cannot_send"


# --------------------------------------------------------------------------------------
# Removal, which is the add in reverse
# --------------------------------------------------------------------------------------


async def test_a_removal_takes_the_binding_off_and_then_narrows_the_grant(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The reverse order of the add, so a failure part way leaves a permission and not a
    binding the target refuses.
    """
    await backend.async_add_link(link())
    fabric.writes.clear()

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.APPLIED
    assert [path for _, path, _ in fabric.writes] == [mp.binding_path(2), mp.ACL_PATH]
    assert fabric.bindings_of(KITCHEN_ACCENT, 2) == []
    assert not any(entry.subjects == (KITCHEN_ACCENT,) for entry in fabric.acl_of(SPARE_EVE))


async def test_a_removal_leaves_the_administer_entry_alone(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    await backend.async_add_link(link())

    await backend.async_remove_link(link())

    assert any(entry.is_administer for entry in fabric.acl_of(SPARE_EVE))


async def test_a_removal_leaves_another_controls_grant_in_place(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The two share a merged entry, so removing one must narrow it rather than delete it."""
    await backend.async_add_link(link())
    await backend.async_add_link(matter_link(KITCHEN_PENDANTS, SPARE_EVE))

    await backend.async_remove_link(link())

    ours = mp.entries_of_fabric(fabric.acl_of(SPARE_EVE), 2)
    grants = [entry for entry in ours if not entry.is_administer]
    assert [entry.subjects for entry in grants] == [(KITCHEN_PENDANTS,)]


async def test_removing_a_link_that_is_not_there_still_clears_a_grant_left_behind(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A removal interrupted half way is finished by the next one rather than left forever."""
    await backend.async_add_link(link())
    fabric.attributes[KITCHEN_ACCENT][mp.binding_path(2)] = []
    fabric.writes.clear()

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert acl_writes(fabric) != []
    assert not any(entry.subjects == (KITCHEN_ACCENT,) for entry in fabric.acl_of(SPARE_EVE))


async def test_a_grant_that_will_not_narrow_does_not_fail_the_removal(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The binding is gone, which is what was asked for. What is left permits nothing."""
    await backend.async_add_link(link())
    fabric.reject_writes.add(mp.ACL_PATH)

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.APPLIED
    assert fabric.bindings_of(KITCHEN_ACCENT, 2) == []


async def test_a_binding_that_would_not_come_off_is_reported_as_failed(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    await backend.async_add_link(link())
    fabric.silent.add(mp.binding_path(2))

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_binding_not_confirmed"


async def test_a_removal_that_the_device_refused_keeps_its_own_words(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    await backend.async_add_link(link())
    fabric.reject_writes.add(mp.binding_path(2))

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.FAILED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_write_failed"


async def test_a_removal_leaves_a_binding_somebody_else_wrote_alone(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    theirs = {"2": 4}
    fabric.add_binding(KITCHEN_ACCENT, 2, theirs)
    await backend.async_add_link(link())

    await backend.async_remove_link(link())

    assert fabric.bindings_of(KITCHEN_ACCENT, 2) == [theirs]


async def test_a_removal_from_a_source_that_is_asleep_is_pending(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The binding is on the source, so a source that is not answering stops everything."""
    await backend.async_add_link(link())
    fabric.go_offline(KITCHEN_ACCENT)
    fabric.writes.clear()

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.PENDING_WAKEUP
    assert fabric.write_count == 0


async def test_a_removal_whose_target_will_not_answer_still_takes_the_binding_off(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The target is only needed to narrow the grant, and that never fails a removal.

    What is left behind is a permission that permits nothing, and the next removal of the
    same link tries to narrow it again.
    """
    await backend.async_add_link(link())
    fabric.unresponsive.add(SPARE_EVE)
    fabric.writes.clear()

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.APPLIED
    assert fabric.bindings_of(KITCHEN_ACCENT, 2) == []
    assert any(entry.subjects == (KITCHEN_ACCENT,) for entry in fabric.acl_of(SPARE_EVE)), (
        "the grant is left behind, because the device it is on is not answering"
    )


async def test_the_controllers_own_subject_is_never_what_a_grant_names(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A grant names the source device, not the controller: the controller already has one."""
    await backend.async_add_link(link())

    ours = mp.entries_of_fabric(fabric.acl_of(SPARE_EVE), 2)
    grants = [entry for entry in ours if not entry.is_administer]
    assert CONTROLLER_NODE_ID not in grants[0].subjects


async def test_a_removal_against_a_target_whose_access_list_will_not_read_is_survivable(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The revoke never fails a link, so an unreadable list costs a log line."""
    await backend.async_add_link(link())
    fabric.set_acl(SPARE_EVE, [{"254": 1}])

    result = await backend.async_remove_link(link())

    assert result.status is LinkResultStatus.APPLIED


async def test_the_tight_eve_is_where_merging_stops_being_optional(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Stage 0's headline number, exercised: 4 of 6 used leaves room for two entries.

    Three rules pointing at this device would not fit as an entry each, and they do fit as
    one merged entry, which is why `grant_for` merges rather than appends.
    """
    first = await backend.async_add_link(matter_link(KITCHEN_ACCENT, TIGHT_EVE))
    second = await backend.async_add_link(matter_link(KITCHEN_PENDANTS, TIGHT_EVE))

    assert first.status is LinkResultStatus.APPLIED
    assert second.status is LinkResultStatus.APPLIED
    assert len(fabric.acl_of(TIGHT_EVE)) == 5


async def test_a_link_asking_for_a_feature_its_cluster_cannot_carry_is_already_there(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The one way the binding merge finds an entry the presence check did not.

    A link's identity carries its feature, and a binding's identity does not: one binding
    is one entry whatever features it stands for. So a rule asking for scenes over OnOff,
    which an imported profile can produce, does not match the observed link for a binding
    that is already there, and the merge is what notices. It answers `already_present`
    rather than writing the same entry twice.
    """
    await backend.async_add_link(link())
    fabric.writes.clear()

    result = await backend.async_add_link(link(feature=Feature.SCENE))

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert binding_writes(fabric) == []


async def test_a_capability_check_of_a_node_that_left_between_the_two_reads(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """`async_check_link` reads for itself, so it meets a node that has gone on its own."""
    built = link()
    fabric.remove_node(SPARE_EVE)

    check = await backend.async_check_link(built)

    assert not check.ok
    assert check.reason is not None
    assert check.reason.translation_key == "matter_unknown_device"


async def test_a_check_of_a_control_with_nowhere_to_keep_a_link_says_that(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A check answers the same refusals a write would, without spending anything."""
    fabric.attributes[KITCHEN_ACCENT][mp.server_list_path(2)] = [3, 29, 64, 65]

    check = await backend.async_check_link(link())

    assert not check.ok
    assert check.reason is not None
    assert check.reason.translation_key == "matter_no_binding_cluster"


async def test_a_binding_to_a_node_that_has_left_the_fabric_can_still_be_removed(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The leftover somebody most wants gone, and it lives entirely on the source.

    A removal that insisted on reading the departed device would leave the entry on the
    switch with nothing in the product able to take it off.
    """
    built = link()
    await backend.async_add_link(built)
    fabric.remove_node(SPARE_EVE)
    fabric.writes.clear()

    result = await backend.async_remove_link(built)

    assert result.status is LinkResultStatus.APPLIED
    assert fabric.bindings_of(KITCHEN_ACCENT, 2) == []


async def test_adding_a_link_to_a_node_that_has_left_the_fabric_is_still_refused(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The other half of the asymmetry: an add has to reach the target to grant access."""
    built = link()
    fabric.remove_node(SPARE_EVE)

    result = await backend.async_add_link(built)

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert result.reason.translation_key == "matter_unknown_device"
