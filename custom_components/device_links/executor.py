"""The executor: a plan becomes writes, and every write becomes an honest answer.

Everything before this module decided what should happen. This is the code that makes it
happen on somebody's actual home, at three in the afternoon, while they are standing in
the room. Four properties are load-bearing, and each of them is a way this could hurt
rather than merely disappoint.

**One device is one conversation.** A Z-Wave mesh handles one command per node at a time.
Two overlapping writes to the same node produce timeouts that look exactly like a faulty
device, and the owner spends an evening hunting hardware that is fine. So the unit of
concurrency here is the device and never the link: one coroutine per device, its items
worked in plan order, and a semaphore bounding how many devices are in flight. Per-device
serialization is therefore structural rather than enforced by a lock: there is only ever
one coroutine that can write to a given node, so there is nothing to interleave.

**A refusal is never retried.** `blocked` means a check said no, and a check that said no
will say no again. Retrying it spends airtime on a shared radio to be told the same thing
three times, which is airtime the light somebody is standing at is not responding in.
`failed` is retried, twice, with a bounded backoff, and then it is reported as failed.

**Cancel stops.** Not "sets a flag and keeps going": nothing new starts after a cancel.
What was already in flight is allowed to finish, because a radio write that has been sent
cannot be un-sent, and it is reported with its real outcome and verified like any other.
`cancelled` in a job summary means "not attempted, nothing reached this device", and it
means only that, so an owner reading the summary can tell the two apart.

**Sent is not the same as done.** After the writes to a device, that device is re-read
through the coordinator with a deep verify, and each write is checked against what came
back. A link that was written and is not there is `unverified` and puts its rule into
drift (E14); it is never reported as applied. A link that is there but whose deep verify
could not be confirmed is `unconfirmed`, which is neither success nor failure: Phase 1B's
`deep_verified` and `deep_verify_timed_out` exist precisely so that "we tried and could
not tell" has somewhere to go other than into the success column (open item T10).

The direction of the dependency is deliberate: the runner depends on the coordinator and
the coordinator knows nothing about the runner. The coordinator owns the observed cache,
so every read this module needs goes through it, which is what makes it impossible for a
job to finish with the cache disagreeing with the devices: the verify read *is* the cache
update. Every device the job attempted anything on is re-read before the job ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import logging
from typing import Final
from uuid import uuid4

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.device_links.backends.base import Backend, LinkResult, LinkResultStatus
from custom_components.device_links.const import DOMAIN
from custom_components.device_links.coordinator import DeviceLinksCoordinator, PlanScope
from custom_components.device_links.models import (
    DeviceHandle,
    Diagnostic,
    Link,
    ObservedLink,
    Plan,
    PlanItem,
    PlanOp,
)
from custom_components.device_links.storage import JobLinkResult, JobSummary, Snapshot

_LOGGER = logging.getLogger(__name__)

# Stage 0 measured an association add at 67 ms and a remove at 253 ms on a listening
# mains-powered node, on Jayant's real network. Thirty seconds is two orders of magnitude
# of headroom over the slower of those and still a bound: a write that has not answered in
# a hundred times the measured worst case is not about to.
OPERATION_TIMEOUT_SECONDS: Final = 30.0

# Two retries, a second and then two. Against the same measured 67 ms and 253 ms, one
# second is already several writes' worth of airtime, which is the point: the wait is there
# to let a busy mesh drain rather than to be imperceptible. Three attempts in all, so the
# worst case for one link is bounded at three timeouts plus three seconds (E13).
RETRY_BACKOFF_SECONDS: Final = (1.0, 2.0)

# Two devices at once. One device is one radio conversation, and a mesh is a shared medium:
# fanning out to every device in a plan turns one slow node into every node being slow.
DEFAULT_MAX_CONCURRENT_DEVICES: Final = 2

# What a pre-apply snapshot is for, recorded on the snapshot itself. Its id is the job id,
# so the rollback flow in Phase 2 can find the snapshot belonging to a job in the history
# without a second index.
SNAPSHOT_REASON: Final = "pre_apply"

# The delay a job waits with. Injectable so the tests can assert the delays the runner
# chose without spending them: what is worth proving is that it backs off by 1 s and then
# 2 s between attempts, not that `asyncio.sleep` sleeps.
type Sleeper = Callable[[float], Awaitable[None]]


class JobStatus(StrEnum):
    """How a whole job ended.

    `PARTIAL` is the honest answer for a job that ran to the end with something in it that
    did not work: calling it completed would hide a failed link in a green summary, and
    calling it failed would hide the nine links that did work.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class LinkOutcome(StrEnum):
    """What became of one link in one job, as the Activity view has to be able to say it.

    Wider than the backend's `LinkResultStatus`, because a backend answers "what happened
    when I wrote" and this answers "what is true now", and the difference between those two
    is the whole point of verifying.

    `UNVERIFIED` is written-and-not-there: the write was accepted and the link is not on the
    device (E14). It is drift, not success. `UNCONFIRMED` is written-and-there-but-the-read
    -could-not-confirm-it: the device did not answer the refresh, so what was read is the
    driver's cache rather than the device's own word. Neither is a failure and neither is a
    success, and collapsing either into `APPLIED` would turn "we could not tell" into
    assurance, which is worse than not verifying at all.

    `CANCELLED` and `INTERRUPTED` mean nothing reached the device. An operation that was in
    flight when the stop arrived keeps its real outcome instead.
    """

    APPLIED = "applied"
    ALREADY_PRESENT = "already_present"
    UNVERIFIED = "unverified"
    UNCONFIRMED = "unconfirmed"
    PENDING_WAKEUP = "pending_wakeup"
    FAILED = "failed"
    BLOCKED = "blocked"
    STALE_PLAN = "stale_plan"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobRunningError(HomeAssistantError):
    """A second apply arrived while one was already running (E16).

    Refused rather than queued: the second caller's plan was computed against the state
    before the first job wrote anything, so running it afterwards would apply a plan nobody
    has looked at since. Re-planning is cheap and correct.
    """


