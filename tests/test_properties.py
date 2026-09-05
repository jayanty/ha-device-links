"""Invariants that must hold for every profile and every starting state.

These use Hypothesis to generate rules, capabilities and observed states, then assert the
properties PRD Section 16 requires. A failure here is a real defect, not a flaky test:
Hypothesis will shrink it to a minimal reproduction.

Two of the five are the safety rules of Section 3 written as code. A lifeline that is removed
stops a device reporting to Home Assistant with nothing on screen to say so, and a hand-made
association that is removed is somebody's work destroyed by a tool that promised not to
(Decision D9). The other three say the core converges: applying a plan reaches what was
asked for, planning again asks for nothing more, and no group is ever overfilled.

Every failure is reported in the shorthand `tests/strategies.py` prints links in, because a
property is only worth having if the counterexample tells somebody what to go and fix.

`deadline=None` on every property is deliberate. These build several hundred plans per run,
and a per-example deadline turns a loaded laptop into a red test suite, which teaches
everybody to ignore the one signal that is supposed to matter.
"""

from __future__ import annotations

from collections.abc import Iterable

from hypothesis import given, settings

from custom_components.device_links.models import PlanItem, PlanOp
from custom_components.device_links.planner import build_plan
from tests.strategies import Network, networks, render_link, render_observed

EXAMPLES = 200


@given(networks())
@settings(max_examples=EXAMPLES, deadline=None)
def test_applying_a_plan_reaches_the_desired_state(network: Network) -> None:
    """Plan then apply on a fake backend converges to desired state."""
    result = network.apply(build_plan(**network.plan_inputs()))

    remaining = build_plan(**network.plan_inputs(observed=result))
    assert not _rendered(remaining.items, PlanOp.ADD), "a second plan still wants to add links"


@given(networks())
@settings(max_examples=EXAMPLES, deadline=None)
def test_a_second_plan_is_empty(network: Network) -> None:
    """Idempotence. Applying twice must not write anything the second time.

    A blocked add stays blocked, so a second plan is not always literally empty. Rather than
    excusing any blocked item, which would let a planner that newly blocks something it had
    just added pass unnoticed, the second plan must be exactly the first plan's blocked
    items: nothing new, nothing that writes, and nothing that has quietly changed its mind.
    """
    first = build_plan(**network.plan_inputs())
    state = network.apply(first)
    second = build_plan(**network.plan_inputs(observed=state))

    writes = [item for item in second.items if item.op is not PlanOp.BLOCKED]
    assert not _rendered(writes), "a second plan would write to a device again"
    assert _rendered(second.items) == _rendered(first.items, PlanOp.BLOCKED), (
        "the second plan is not the first plan's blocked items"
    )


@given(networks())
@settings(max_examples=EXAMPLES, deadline=None)
def test_a_lifeline_is_never_removed(network: Network) -> None:
    """The invariant that matters most. No generated input may violate it."""
    plan = build_plan(**network.plan_inputs(remove_everything=True))

    for item in plan.items:
        if item.op is PlanOp.REMOVE and item.link is not None:
            assert not item.link.is_system, (
                f"planned removal of a system link: {render_link(item.link)}"
            )
    assert not [render_observed(entry) for entry in plan.unmanaged if entry.is_system], (
        "a system link was offered for removal as an unmanaged one"
    )


@given(networks())
@settings(max_examples=EXAMPLES, deadline=None)
def test_group_capacity_is_never_exceeded(network: Network) -> None:
    """A group that overflows loses an association, and nothing on screen says which."""
    plan = build_plan(**network.plan_inputs())
    state = network.apply(plan)

    for group_id, entries in network.entries_by_group(state).items():
        assert len(entries) <= network.capacity_of(group_id), f"{group_id} exceeded its capacity"


@given(networks())
@settings(max_examples=EXAMPLES, deadline=None)
def test_unmanaged_links_survive_unless_selected(network: Network) -> None:
    """D9: the integration never destroys what it did not create.

    The second half is the same rule from the other side. Report-only would be no feature at
    all if an explicit per-link selection did not actually take the link off.
    """
    before = network.unmanaged_fingerprints()
    state = network.apply(build_plan(**network.plan_inputs()))
    after = {entry.fingerprint for entry in state}
    held = {entry.fingerprint: entry for entry in network.observed}

    assert before <= after, (
        f"unmanaged links disappeared: {[render_observed(held[gone]) for gone in before - after]}"
    )
    survived = network.selected_fingerprints() & after
    assert not survived, (
        f"a selected unmanaged link survived: {[render_observed(held[kept]) for kept in survived]}"
    )


def _rendered(items: Iterable[PlanItem], op: PlanOp | None = None) -> set[str]:
    """Return these plan items as readable strings, optionally only the ones doing one thing.

    A set of strings rather than of fingerprints because two plans are compared here and a
    mismatch has to be legible. Nothing generated varies a link's source endpoint, so what is
    rendered names one plan item as exactly as its fingerprint does.
    """
    return {
        f"{item.op} {'nothing' if item.link is None else render_link(item.link)}"
        for item in items
        if op is None or item.op is op
    }
