"""The whole loop: compile, plan, apply, verify, re-plan. The first test of all of it.

Everything before this file tests one layer against the layer below it. This one drives
the bedroom that this integration was written for, end to end, against the Stage 0 fake of
Jayant's real network: two of the PRD's acceptance scenarios, expressed as the rules a user
would author, applied through the real Z-Wave adapter, and then checked by reading the
devices back and planning again.

Two of these assertions are the reason the file exists.

**A second plan is empty.** Convergence and idempotence in one line. A system that applies
successfully and then still wants to write something has either not done what it said or
cannot tell that it has, and either way pressing apply becomes a thing users do twice.

**An unmanaged link is reported and not removed, until it is picked out by hand.** That is
Decision D9 and it is the difference between an integration that tidies up and one that
deletes an association somebody made in Z-Wave JS UI years ago.

The last test is the ugly case: a write that fails halfway through a plan. What matters is
that the half that worked is applied and says so, the half that did not is reported as
failed and not as anything softer, the snapshot still holds what was there before any of
it, and planning again proposes exactly the work that is left. That last part is what makes
"just press apply again" a safe instruction rather than a hopeful one.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from zwave_js_server.exceptions import FailedZWaveCommand
from zwave_js_server.model.association import AssociationAddress

from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.coordinator import DeviceLinksCoordinator, RuleState
from custom_components.device_links.executor import JobRunner, JobStatus, LinkOutcome
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    Feature,
    Link,
    ObservedLink,
    Plan,
    PlanOp,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from custom_components.device_links.storage import DeviceLinksStore, StoredState
from tests.factories import handle, profiles
from tests.fakes.backend import RecordingBackend
from tests.fakes.zwave import FakeDriver, build_driver_from_fixture

TEST_DEBOUNCE = 0.05

# The bedroom, as PRD Section 15 names it. Node numbers rather than names in the code
# because the fixture is keyed by node id, and the names are here so the scenarios read.
CONTROLLER = 36  # Bedroom Scene Controller (Zooz ZEN35)
MAIN_LIGHTS = 37  # Master Bedroom Lights
LOBBY = 35  # Entrance Lobby Light
BEDSIDE_L = 38  # Bedside Light L
BEDSIDE_R = 39  # Bedside Light R

DIMMING = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})
PRESS_AND_HOLD = frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD})


@pytest.fixture(autouse=True)
def _use_storage(hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Keep every store in these tests in memory, so no test ever writes a real file."""
    return hass_storage


@pytest.fixture
def driver() -> FakeDriver:
    return build_driver_from_fixture()


@pytest.fixture
def backend(driver: FakeDriver) -> RecordingBackend:
    return RecordingBackend(ZWaveBackend(driver=driver, profiles=profiles(), debounce_seconds=0))


@pytest.fixture
async def coordinator(
    hass: HomeAssistant, backend: RecordingBackend
) -> AsyncGenerator[DeviceLinksCoordinator]:
    coordinator = DeviceLinksCoordinator(
        hass,
        backends={BackendId.ZWAVE: backend},
        store=DeviceLinksStore(hass),
        refresh_debounce_seconds=TEST_DEBOUNCE,
    )
    await coordinator.async_setup()
    yield coordinator
    await coordinator.async_shutdown()


async def _no_sleep(delay: float) -> None:
    """Stand in for the retry backoff, so a failing write costs three seconds of nothing."""
    return


@pytest.fixture
def runner(coordinator: DeviceLinksCoordinator) -> JobRunner:
    return JobRunner(coordinator, sleep=_no_sleep)


def a_rule(
    rule_id: str, name: str, template: Template, source: RuleSource, target: RuleTarget
) -> Rule:
    """Return one rule as a user would author it: one control, one target, one intent."""
    return Rule(
        id=rule_id,
        name=name,
        template=template,
        backend=BackendId.ZWAVE,
        source=source,
        targets=(target,),
        features=DIMMING if template is Template.REMOTE else PRESS_AND_HOLD,
    )


