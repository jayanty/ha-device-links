"""The whole Zigbee loop, and the test that decides whether the `Backend` seam held.

`tests/test_apply_loop.py` does this for Z-Wave. This file does it for Zigbee and then does
the thing neither protocol can do alone: one profile holding a Z-Wave rule and a Zigbee
rule, planned and applied together, through a coordinator and an executor that were written
before Zigbee existed and were not touched to make it work.

Three assertions carry the file.

**A second plan is empty.** For Zigbee that is a sharper claim than it looks. One binding
carries two features, several targets go behind one managed group, and a rule that asked
for both level features must not leave one of them proposed as an add forever.

**A partial cluster failure is a failed link, and the plan converges on retry.** Applying
again writes exactly the work that is left, which is what makes "press apply again" a safe
instruction rather than a hopeful one.

**The mixed profile needed no change to `compiler.py`, `planner.py` or `coordinator.py`.**
That is the whole point of the `Backend` protocol, and this is where it is either true or
it is not.

The write half of all of this is modelled: item G2 was never approved, so no bind has been
performed on this network. Assumption A2, issue #6.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_links.backends import zigbee_protocol as zp
from custom_components.device_links.backends.zigbee2mqtt import ZigbeeBackend
from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.coordinator import DeviceLinksCoordinator, PlanScope
from custom_components.device_links.executor import JobRunner, JobStatus, LinkOutcome
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    Direction,
    Feature,
    ObservedLink,
    Plan,
    PlanItem,
    PlanOp,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from custom_components.device_links.storage import DeviceLinksStore, StoredState
from tests.factories import (
    AUX_IEEE,
    COORDINATOR_IEEE,
    LIGHT_IEEE,
    OLD_FIRMWARE_IEEE,
    SECOND_LIGHT_IEEE,
    handle,
    profiles,
    zigbee_handle,
)
from tests.fakes.zigbee import FakeBridge, build_bridge_from_fixture
from tests.fakes.zwave import build_driver_from_fixture

AUX = "Entrance Inside Lights Aux"
LIGHT = "Entrance Inside Lights"

# What "on/off and dim" means as a set of features. `LEVEL_SET` and `LEVEL_HOLD` are two
# features and, on Zigbee, one cluster: `genLevelCtrl` carries both, and there is no way to
# bind one without the other.
DIMMING = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})

# The bedroom pair the Z-Wave loop tests use, so the mixed profile is two scenarios that
# are each already proven on their own.
CONTROLLER = 36
MAIN_LIGHTS = 37


@pytest.fixture(autouse=True)
def _use_storage(hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Keep every store in these tests in memory, so no test ever writes a real file."""
    return hass_storage


@pytest.fixture
def bridge() -> FakeBridge:
    return build_bridge_from_fixture()


@pytest.fixture
async def zigbee(bridge: FakeBridge) -> ZigbeeBackend:
    backend = ZigbeeBackend(client=bridge, profiles=profiles(), request_timeout=0.2)
    await backend.async_start()
    return backend


@pytest.fixture
async def coordinator(
    hass: HomeAssistant, zigbee: ZigbeeBackend
) -> AsyncGenerator[DeviceLinksCoordinator]:
    built = DeviceLinksCoordinator(
        hass, backends={BackendId.ZIGBEE2MQTT: zigbee}, store=DeviceLinksStore(hass)
    )
    await built.async_setup()
    yield built
    await built.async_shutdown()


@pytest.fixture
async def both(
    hass: HomeAssistant, zigbee: ZigbeeBackend
) -> AsyncGenerator[DeviceLinksCoordinator]:
    """A coordinator holding a Z-Wave network and a Zigbee network at the same time."""
    built = DeviceLinksCoordinator(
        hass,
        backends={
            BackendId.ZWAVE: ZWaveBackend(
                driver=build_driver_from_fixture(), profiles=profiles(), debounce_seconds=0
            ),
            BackendId.ZIGBEE2MQTT: zigbee,
        },
        store=DeviceLinksStore(hass),
    )
    await built.async_setup()
    yield built
    await built.async_shutdown()


async def _no_sleep(delay: float) -> None:
    """Stand in for the retry backoff, so a failing write costs three seconds of nothing."""
    return


@pytest.fixture
def runner(coordinator: DeviceLinksCoordinator) -> JobRunner:
    return JobRunner(coordinator, sleep=_no_sleep)


