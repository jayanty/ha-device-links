"""Verify after apply, and the snapshot taken before it. Sent is not the same as done.

The promise in the PRD is a verify from a fresh read, not from what we sent. That promise
is worth exactly as much as this file, because there are three ways to break it and each
one looks like success from the inside:

- Reporting the write's own answer as the verified state. The driver accepted the command;
  that is not the device holding the entry.
- Reading the cache the write just updated. Stage 0 confirmed the driver's cache reflects
  our own writes immediately, so a shallow verify agrees with itself no matter what the
  device did. That is why the re-read is deep.
- Treating "the device did not answer the refresh" as "the device confirmed it". Open item
  T10 says that may be the common case on real hardware rather than a rare one, which is
  precisely why it gets an outcome of its own instead of being folded into `applied`.

The snapshot is the other half. It is taken after the pre-apply read and before the first
write, so what it holds is what was really there, and it survives an apply that then fails,
which is the case it exists for: a rollback is wanted after something went wrong, not after
everything went right.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_links.backends.zwave import SKIPPED_ASLEEP, ZWaveBackend
from custom_components.device_links.coordinator import DeviceLinksCoordinator, RuleState
from custom_components.device_links.executor import (
    SNAPSHOT_REASON,
    JobRunner,
    JobStatus,
    LinkOutcome,
)
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceHandle,
    Feature,
    Link,
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
from custom_components.device_links.storage import (
    MAX_SNAPSHOTS,
    DeviceLinksStore,
    Snapshot,
    StoredState,
)
from tests.factories import handle, profiles
from tests.fakes.backend import RecordingBackend
from tests.fakes.zwave import FakeDriver, build_driver_from_fixture

TEST_DEBOUNCE = 0.05

# One test deliberately waits this out, so it is short. The others need a fake whose refresh
# lands immediately to land inside it, and that is a scheduling race on a loaded machine
# rather than a real wait, so there is an order of magnitude of headroom over the zero delay
# the fake actually takes. Both directions of flakiness are bounded: this is a quarter of a
# second of suite time at worst, and a machine slow enough to miss it would fail loudly
# rather than pass by accident.
TEST_DEEP_VERIFY_TIMEOUT = 0.25


@pytest.fixture(autouse=True)
def _use_storage(hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Keep every store in these tests in memory, so no test ever writes a real file."""
    return hass_storage


@pytest.fixture
def driver() -> FakeDriver:
    return build_driver_from_fixture()


@pytest.fixture
def backend(driver: FakeDriver) -> RecordingBackend:
    return RecordingBackend(
        ZWaveBackend(
            driver=driver,
            profiles=profiles(),
            debounce_seconds=0,
            deep_verify_timeout=TEST_DEEP_VERIFY_TIMEOUT,
        )
    )


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
def runner(coordinator: DeviceLinksCoordinator) -> JobRunner:
    async def _sleep(delay: float) -> None:
        return

    return JobRunner(coordinator, sleep=_sleep)


def remote_rule(
    rule_id: str = "rule-1",
    *,
    source: int = 36,
    emitter: str = "g2",
    target: int = 37,
    features: frozenset[Feature] = frozenset({Feature.ON_OFF}),
) -> Rule:
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
    profile = Profile(id="profile-1", name="Bedroom", rules=rules)
    coordinator.async_update_state(StoredState(profiles=(profile,), active_profile_id=profile.id))


def links_of(coordinator: DeviceLinksCoordinator, node_id: int) -> tuple[ObservedLink, ...]:
    device = coordinator.observed_for(handle(node_id))
    assert device is not None
    return device.links


async def rewrite(driver: FakeDriver, *, source: int, group: int, target: int) -> None:
    """Put an association on the device the way the mesh does when a write really lands.

    Used for the case a report cannot see: the write was reported as failed because the
    transmit acknowledgement was lost, and the entry is on the device all the same.
    """
    from zwave_js_server.model.association import AssociationAddress  # noqa: PLC0415

    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=source),
        group,
        [AssociationAddress(controller, node_id=target)],
    )


async def unwrite(driver: FakeDriver, *, source: int, group: int, target: int) -> None:
    """Take an association back off the device behind the executor's back.

    This is a write that the driver accepted and the device did not keep: a transmit that
    was acknowledged by a repeater and never reached the node, an entry a firmware quietly
    dropped. From here it is indistinguishable from either, which is the point.
    """
    from zwave_js_server.model.association import AssociationAddress  # noqa: PLC0415

    controller = driver.controller
    await controller.async_remove_associations(
        AssociationAddress(controller, node_id=source),
        group,
        [AssociationAddress(controller, node_id=target)],
    )