def s2_rules() -> tuple[Rule, ...]:
    """PRD scenario S2, as two rules: the button drives the light, the light reports back.

    Two rules rather than one two-way rule, because that is what S2 describes: adds for
    036 groups 2, 3 and 4 to 037, and 037's report group to 036. A two-way rule would put
    the reverse leg on every group the forward leg uses, which is more than was asked for.
    """
    return (
        a_rule(
            "s2-main",
            "036 main button controls Master Bedroom Lights",
            Template.REMOTE,
            RuleSource(device=handle(CONTROLLER), endpoint=0, emitter_id="g2"),
            RuleTarget(device=handle(MAIN_LIGHTS), endpoint=None),
        ),
        Rule(
            id="s2-status",
            name="Master Bedroom Lights reports back to 036",
            template=Template.STATUS_FEEDBACK,
            backend=BackendId.ZWAVE,
            source=RuleSource(device=handle(MAIN_LIGHTS), endpoint=0, emitter_id="paddle"),
            targets=(RuleTarget(device=handle(CONTROLLER), endpoint=None),),
            features=frozenset({Feature.ON_OFF}),
        ),
    )


def s3_rules() -> tuple[Rule, ...]:
    """PRD scenario S3: buttons 1, 3 and 4 of 036, with dim. Button 2 is left alone (D15)."""
    return tuple(
        a_rule(
            f"s3-button-{button}",
            f"Button {button} controls node {target}",
            Template.SCENE_BUTTON,
            RuleSource(device=handle(CONTROLLER), endpoint=0, emitter_id=emitter),
            RuleTarget(device=handle(target), endpoint=None),
        )
        for button, emitter, target in (
            (1, "g5", LOBBY),
            (3, "g9", BEDSIDE_L),
            (4, "g11", BEDSIDE_R),
        )
    )


def activate(coordinator: DeviceLinksCoordinator, *rules: Rule) -> None:
    """Make a profile of these rules the active one, as saving in the panel would."""
    profile = Profile(id="bedroom", name="Bedroom", rules=rules)
    coordinator.async_update_state(StoredState(profiles=(profile,), active_profile_id=profile.id))


def links_of(coordinator: DeviceLinksCoordinator, node_id: int) -> tuple[ObservedLink, ...]:
    device = coordinator.observed_for(handle(node_id))
    assert device is not None
    return device.links


def groups_of(coordinator: DeviceLinksCoordinator, node_id: int) -> dict[str, list[int]]:
    """Return what each association group of a node holds, as node ids.

    This is the shape a person reads in Z-Wave JS UI, which is the point: what the loop
    has to be judged against is what is on the device, not what our own types say.
    """
    groups: dict[str, list[int]] = {}
    for link in links_of(coordinator, node_id):
        groups.setdefault(link.emitter_group, []).append(_node_id(link))
    return {group: sorted(nodes) for group, nodes in sorted(groups.items())}


def _node_id(link: Link) -> int:
    return int(link.target.handle.protocol_id.split(":")[-1])


async def apply_by_hand(driver: FakeDriver, *, source: int, group: int, target: int) -> None:
    """Add an association the way somebody using Z-Wave JS UI would, with nothing of ours."""
    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=source),
        group,
        [AssociationAddress(controller, node_id=target)],
    )


async def plan_and_apply(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, **kwargs: Any
) -> tuple[Plan, Any]:
    """Do what pressing Plan and then Apply does, and return both halves."""
    plan = await coordinator.async_plan(**kwargs)
    return plan, await runner.async_apply(plan, **kwargs)


# S2.