# What the backend said, mapped to what the job says about it before verification.
_OUTCOME_OF: Final[Mapping[LinkResultStatus, LinkOutcome]] = {
    LinkResultStatus.APPLIED: LinkOutcome.APPLIED,
    LinkResultStatus.ALREADY_PRESENT: LinkOutcome.ALREADY_PRESENT,
    LinkResultStatus.PENDING_WAKEUP: LinkOutcome.PENDING_WAKEUP,
    LinkResultStatus.FAILED: LinkOutcome.FAILED,
    LinkResultStatus.BLOCKED: LinkOutcome.BLOCKED,
}

# The outcomes a re-read has something to say about. A failure has already been reported as
# a failure, and a sleeping node cannot answer a verify at all.
_VERIFIABLE: Final = frozenset({LinkOutcome.APPLIED, LinkOutcome.ALREADY_PRESENT})

# The outcomes that mean the job did what it set out to do for that link.
_SUCCESSFUL: Final = frozenset(
    {LinkOutcome.APPLIED, LinkOutcome.ALREADY_PRESENT, LinkOutcome.PENDING_WAKEUP}
)

# The outcomes that count as "this rule has been applied at least once", which is what
# separates drift from never-applied (FR-A5). `UNVERIFIED` is in the set on purpose: an
# apply did happen and did not stick, and that is exactly what drift means. Leaving it out
# would report the rule as pending, which reads as "not done yet" rather than "gone wrong".
_APPLIED_AT_LEAST_ONCE: Final = _VERIFIABLE | {LinkOutcome.UNVERIFIED, LinkOutcome.UNCONFIRMED}

# What a stop makes of the operations it prevented from starting.
_NOT_ATTEMPTED: Final[Mapping[JobStatus, LinkOutcome]] = {
    JobStatus.CANCELLED: LinkOutcome.CANCELLED,
    JobStatus.INTERRUPTED: LinkOutcome.INTERRUPTED,
}