def s8_rule(*targets: str, rule_id: str = "s8") -> Rule:
    """PRD scenario S8, as a user would author it.

    "Entrance Inside Lights Aux" endpoint 2 (the paddle) controls "Entrance Inside Lights"
    endpoint 1 (the load) with on/off and dim. This is the pair Stage 0 item G2 would have
    bound, and the capture confirms both ends are unbound today.

    The target endpoint is named, and has to be: a Zigbee binding always names one, and the
    adapter refuses a link that does not rather than choosing on the user's behalf.
    """
    return Rule(
        id=rule_id,
        name="Entrance aux paddle controls the entrance lights",
        template=Template.REMOTE,
        backend=BackendId.ZIGBEE2MQTT,
        source=RuleSource(device=zigbee_handle(AUX_IEEE), endpoint=2, emitter_id="ep2"),
        targets=tuple(
            RuleTarget(device=zigbee_handle(ieee), endpoint=1)
            for ieee in (targets or (LIGHT_IEEE,))
        ),
        features=DIMMING,
    )


def zwave_rule() -> Rule:
    """The bedroom rule from the Z-Wave loop tests, unchanged."""
    return Rule(
        id="bedroom-main",
        name="036 main button controls Master Bedroom Lights",
        template=Template.REMOTE,
        backend=BackendId.ZWAVE,
        source=RuleSource(device=handle(CONTROLLER), endpoint=0, emitter_id="g2"),
        targets=(RuleTarget(device=handle(MAIN_LIGHTS), endpoint=None),),
        features=DIMMING,
    )


def activate(coordinator: DeviceLinksCoordinator, *rules: Rule) -> None:
    """Make a profile of these rules the active one, as saving in the panel would."""
    profile = Profile(id="house", name="House", rules=rules)
    coordinator.async_update_state(StoredState(profiles=(profile,), active_profile_id=profile.id))


def links_of(coordinator: DeviceLinksCoordinator, ieee: str) -> tuple[ObservedLink, ...]:
    device = coordinator.observed_for(zigbee_handle(ieee))
    assert device is not None
    return device.links


def bound(coordinator: DeviceLinksCoordinator, ieee: str, endpoint: int) -> set[tuple[str, str]]:
    """Return what one endpoint of a device drives, as (cluster, target address) pairs.

    The shape a person reads in Zigbee2MQTT, which is the point: what the loop has to be
    judged against is what is on the device, not what our own types say. The bridge's own
    reporting bindings are left out, because they are there before any rule is and are
    still there after every one of them.
    """
    return {
        (link.emitter_group, link.target.handle.protocol_id)
        for link in links_of(coordinator, ieee)
        if link.source_endpoint == endpoint and not link.is_system
    }


async def plan_and_apply(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, **kwargs: Any
) -> tuple[Any, Any]:
    """Do what pressing Plan and then Apply does, and return both halves."""
    plan = await coordinator.async_plan(**kwargs)
    return plan, await runner.async_apply(plan, **kwargs)


# --------------------------------------------------------------------------------------
# S8
# --------------------------------------------------------------------------------------


