"""The seam between the core and the protocols: one Backend, many implementations.

Core code (the coordinator, the executor, the WebSocket API) depends on this module and on
nothing protocol-specific. Z-Wave is here today, Zigbee and Matter arrive later, and neither
arrival changes a line of core code: each is a new module implementing `Backend`, and core
code never branches on which one it is holding. That property is worth defending, so
`tests/test_backend_base.py` fails if anything Z-Wave, Zigbee, Matter or MQTT is imported
into this file.

The result types are here rather than in `models.py` because they describe what an adapter
answers, not what a rule means. They are frozen and validate on construction: a `FAILED`
result with no reason, or a refusal with nothing to tell the user, is the shape that turns
into an untriageable job log, so it cannot be built at all.

This module may import Home Assistant (it is not in the enforced `PURE_MODULES` list), but
it does not need to, and it does not: the only Home Assistant type it would use is
`CALLBACK_TYPE`, which is `Callable[[], None]` spelled out below. Staying import-free keeps
this usable from `tools/` probe scripts alongside the pure modules.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Diagnostic,
    Link,
    ObservedLink,
)


class SystemScope(StrEnum):
    """What a backend's `ObservedLink.is_system` mark applies to.

    The one place two protocols mean genuinely different things by the same flag, so each
    backend says which, and core asks rather than guessing. Both sentences are worth having
    where the decision lives:

    - **Z-Wave is `SLOT`**: an association group has one purpose, so a group holding the
      controller is a lifeline and nothing else may ever go into it, whatever we are trying
      to put there.
    - **Zigbee is `ENTRY`**: an endpoint's cluster is a table of independent bindings, so a
      reporting binding to the coordinator protects itself and nothing beside it.

    Asking by slot everywhere was open item T49. It is right for Z-Wave and false on Zigbee,
    where Zigbee2MQTT puts a reporting binding on exactly the endpoint and cluster a button's
    presses come from: every rule from the first Zigbee remote added to a network would have
    been refused with no way out from the UI.

    A backend that is unsure answers `SLOT`, which refuses more than it must rather than
    less: this flag guards CLAUDE.md Section 3 rule 4, and the safe direction to be wrong in
    is the one that declines to write.
    """

    SLOT = "slot"
    ENTRY = "entry"


class LinkResultStatus(StrEnum):
    """What became of one link the executor asked a backend to write.

    These five are the whole space (FR-A2): a missing one is an unhandled case in a job
    summary rather than a compile error, which is why they are named here once and matched
    exhaustively everywhere else.
    """

    APPLIED = "applied"
    ALREADY_PRESENT = "already_present"
    PENDING_WAKEUP = "pending_wakeup"
    FAILED = "failed"
    BLOCKED = "blocked"


# The outcomes that owe the user an explanation. A blocked link the user cannot be told
# about is a refusal they cannot act on, and a failure with no reason cannot be triaged
# from a job log, so both are refused at construction rather than discovered in support.
_STATUSES_NEEDING_A_REASON = frozenset({LinkResultStatus.FAILED, LinkResultStatus.BLOCKED})


@dataclass(frozen=True, slots=True)
class LinkResult:
    """The outcome of writing (or declining to write) one link.

    `reason` is a translation key and its placeholders, never an English sentence.
    `raw_error` is the backend's own untranslated text, kept because PRD Section 9 wants it
    visible under an expander for issue reports. It is never shown as the primary message:
    "ZW0201: transmit failed" is for the person filing the bug, not for the person whose
    light did not turn on.
    """

    status: LinkResultStatus
    reason: Diagnostic | None = None
    raw_error: str | None = None

    def __post_init__(self) -> None:
        """Refuse an outcome that cannot be explained to the user who caused it."""
        if self.status in _STATUSES_NEEDING_A_REASON and self.reason is None:
            raise ValueError(f"a {self.status} link result must carry a reason")


@dataclass(frozen=True, slots=True)
class LinkCheck:
    """Whether a link could be written, asked without writing it (PRD Section 8.3)."""

    ok: bool
    reason: Diagnostic | None = None

    def __post_init__(self) -> None:
        """Refuse a refusal that says nothing."""
        if not self.ok and self.reason is None:
            raise ValueError("a failing link check must carry a reason")


@dataclass(frozen=True, slots=True)
class SettingValue:
    """One named device setting as it currently reads.

    `parameter` and `bitmask` are where the setting really lives, carried alongside the
    value so a diagnostic can say which parameter was read without resolving the adapter a
    second time. `bitmask` is None when the setting owns the whole parameter, and `value`
    is None when the device has not reported it yet.
    """

    capability: str
    parameter: int
    bitmask: int | None
    value: int | None


@dataclass(frozen=True, slots=True)
class SettingResult:
    """The outcome of writing one named device setting.

    `read_back` is what the device reported after the write (PRD Section 8.4 requires the
    read-back), so a write that was accepted and then ignored is visible rather than
    reported as success.
    """

    ok: bool
    read_back: int | None = None
    reason: Diagnostic | None = None

    def __post_init__(self) -> None:
        """Refuse a failed write that says nothing."""
        if not self.ok and self.reason is None:
            raise ValueError("a failed setting write must carry a reason")


@dataclass(frozen=True, slots=True)
class BackendDevice:
    """One device a backend can see.

    A named type rather than a bare handle because `async_devices` is the listing the
    coordinator builds its device view from, and what a listing has to say about a device
    grows (readiness, availability) without the protocol's shape changing under it.
    """

    handle: DeviceHandle


@dataclass(frozen=True, slots=True)
class ObservedDevice:
    """What a device really has on it right now, which the planner diffs against.

    `links` are the associations, bindings or ACL entries read back from the device, with
    `is_system` already set on the ones that are never ours to remove. `settings` are the
    named settings the profile database knows about, by capability name, so the planner can
    see a setting that is already right and not plan a write for it.

    The three deep-verify fields exist to keep "the device confirmed this" apart from "this
    is what we had cached", which is the whole value of a verify. A deep read that was asked
    for and could not be confirmed is reported as such rather than as a normal answer,
    because reporting it as confirmation is worse than not verifying at all: it looks like
    assurance. `deep_verified` is true only when the device actually answered;
    `deep_verify_timed_out` says it was asked and did not answer in time; and
    `deep_verify_skipped_reason` says it was never asked, and why. A shallow read leaves all
    three at their defaults, so it can never be mistaken for a confirmed one.
    """

    handle: DeviceHandle
    links: tuple[ObservedLink, ...]
    settings: Mapping[str, int] = field(default_factory=dict)
    deep_verified: bool = False
    deep_verify_timed_out: bool = False
    deep_verify_skipped_reason: str | None = None


@runtime_checkable
class Backend(Protocol):
    """What every protocol adapter offers, and the only backend surface core code sees.

    Not to be confused with `models.Backend`, which is the StrEnum naming the protocols
    ("zwave", "zigbee2mqtt", "matter"). They are different kinds of thing that happen to
    share a good name: this one is the adapter interface, that one is an id. A module
    needing both imports the enum as `BackendId`
    (`from custom_components.device_links.models import Backend as BackendId`), which is
    what `backends/zwave.py` does, and `tests/test_backend_base.py` pins that neither can
    pass for the other.

    Implementations fetch, translate and write. Every decision that can be made without
    touching a radio belongs in the pure modules (`compiler.py`, `planner.py`, the
    `*_protocol.py` modules), where it can be property-tested: a branch in an adapter that
    does not touch its client is a branch in the wrong place.
    """

    async def async_devices(self) -> list[BackendDevice]:
        """Return every device this backend can address."""

    async def async_capabilities(self, handle: DeviceHandle) -> DeviceCapabilities:
        """Return what this device can emit and receive, and the settings it exposes."""

    async def async_observed(self, handle: DeviceHandle, deep: bool = False) -> ObservedDevice:
        """Return what is really on this device now.

        `deep` asks for the device to be re-read rather than the client's cache trusted.
        It costs radio time, so it is opt-in per request.
        """

    async def async_check_link(self, link: Link) -> LinkCheck:
        """Say whether this link could be written, without writing it."""

    async def async_add_link(self, link: Link) -> LinkResult:
        """Write one link to the device, or explain why it was not written."""

    async def async_remove_link(self, link: Link) -> LinkResult:
        """Remove one link from the device, or explain why it was not removed."""

    async def async_read_setting(self, handle: DeviceHandle, capability: str) -> SettingValue:
        """Read one named setting off the device."""

    async def async_write_setting(
        self, handle: DeviceHandle, capability: str, value: int
    ) -> SettingResult:
        """Write one named setting to the device and read it back."""

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        """Call `callback` with a device identity whenever that device's state changes.

        Returns the unsubscribe callable. It must remove every listener it registered: one
        that outlives a config entry unload fires against a dead entry, survives a reload,
        and is exactly the leak nobody finds.
        """

    def wake_instructions(self, handle: DeviceHandle) -> str | None:
        """Return how a user wakes this device, or None when it is always listening."""

    def system_scope(self) -> SystemScope:
        """Return whether this protocol's system entries reserve their whole slot.

        A constant per adapter rather than a question about one link: it is a fact about the
        protocol, not about a device, and answering it per link would invite an adapter to
        make it depend on state. See `SystemScope` for what each answer means.
        """
