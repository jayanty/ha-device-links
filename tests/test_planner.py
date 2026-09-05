"""Planning: desired versus observed, with the safety rules that must never bend."""

from __future__ import annotations

from dataclasses import replace

from custom_components.device_links.models import Feature, PlanOp
from custom_components.device_links.planner import build_plan
from tests.factories import capabilities_for, handle, link, observed


def test_a_missing_link_is_planned_as_an_add() -> None:
    desired = (link(36, "g9", 38, Feature.ON_OFF),)
    plan = build_plan(desired=desired, observed=(), capabilities=capabilities_for(36, 38))

    assert [item.op for item in plan.items] == [PlanOp.ADD]


def test_a_link_that_already_exists_is_not_rewritten() -> None:
    """E12: writing a link that is already present wastes a radio round trip."""
    wanted = link(36, "g9", 38, Feature.ON_OFF)
    plan = build_plan(
        desired=(wanted,),
        observed=(observed(wanted, rule_id="rule-1"),),
        capabilities=capabilities_for(36, 38),
    )

    assert not [item for item in plan.items if item.op is PlanOp.ADD]
    assert plan.unchanged_count == 1


def test_a_managed_link_no_longer_desired_is_planned_for_removal() -> None:
    """A disabled or deleted rule's links must actually come off the device."""
    stale = link(36, "g9", 38, Feature.ON_OFF)
    plan = build_plan(
        desired=(),
        observed=(observed(stale, rule_id="rule-1"),),
        capabilities=capabilities_for(36, 38),
    )

    assert [item.op for item in plan.items] == [PlanOp.REMOVE]


def test_an_unmanaged_link_is_reported_but_never_removed_by_default() -> None:
    """D9 and FR-U1. This is the difference between a tool and a hazard."""
    foreign = link(36, "g9", 35, Feature.ON_OFF)
    plan = build_plan(
        desired=(),
        observed=(observed(foreign, rule_id=None),),
        capabilities=capabilities_for(36, 35),
    )

    assert not [item for item in plan.items if item.op is PlanOp.REMOVE]
    assert len(plan.unmanaged) == 1


def test_an_unmanaged_link_is_removed_only_when_explicitly_selected() -> None:
    foreign = link(36, "g9", 35, Feature.ON_OFF)
    observed_foreign = observed(foreign, rule_id=None)
    plan = build_plan(
        desired=(),
        observed=(observed_foreign,),
        capabilities=capabilities_for(36, 35),
        remove_unmanaged=frozenset({observed_foreign.fingerprint}),
    )

    assert [item.op for item in plan.items] == [PlanOp.REMOVE]


def test_a_lifeline_entry_is_never_planned_for_removal() -> None:
    """The single most dangerous write in the system. Refuse it in code, not in the UI."""
    lifeline = observed(link(36, "g1", 1, Feature.STATUS_REPORT), rule_id=None, system=True)
    plan = build_plan(
        desired=(),
        observed=(lifeline,),
        capabilities=capabilities_for(36),
        remove_unmanaged=frozenset({lifeline.fingerprint}),
    )

    assert not [item for item in plan.items if item.op is PlanOp.REMOVE], (
        "a lifeline was planned for removal even though it was explicitly selected"
    )
    assert lifeline not in plan.unmanaged, "a lifeline is a system link, not an unmanaged one"


def test_a_full_group_blocks_the_add_and_says_how_full_it_is() -> None:
    """E6 and FR-R6: the message must be actionable, with counts."""
    existing = tuple(
        observed(link(40, "g2", target, Feature.ON_OFF), rule_id=None)
        for target in (30, 31, 32, 33, 34)
    )
    plan = build_plan(
        desired=(link(40, "g2", 35, Feature.ON_OFF),),
        observed=existing,
        capabilities=capabilities_for(40, 35, 30, 31, 32, 33, 34),
    )

    blocked = [item for item in plan.items if item.op is PlanOp.BLOCKED]
    assert len(blocked) == 1
    assert "group_full" in blocked[0].reason.translation_key
    assert blocked[0].reason.placeholders["used"] == "5"
    assert blocked[0].reason.placeholders["capacity"] == "5"


