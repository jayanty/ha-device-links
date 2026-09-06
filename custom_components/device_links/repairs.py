"""Repairs: the four things a user has to be told, and the rule for taking them back.

**An issue is withdrawn the moment its cause is gone.** That is the property this module
is built around, not the raising. An issue that outlives its cause teaches people to
ignore the Repairs panel, and a panel nobody reads is worse than one nothing was ever
written to. So nothing here remembers what it raised: every check computes the whole set
of issues that should exist right now, and everything of ours that is not in that set is
deleted. A condition that clears cannot leave an issue behind, because no code path
exists that would keep one.

The four:

- **E1**, a backend that stopped answering. Not "the upstream integration is missing":
  with one adapted protocol, that state fails setup with `ConfigEntryNotReady` and the
  entry never loads. What is reachable, and what a user actually meets, is Z-Wave JS
  restarting underneath a loaded integration, which leaves every device unreadable and
  every rule unknown.
- **E5**, a write queued at a sleeping device for more than a day. Below that it is
  normal: a battery remote wakes when it wakes, and a Repairs issue for the documented
  behaviour of a battery device is noise.
- **E19**, a rule naming a device that is not on the network. Deliberately not the same
  question as "can we read it": a node that is asleep or a backend that is restarting
  makes a rule `unknown` (E4), and raising the swap-flow issue for that is how somebody
  learns to dismiss it.
- **E18**, stored data that could not be read at all. The entry does not load in that
  state, so this issue is the only thing that can explain what happened, and it names the
  file so the user can move it aside.

**Two of the four cannot be noticed by an event.** A queued write ages without anything
happening: no device answers, no state moves, nothing fires. So the checks also run on a
timer, which is what makes "more than a day" a real threshold rather than one that only
triggers when something else happens to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STORAGE_KEY

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from . import DeviceLinksConfigEntry, DeviceLinksRuntimeData
    from .coordinator import DeviceLinksCoordinator
    from .storage import StorageSchemaError

_LOGGER = logging.getLogger(__name__)

ISSUE_BACKEND_UNAVAILABLE: Final = "backend_unavailable"
ISSUE_PENDING_WAKEUP: Final = "pending_wakeup"
# The same issue, said differently because the profile database knows how to wake this
# model. Two keys rather than one with an optional placeholder: a sentence with a hole in
# it where the instruction should be is worse than a sentence that does not promise one.
ISSUE_PENDING_WAKEUP_INSTRUCTED: Final = "pending_wakeup_instructed"
ISSUE_RULES_MISSING_DEVICES: Final = "rules_missing_devices"
ISSUE_STORAGE_UNREADABLE: Final = "storage_unreadable"

# E5 says 24 hours. A battery remote that has not been touched for a day is one where
# something is wrong with the device or with the mesh, rather than one nobody has pressed.
PENDING_WAKEUP_AFTER: Final = timedelta(hours=24)

# How often the checks run when nothing has happened. Hourly, because the only threshold
# that needs a clock is a day long, and a check that costs nothing is still a wake-up.
RECHECK_INTERVAL: Final = timedelta(hours=1)

# Where the file is, as the user has to be able to find it.
STORAGE_PATH: Final = f".storage/{STORAGE_KEY}"


@dataclass(frozen=True, slots=True)
class _Issue:
    """One issue that should exist right now: what it says, and how loudly."""

    translation_key: str
    severity: ir.IssueSeverity
    placeholders: dict[str, str]


@callback
def async_setup_repairs(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> None:
    """Start watching for the conditions E1, E5 and E19 describe.

    Two triggers, because two of the conditions have no event behind them: the coordinator
    tells us whenever anything it knows changed, and the timer covers the passage of time
    itself. Both are unregistered with the entry, so neither outlives it.
    """
    coordinator = entry.runtime_data.coordinator

    @callback
    def _check() -> None:
        async_check_issues(hass, entry)

    @callback
    def _on_timer(_now: datetime) -> None:
        _check()

    entry.async_on_unload(coordinator.async_add_listener(_check))
    entry.async_on_unload(async_track_time_interval(hass, _on_timer, RECHECK_INTERVAL))
    _check()


@callback
def async_check_issues(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> None:
    """Raise every issue that should exist now, and withdraw everything else of ours."""
    runtime = entry.runtime_data
    wanted: dict[str, _Issue] = {}
    _backends(runtime, wanted)
    _pending_wakeups(runtime, wanted)
    _missing_devices(runtime, wanted)

    registry = ir.async_get(hass)
    existing = {issue_id for (domain, issue_id) in list(registry.issues) if domain == DOMAIN}
    for issue_id in sorted(existing - set(wanted)):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    for issue_id, issue in sorted(wanted.items()):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=issue.severity,
            translation_key=issue.translation_key,
            translation_placeholders=issue.placeholders,
        )


@callback
def async_clear_issues(hass: HomeAssistant) -> None:
    """Withdraw every issue this integration raised, because it is going away.

    An unloaded integration is not reporting on anything and cannot re-evaluate any of
    this, so leaving an issue behind would leave somebody reading about a backend that
    stopped answering for an integration that is no longer running.
    """
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_raise_storage_issue(hass: HomeAssistant, error: StorageSchemaError) -> None:
    """Say that the stored profiles could not be read, and where the file is (E18).

    Raised from a setup that is about to fail, so this is the only thing that will explain
    to the user why the integration is not there. The file is deliberately left exactly as
    it is: it is somebody's work, and the fix is theirs to choose.
    """
    _LOGGER.error(
        "the stored profiles in %s could not be read, so the integration did not start "
        "and the file was left untouched: %s",
        STORAGE_PATH,
        error,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_STORAGE_UNREADABLE,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_STORAGE_UNREADABLE,
        translation_placeholders={"path": STORAGE_PATH, "error": str(error)},
    )


def _backends(runtime: DeviceLinksRuntimeData, wanted: dict[str, _Issue]) -> None:
    """Add an issue for every backend that is not answering (E1)."""
    availability = runtime.coordinator.backend_availability
    for info in runtime.backend_info:
        if not availability.get(info.backend_id, False):
            wanted[f"{ISSUE_BACKEND_UNAVAILABLE}_{info.backend_id}"] = _Issue(
                translation_key=ISSUE_BACKEND_UNAVAILABLE,
                severity=ir.IssueSeverity.ERROR,
                placeholders={
                    "backend": str(info.backend_id),
                    "integration": info.upstream_domain,
                },
            )


def _pending_wakeups(runtime: DeviceLinksRuntimeData, wanted: dict[str, _Issue]) -> None:
    """Add an issue per device holding a write that has been queued too long (E5).

    Per device rather than per link, because waking a device answers every write queued at
    it, and four issues about one remote is four times the noise for one action.

    A queued write whose rule has since been deleted is not reported, and that is a
    limitation rather than a decision: a job records fingerprints, and the device a
    fingerprint belongs to is only knowable here by matching it against what the active
    profile compiles to. Nothing is lost by it: when the device wakes, the write lands, and
    the link it made shows up as unmanaged on the next read, which is what a link nobody
    has a rule for is.
    """
    coordinator = runtime.coordinator
    pending = coordinator.pending_link_fingerprints()
    if not pending:
        return
    since = _pending_since(coordinator)
    cutoff = dt_util.utcnow() - PENDING_WAKEUP_AFTER
    profile = coordinator.active_profile
    waiting: dict[str, int] = {}
    for rule in profile.rules if profile is not None else ():
        compiled = coordinator.compiled_for(rule.id)
        for link in compiled.links if compiled is not None else ():
            if link.fingerprint in pending and since.get(link.fingerprint, cutoff) < cutoff:
                waiting[link.source.identity] = waiting.get(link.source.identity, 0) + 1
    for identity, count in waiting.items():
        handle = coordinator.handle_for(identity)
        if handle is None:
            continue
        backend = coordinator.backend_for(handle)
        instruction = None if backend is None else backend.wake_instructions(handle)
        placeholders = {
            "device": handle.name_at_authoring,
            "links": str(count),
            "hours": str(int(PENDING_WAKEUP_AFTER.total_seconds() // 3600)),
        }
        if instruction is not None:
            placeholders["instruction"] = instruction
        wanted[f"{ISSUE_PENDING_WAKEUP}_{identity}"] = _Issue(
            translation_key=(
                ISSUE_PENDING_WAKEUP if instruction is None else ISSUE_PENDING_WAKEUP_INSTRUCTED
            ),
            severity=ir.IssueSeverity.WARNING,
            placeholders=placeholders,
        )


def _pending_since(coordinator: DeviceLinksCoordinator) -> Mapping[str, datetime]:
    """Return when each queued write was queued, by fingerprint.

    The latest job to mention a fingerprint is the one that counts, exactly as the
    coordinator decides whether it is still pending: a later apply that landed answers an
    earlier one that was queued.
    """
    now = dt_util.utcnow()
    since: dict[str, datetime] = {}
    for job in coordinator.state.jobs:
        queued = dt_util.parse_datetime(job.created_at) or now
        for result in job.results:
            since[result.fingerprint] = queued
    return since


def _missing_devices(runtime: DeviceLinksRuntimeData, wanted: dict[str, _Issue]) -> None:
    """Add one issue naming every rule whose device is not on the network (E19).

    One issue for all of them, because the answer is the same for each: the swap flow,
    when Phase 2 brings it. Until then, saying which rules are stranded and which devices
    they are waiting for is what a user can act on.

    Presence is asked of the network rather than of the Home Assistant device registry.
    A registry entry can be missing for a device that is perfectly alive (Zigbee and
    Matter handles cannot be resolved to one at all yet), and an issue that fired for that
    would be wrong on every install that has one.
    """
    coordinator = runtime.coordinator
    profile = coordinator.active_profile
    if profile is None:
        return
    rules: set[str] = set()
    devices: set[str] = set()
    for rule in profile.rules:
        for handle in (rule.source.device, *(target.device for target in rule.targets)):
            if coordinator.handle_for(handle.identity) is None:
                rules.add(rule.id)
                devices.add(handle.name_at_authoring)
    if not rules:
        return
    wanted[ISSUE_RULES_MISSING_DEVICES] = _Issue(
        translation_key=ISSUE_RULES_MISSING_DEVICES,
        severity=ir.IssueSeverity.WARNING,
        placeholders={
            "count": str(len(rules)),
            "rules": ", ".join(sorted(rules)),
            "devices": ", ".join(sorted(devices)),
        },
    )
