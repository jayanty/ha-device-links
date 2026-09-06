"""A backend that does the real thing and records exactly how it was driven.

The executor tests are about scheduling: what ran, in what order, on which device, how
many times, and what was still running while something else started. None of that is
visible from a plan or a job summary, and none of it can be asserted against the Z-Wave
adapter alone, so this wrapper sits between the executor and the real `ZWaveBackend` and
writes down what went past.

Two things make the recording worth trusting.

**Every write still reaches the fake driver.** Nothing here invents a success: an add that
this wrapper does not deliberately fail is performed by `ZWaveBackend` against the Stage 0
fake, so the verify that follows reads real state rather than a claim. The hooks that do
intervene (`fail_times`, `block`, `hang`, `raise_on`) each stand for something the adapter
or the mesh really produces, and they are named after that thing.

**Every write yields to the event loop while it is in flight.** A coroutine that never
awaits cannot be interleaved with another, so a serialization test over writes that do not
yield passes whatever the executor does, which is the classic way to prove nothing at all.
`yields` is how long a write stays open in scheduler terms, and `overlapped` is what a test
asserts against: it records a device that was written to while a write to that same device
was already open.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable

from custom_components.device_links.backends.base import (
    Backend,
    BackendDevice,
    LinkCheck,
    LinkResult,
    LinkResultStatus,
    ObservedDevice,
    SettingResult,
    SettingValue,
)
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Diagnostic,
    Link,
)

type Hook = Callable[[Link], Awaitable[None]]


class RecordingBackend:
    """The real Z-Wave adapter, with a record of how the executor drove it."""

    def __init__(self, inner: Backend, *, yields: int = 4) -> None:
        """Wrap an adapter. `yields` is how long each write stays open, in loop turns."""
        self.inner = inner
        self._yields = yields

        # Scheduling, which is what the concurrency tests read.
        self.in_flight: list[str] = []
        self.peak = 0
        self.overlapped: list[str] = []
        self.writes: list[str] = []
        self.attempts: Counter[str] = Counter()

        # Conditions a test asks for, each named after what it stands for.
        self.fail_times: dict[str, int] = {}
        self.block: set[str] = set()
        self.hang: set[str] = set()
        self.raise_on: set[str] = set()
        self.unavailable: set[str] = set()

        # Called at the start and the end of one write, so a test can make something
        # happen at a moment it cannot otherwise reach: cancel the job from inside the
        # first write, or take an association back off behind the executor's back.
        self.before_write: Hook | None = None
        self.after_write: Hook | None = None

        self.deep_reads = 0

    # Reads.

    async def async_devices(self) -> list[BackendDevice]:
        return await self.inner.async_devices()

    async def async_capabilities(self, handle: DeviceHandle) -> DeviceCapabilities:
        self._check(handle.identity)
        return await self.inner.async_capabilities(handle)

    async def async_observed(self, handle: DeviceHandle, deep: bool = False) -> ObservedDevice:
        self._check(handle.identity)
        self.deep_reads += int(deep)
        return await self.inner.async_observed(handle, deep)

    def _check(self, identity: str) -> None:
        if identity in self.unavailable:
            raise ConnectionError(f"{identity} did not answer")

    async def async_check_link(self, link: Link) -> LinkCheck:
        return await self.inner.async_check_link(link)

    # Writes.

    async def async_add_link(self, link: Link) -> LinkResult:
        return await self._write(link, adding=True)

    async def async_remove_link(self, link: Link) -> LinkResult:
        return await self._write(link, adding=False)

    async def _write(self, link: Link, *, adding: bool) -> LinkResult:
        """Perform one write, recording what was in flight while it was open."""
        identity = link.source.identity
        if identity in self.in_flight:
            self.overlapped.append(identity)
        self.in_flight.append(identity)
        self.peak = max(self.peak, len(self.in_flight))
        self.writes.append(link.fingerprint)
        self.attempts[link.fingerprint] += 1
        try:
            if self.before_write is not None:
                await self.before_write(link)
            for _ in range(self._yields):
                await asyncio.sleep(0)
            return await self._outcome(link, adding=adding)
        finally:
            self.in_flight.remove(identity)

    async def _outcome(self, link: Link, *, adding: bool) -> LinkResult:
        """Return what this write does: a condition the test asked for, or the real thing."""
        if link.fingerprint in self.hang:
            await asyncio.Event().wait()
        if link.fingerprint in self.raise_on:
            raise ConnectionError(f"the driver dropped while writing {link.fingerprint}")
        if self.fail_times.get(link.fingerprint, 0) > 0:
            self.fail_times[link.fingerprint] -= 1
            return LinkResult(
                status=LinkResultStatus.FAILED,
                reason=Diagnostic("link_write_failed", {"link": link.fingerprint}),
                raw_error="ZW0201: transmit failed",
            )
        if link.fingerprint in self.block:
            return LinkResult(
                status=LinkResultStatus.BLOCKED,
                reason=Diagnostic("blocked_for_the_test", {"link": link.fingerprint}),
            )
        result = await (
            self.inner.async_add_link(link) if adding else self.inner.async_remove_link(link)
        )
        if self.after_write is not None:
            await self.after_write(link)
        return result

    # Settings and subscriptions, passed straight through.

    async def async_read_setting(self, handle: DeviceHandle, capability: str) -> SettingValue:
        return await self.inner.async_read_setting(handle, capability)

    async def async_write_setting(
        self, handle: DeviceHandle, capability: str, value: int
    ) -> SettingResult:
        return await self.inner.async_write_setting(handle, capability, value)

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        return self.inner.subscribe(callback)

    def wake_instructions(self, handle: DeviceHandle) -> str | None:
        return self.inner.wake_instructions(handle)