def test_capacity_counts_unmanaged_entries_too() -> None:
    """A group full of links we did not create is still full."""
    existing = tuple(
        observed(link(40, "g2", target, Feature.ON_OFF), rule_id=None)
        for target in (30, 31, 32, 33)
    )
    plan = build_plan(
        desired=(link(40, "g2", 35, Feature.ON_OFF), link(40, "g2", 36, Feature.ON_OFF)),
        observed=existing,
        capabilities=capabilities_for(40, 35, 36, 30, 31, 32, 33),
    )

    assert len([i for i in plan.items if i.op is PlanOp.ADD]) == 1
    assert len([i for i in plan.items if i.op is PlanOp.BLOCKED]) == 1


def test_the_plan_token_changes_when_observed_state_changes() -> None:
    """FR-A3: applying a stale plan must be detectable."""
    desired = (link(36, "g9", 38, Feature.ON_OFF),)
    caps = capabilities_for(36, 38, 35)

    empty = build_plan(desired=desired, observed=(), capabilities=caps)
    changed = build_plan(
        desired=desired,
        observed=(observed(link(36, "g9", 35, Feature.ON_OFF), rule_id=None),),
        capabilities=caps,
    )

    assert empty.token != changed.token


def test_the_plan_token_is_stable_for_identical_inputs() -> None:
    desired = (link(36, "g9", 38, Feature.ON_OFF),)
    caps = capabilities_for(36, 38)

    assert build_plan(desired=desired, observed=(), capabilities=caps).token == (
        build_plan(desired=desired, observed=(), capabilities=caps).token
    )


def test_a_plan_groups_its_items_by_device() -> None:
    """The apply dialog and the executor both work per device."""
    plan = build_plan(
        desired=(link(36, "g9", 38, Feature.ON_OFF), link(37, "paddle", 35, Feature.ON_OFF)),
        observed=(),
        capabilities=capabilities_for(36, 37, 38, 35),
    )

    assert set(plan.by_device()) == {handle(36).identity, handle(37).identity}


def test_an_empty_plan_is_reported_as_empty() -> None:
    """Idempotence: applying twice must produce nothing the second time."""
    wanted = link(36, "g9", 38, Feature.ON_OFF)
    plan = build_plan(
        desired=(wanted,),
        observed=(observed(wanted, rule_id="rule-1"),),
        capabilities=capabilities_for(36, 38),
    )

    assert plan.is_empty


# The tests above are the plan's. The ones below hold the same safety rules against the ways
# they could be got around, and cover the decisions the plan left to the implementation.


def test_a_system_link_is_not_removed_even_when_a_rule_claims_to_own_it() -> None:
    """Ownership is not a licence. A lifeline stays whoever recorded themselves against it.

    This is the way the lifeline rule could be lost without anyone noticing: a storage bug,
    a bad migration or a hand-edited file marks a lifeline as managed, and the next plan
    quietly takes the device off the network.
    """
    lifeline = observed(link(36, "g1", 1, Feature.STATUS_REPORT), rule_id="rule-1", system=True)

    plan = build_plan(desired=(), observed=(lifeline,), capabilities=capabilities_for(36))

    assert not [item for item in plan.items if item.op is PlanOp.REMOVE]
    assert plan.is_empty


def test_no_op_in_any_plan_ever_touches_a_system_link() -> None:
    """Every route into the planner at once: desired, managed, selected and full."""
    lifeline = observed(link(36, "g1", 1, Feature.STATUS_REPORT), rule_id="rule-1", system=True)
    other = observed(link(36, "g9", 38, Feature.ON_OFF), rule_id=None, system=True)

    plan = build_plan(
        desired=(link(36, "g9", 38, Feature.ON_OFF),),
        observed=(lifeline, other),
        capabilities=capabilities_for(36, 38),
        remove_unmanaged=frozenset({lifeline.fingerprint, other.fingerprint}),
    )

    assert not [item for item in plan.items if item.link is not None and item.link.is_system]
    assert not plan.unmanaged