_WRITE_OPS: Final = frozenset({PlanOp.ADD, PlanOp.REMOVE})


@dataclass(frozen=True, slots=True)
class LinkReport:
    """What became of one plan item, with everything needed to explain it.

    `attempts` is here because "it failed" and "it failed three times over three seconds"
    are different things to somebody deciding whether their mesh is unwell. `verified_at`
    is set only when a device confirmed the link on a fresh read, so its absence is
    meaningful rather than merely missing.
    """

    fingerprint: str
    device_identity: str
    op: PlanOp
    outcome: LinkOutcome
    reason: Diagnostic | None = None
    raw_error: str | None = None
    attempts: int = 0
    verified_at: str | None = None


@dataclass(frozen=True, slots=True)
class JobReport:
    """One apply, in full, as the caller and the Activity view see it.

    `snapshot_id` is the id of the snapshot taken before the first write, which is the same
    as the job id: a rollback needs to get from "this job" to "what was there before it"
    without a second index to keep consistent. It is None when the job had nothing to
    write, because a job that wrote nothing has nothing to roll back, and spending one of
    the twenty snapshot slots on it would let twenty presses of Apply on an already
    converged network push out every snapshot worth keeping.
    """

    id: str
    created_at: str
    scope: str
    status: JobStatus
    snapshot_id: str | None
    results: tuple[LinkReport, ...]


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Where a running job has got to, for a subscription to stream in Phase 1D."""

    id: str
    total: int
    completed: int
    devices_in_flight: tuple[str, ...]


@dataclass(slots=True)
class _Op:
    """One plan item as the runner works it, and what it has decided about it so far.

    `outcome` being None is the whole of "not decided yet": it is what the stop check, the
    stale check and the scheduler all read to know whether there is anything left to do.
    """

    item: PlanItem
    outcome: LinkOutcome | None = None
    reason: Diagnostic | None = None
    raw_error: str | None = None
    attempts: int = 0
    verified_at: str | None = None

    @property
    def fingerprint(self) -> str:
        """Return the link's identity, or nothing for an item that is not about a link."""
        return "" if self.item.link is None else self.item.link.fingerprint

    def report(self) -> LinkReport:
        """Return this operation as the caller sees it.

        Every path through a job decides every operation: refused, skipped as stale, not
        attempted because the job stopped, or written. An undecided one is therefore a bug
        in this module rather than a state a user can reach, and it reads as `failed`
        because a link nobody can account for is not one to report as done.
        """
        return LinkReport(
            fingerprint=self.fingerprint,
            device_identity=self.item.device_identity,
            op=self.item.op,
            outcome=LinkOutcome.FAILED if self.outcome is None else self.outcome,
            reason=self.reason,
            raw_error=self.raw_error,
            attempts=self.attempts,
            verified_at=self.verified_at,
        )


@dataclass(slots=True)
class _Write:
    """One operation that really is a write, with its link resolved once.

    Separate from `_Op` so that everything downstream of the refusals holds a `Link` rather
    than an optional one: an item with no link cannot be written and has already been
    answered by the time anything here sees it.
    """

    op: _Op
    link: Link


@dataclass(slots=True)
class _Job:
    """One apply while it is happening."""

    id: str
    created_at: str
    scope: str
    ops: list[_Op]
    finished: asyncio.Event
    writes: list[_Write] = field(default_factory=list)
    devices_in_flight: set[str] = field(default_factory=set)
    snapshot_id: str | None = None
    stop: JobStatus | None = None