# Verify.


async def test_every_applied_link_is_verified_from_a_fresh_read(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """A deep read per device, and a `verified_at` only where the device confirmed."""
    activate(
        coordinator,
        remote_rule(features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET})),
    )
    plan = await coordinator.async_plan()

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.APPLIED] * 2
    assert all(result.verified_at is not None for result in report.results)
    assert backend.deep_reads == 1


async def test_the_verify_read_is_the_cache_the_rest_of_the_integration_answers_from(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """A job must not end with the coordinator's idea of a device out of date.

    The verify goes through the coordinator rather than round it, so proving the links are
    verified and proving the cache is current are the same read. If the runner kept its own
    private view instead, the panel and the radio would disagree at exactly the moment
    somebody is looking at both.
    """
    activate(coordinator, remote_rule())
    plan = await coordinator.async_plan()

    await runner.async_apply(plan)

    assert plan.items[0].link.fingerprint in {
        link.fingerprint for link in links_of(coordinator, 36)
    }
    assert (await coordinator.async_plan()).is_empty


async def test_a_link_that_was_written_but_is_not_there_is_drift_and_never_success(
    coordinator: DeviceLinksCoordinator,
    runner: JobRunner,
    driver: FakeDriver,
) -> None:
    """E14. This is the test that keeps the whole promise honest.

    The write was accepted. The entry is not on the device. Reporting that as applied is
    the single most misleading thing this integration could do, because everything the user
    is told afterwards (the rule is in sync, the switch entity is on, no Repairs issue)
    would be built on it. It is `unverified`, and the rule it belongs to is in drift.
    """
    activate(coordinator, remote_rule())
    plan = await coordinator.async_plan()

    async def _lose_it(link: Link) -> None:
        await unwrite(driver, source=36, group=2, target=37)

    backend = coordinator.backend_for(handle(36))
    assert isinstance(backend, RecordingBackend)
    backend.after_write = _lose_it

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.UNVERIFIED]
    assert report.results[0].verified_at is None
    assert report.status is JobStatus.PARTIAL
    assert coordinator.drift_state() == {"rule-1": RuleState.DRIFT}


async def test_a_deep_verify_that_could_not_confirm_is_neither_success_nor_failure(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """Open item T10, carried through instead of being papered over.

    The device did not report its associations back, so what was read is the driver's
    cache: the very thing the write updated, which agrees with the write whatever the
    device did. The entry is where it should be according to a source that cannot be
    contradicted, which is not the same as confirmed. On real hardware this may be the
    common case rather than a rare one, so it is reported as what it is and not as an
    error either.
    """
    activate(coordinator, remote_rule())
    plan = await coordinator.async_plan()
    driver.controller.refresh_never_lands = True

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.UNCONFIRMED]
    assert report.results[0].verified_at is None
    assert report.results[0].reason is not None
    assert report.results[0].reason.placeholders["why"] == "no_answer"


async def test_a_sleeping_node_stays_pending_wakeup_and_is_not_a_failure(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """A battery remote that has not woken up yet has not gone wrong (CLAUDE.md Section 10).

    Nothing here is evidence about real hardware: Stage 0 item Z4 was never approved, so
    what a queued write really does is unproven (open item J1, issue #5). What this pins is
    that the runner does not turn a queue into a failure and never claims a queued write
    was verified. The device is re-read like any other the job wrote to, and that costs no
    radio time here: the adapter sees a sleeping node and skips the refresh rather than
    asking it to confirm something it cannot answer.

    `completed` for a job that confirmed nothing is deliberate and is argued in
    `JobStatus`: a queued write to a battery device is the documented, expected answer, the
    link keeps `pending_wakeup` where anybody looking at the job can see it, and the rule is
    not recorded as applied, so it stays pending rather than reading as in sync.
    """
    activate(coordinator, remote_rule(source=40, emitter="buttons_1_2", target=39))
    plan = await coordinator.async_plan()

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.PENDING_WAKEUP]
    assert report.status is JobStatus.COMPLETED
    assert report.results[0].verified_at is None
    assert coordinator.state.applied_rule_ids == frozenset()