def test_a_link_a_rule_wants_is_not_removed_even_when_selected() -> None:
    """A selection is about links nothing accounts for, and this one is accounted for."""
    wanted = link(36, "g9", 38, Feature.ON_OFF)
    foreign = observed(wanted, rule_id=None)

    plan = build_plan(
        desired=(wanted,),
        observed=(foreign,),
        capabilities=capabilities_for(36, 38),
        remove_unmanaged=frozenset({foreign.fingerprint}),
    )

    assert plan.is_empty
    assert plan.unchanged_count == 1
    assert not plan.unmanaged


def test_removals_come_before_adds_on_the_same_device() -> None:
    """Order is execution order: a removal frees a slot the add in front of it may need."""
    stale = observed(link(36, "g9", 35, Feature.ON_OFF), rule_id="rule-1")
    plan = build_plan(
        desired=(link(36, "g9", 38, Feature.ON_OFF),),
        observed=(stale,),
        capabilities=capabilities_for(36, 35, 38),
    )

    assert [item.op for item in plan.items] == [PlanOp.REMOVE, PlanOp.ADD]


def test_a_removal_frees_the_slot_the_add_needs() -> None:
    """A full group is not full if we are about to take one of our own entries out of it."""
    existing = tuple(
        observed(link(40, "g2", target, Feature.ON_OFF), rule_id="rule-1")
        for target in (30, 31, 32, 33, 34)
    )
    plan = build_plan(
        desired=(link(40, "g2", 35, Feature.ON_OFF),),
        observed=existing,
        capabilities=capabilities_for(40, 35, 30, 31, 32, 33, 34),
    )

    assert not [item for item in plan.items if item.op is PlanOp.BLOCKED]
    assert len([item for item in plan.items if item.op is PlanOp.ADD]) == 1


def test_which_add_is_blocked_does_not_depend_on_the_order_they_arrive_in() -> None:
    """A plan token that changed with dict ordering would be worthless, and the UI would flicker."""
    full = tuple(
        observed(link(40, "g2", target, Feature.ON_OFF), rule_id=None)
        for target in (30, 31, 32, 33)
    )
    first = link(40, "g2", 35, Feature.ON_OFF)
    second = link(40, "g2", 36, Feature.ON_OFF)
    capabilities = capabilities_for(40, 35, 36, 30, 31, 32, 33)

    forwards = build_plan(desired=(first, second), observed=full, capabilities=capabilities)
    backwards = build_plan(desired=(second, first), observed=full, capabilities=capabilities)

    def blocked(plan: object) -> set[str]:
        return {i.link.fingerprint for i in plan.items if i.op is PlanOp.BLOCKED}  # type: ignore[attr-defined]

    assert blocked(forwards) == blocked(backwards)
    assert forwards.token == backwards.token


def test_an_add_to_a_group_no_control_claims_is_blocked_rather_than_attempted() -> None:
    """Fail closed: a group whose capacity is unknown could be anything, including full."""
    caps = capabilities_for(36, 38)
    caps[handle(36).identity] = replace(caps[handle(36).identity], emitters=())

    plan = build_plan(desired=(link(36, "g9", 38, Feature.ON_OFF),), observed=(), capabilities=caps)

    blocked = [item for item in plan.items if item.op is PlanOp.BLOCKED]
    assert len(blocked) == 1
    assert "unknown_group" in blocked[0].reason.translation_key


def test_an_add_to_a_device_the_capabilities_do_not_describe_is_blocked() -> None:
    """A device that has gone missing gets no writes, however good the plan looked."""
    plan = build_plan(desired=(link(36, "g9", 38, Feature.ON_OFF),), observed=(), capabilities={})

    assert [item.op for item in plan.items] == [PlanOp.BLOCKED]