class JobRunner:
    """Applies plans, one at a time, and says what really happened."""

    def __init__(
        self,
        coordinator: DeviceLinksCoordinator,
        *,
        max_concurrent_devices: int = DEFAULT_MAX_CONCURRENT_DEVICES,
        operation_timeout_seconds: float = OPERATION_TIMEOUT_SECONDS,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        """Hold what the runner needs. Nothing is read and nothing is written yet."""
        self._coordinator = coordinator
        self._max_concurrent_devices = max_concurrent_devices
        self._operation_timeout = operation_timeout_seconds
        self._sleep = sleep
        self._job: _Job | None = None

    @property
    def progress(self) -> JobProgress | None:
        """Return where the running job has got to, or None when none is running."""
        job = self._job
        if job is None:
            return None
        return JobProgress(
            id=job.id,
            total=len(job.ops),
            completed=sum(1 for op in job.ops if op.outcome is not None),
            devices_in_flight=tuple(sorted(job.devices_in_flight)),
        )

    async def async_apply(
        self,
        plan: Plan,
        *,
        scope: PlanScope | None = None,
        remove_unmanaged: frozenset[str] = frozenset(),
    ) -> JobReport:
        """Apply this plan and return what happened to every item in it.

        `scope` and `remove_unmanaged` must be the ones the plan was built with: they are
        how the plan is rebuilt to find out whether it is still current (E15).
        """
        if self._job is not None:
            raise JobRunningError(
                "an apply is already running, so this one was refused rather than queued "
                "behind a plan that will be out of date by the time it runs",
                translation_domain=DOMAIN,
                translation_key="job_running",
            )
        job = _Job(
            id=uuid4().hex,
            created_at=_now(),
            scope=_describe(scope),
            ops=[_Op(item) for item in plan.items],
            finished=asyncio.Event(),
        )
        self._job = job
        _LOGGER.info("job %s starting: %s items, scope %s", job.id, len(job.ops), job.scope)
        try:
            return await self._run(job, plan, scope, remove_unmanaged)
        finally:
            self._job = None
            job.finished.set()

    @callback
    def async_cancel(self) -> None:
        """Stop scheduling new operations, and let the in-flight ones finish.

        Deliberately not awaited: the caller is a service call or a button, and it must
        return as soon as the decision is recorded. A write that is already on the radio
        finishes and is reported with its real outcome; a backoff that is already being
        waited out is seen through, which is bounded at two seconds and costs nothing.
        """
        self._stop(JobStatus.CANCELLED)

    async def async_shutdown(self) -> None:
        """Stop the running job as interrupted and wait for it to unwind (E17).

        Awaited, unlike cancel, because the caller is a config entry unload: returning
        while writes are still in flight would tear the backends down underneath them.
        The job is not recorded anywhere as resumable, and nothing resumes it: re-running
        apply recomputes the plan from a fresh read, which is the only safe way back.
        """
        job = self._job
        if job is None:
            return
        self._stop(JobStatus.INTERRUPTED)
        await job.finished.wait()

    def _stop(self, status: JobStatus) -> None:
        """Record that the running job, if there is one, must stop starting things."""
        if self._job is not None:
            self._job.stop = status
            _LOGGER.info("job %s asked to stop: %s", self._job.id, status)

    # One job, in order.

    async def _run(
        self,
        job: _Job,
        plan: Plan,
        scope: PlanScope | None,
        remove_unmanaged: frozenset[str],
    ) -> JobReport:
        """Refuse, re-read, snapshot, write, verify, record. In that order, always.

        The refusals come first because they depend on nothing: a lifeline is never ours
        whatever the state of the network, and asking a state-dependent question first
        could answer instead of one of them. The snapshot comes after the re-read and
        before the first write, so that what it holds is really what was there.
        """
        self._refuse_impossible(job)
        handles, backends = self._resolve_devices(job)
        by_device = _grouped(job.writes)
        await self._reread(handles)
        stale = await self._stale_devices(plan, scope, remove_unmanaged, by_device)
        self._take_snapshot(job, handles)
        _mark(stale, by_device, LinkOutcome.STALE_PLAN, self._stale_reason)

        semaphore = asyncio.Semaphore(self._max_concurrent_devices)
        await asyncio.gather(
            *(
                self._run_device(job, semaphore, handles[identity], backends[identity], writes)
                for identity, writes in by_device.items()
                if identity not in stale
            )
        )
        return self._finish(job)

    def _refuse_impossible(self, job: _Job) -> None:
        """Answer every item that cannot be written, before anything is read or sent.

        The order is the safety rule and is the same order the Z-Wave adapter uses. A
        system link is refused first, so that no later question and no ownership record can
        reach a lifeline: the planner never emits one and the coordinator never marks one
        as ours, which means an item that gets here is already evidence that something
        upstream is wrong, and a guard that only exists where the mistake is not is not a
        guard (CLAUDE.md Section 3 rule 4).
        """
        for op in job.ops:
            refusal = self._refusal(op.item)
            if refusal is not None:
                op.outcome = LinkOutcome.BLOCKED
                op.reason = refusal

    def _refusal(self, item: PlanItem) -> Diagnostic | None:
        """Return why this item will not be attempted, or None when it will be."""
        link = item.link
        if isinstance(link, ObservedLink) and link.is_system:
            return Diagnostic("system_link_protected", _about(link))
        if item.op is PlanOp.BLOCKED:
            return item.reason or Diagnostic("blocked_by_plan", {"device": item.device_identity})
        if link is None or item.op not in _WRITE_OPS:
            # Nothing produces a setting write or a pending item yet (open items T2, T15).
            # Reported rather than dropped: an item that silently disappears is a device
            # setting a rule asked for that nobody notices is missing.
            return Diagnostic(
                "unsupported_operation",
                {"operation": str(item.op), "device": item.device_identity},
            )
        return None

    def _resolve_devices(self, job: _Job) -> tuple[dict[str, DeviceHandle], dict[str, Backend]]:
        """Return the handle and the adapter of every device still to be written to.

        The last of the refusals lives here rather than beside the others, because it is
        the one that is answered by looking a backend up: an item for a protocol whose
        adapter is not loaded (a Zigbee link before Phase 2, or after `mqtt` was removed)
        is refused rather than attempted, and asking for the adapter twice to keep the
        refusal somewhere tidier would be two lookups that can disagree.

        Fills `job.writes` on the way through, which is the list everything after the
        refusals works from: each entry carries a link that really exists, so nothing
        downstream has to ask again whether an item is about a link.
        """
        handles: dict[str, DeviceHandle] = {}
        backends: dict[str, Backend] = {}
        for op in job.ops:
            link = op.item.link
            if op.outcome is not None or link is None:
                continue
            backend = self._coordinator.backend_for(link.source)
            if backend is None:
                op.outcome = LinkOutcome.BLOCKED
                op.reason = Diagnostic(
                    "backend_not_loaded", {"backend": str(link.backend), **_about(link)}
                )
                continue
            identity = link.source.identity
            handles.setdefault(identity, link.source)
            backends.setdefault(identity, backend)
            job.writes.append(_Write(op=op, link=link))
        return handles, backends

    async def _reread(self, handles: Mapping[str, DeviceHandle]) -> None:
        """Read every device this plan touches, so the staleness check is about now.

        A shallow read: this asks the driver's cache, which Stage 0 confirmed is right
        about our own writes and can only be behind on somebody else's, and being behind on
        somebody else's is exactly what the staleness check is looking for.
        """
        for handle in handles.values():
            await self._coordinator.async_refresh(handle)

    async def _stale_devices(
        self,
        plan: Plan,
        scope: PlanScope | None,
        remove_unmanaged: frozenset[str],
        by_device: Mapping[str, Sequence[_Write]],
    ) -> set[str]:
        """Return the devices whose work is no longer the work the user approved (E15).

        The token answers the common case in one comparison: same inputs, same plan,
        nothing to check per device. When it differs, something changed somewhere, and the
        question becomes which device it changed on, because refusing the whole job would
        punish every other device for one external edit.

        What is compared per device is the work itself, not the token: an edit that changes
        what the device holds without changing what we would write to it (somebody adding
        an association we were never going to touch) leaves the approved writes exactly as
        approved, and there is nothing to warn about. An edit that would change the writes,
        including one that fills a group so that an add no longer fits, changes the items
        and is caught. A device that has stopped answering drops out of the fresh plan
        entirely, so every one of its links is missing from the fresh work, which lands
        here too: a plan for a device we cannot see is not a plan we can trust (E1).

        The comparison is per link rather than per device list, because the two are not the
        same question. "Does the fresh plan still do exactly this to this link?" is what
        makes an approved write still safe; "is the fresh plan for this device identical?"
        would also refuse when the fresh plan grew work nobody has approved, which is not a
        reason to withhold the work they did approve.
        """
        fresh = await self._coordinator.async_plan(scope, remove_unmanaged=remove_unmanaged)
        if fresh.token == plan.token:
            return set()
        current = {
            item.link.fingerprint: str(item.op) for item in fresh.items if item.link is not None
        }
        return {
            identity
            for identity, writes in by_device.items()
            if any(
                current.get(write.link.fingerprint) != str(write.op.item.op)
                for write in writes
                if write.op.outcome is None
            )
        }

    def _stale_reason(self, write: _Write) -> Diagnostic:
        """Say why this device was skipped, which is not always that somebody edited it."""
        key = (
            "stale_plan"
            if self._coordinator.is_available(write.link.source.identity)
            else "device_unavailable"
        )
        return Diagnostic(key, _about(write.link))

    def _take_snapshot(self, job: _Job, handles: Mapping[str, DeviceHandle]) -> None:
        """Record everything every touched device holds, before a single write (FR-P3).

        Whole devices, not only the links this plan changes. A rollback is re-applied as a
        plan, and a plan needs the complete before-state of the groups it works in: what
        else was in the group (so capacity is counted right), which entries were somebody
        else's (so rollback does not offer to remove them) and which were system links (so
        it never can). A snapshot of only the changed links could replay the inverse of
        each operation and nothing more, which stops being correct the moment anything else
        about the device has moved in between, and that is precisely when a rollback is
        being asked for.

        Nothing is recorded when the plan turns out to have nothing to write. A snapshot of
        a job that changed nothing is a slot spent on a state that is still the current one.
        """
        if not handles:
            return
        links: list[ObservedLink] = []
        for identity in sorted(handles):
            device = self._coordinator.observed_for(handles[identity])
            if device is not None:
                links.extend(device.links)
        snapshot = Snapshot(
            id=job.id, created_at=job.created_at, reason=SNAPSHOT_REASON, links=tuple(links)
        )
        job.snapshot_id = snapshot.id
        self._coordinator.async_update_state(self._coordinator.state.with_snapshot(snapshot))

    # One device.

    async def _run_device(
        self,
        job: _Job,
        semaphore: asyncio.Semaphore,
        handle: DeviceHandle,
        backend: Backend,
        writes: Sequence[_Write],
    ) -> None:
        """Work one device's operations in order, then find out what really happened.

        The whole conversation with one node, verify included, happens inside the
        semaphore: a deep verify is a radio round trip like any other, and letting one
        start while the cap says two devices are already busy would make the cap a
        suggestion.
        """
        async with semaphore:
            job.devices_in_flight.add(handle.identity)
            try:
                if await self._write_all(job, backend, writes):
                    await self._verify(handle, writes)
            finally:
                job.devices_in_flight.discard(handle.identity)

    async def _write_all(self, job: _Job, backend: Backend, writes: Sequence[_Write]) -> bool:
        """Perform this device's writes in plan order, stopping when the job is stopped.

        Returns whether anything was attempted at all, which is what decides whether this
        device is worth re-reading: a device nothing was sent to has not changed, and
        spending a deep verify on it would be radio time bought with nothing.
        """
        attempted = False
        for write in writes:
            if job.stop is not None:
                write.op.outcome = _NOT_ATTEMPTED[job.stop]
                continue
            attempted = True
            await self._write(job, backend, write)
        return attempted

    async def _write(self, job: _Job, backend: Backend, write: _Write) -> None:
        """Write one link, retrying a failure twice and a refusal never (E13).

        The retry condition is `FAILED` and only `FAILED`. `BLOCKED` came from a check that
        will give the same answer next time; `PENDING_WAKEUP` is a queued write that has
        not failed at all; `ALREADY_PRESENT` is nothing to do. Retrying any of them would
        be airtime spent to learn what is already known.
        """
        op = write.op
        op.attempts = 1
        result = await self._call(backend, op.item.op, write.link)
        for backoff in RETRY_BACKOFF_SECONDS:
            if result.status is not LinkResultStatus.FAILED:
                break
            await self._sleep(backoff)
            if job.stop is not None:
                # Stopped while waiting to try again. The last attempt's result stands:
                # it was really attempted, and reporting it as cancelled would claim
                # nothing reached the device when something did.
                break
            op.attempts += 1
            result = await self._call(backend, op.item.op, write.link)
        op.outcome = _OUTCOME_OF[result.status]
        op.reason = result.reason
        op.raw_error = result.raw_error

    async def _call(self, backend: Backend, op: PlanOp, link: Link) -> LinkResult:
        """Make one bounded call to a backend, and turn anything at all into a result.

        The `Backend` contract says an adapter answers rather than raises, and the Z-Wave
        one does. This catches anyway: the executor owes a result for every link in the
        plan, and an adapter that raised would otherwise take the whole job's report with
        it, including the results of the links that did work.
        """
        try:
            async with asyncio.timeout(self._operation_timeout):
                if op is PlanOp.ADD:
                    return await backend.async_add_link(link)
                return await backend.async_remove_link(link)
        except TimeoutError:
            _LOGGER.warning(
                "%s did not answer within %ss", link.fingerprint, self._operation_timeout
            )
            return LinkResult(
                status=LinkResultStatus.FAILED,
                reason=Diagnostic(
                    "operation_timeout", {**_about(link), "seconds": str(self._operation_timeout)}
                ),
            )
        except Exception as err:  # an adapter may raise anything its client raises
            _LOGGER.warning("writing %s raised: %s", link.fingerprint, err)
            return LinkResult(
                status=LinkResultStatus.FAILED,
                reason=Diagnostic("link_write_raised", _about(link)),
                raw_error=str(err),
            )

    async def _verify(self, handle: DeviceHandle, writes: Sequence[_Write]) -> None:
        """Re-read the device and check every write against what came back.

        Through the coordinator, and deep, which is two decisions rather than one. Deep,
        because a verify that reads the same cache the write updated agrees with itself
        whatever the device did, and an agreement like that looks like assurance while
        being worth nothing. Through the coordinator, because the cache the rest of the
        integration answers from must be the one that was just proved right: a job that
        left its own private idea of the device behind would put the panel and the radio
        into disagreement at exactly the moment somebody is looking at both.
        """
        pending = [write for write in writes if write.op.outcome in _VERIFIABLE]
        if not pending:
            return
        await self._coordinator.async_refresh(handle, deep=True)
        device = self._coordinator.observed_for(handle)
        if not self._coordinator.is_available(handle.identity) or device is None:
            for write in pending:
                write.op.outcome = LinkOutcome.UNCONFIRMED
                write.op.reason = Diagnostic("verify_unreadable", _about(write.link))
            return
        present = {link.fingerprint for link in device.links}
        for write in pending:
            wanted = write.op.item.op is PlanOp.ADD
            if (write.link.fingerprint in present) is not wanted:
                # E14. Sent is not the same as done, and a link that was written and is not
                # there is drift. Reporting it as applied is the single most misleading
                # thing this integration could do, because the promise is a verify from a
                # fresh read rather than from what we sent.
                write.op.outcome = LinkOutcome.UNVERIFIED
                write.op.reason = Diagnostic(
                    "verify_missing" if wanted else "verify_still_present", _about(write.link)
                )
            elif not device.deep_verified:
                # The device is in the state we wanted according to a read the device did
                # not confirm. That is not a failure and it is not a confirmation, and open
                # item T10 says it may be the common case on real hardware, so it says what
                # it knows and nothing more.
                write.op.outcome = LinkOutcome.UNCONFIRMED
                write.op.reason = Diagnostic(
                    "verify_not_confirmed",
                    {
                        **_about(write.link),
                        "why": device.deep_verify_skipped_reason or "no_answer",
                    },
                )
            else:
                write.op.verified_at = _now()

    # Recording what happened.

    def _finish(self, job: _Job) -> JobReport:
        """Note which rules were applied, persist the summary, and return the report."""
        status = job.stop or (
            JobStatus.COMPLETED
            if all(op.outcome in _SUCCESSFUL for op in job.ops)
            else JobStatus.PARTIAL
        )
        applied = {
            write.link.rule_id
            for write in job.writes
            if write.op.outcome in _APPLIED_AT_LEAST_ONCE and write.link.rule_id is not None
        }
        self._coordinator.async_note_applied(sorted(applied))
        results = tuple(op.report() for op in job.ops)
        summary = JobSummary(
            id=job.id,
            created_at=job.created_at,
            scope=job.scope,
            status=str(status),
            results=tuple(
                JobLinkResult(
                    fingerprint=result.fingerprint,
                    status=str(result.outcome),
                    reason=None if result.reason is None else result.reason.translation_key,
                )
                for result in results
            ),
        )
        self._coordinator.async_update_state(self._coordinator.state.with_job(summary))
        _LOGGER.info(
            "job %s %s: %s", job.id, status, ", ".join(sorted({r.outcome for r in results}))
        )
        return JobReport(
            id=job.id,
            created_at=job.created_at,
            scope=job.scope,
            status=status,
            snapshot_id=job.snapshot_id,
            results=results,
        )


def _now() -> str:
    """Return the current time in UTC, as it is written into storage."""
    return dt_util.utcnow().isoformat()


def _describe(scope: PlanScope | None) -> str:
    """Return a one-line description of what a job was about, for the history.

    "Which rule did this?" is the first question anybody asks of a job summary six weeks
    later, so the answer is stored with the summary rather than reconstructed from it.
    """
    if scope is None:
        return "all"
    parts = []
    if scope.rule_ids:
        parts.append("rules:" + ",".join(sorted(scope.rule_ids)))
    if scope.device_identities:
        parts.append("devices:" + ",".join(sorted(scope.device_identities)))
    return " ".join(parts) if parts else "all"


def _about(link: Link) -> dict[str, str]:
    """Return the placeholders every message about one link needs to be actionable."""
    return {
        "device": link.source.name_at_authoring,
        "target": link.target.handle.name_at_authoring,
        "group": link.emitter_group,
    }


def _grouped(writes: Sequence[_Write]) -> dict[str, list[_Write]]:
    """Group writes by the device they go to, keeping plan order within each device.

    One device is one radio conversation and therefore one coroutine, so this grouping is
    what makes per-device serialization structural: there is only ever one place a write to
    a given node can come from, which is a stronger guarantee than a lock because there is
    nothing to forget to take.
    """
    grouped: dict[str, list[_Write]] = {}
    for write in writes:
        grouped.setdefault(write.link.source.identity, []).append(write)
    return grouped


def _mark(
    identities: set[str],
    by_device: Mapping[str, Sequence[_Write]],
    outcome: LinkOutcome,
    reason: Callable[[_Write], Diagnostic],
) -> None:
    """Answer every operation still to be performed on these devices the same way.

    Only the operations still to be performed reach here: anything already refused was
    left out of `job.writes` when the devices were resolved, so a per-device skip can
    never relabel an item that was answered for a reason of its own.
    """
    for identity in identities:
        for write in by_device[identity]:
            write.op.outcome = outcome
            write.op.reason = reason(write)