async def test_a_deep_verify_a_sleeping_node_is_asked_for_at_all_says_why_it_was_skipped(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """A node that fell asleep between the write and the verify still owes an answer.

    Not reachable through a plan today, because a write to a sleeping node comes back
    `pending_wakeup` and is never verified. It is reachable on hardware: a node awake long
    enough to take the write and asleep again by the verify, which is exactly what a
    battery remote does. What it must not produce is `applied`.
    """
    activate(coordinator, remote_rule())
    plan = await coordinator.async_plan()
    node = driver.controller.nodes[36]

    async def _fall_asleep(link: Link) -> None:
        from zwave_js_server.const import NodeStatus  # noqa: PLC0415

        node.status = NodeStatus.ASLEEP

    backend = coordinator.backend_for(handle(36))
    assert isinstance(backend, RecordingBackend)
    backend.after_write = _fall_asleep

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.UNCONFIRMED]
    assert report.results[0].reason is not None
    assert report.results[0].reason.placeholders["why"] == SKIPPED_ASLEEP


async def test_a_device_that_stops_answering_before_the_verify_is_unconfirmed(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """The write went out and then the connection dropped. That is not a confirmed write."""
    activate(coordinator, remote_rule())
    plan = await coordinator.async_plan()

    async def _drop(link: Link) -> None:
        backend.unavailable.add(handle(36).identity)

    backend.after_write = _drop

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.UNCONFIRMED]
    assert report.results[0].reason is not None
    assert report.results[0].reason.translation_key == "verify_unreadable"


async def test_a_device_whose_every_write_failed_is_re_read_anyway(
    coordinator: DeviceLinksCoordinator,
    runner: JobRunner,
    backend: RecordingBackend,
    driver: FakeDriver,
) -> None:
    """Open item T18, and the case where its "nothing is left wrong" was not true.

    A lost transmit acknowledgement is a documented Z-Wave failure: the write is reported
    as failed and the entry is on the device. The verify used to return before its read
    whenever there was nothing to check, so a device where every write failed was written
    to and then never re-read: the job said failed, the cache still held the pre-apply
    read, and the panel disagreed with the device until something else happened to refresh
    it. The report is still `failed`, which is what the backend said and all it can say.
    What is fixed is that the cache is not left wrong about it.
    """
    activate(coordinator, remote_rule())
    plan = await coordinator.async_plan()
    fingerprint = plan.items[0].link.fingerprint
    backend.fail_times[fingerprint] = 99

    async def _land_it_behind_our_back(link: Link) -> None:
        backend.before_write = None
        await rewrite(driver, source=36, group=2, target=37)

    backend.before_write = _land_it_behind_our_back

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.FAILED]
    assert backend.deep_reads == 1
    assert fingerprint in {link.fingerprint for link in links_of(coordinator, 36)}
    assert (await coordinator.async_plan()).is_empty


async def test_a_refresh_taken_during_a_job_cannot_land_on_top_of_the_verify(
    hass: HomeAssistant,
    coordinator: DeviceLinksCoordinator,
    runner: JobRunner,
    backend: RecordingBackend,
    driver: FakeDriver,
) -> None:
    """The promise is that a job cannot end with the cache disagreeing with the devices.

    Our own writes make the driver emit the value-updated events the coordinator refreshes
    on, so the first write of a job arms a read of the same node two seconds later. That
    read is taken while the job is still writing and can be delivered after the verify has
    stored its own: what lands in the cache is then a picture of the device from before the
    job finished, and every link written after it was taken reads as missing. The panel
    says the rule has drifted, the next plan proposes writes the device does not need, and
    nothing about the user's hardware is wrong.

    The read is held open here rather than raced: a driver that captured its answer at one
    moment and delivered it at a later one is the ordering this has to survive, and waiting
    on a clock to produce it would prove nothing on a machine that scheduled it the other
    way round. The cache is then read at once, because the window this opens closes only
    when something happens to re-read the device again: the fake's deep verify emits a
    value-updated event of its own and so heals it within a debounce window, and whether a
    real driver emits anything for a refresh that changed nothing is exactly what open item
    T10 says nobody has measured.
    """
    activate(
        coordinator,
        remote_rule(features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET})),
    )
    plan = await coordinator.async_plan()
    delivered = asyncio.Event()

    async def _hold_the_answer_back(_handle: DeviceHandle, deep: bool) -> None:
        if deep:
            return
        backend.after_read = None
        await delivered.wait()

    async def _announce_and_dawdle(link: Link) -> None:
        backend.before_write = None
        backend.after_read = _hold_the_answer_back
        driver.controller.emit_association_changed(36)
        # Long enough that the refresh fires, and reads, while this write is still open.
        await asyncio.sleep(TEST_DEBOUNCE * 4)

    backend.before_write = _announce_and_dawdle

    report = await runner.async_apply(plan)
    delivered.set()
    await hass.async_block_till_done()

    assert [result.outcome for result in report.results] == [LinkOutcome.APPLIED] * 2
    assert all(result.verified_at is not None for result in report.results)
    assert {item.link.fingerprint for item in plan.items} <= {
        link.fingerprint for link in links_of(coordinator, 36)
    }
    assert (await coordinator.async_plan()).is_empty
    assert coordinator.drift_state() == {"rule-1": RuleState.IN_SYNC}