def test_the_plan_token_changes_when_the_desired_state_changes() -> None:
    caps = capabilities_for(36, 38, 35)
    one = build_plan(desired=(link(36, "g9", 38, Feature.ON_OFF),), observed=(), capabilities=caps)
    other = build_plan(
        desired=(link(36, "g9", 35, Feature.ON_OFF),), observed=(), capabilities=caps
    )

    assert one.token != other.token


def test_the_plan_token_changes_when_a_group_capacity_changes() -> None:
    """A plan built when a group had room is stale once the room is gone."""
    desired = (link(36, "g9", 38, Feature.ON_OFF),)
    caps = capabilities_for(36, 38)
    identity = handle(36).identity
    smaller = dict(caps)
    emitters = caps[identity].emitters
    smaller[identity] = replace(
        caps[identity],
        emitters=tuple(
            replace(emitter, capacity=1) if emitter.emitter_id == "g9" else emitter
            for emitter in emitters
        ),
    )

    assert build_plan(desired=desired, observed=(), capabilities=caps).token != (
        build_plan(desired=desired, observed=(), capabilities=smaller).token
    )


def test_the_plan_token_changes_when_a_link_changes_hands() -> None:
    """The same entry, ours or not, is a different plan: one is removable and one is not."""
    entry = link(36, "g9", 38, Feature.ON_OFF)
    caps = capabilities_for(36, 38)

    ours = build_plan(desired=(), observed=(observed(entry, rule_id="rule-1"),), capabilities=caps)
    theirs = build_plan(desired=(), observed=(observed(entry, rule_id=None),), capabilities=caps)

    assert ours.token != theirs.token


def test_the_plan_token_changes_when_an_unmanaged_link_is_selected_for_removal() -> None:
    """The selection is an input to the plan, so a stale one has to be detectable too."""
    foreign = observed(link(36, "g9", 38, Feature.ON_OFF), rule_id=None)
    caps = capabilities_for(36, 38)

    assert build_plan(desired=(), observed=(foreign,), capabilities=caps).token != (
        build_plan(
            desired=(),
            observed=(foreign,),
            capabilities=caps,
            remove_unmanaged=frozenset({foreign.fingerprint}),
        ).token
    )


def test_a_selection_naming_nothing_on_the_device_does_not_change_the_plan() -> None:
    """Too eager a token forces re-plans that change nothing, and users learn to click through."""
    foreign = observed(link(36, "g9", 38, Feature.ON_OFF), rule_id=None)
    caps = capabilities_for(36, 38)

    assert build_plan(desired=(), observed=(foreign,), capabilities=caps).token == (
        build_plan(
            desired=(),
            observed=(foreign,),
            capabilities=caps,
            remove_unmanaged=frozenset({"a link that is not on this device"}),
        ).token
    )


def test_the_same_link_desired_twice_is_planned_once() -> None:
    """Two rules can want the same link, and the device holds one entry either way."""
    wanted = link(36, "g9", 38, Feature.ON_OFF)
    plan = build_plan(
        desired=(wanted, replace(wanted, rule_id="rule-2")),
        observed=(),
        capabilities=capabilities_for(36, 38),
    )

    assert [item.op for item in plan.items] == [PlanOp.ADD]


def test_a_removal_carries_the_link_as_it_was_observed() -> None:
    """Whoever applies a removal has to be able to see what they are taking off the device."""
    stale = observed(link(36, "g9", 38, Feature.ON_OFF), rule_id="rule-1")
    plan = build_plan(desired=(), observed=(stale,), capabilities=capabilities_for(36, 38))

    assert plan.items[0].link is stale
    assert plan.items[0].device_identity == handle(36).identity


def test_a_plan_with_nothing_to_do_still_reports_what_it_found() -> None:
    """Reporting is not acting: unmanaged links are visible without being planned."""
    foreign = observed(link(36, "g9", 38, Feature.ON_OFF), rule_id=None)
    plan = build_plan(desired=(), observed=(foreign,), capabilities=capabilities_for(36, 38))

    assert plan.is_empty
    assert plan.unmanaged == (foreign,)
    assert plan.by_device() == {}