async def test_s2_the_main_button_drives_the_light_and_the_light_reports_back(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """PRD S2, end to end: plan, apply, verify, and the device holds exactly this.

    The lifeline in group 1 is asserted alongside the new entries rather than filtered out,
    because "exactly these entries" has to include the one that was already there and must
    still be there afterwards. No configuration parameter is written either: S2 asks for
    none, and Decision D4 says a rule that did not ask about a setting does not touch it.
    """
    activate(coordinator, *s2_rules())

    plan, report = await plan_and_apply(coordinator, runner)

    assert [item.op for item in plan.items] == [PlanOp.ADD] * 4
    assert report.status is JobStatus.COMPLETED
    assert {result.outcome for result in report.results} == {LinkOutcome.APPLIED}
    assert all(result.verified_at is not None for result in report.results)
    assert groups_of(coordinator, CONTROLLER) == {
        "1": [1],
        "2": [MAIN_LIGHTS],
        "3": [MAIN_LIGHTS],
        "4": [MAIN_LIGHTS],
    }
    assert groups_of(coordinator, MAIN_LIGHTS) == {"1": [1], "2": [CONTROLLER]}
    assert driver.controller.written_parameters == {}
    assert coordinator.drift_state() == {
        "s2-main": RuleState.IN_SYNC,
        "s2-status": RuleState.IN_SYNC,
    }


async def test_s2_planning_again_after_a_successful_apply_proposes_nothing(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """Convergence and idempotence, end to end. Applying twice must not write twice."""
    activate(coordinator, *s2_rules())
    await plan_and_apply(coordinator, runner)

    again = await coordinator.async_plan()

    assert again.is_empty
    assert again.unmanaged == ()
    assert again.unchanged_count == 4


async def test_s2_applying_a_plan_that_is_already_satisfied_writes_nothing(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """The second press of Apply. Nothing to do is a job that does nothing to the mesh."""
    activate(coordinator, *s2_rules())
    await plan_and_apply(coordinator, runner)
    writes = len(backend.writes)

    _, report = await plan_and_apply(coordinator, runner)

    assert report.results == ()
    assert len(backend.writes) == writes
    assert len(coordinator.state.snapshots) == 1


# S3.


async def test_s3_three_scene_buttons_and_button_two_left_empty(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """PRD S3: the Pressed and Held pairs 5/6, 9/10 and 11/12, and nothing in 7/8.

    Button 2 being empty is Decision D15, and it is asserted as absence rather than assumed:
    the failure it guards against is a template that helpfully fills in every button on the
    device, which is exactly the kind of helpfulness nobody asked for.
    """
    activate(coordinator, *s3_rules())

    plan, report = await plan_and_apply(coordinator, runner)

    assert len(plan.items) == 6
    assert report.status is JobStatus.COMPLETED
    assert groups_of(coordinator, CONTROLLER) == {
        "1": [1],
        "5": [LOBBY],
        "6": [LOBBY],
        "9": [BEDSIDE_L],
        "10": [BEDSIDE_L],
        "11": [BEDSIDE_R],
        "12": [BEDSIDE_R],
    }
    assert (await coordinator.async_plan()).is_empty


# Disabling.


async def test_disabling_a_rule_plans_exactly_its_links_for_removal_and_nothing_else(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """FR-R5. Disabling is not deleting, and it is not a licence to tidy the device either.

    The other rule's links are on the same device and in adjacent groups, which is the
    situation where an over-broad removal would not be noticed until the light it belonged
    to stopped responding.
    """
    activate(coordinator, *s3_rules())
    await plan_and_apply(coordinator, runner)
    button_1, button_3, button_4 = s3_rules()
    activate(coordinator, replace(button_1, enabled=False), button_3, button_4)

    plan, report = await plan_and_apply(coordinator, runner)

    assert [item.op for item in plan.items] == [PlanOp.REMOVE, PlanOp.REMOVE]
    assert {_node_id(item.link) for item in plan.items if item.link is not None} == {LOBBY}
    assert report.status is JobStatus.COMPLETED
    assert groups_of(coordinator, CONTROLLER) == {
        "1": [1],
        "9": [BEDSIDE_L],
        "10": [BEDSIDE_L],
        "11": [BEDSIDE_R],
        "12": [BEDSIDE_R],
    }


# Somebody else's association.


async def test_an_unmanaged_link_is_reported_and_never_removed_by_default(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """Decision D9. Somebody made this by hand, and it is not ours to take off.

    It is in the same group as one of our own links, which is the case that matters: a
    removal decided by group rather than by fingerprint would take it with it.
    """
    activate(coordinator, *s2_rules())
    await plan_and_apply(coordinator, runner)
    await apply_by_hand(driver, source=CONTROLLER, group=2, target=BEDSIDE_L)
    await coordinator.async_refresh()

    plan = await coordinator.async_plan()

    assert plan.items == ()
    assert [_node_id(entry) for entry in plan.unmanaged] == [BEDSIDE_L]
    assert groups_of(coordinator, CONTROLLER)["2"] == sorted([MAIN_LIGHTS, BEDSIDE_L])


async def test_an_unmanaged_link_the_user_picked_out_by_hand_is_removed(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """The other half of D9: reported by default, removed on an explicit per-link decision."""
    activate(coordinator, *s2_rules())
    await plan_and_apply(coordinator, runner)
    await apply_by_hand(driver, source=CONTROLLER, group=2, target=BEDSIDE_L)
    await coordinator.async_refresh()
    foreign = (await coordinator.async_plan()).unmanaged[0]

    plan, report = await plan_and_apply(
        coordinator, runner, remove_unmanaged=frozenset({foreign.fingerprint})
    )

    assert [item.op for item in plan.items] == [PlanOp.REMOVE]
    assert report.status is JobStatus.COMPLETED
    assert groups_of(coordinator, CONTROLLER)["2"] == [MAIN_LIGHTS]


# The apply that goes wrong halfway.


async def test_a_write_that_fails_midway_leaves_a_state_a_second_apply_finishes(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """The ugly one, and the one that decides whether "press apply again" is safe advice.

    The mesh stops accepting writes after the first one. What must be true afterwards: the
    first link is really on the device and reported applied, the rest are reported failed
    rather than as anything softer, the snapshot still holds what was there before any of
    it, and a fresh plan proposes exactly the work that is left and nothing that was
    already done.
    """
    activate(coordinator, *s2_rules())
    before = {
        link.fingerprint
        for node_id in (CONTROLLER, MAIN_LIGHTS)
        for link in links_of(coordinator, node_id)
    }
    backend = coordinator.backend_for(handle(CONTROLLER))
    assert isinstance(backend, RecordingBackend)
    # One device at a time, so which write is the one that succeeds is decided by the plan
    # rather than by how many awaits happen to be on the path through the adapter.
    runner = JobRunner(coordinator, max_concurrent_devices=1, sleep=_no_sleep)

    async def _break_the_mesh(link: Link) -> None:
        backend.after_write = None
        driver.controller.raise_on_write = FailedZWaveCommand(
            "controller.add_associations", 100, "transmit failed"
        )

    backend.after_write = _break_the_mesh
    plan, report = await plan_and_apply(coordinator, runner)

    applied = [result for result in report.results if result.outcome is LinkOutcome.APPLIED]
    failed = [result for result in report.results if result.outcome is LinkOutcome.FAILED]

    assert report.status is JobStatus.PARTIAL
    assert len(applied) == 1
    assert len(failed) == len(plan.items) - 1
    assert all(result.raw_error is not None for result in failed)
    assert {link.fingerprint for link in coordinator.state.snapshots[-1].links} == before

    driver.controller.raise_on_write = None
    remaining = await coordinator.async_plan()

    assert {item.link.fingerprint for item in remaining.items if item.link is not None} == {
        result.fingerprint for result in failed
    }

    await runner.async_apply(remaining)

    assert (await coordinator.async_plan()).is_empty
    assert coordinator.drift_state() == {
        "s2-main": RuleState.IN_SYNC,
        "s2-status": RuleState.IN_SYNC,
    }