async def test_a_removal_that_did_not_take_is_unverified_rather_than_applied(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """The verify question inverts for a removal: gone means gone, not present means done."""
    activate(coordinator, remote_rule())
    await runner.async_apply(await coordinator.async_plan())
    activate(coordinator, replace(remote_rule(), enabled=False))
    plan = await coordinator.async_plan()

    async def _put_it_back(link: Link) -> None:
        from zwave_js_server.model.association import AssociationAddress  # noqa: PLC0415

        controller = driver.controller
        await controller.async_add_associations(
            AssociationAddress(controller, node_id=36),
            2,
            [AssociationAddress(controller, node_id=37)],
        )

    backend = coordinator.backend_for(handle(36))
    assert isinstance(backend, RecordingBackend)
    backend.after_write = _put_it_back

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.UNVERIFIED]
    assert report.results[0].reason is not None
    assert report.results[0].reason.translation_key == "verify_still_present"


# Snapshots.


async def test_a_snapshot_of_every_touched_device_is_taken_before_any_write(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """FR-P3, and the whole device rather than only the links this plan changes.

    A rollback is re-applied as a plan, and a plan needs the complete before-state of the
    groups it works in: what else was in the group, whose it was, and which entries are
    system links it must never touch. The lifeline being in here is the visible proof that
    it is the device that was recorded and not the diff.
    """
    activate(coordinator, remote_rule())
    before = {link.fingerprint for link in links_of(coordinator, 36)}
    plan = await coordinator.async_plan()

    report = await runner.async_apply(plan)
    snapshot = coordinator.state.snapshots[-1]

    assert snapshot.id == report.snapshot_id
    assert snapshot.reason == SNAPSHOT_REASON
    assert snapshot.devices == (handle(36).identity,)
    assert {link.fingerprint for link in snapshot.links} == before
    assert any(link.is_system for link in snapshot.links)


async def test_the_snapshot_still_holds_the_pre_apply_state_when_the_apply_fails(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, backend: RecordingBackend
) -> None:
    """The case a snapshot exists for. Nobody wants a rollback after everything went well."""
    activate(
        coordinator,
        remote_rule(features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET})),
    )
    before = {link.fingerprint for link in links_of(coordinator, 36)}
    plan = await coordinator.async_plan()
    backend.raise_on.add(plan.items[1].link.fingerprint)

    report = await runner.async_apply(plan)
    snapshot = coordinator.state.snapshots[-1]

    assert LinkOutcome.FAILED in {result.outcome for result in report.results}
    assert {link.fingerprint for link in snapshot.links} == before


async def test_a_snapshot_covers_only_the_devices_the_job_will_really_write_to(
    coordinator: DeviceLinksCoordinator, runner: JobRunner, driver: FakeDriver
) -> None:
    """A device skipped as stale is a device this job did not touch.

    The snapshot used to be taken over every device the plan named, which was decided
    before staleness and availability were: it recorded the before-state of a device the
    job then refused to write to. That is not merely a wasted slot. Somebody edited that
    device by hand, which is why it was skipped, and a rollback of this job replaying that
    record would offer to undo their edit as though this job had made it.
    """
    activate(coordinator, remote_rule(), remote_rule("rule-2", source=39, target=38))
    plan = await coordinator.async_plan()
    await rewrite(driver, source=36, group=2, target=37)

    report = await runner.async_apply(plan)
    snapshot = coordinator.state.snapshots[-1]

    assert LinkOutcome.STALE_PLAN in {result.outcome for result in report.results}
    assert snapshot.devices == (handle(39).identity,)
    assert {link.source.identity for link in snapshot.links} == {handle(39).identity}