async def test_s8_the_aux_paddle_drives_the_entrance_lights(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """PRD S8, end to end: compile, plan, apply, verify, and the bridge holds exactly this.

    Three links and two bindings, which is the honest arithmetic of Zigbee: `genLevelCtrl`
    carries both level features, so the second of them is already present by the time it is
    asked for and nothing is written twice.
    """
    activate(coordinator, s8_rule())

    plan, report = await plan_and_apply(coordinator, runner)

    assert len(plan.items) == 3
    assert report.status is JobStatus.COMPLETED
    assert sorted(result.outcome for result in report.results) == [
        LinkOutcome.ALREADY_PRESENT,
        LinkOutcome.APPLIED,
        LinkOutcome.APPLIED,
    ]
    assert bound(coordinator, AUX_IEEE, 2) == {
        (zp.GEN_ON_OFF, LIGHT_IEEE),
        (zp.GEN_LEVEL_CTRL, LIGHT_IEEE),
    }
    assert [b["cluster"] for b in bridge.bindings_of(AUX, 2)] == [
        "manuSpecificInovelli",
        zp.GEN_LEVEL_CTRL,
        zp.GEN_ON_OFF,
    ]


async def test_s8_verifies_from_a_fresh_read_rather_than_from_what_was_sent(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    activate(coordinator, s8_rule())

    _, report = await plan_and_apply(coordinator, runner)

    written = [r for r in report.results if r.outcome is LinkOutcome.APPLIED]
    assert written
    assert all(result.verified_at is not None for result in written)


async def test_s8_planned_again_has_nothing_to_do(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """Convergence and idempotence in one line, and the sharpest test of the level model.

    A binding reported under one of its two features would leave the other missing from
    every plan: proposed as an add, answered `already_present`, and proposed again forever.
    """
    activate(coordinator, s8_rule())
    await plan_and_apply(coordinator, runner)

    assert (await coordinator.async_plan()).is_empty


async def test_the_reporting_bindings_are_never_proposed_for_removal(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """Every binding on this network targets the coordinator. They stay exactly as they are."""
    activate(coordinator, s8_rule())

    plan, _ = await plan_and_apply(coordinator, runner)

    assert {item.op for item in plan.items} == {PlanOp.ADD}
    reporting = {
        (link.source_endpoint, link.emitter_group)
        for link in links_of(coordinator, AUX_IEEE)
        if link.is_system
    }
    assert len(reporting) == 6, "the six bindings the bridge made are all still there"
    assert not plan.unmanaged, "a system link must not be offered as an unmanaged one either"


async def test_disabling_the_rule_takes_the_bindings_back_off(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """FR-R5, and the other half of what "the switch physically writes links" means (D7)."""
    activate(coordinator, s8_rule())
    await plan_and_apply(coordinator, runner)

    activate(coordinator, s8_rule().with_enabled(False))
    _, report = await plan_and_apply(coordinator, runner)

    assert report.status is JobStatus.COMPLETED
    assert bound(coordinator, AUX_IEEE, 2) == set()
    assert [b["cluster"] for b in bridge.bindings_of(AUX, 2)] == ["manuSpecificInovelli"]


# --------------------------------------------------------------------------------------
# One rule, several targets
# --------------------------------------------------------------------------------------


async def test_a_one_to_many_rule_ends_up_behind_a_managed_group(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """Decision D5, driven entirely by the executor writing one link at a time.

    The first target is a plain binding and the rest go through `dl_<rule id>`, so three
    targets cost two binding table entries per cluster instead of three, and nothing that
    was already on the device is moved.
    """
    activate(coordinator, s8_rule(LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE))

    _, report = await plan_and_apply(coordinator, runner)

    assert report.status is JobStatus.COMPLETED
    group = bridge.group_named("dl_s8")
    assert group is not None
    # In fingerprint order, which is what the plan is applied in: the lowest target address
    # gets the plain binding and the other two join the group.
    assert [member["ieee_address"] for member in group["members"]] == [
        OLD_FIRMWARE_IEEE,
        SECOND_LIGHT_IEEE,
    ]
    assert len(bridge.bindings_of(AUX, 2)) == 5, "one reporting, two plain, two to the group"


async def test_every_target_of_a_one_to_many_rule_reads_back(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """A group binding has to expand back into the links that asked for it, or nothing else
    downstream can tell that the rule is done.
    """
    activate(coordinator, s8_rule(LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE))
    await plan_and_apply(coordinator, runner)

    assert bound(coordinator, AUX_IEEE, 2) == {
        (cluster, ieee)
        for cluster in (zp.GEN_ON_OFF, zp.GEN_LEVEL_CTRL)
        for ieee in (LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE)
    }


async def test_a_one_to_many_rule_planned_again_has_nothing_to_do(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    activate(coordinator, s8_rule(LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE))
    await plan_and_apply(coordinator, runner)

    assert (await coordinator.async_plan()).is_empty


async def test_editing_a_rule_to_drop_a_target_leaves_that_target_in_the_group(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """Open item T11, seen for the first time through a Zigbee group, and worth pinning.

    Ownership is derived from the profile as it compiles now, not from a record written
    when a link was applied, so a rule edited to point somewhere else stops claiming what
    it used to write. Those links become unmanaged: reported rather than removed, which is
    the safe half, and orphaned, which is the other half. On Zigbee the orphan is a member
    of a managed group rather than a lone binding, so the group's membership goes stale in
    a way nothing plans to correct. See docs/open-items.md T11 and T44.
    """
    activate(coordinator, s8_rule(LIGHT_IEEE, SECOND_LIGHT_IEEE, OLD_FIRMWARE_IEEE))
    await plan_and_apply(coordinator, runner)

    activate(coordinator, s8_rule(LIGHT_IEEE, SECOND_LIGHT_IEEE))
    plan = await coordinator.async_plan()

    assert plan.is_empty, "the dropped target is unmanaged now, and unmanaged is never removed"
    group = bridge.group_named("dl_s8")
    assert group is not None
    assert OLD_FIRMWARE_IEEE in [member["ieee_address"] for member in group["members"]]
    assert any(
        link.target.handle.protocol_id == OLD_FIRMWARE_IEEE and link.managed_by is None
        for link in links_of(coordinator, AUX_IEEE)
    )


async def test_disabling_a_one_to_many_rule_takes_the_group_away_with_it(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """Nothing is left on the bridge for a rule that no longer drives anything."""
    activate(coordinator, s8_rule(LIGHT_IEEE, SECOND_LIGHT_IEEE))
    await plan_and_apply(coordinator, runner)

    activate(coordinator, s8_rule(LIGHT_IEEE, SECOND_LIGHT_IEEE).with_enabled(False))
    await plan_and_apply(coordinator, runner)

    assert bridge.group_named("dl_s8") is None
    assert [b["cluster"] for b in bridge.bindings_of(AUX, 2)] == ["manuSpecificInovelli"]


# --------------------------------------------------------------------------------------
# When half of it works
# --------------------------------------------------------------------------------------


async def test_a_partial_cluster_failure_is_a_failed_link_with_the_cluster_named(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """The bug this whole phase was warned about, seen from the top of the stack.

    The bridge says `ok` and lists the cluster in `failed`. If that read as success, the
    job would be green, the rule would be in sync, and the user would have a paddle that
    turns the light on and cannot dim it.
    """
    bridge.fail_clusters = {zp.GEN_LEVEL_CTRL}
    bridge.ok_despite_total_failure = True
    activate(coordinator, s8_rule())

    _, report = await plan_and_apply(coordinator, runner)

    assert report.status is JobStatus.PARTIAL
    failed = [result for result in report.results if result.outcome is LinkOutcome.FAILED]
    assert failed
    assert all(result.reason is not None for result in failed)
    assert {result.reason.translation_key for result in failed if result.reason} == {
        "zigbee_clusters_failed"
    }
    assert all(zp.GEN_LEVEL_CTRL in result.reason.placeholders["clusters"] for result in failed)


async def test_the_half_that_worked_is_applied_and_says_so(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    bridge.fail_clusters = {zp.GEN_LEVEL_CTRL}
    bridge.ok_despite_total_failure = True
    activate(coordinator, s8_rule())

    _, report = await plan_and_apply(coordinator, runner)

    assert LinkOutcome.APPLIED in {result.outcome for result in report.results}
    assert bound(coordinator, AUX_IEEE, 2) == {(zp.GEN_ON_OFF, LIGHT_IEEE)}


async def test_the_plan_converges_when_the_cluster_binds_on_the_retry(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """What makes "press apply again" a safe instruction rather than a hopeful one."""
    bridge.fail_clusters = {zp.GEN_LEVEL_CTRL}
    bridge.ok_despite_total_failure = True
    activate(coordinator, s8_rule())
    await plan_and_apply(coordinator, runner)

    bridge.fail_clusters = set()
    plan, report = await plan_and_apply(coordinator, runner)

    assert len(plan.items) == 2, "exactly the work that was left"
    assert report.status is JobStatus.COMPLETED
    assert (await coordinator.async_plan()).is_empty


# --------------------------------------------------------------------------------------
# The test the Backend protocol exists for
# --------------------------------------------------------------------------------------


async def test_a_mixed_profile_plans_and_applies_both_protocols_together(
    hass: HomeAssistant, both: DeviceLinksCoordinator, bridge: FakeBridge
) -> None:
    """One profile, one Z-Wave rule, one Zigbee rule, one plan, one apply.

    **This needed no change to `compiler.py`, `planner.py` or `coordinator.py`.** Those
    three were written for Z-Wave, before a second protocol existed, and the Zigbee backend
    arrived as a new module implementing `Backend` and nothing else. Every difference
    between the protocols is expressed in what the adapter reports: a cluster where Z-Wave
    reports a group number, an endpoint where Z-Wave reports a node, two features on one
    cluster where Z-Wave gives each its own group. The core never asks which it is holding.
    """
    runner = JobRunner(both, sleep=_no_sleep)
    activate(both, zwave_rule(), s8_rule())

    plan, report = await plan_and_apply(both, runner)

    backends = {item.device_identity.split(":")[0] for item in plan.items}
    assert backends == {"zwave", "zigbee2mqtt"}
    assert report.status is JobStatus.COMPLETED
    assert bound(both, AUX_IEEE, 2) == {
        (zp.GEN_ON_OFF, LIGHT_IEEE),
        (zp.GEN_LEVEL_CTRL, LIGHT_IEEE),
    }
    zwave_device = both.observed_for(handle(CONTROLLER))
    assert zwave_device is not None
    assert {link.emitter_group for link in zwave_device.links if not link.is_system} == {
        "2",
        "3",
        "4",
    }


async def test_a_mixed_profile_planned_again_has_nothing_to_do(
    both: DeviceLinksCoordinator,
) -> None:
    runner = JobRunner(both, sleep=_no_sleep)
    activate(both, zwave_rule(), s8_rule())
    await plan_and_apply(both, runner)

    assert (await both.async_plan()).is_empty


async def test_one_protocol_can_be_applied_without_touching_the_other(
    both: DeviceLinksCoordinator, bridge: FakeBridge
) -> None:
    """A scope is about devices and rules, not about protocols, and that is the point."""
    runner = JobRunner(both, sleep=_no_sleep)
    activate(both, zwave_rule(), s8_rule())

    scope = PlanScope(rule_ids=frozenset({"s8"}))
    plan, report = await plan_and_apply(both, runner, scope=scope)

    assert {item.device_identity.split(":")[0] for item in plan.items} == {"zigbee2mqtt"}
    assert report.status is JobStatus.COMPLETED
    zwave_device = both.observed_for(handle(CONTROLLER))
    assert zwave_device is not None
    assert all(link.is_system for link in zwave_device.links)


async def test_one_backend_falling_over_leaves_the_other_working(
    both: DeviceLinksCoordinator, bridge: FakeBridge
) -> None:
    """E1 and E26 together. Half a house being unreachable does not make the other half
    unknowable, and nothing is planned for the half that cannot be seen.
    """
    runner = JobRunner(both, sleep=_no_sleep)
    activate(both, zwave_rule(), s8_rule())
    bridge.go_offline()

    await both.async_refresh()
    plan, report = await plan_and_apply(both, runner)

    assert both.backend_availability == {
        BackendId.ZWAVE: True,
        BackendId.ZIGBEE2MQTT: False,
    }
    assert {item.device_identity.split(":")[0] for item in plan.items} == {"zwave"}
    assert report.status is JobStatus.COMPLETED


# --------------------------------------------------------------------------------------
# The two places core used to speak Z-Wave at a Zigbee device
# --------------------------------------------------------------------------------------


async def test_a_two_way_zigbee_rule_drives_both_ways(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """Open item T48, closed: the canonical two-Inovelli-Blue 3-way, end to end.

    **This test used to assert the opposite**, and saying what it asserted is the point of
    keeping it. It pinned the broken behaviour: `compiler._compile_reverse` wrote the reverse
    leg from `writer_endpoint=0` and targeted `rule.source.endpoint`, which are Z-Wave shapes.
    Endpoint 0 is the Z-Wave root and is nothing at all on a Zigbee device (the paddle is
    endpoint 2), and the source's paddle endpoint serves no bindable cluster (the load is
    endpoint 1). So every reverse leg was refused at apply time with `zigbee_source_cannot_send`
    while the compiler reported neither a warning nor an error: the plan looked clean and
    never converged. The panel defaults `virtual_3way` to two-way, so that was the ordinary
    case rather than an exotic one.

    What changed is the shared capability model rather than anything Zigbee-shaped in core.
    A control now says which endpoint it drives from (`Emitter.endpoint`) and a device says
    which endpoint a link lands on (`DeviceCapabilities.receiving_endpoint`). Z-Wave answers
    0 and None, which is exactly what the compiler used to assume for everybody.
    """
    two_way = replace(s8_rule(), template=Template.VIRTUAL_3WAY, direction=Direction.TWO_WAY)
    activate(coordinator, two_way)

    compiled = coordinator.compiled_for("s8")
    _, report = await plan_and_apply(coordinator, runner)

    assert compiled is not None
    assert compiled.warnings == ()
    assert compiled.errors == ()
    assert not [link for link in compiled.links if link.source_endpoint == 0]
    # The forward leg drives from the aux paddle onto the light's load, and the reverse leg
    # drives from the light's paddle onto the aux's load. Both ends of both legs are the
    # endpoints the hardware actually has.
    assert {
        (link.source.protocol_id, link.source_endpoint, link.target.endpoint)
        for link in compiled.links
    } == {(AUX_IEEE, 2, 1), (LIGHT_IEEE, 2, 1)}
    assert report.status is JobStatus.COMPLETED
    assert not [r for r in report.results if r.outcome is LinkOutcome.BLOCKED]
    assert bound(coordinator, LIGHT_IEEE, 2) == {
        (zp.GEN_ON_OFF, AUX_IEEE),
        (zp.GEN_LEVEL_CTRL, AUX_IEEE),
    }
    assert [b["cluster"] for b in bridge.bindings_of(LIGHT, 2)] == [
        "manuSpecificInovelli",
        zp.GEN_LEVEL_CTRL,
        zp.GEN_ON_OFF,
    ]


async def test_a_two_way_zigbee_rule_planned_again_has_nothing_to_do(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """The half of T48 that mattered most: a two-way Zigbee plan converges."""
    two_way = replace(s8_rule(), template=Template.VIRTUAL_3WAY, direction=Direction.TWO_WAY)
    activate(coordinator, two_way)
    await plan_and_apply(coordinator, runner)

    assert (await coordinator.async_plan()).is_empty


async def test_a_coordinator_binding_on_a_rule_s_own_cluster_leaves_that_rule_alone(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """Open item T49, closed: one system binding no longer condemns the whole cluster.

    **This test used to assert the opposite**, and saying what it asserted is the point of
    keeping it. It pinned `JobRunner._is_system` refusing every link on an endpoint's cluster
    because one binding in that cluster targeted the coordinator, and it asserted both the
    resulting `system_link_protected` and the plan that could never converge. That is a
    Z-Wave truth read onto Zigbee: a lifeline group holds the controller and nothing else may
    go into it, while one endpoint's cluster holds many independent bindings side by side.
    Zigbee2MQTT puts a reporting binding on exactly the endpoint and cluster a button's
    presses come from, so the first Zigbee remote added to this network would have had every
    rule from it refused with no way out from the UI.

    Each backend now says which of the two its `is_system` mark means
    (`backends.base.SystemScope`), so Z-Wave keeps refusing a lifeline group wholesale and
    Zigbee protects the individual coordinator binding and nothing beside it.
    """
    bridge.add_binding(
        AUX,
        2,
        zp.GEN_ON_OFF,
        {"type": "endpoint", "ieee_address": COORDINATOR_IEEE, "endpoint": 1},
    )
    await coordinator.async_refresh()
    activate(coordinator, s8_rule())

    _, report = await plan_and_apply(coordinator, runner)

    assert report.status is JobStatus.COMPLETED
    assert not [r for r in report.results if r.outcome is LinkOutcome.BLOCKED]
    assert (await coordinator.async_plan()).is_empty
    assert bound(coordinator, AUX_IEEE, 2) == {
        (zp.GEN_ON_OFF, LIGHT_IEEE),
        (zp.GEN_LEVEL_CTRL, LIGHT_IEEE),
    }
    # And the binding that provoked all this is untouched, still the bridge's own.
    assert any(
        link.is_system
        and link.source_endpoint == 2
        and link.emitter_group == zp.GEN_ON_OFF
        and link.target.handle.protocol_id == COORDINATOR_IEEE
        for link in links_of(coordinator, AUX_IEEE)
    )


async def test_the_bridge_s_own_binding_is_still_never_offered_for_removal(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, bridge: FakeBridge
) -> None:
    """The other half of T49: narrowing the guard took nothing off the coordinator.

    A hand-built plan removing the reporting binding a rule's own cluster shares is refused
    here, by the entry's own `is_system`, before anything reaches the bridge.
    """
    bridge.add_binding(
        AUX,
        2,
        zp.GEN_ON_OFF,
        {"type": "endpoint", "ieee_address": COORDINATOR_IEEE, "endpoint": 1},
    )
    await coordinator.async_refresh()
    activate(coordinator, s8_rule())
    reporting = next(
        link
        for link in links_of(coordinator, AUX_IEEE)
        if link.is_system and link.emitter_group == zp.GEN_ON_OFF
    )

    report = await runner.async_apply(
        Plan(
            token="hand-built",
            items=(
                PlanItem(
                    op=PlanOp.REMOVE,
                    device_identity=reporting.source.identity,
                    link=reporting,
                ),
            ),
            unmanaged=(),
            unchanged_count=0,
        )
    )

    assert [result.outcome for result in report.results] == [LinkOutcome.BLOCKED]
    assert [r.reason.translation_key for r in report.results if r.reason] == [
        "system_link_protected"
    ]
    assert bridge.write_count == 0
