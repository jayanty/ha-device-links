"""The job runner: what reaches a radio, in what order, and what never reaches one twice.

This file is about scheduling, and scheduling is where an executor can hurt a working home
rather than merely disappoint its owner. Four of these tests are load-bearing:

- **Per-device serialization.** A Z-Wave mesh handles one command per node at a time. Two
  overlapping writes to one node produce timeouts that look exactly like a faulty device,
  and the owner goes hunting for hardware that is fine.
- **A blocked result is never retried.** A refusal cannot succeed on a second attempt, so a
  retry spends mesh airtime to be told the same thing again.
- **Cancel really stops.** A cancel that keeps scheduling leaves a half-applied plan and an
  owner who cannot tell what state their house is in.
- **A lifeline is never removed**, whatever a hand-built plan says. That guard exists in the
  planner and in the coordinator too; this is the third one, on the last path before a write.

The concurrency assertions are made without any real sleeping, and deliberately so. A test
that proves ordering by waiting on the clock is slow, is flaky on a loaded machine, and
proves less: it can only say "this took at least a second". Two devices are used instead.

`RecordingBackend` yields to the event loop several times inside every write, so a write is
genuinely open across scheduler turns and a second write to the same device would be
admitted if the runner allowed one. It records the device of every write that was open at
that moment, so `overlapped` is direct evidence rather than an inference from timing, and
`peak` is the real high-water mark of devices in flight.

The backoff delays are asserted by injecting the sleeper the runner waits with. What that
proves is that the runner computes 1 s and then 2 s and waits between attempts; it
deliberately does not attempt to prove that `asyncio.sleep` sleeps. The default is the real
`asyncio.sleep`, so the substitution is at the seam and not in the code under test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.coordinator import DeviceLinksCoordinator, PlanScope
from custom_components.device_links.executor import (
    JobRunner,
    JobRunningError,
    JobStatus,
    LinkOutcome,
)
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    Diagnostic,
    Feature,
    Link,
    LinkTarget,
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
from tests.factories import handle, profiles
from tests.fakes.backend import RecordingBackend
from tests.fakes.zwave import FakeDriver, build_driver_from_fixture

TEST_DEBOUNCE = 0.05


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


@pytest.fixture
def sleeps() -> list[float]:
    """Every delay the runner waited for, in order, without any of them being waited."""
    return []


@pytest.fixture
def make_runner(
    coordinator: DeviceLinksCoordinator, sleeps: list[float]
) -> Callable[..., JobRunner]:
    async def _sleep(delay: float) -> None:
        sleeps.append(delay)

    def _make(**kwargs: Any) -> JobRunner:
        return JobRunner(coordinator, sleep=_sleep, **kwargs)

    return _make


@pytest.fixture
def runner(make_runner: Callable[..., JobRunner]) -> JobRunner:
    return make_runner()


def remote_rule(
    rule_id: str,
    *,
    source: int = 36,
    emitter: str = "g2",
    target: int = 37,
    features: frozenset[Feature] = frozenset({Feature.ON_OFF}),
) -> Rule:
    """Return one rule: this control on this device drives that light."""
    return Rule(
        id=rule_id,
        name=f"Rule {rule_id}",
        template=Template.REMOTE,
        backend=BackendId.ZWAVE,
        source=RuleSource(device=handle(source), endpoint=0, emitter_id=emitter),
        targets=(RuleTarget(device=handle(target), endpoint=None),),
        features=features,
    )


def activate(coordinator: DeviceLinksCoordinator, *rules: Rule) -> None:
    """Make a profile of these rules the active one, as a profile edit would."""
    profile = Profile(id="profile-1", name="Bedroom", rules=rules)
    coordinator.async_update_state(StoredState(profiles=(profile,), active_profile_id=profile.id))


def three_adds_across_two_devices(coordinator: DeviceLinksCoordinator) -> None:
    """Two links off node 36 and one off node 39, which is two radio conversations."""
    activate(
        coordinator,
        remote_rule("rule-1", features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET})),
        remote_rule("rule-2", source=39, target=38),
    )


def links_of(coordinator: DeviceLinksCoordinator, node_id: int) -> tuple[ObservedLink, ...]:
    device = coordinator.observed_for(handle(node_id))
    assert device is not None
    return device.links


def outcomes(report: Any) -> list[LinkOutcome]:
    return [result.outcome for result in report.results]


# What a job does.


async def test_a_plan_of_three_adds_across_two_devices_applies_all_three(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()

    report = await runner.async_apply(plan)

    assert report.status is JobStatus.COMPLETED
    assert outcomes(report) == [LinkOutcome.APPLIED] * 3
    assert {result.fingerprint for result in report.results} == {
        item.link.fingerprint for item in plan.items if item.link is not None
    }
    assert len(links_of(coordinator, 36)) == 3  # the lifeline plus the two new links
    assert len(links_of(coordinator, 39)) == 2


async def test_an_empty_plan_is_a_completed_job_that_touches_nothing(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """Apply on a network already in the state it should be in must not be a radio event.

    Nor a snapshot: twenty presses of Apply on a converged network would otherwise push
    out every snapshot that was worth keeping, which is the history a rollback needs.
    """
    plan = await coordinator.async_plan()

    report = await runner.async_apply(plan)

    assert report.status is JobStatus.COMPLETED
    assert report.results == ()
    assert backend.writes == []
    assert report.snapshot_id is None
    assert coordinator.state.snapshots == ()


# Scheduling.


async def test_two_writes_to_one_device_are_never_in_flight_together(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """A mesh handles one command per node at a time (Stage 0, and every Z-Wave document).

    Overlapping writes to one node time out in a way that looks exactly like a broken
    device, and the owner spends an evening on hardware that is fine. The three links here
    are on one device on purpose, and `RecordingBackend` keeps each write open across
    several scheduler turns, so a runner that fanned out per link rather than per device
    would be caught here rather than on somebody's mesh.
    """
    activate(
        coordinator,
        remote_rule(
            "rule-1",
            features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD}),
        ),
    )
    plan = await coordinator.async_plan()

    await runner.async_apply(plan)

    assert len(backend.writes) == 3
    assert backend.overlapped == []
    assert backend.peak == 1


@pytest.mark.parametrize("limit", [1, 2, 3])
async def test_at_most_the_configured_number_of_devices_are_worked_at_once(
    coordinator: DeviceLinksCoordinator,
    make_runner: Callable[..., JobRunner],
    backend: RecordingBackend,
    limit: int,
) -> None:
    """The cap is a real cap and not an accident of there being nothing to overlap.

    Three devices, three settings of the limit, and the observed peak equal to the limit
    every time. Asserting only `peak <= limit` would pass on a runner that was accidentally
    serial, which is why the equality is asserted instead.
    """
    activate(
        coordinator,
        remote_rule("rule-1", source=36, target=37),
        remote_rule("rule-2", source=39, target=38),
        remote_rule("rule-3", source=30, target=35),
    )
    plan = await coordinator.async_plan()
    runner = make_runner(max_concurrent_devices=limit)

    await runner.async_apply(plan)

    assert backend.peak == limit
    assert backend.overlapped == []


# Retries.


async def test_a_failed_write_is_retried_twice_with_increasing_backoff(
    coordinator: DeviceLinksCoordinator,
    runner: JobRunner,
    backend: RecordingBackend,
    sleeps: list[float],
) -> None:
    """E13: three attempts in all, one second then two, and then `failed`.

    The delays come from the sleeper the runner was given, so this asserts what the runner
    decided to wait for rather than what a clock did. Unbounded retries are the failure
    this bounds: a mesh being hammered by a node that cannot answer is a mesh that stops
    answering for everything else too.
    """
    activate(coordinator, remote_rule("rule-1"))
    plan = await coordinator.async_plan()
    fingerprint = plan.items[0].link.fingerprint
    backend.fail_times[fingerprint] = 99

    report = await runner.async_apply(plan)

    assert backend.attempts[fingerprint] == 3
    assert sleeps == [1.0, 2.0]
    assert outcomes(report) == [LinkOutcome.FAILED]
    assert report.status is JobStatus.PARTIAL
    assert report.results[0].attempts == 3
    assert report.results[0].raw_error == "ZW0201: transmit failed"


async def test_a_write_that_succeeds_on_the_second_attempt_is_applied(
    coordinator: DeviceLinksCoordinator,
    runner: JobRunner,
    backend: RecordingBackend,
    sleeps: list[float],
) -> None:
    activate(coordinator, remote_rule("rule-1"))
    plan = await coordinator.async_plan()
    backend.fail_times[plan.items[0].link.fingerprint] = 1

    report = await runner.async_apply(plan)

    assert sleeps == [1.0]
    assert outcomes(report) == [LinkOutcome.APPLIED]
    assert report.results[0].attempts == 2


async def test_a_blocked_result_is_never_retried(
    coordinator: DeviceLinksCoordinator,
    runner: JobRunner,
    backend: RecordingBackend,
    sleeps: list[float],
) -> None:
    """A refusal cannot succeed on a second attempt, so a retry is airtime spent on nothing.

    Worse than wasteful: the mesh is shared, so time spent being told "no" three times is
    time a light somebody is standing at is not responding in.
    """
    activate(coordinator, remote_rule("rule-1"))
    plan = await coordinator.async_plan()
    fingerprint = plan.items[0].link.fingerprint
    backend.block.add(fingerprint)

    report = await runner.async_apply(plan)

    assert backend.attempts[fingerprint] == 1
    assert sleeps == []
    assert outcomes(report) == [LinkOutcome.BLOCKED]
    assert report.results[0].reason is not None


async def test_an_operation_that_never_answers_times_out_and_is_reported_failed(
    coordinator: DeviceLinksCoordinator,
    make_runner: Callable[..., JobRunner],
    backend: RecordingBackend,
) -> None:
    """A write that hangs must not hang the job. Stage 0 measured 67 ms and 253 ms."""
    activate(coordinator, remote_rule("rule-1"))
    plan = await coordinator.async_plan()
    backend.hang.add(plan.items[0].link.fingerprint)
    runner = make_runner(operation_timeout_seconds=0.01)

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.FAILED]
    assert report.results[0].attempts == 3


async def test_a_backend_that_raises_is_a_failed_link_and_not_a_failed_job(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """Every link owes the user a result. A traceback out of the runner is not one."""
    activate(
        coordinator,
        remote_rule("rule-1", features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET})),
    )
    plan = await coordinator.async_plan()
    backend.raise_on.add(plan.items[0].link.fingerprint)

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.FAILED, LinkOutcome.APPLIED]
    assert report.results[0].raw_error is not None


# Cancel and shutdown.


async def test_cancel_stops_scheduling_and_reports_the_rest_as_cancelled(
    coordinator: DeviceLinksCoordinator,
    make_runner: Callable[..., JobRunner],
    backend: RecordingBackend,
) -> None:
    """A cancel that only sets a flag leaves a half-applied plan nobody can reason about.

    The cancel is raised from inside the first write, which is the moment that matters: one
    operation is in flight and cannot be un-sent, and everything after it must not start.
    With one device worked at a time, "nothing new started" is exactly one write.
    """
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()
    runner = make_runner(max_concurrent_devices=1)

    async def _cancel_once(link: Link) -> None:
        backend.before_write = None
        runner.async_cancel()

    backend.before_write = _cancel_once

    report = await runner.async_apply(plan)

    assert len(backend.writes) == 1
    assert report.status is JobStatus.CANCELLED
    assert outcomes(report).count(LinkOutcome.CANCELLED) == 2
    assert LinkOutcome.APPLIED in outcomes(report)


async def test_an_operation_already_in_flight_when_cancel_arrives_still_reports_its_outcome(
    coordinator: DeviceLinksCoordinator,
    make_runner: Callable[..., JobRunner],
    backend: RecordingBackend,
) -> None:
    """A radio write that has been sent cannot be un-sent, so it is reported, not erased.

    `cancelled` in a job summary means "not attempted, nothing reached this device". An
    operation that was in flight gets its real outcome, verified like any other, because
    telling somebody an operation was cancelled when it was actually performed is how a
    house ends up in a state its owner has been told it is not in.
    """
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()
    runner = make_runner(max_concurrent_devices=1)

    async def _cancel_once(link: Link) -> None:
        backend.before_write = None
        runner.async_cancel()

    backend.before_write = _cancel_once
    report = await runner.async_apply(plan)

    applied = [result for result in report.results if result.outcome is LinkOutcome.APPLIED]

    assert len(applied) == 1
    assert applied[0].fingerprint == backend.writes[0]
    assert applied[0].verified_at is not None


async def test_a_job_interrupted_by_shutdown_is_marked_interrupted_and_not_resumed(
    coordinator: DeviceLinksCoordinator,
    make_runner: Callable[..., JobRunner],
    backend: RecordingBackend,
) -> None:
    """E17: an unload during an apply stops, says so, and never picks itself back up.

    Auto-resuming would apply a plan against a network nobody has looked at since, which is
    exactly the situation the plan token exists to refuse. Re-running apply is safe because
    the plan is recomputed from a fresh read.
    """
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()
    runner = make_runner(max_concurrent_devices=1)
    started = asyncio.Event()

    async def _note(link: Link) -> None:
        started.set()

    backend.before_write = _note
    task = asyncio.create_task(runner.async_apply(plan))
    await started.wait()
    await runner.async_shutdown()
    report = await task

    assert report.status is JobStatus.INTERRUPTED
    assert LinkOutcome.INTERRUPTED in outcomes(report)
    assert runner.progress is None
    assert coordinator.state.jobs[-1].status == "interrupted"


async def test_shutting_down_with_no_job_running_does_nothing(runner: JobRunner) -> None:
    await runner.async_shutdown()

    assert runner.progress is None


async def test_cancelling_with_no_job_running_does_nothing(runner: JobRunner) -> None:
    runner.async_cancel()

    assert runner.progress is None


# The job lock and the plan token.


async def test_a_second_apply_while_one_is_running_is_rejected(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """E16: the panel and an automation both pressing apply must not both write."""
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()
    started = asyncio.Event()

    async def _note(link: Link) -> None:
        started.set()

    backend.before_write = _note
    task = asyncio.create_task(runner.async_apply(plan))
    await started.wait()

    with pytest.raises(JobRunningError):
        await runner.async_apply(plan)

    report = await task

    assert report.status is JobStatus.COMPLETED


async def test_a_device_whose_state_changed_since_the_plan_is_skipped_as_stale(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """E15: one device's plan is out of date, so that device is skipped and the rest run.

    The whole job is not refused, because the other device's work is still exactly what the
    user looked at and approved. What is refused is writing to a device whose state is no
    longer the state the plan was computed from.
    """
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()
    await apply_by_hand(driver, source=36, group=2, target=37)

    report = await runner.async_apply(plan)

    stale = [result for result in report.results if result.outcome is LinkOutcome.STALE_PLAN]
    applied = [result for result in report.results if result.outcome is LinkOutcome.APPLIED]

    assert {result.device_identity for result in stale} == {handle(36).identity}
    assert {result.device_identity for result in applied} == {handle(39).identity}
    assert report.status is JobStatus.PARTIAL


async def test_a_device_that_stopped_answering_between_plan_and_apply_is_not_written_to(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """A device we cannot see is a device whose plan we cannot trust (E1 and E15 together)."""
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()
    backend.unavailable.add(handle(36).identity)

    report = await runner.async_apply(plan)

    skipped = [result for result in report.results if result.outcome is LinkOutcome.STALE_PLAN]

    written = {result.fingerprint for result in report.results} & set(backend.writes)

    assert {result.device_identity for result in skipped} == {handle(36).identity}
    assert all(result.reason is not None for result in skipped)
    assert written == {
        result.fingerprint
        for result in report.results
        if result.device_identity == handle(39).identity
    }


async def apply_by_hand(driver: FakeDriver, *, source: int, group: int, target: int) -> None:
    """Put an association on a device the way somebody using Z-Wave JS UI would."""
    from zwave_js_server.model.association import AssociationAddress  # noqa: PLC0415

    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=source),
        group,
        [AssociationAddress(controller, node_id=target)],
    )


# Refusals that never reach a radio.


async def test_a_lifeline_is_refused_even_when_a_hand_built_plan_asks_for_its_removal(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """CLAUDE.md Section 3 rule 4, guarded a third time on the last path before a write.

    The planner never emits this item and the coordinator never marks a lifeline as ours,
    so reaching here means something upstream is already wrong. A guard that only exists
    where the mistake is not is not a guard.
    """
    lifeline = next(link for link in links_of(coordinator, 36) if link.is_system)
    plan = Plan(
        token="hand-built",
        items=(
            PlanItem(op=PlanOp.REMOVE, device_identity=lifeline.source.identity, link=lifeline),
        ),
        unmanaged=(),
        unchanged_count=0,
    )

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.BLOCKED]
    assert backend.writes == []
    assert any(link.is_system for link in links_of(coordinator, 36))


async def test_an_item_no_backend_is_loaded_for_is_blocked_rather_than_attempted(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """Zigbee arrives in Phase 2. A Zigbee item today is refused, not a traceback."""
    zigbee = replace(handle(36), backend=BackendId.ZIGBEE2MQTT)
    link = Link(
        backend=BackendId.ZIGBEE2MQTT,
        source=zigbee,
        source_endpoint=0,
        emitter_id="g2",
        target=LinkTarget(handle=handle(37), endpoint=None),
        feature=Feature.ON_OFF,
    )
    plan = Plan(
        token="hand-built",
        items=(PlanItem(op=PlanOp.ADD, device_identity=zigbee.identity, link=link),),
        unmanaged=(),
        unchanged_count=0,
    )

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.BLOCKED]


async def test_a_plan_item_the_planner_already_blocked_is_reported_and_never_attempted(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """A group that was full when the plan was built is still full now, for the same reason.

    The reason travels with the item rather than being invented again here: the planner
    knows why it refused, and re-deriving it at apply time is how two explanations of the
    same refusal end up disagreeing.
    """
    activate(coordinator, remote_rule("rule-1"))
    planned = await coordinator.async_plan()
    reason = Diagnostic("group_full", {"group": "2"})
    plan = replace(
        planned,
        items=(replace(planned.items[0], op=PlanOp.BLOCKED, reason=reason),),
    )

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.BLOCKED]
    assert report.results[0].reason == reason
    assert backend.writes == []


async def test_an_operation_this_version_cannot_perform_is_blocked_rather_than_ignored(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """Nothing produces a setting write yet (open items T2 and T15).

    Dropping the item silently would make a scoped apply quietly skip the device setting a
    rule asked for, which nobody notices until the hold-to-dim they configured does nothing.
    """
    plan = Plan(
        token="hand-built",
        items=(PlanItem(op=PlanOp.SET_PARAM, device_identity=handle(36).identity),),
        unmanaged=(),
        unchanged_count=0,
    )

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.BLOCKED]
    assert report.results[0].fingerprint == ""


# What is recorded.


async def test_the_job_summary_records_every_link_and_is_persisted(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """FR-A2: what happened to each link, kept where a support request can read it back."""
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()

    report = await runner.async_apply(plan)
    summary = coordinator.state.jobs[-1]

    assert summary.id == report.id
    assert summary.status == JobStatus.COMPLETED
    assert summary.scope == "all"
    assert {result.fingerprint for result in summary.results} == {
        result.fingerprint for result in report.results
    }
    assert {result.status for result in summary.results} == {LinkOutcome.APPLIED}


async def test_the_scope_a_job_ran_with_is_recorded(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """Which rule did this is the first question anybody asks of a job history."""
    three_adds_across_two_devices(coordinator)
    scope = PlanScope(rule_ids=frozenset({"rule-2"}))
    plan = await coordinator.async_plan(scope)

    report = await runner.async_apply(plan, scope=scope)

    assert report.scope == "rules:rule-2"
    assert len(report.results) == 1


async def test_progress_is_readable_while_a_job_is_running(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """Phase 1D streams this to the panel. Today it is enough that it is true while running."""
    three_adds_across_two_devices(coordinator)
    plan = await coordinator.async_plan()
    seen: list[Any] = []

    async def _note(link: Link) -> None:
        seen.append(runner.progress)

    backend.before_write = _note
    report = await runner.async_apply(plan)

    assert runner.progress is None
    assert [progress.id for progress in seen] == [report.id] * 3
    assert seen[0].total == 3
    assert seen[0].completed == 0
    assert max(progress.completed for progress in seen) > 0


async def test_applying_a_rule_records_it_as_applied_so_drift_can_be_reported(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """FR-A5: drift is measured from the last successful apply, so the apply has to be noted."""
    activate(coordinator, remote_rule("rule-1"))
    plan = await coordinator.async_plan()

    await runner.async_apply(plan)

    assert coordinator.state.applied_rule_ids == frozenset({"rule-1"})


async def test_a_cancel_during_a_backoff_stops_the_retry_and_keeps_the_failure(
    coordinator: DeviceLinksCoordinator,
    runner: JobRunner,
    backend: RecordingBackend,
    sleeps: list[float],
) -> None:
    """Stopping mid-retry reports what really happened, not "cancelled".

    The write was attempted and it failed. Reporting it as cancelled would tell the owner
    nothing reached the device, when something did and was refused by the mesh.
    """
    activate(coordinator, remote_rule("rule-1"))
    plan = await coordinator.async_plan()
    fingerprint = plan.items[0].link.fingerprint
    backend.fail_times[fingerprint] = 99

    async def _cancel_once(link: Link) -> None:
        backend.before_write = None
        runner.async_cancel()

    backend.before_write = _cancel_once
    report = await runner.async_apply(plan)

    assert backend.attempts[fingerprint] == 1
    assert sleeps == [1.0]
    assert outcomes(report) == [LinkOutcome.FAILED]
    assert report.status is JobStatus.CANCELLED


async def test_a_disabled_rule_s_links_are_removed(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """FR-R5: disabling is not deleting, and what it does mean is a removal that happens."""
    activate(coordinator, remote_rule("rule-1"))
    await runner.async_apply(await coordinator.async_plan())
    activate(coordinator, replace(remote_rule("rule-1"), enabled=False))
    plan = await coordinator.async_plan()

    report = await runner.async_apply(plan)

    assert [result.op for result in report.results] == [PlanOp.REMOVE]
    assert outcomes(report) == [LinkOutcome.APPLIED]
    assert [link.emitter_group for link in links_of(coordinator, 36)] == ["1"]


async def test_a_refused_item_does_not_stop_the_rest_of_that_device_s_work(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """One impossible item is one impossible item, not a device left half configured."""
    activate(coordinator, remote_rule("rule-1"))
    planned = await coordinator.async_plan()
    lifeline = next(link for link in links_of(coordinator, 36) if link.is_system)
    plan = replace(
        planned,
        items=(
            PlanItem(op=PlanOp.REMOVE, device_identity=lifeline.source.identity, link=lifeline),
            *planned.items,
        ),
    )

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.BLOCKED, LinkOutcome.APPLIED]
    assert len(backend.writes) == 1
    assert any(link.is_system for link in links_of(coordinator, 36))


async def test_a_refused_item_on_a_stale_device_keeps_its_own_answer(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """Two different reasons for not writing, and neither is allowed to overwrite the other.

    Skipping a device wholesale is a per-device answer, and it must not relabel an item
    that was already refused for a reason of its own: "the plan is out of date" would send
    the owner off to re-plan a lifeline removal that will never be performed at all.
    """
    activate(coordinator, remote_rule("rule-1"))
    planned = await coordinator.async_plan()
    lifeline = next(link for link in links_of(coordinator, 36) if link.is_system)
    plan = replace(
        planned,
        items=(
            PlanItem(op=PlanOp.REMOVE, device_identity=lifeline.source.identity, link=lifeline),
            *planned.items,
        ),
    )
    backend.unavailable.add(handle(36).identity)

    report = await runner.async_apply(plan)

    assert outcomes(report) == [LinkOutcome.BLOCKED, LinkOutcome.STALE_PLAN]
    assert report.results[0].reason is not None
    assert report.results[0].reason.translation_key == "system_link_protected"


def test_a_scope_of_devices_alone_is_described_by_its_devices() -> None:
    """A device-scoped apply is a real thing a user does from a device page."""
    from custom_components.device_links.executor import _describe  # noqa: PLC0415

    assert _describe(PlanScope(device_identities=frozenset({"zwave:1:36"}))) == (
        "devices:zwave:1:36"
    )
    assert _describe(PlanScope()) == "all"