async def test_a_job_that_reaches_no_device_at_all_spends_no_snapshot_slot(
    hass: HomeAssistant, backend: RecordingBackend
) -> None:
    """FR-P3 keeps twenty snapshots, and an apply that wrote nothing must not evict one.

    The Z-Wave JS add-on restarts: every device is unavailable, the fresh plan is empty,
    every device in the plan the user is holding is stale, and not one byte reaches the
    mesh. A snapshot was still written, holding nothing, and twenty presses of Apply during
    a restart pushed out every snapshot a rollback could have used. The empty-plan guard
    did not catch this, because the plan was not empty when the user pressed the button.
    """
    backend.unavailable.add(handle(36).identity)
    coordinator = DeviceLinksCoordinator(
        hass,
        backends={BackendId.ZWAVE: backend},
        store=DeviceLinksStore(hass),
        refresh_debounce_seconds=TEST_DEBOUNCE,
    )
    await coordinator.async_setup()
    runner = JobRunner(coordinator)
    link = next(
        item.link
        for item in (await _plan_for_unreadable(coordinator)).items
        if item.link is not None
    )
    plan = Plan(
        token="hand-built",
        items=(PlanItem(op=PlanOp.ADD, device_identity=handle(36).identity, link=link),),
        unmanaged=(),
        unchanged_count=0,
    )

    report = await runner.async_apply(plan)

    assert [result.outcome for result in report.results] == [LinkOutcome.STALE_PLAN]
    assert backend.writes == []
    assert coordinator.state.snapshots == ()
    assert report.snapshot_id is None
    await coordinator.async_shutdown()


async def test_a_snapshot_names_the_devices_it_covers_and_claims_no_others(
    hass: HomeAssistant, backend: RecordingBackend
) -> None:
    """A device that held nothing is not a device nobody could read.

    Both contribute no links, so a snapshot that only listed links could not tell them
    apart, and a Phase 2 rollback re-applying one as a plan would read the second as the
    first and propose removing everything that device turns out to hold now. `devices` is
    what makes the difference readable: listed means the links here are the whole of what
    that device held, and absent means nothing at all is claimed about it.

    Reaching this needs a plan whose token still matches while its device cannot be read,
    which is what a replayed or hand-built plan can produce and the staleness check then
    waves through. The write goes out, and the snapshot says honestly that it covers
    nothing rather than recording an empty before-state for a device it never saw.
    """
    backend.unavailable.add(handle(36).identity)
    coordinator = DeviceLinksCoordinator(
        hass,
        backends={BackendId.ZWAVE: backend},
        store=DeviceLinksStore(hass),
        refresh_debounce_seconds=TEST_DEBOUNCE,
    )
    await coordinator.async_setup()
    runner = JobRunner(coordinator)
    link = next(
        item.link
        for item in (await _plan_for_unreadable(coordinator)).items
        if item.link is not None
    )
    plan = Plan(
        token=(await coordinator.async_plan()).token,
        items=(PlanItem(op=PlanOp.ADD, device_identity=handle(36).identity, link=link),),
        unmanaged=(),
        unchanged_count=0,
    )

    report = await runner.async_apply(plan)

    assert backend.writes == [link.fingerprint]
    assert [result.outcome for result in report.results] == [LinkOutcome.UNCONFIRMED]
    assert coordinator.state.snapshots == ()
    await coordinator.async_shutdown()


async def _plan_for_unreadable(coordinator: DeviceLinksCoordinator) -> Plan:
    """Return a plan whose one item is for the device that cannot be read.

    Built by activating the rule and planning against a network where node 36 answers, then
    reusing the link: the coordinator will not plan for a device it cannot see, which is
    precisely the behaviour under test, so the link has to come from somewhere else.
    """
    from custom_components.device_links.compiler import compile_rule  # noqa: PLC0415
    from tests.factories import capabilities_for  # noqa: PLC0415

    activate(coordinator, remote_rule())
    compiled = compile_rule(remote_rule(), capabilities_for(36, 37))
    return Plan(
        token="compiled",
        items=tuple(
            PlanItem(op=PlanOp.ADD, device_identity=link.source.identity, link=link)
            for link in compiled.links
        ),
        unmanaged=(),
        unchanged_count=0,
    )


async def test_snapshots_are_capped_by_the_store_rather_than_by_the_runner(
    coordinator: DeviceLinksCoordinator, runner: JobRunner
) -> None:
    """FR-P3 caps the history at 20, and the cap lives on the state for a reason.

    A runner that appended to the list itself would be a second place the cap has to be
    remembered, and a cap enforced at one of two call sites is a cap that is missing at the
    other. This asserts the runner went through `with_snapshot`.
    """
    activate(coordinator, remote_rule())
    coordinator.async_update_state(
        replace(
            coordinator.state,
            snapshots=tuple(
                Snapshot(id=f"old-{index}", created_at="2026-09-05T00:00:00+00:00", reason="test")
                for index in range(MAX_SNAPSHOTS)
            ),
        )
    )

    report = await runner.async_apply(await coordinator.async_plan())

    assert len(coordinator.state.snapshots) == MAX_SNAPSHOTS
    assert coordinator.state.snapshots[-1].id == report.snapshot_id
    assert coordinator.state.snapshots[0].id == "old-1"
