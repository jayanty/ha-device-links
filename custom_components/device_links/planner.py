"""Planning: what is wanted against what is there, and what may be done about the difference.

This is where the safety rules stop being prose. Everything this module refuses to do is
something that could otherwise damage a working home, so the refusals live here in the pure
core rather than in the UI above it, where a second caller, a service call or a future panel
could route around them.

Two of them are absolute:

- **A system link is never planned for removal.** A Z-Wave lifeline is how a device reports
  to Home Assistant at all. Removing one stops the reporting, gives the user no signal that
  it happened, and leaves them no easy way to put it back. No rule, no ownership record and
  no explicit selection makes one removable.
- **An unmanaged link is never removed by default** (Decision D9). These are associations
  somebody made by hand, possibly years ago, in Z-Wave JS UI or with a scene controller's own
  buttons. They are reported and offered for removal one at a time, and nothing else.

Blocked items carry a `Diagnostic`: a translation key and placeholders, never a sentence.
The keys reach `strings.json` when the Home Assistant layer surfaces them.

It is pure: no Home Assistant import, no I/O and no clock. `Plan.token` is a hash over the
sorted inputs, so two identical inputs produce the same token in a different process, and a
plan built against a state that has since changed is detectable rather than silently applied.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
from typing import Final

from custom_components.device_links.models import (
    DeviceCapabilities,
    Diagnostic,
    Link,
    ObservedLink,
    Plan,
    PlanItem,
    PlanOp,
)

# Removals go out before adds on the same device, because a removal frees a slot in a group
# an add may be waiting for. Blocked items carry no write and come last, where they read as
# what the plan could not do rather than as part of what it will.
_OP_ORDER: Final[Mapping[PlanOp, int]] = {
    PlanOp.REMOVE: 0,
    PlanOp.SET_PARAM: 1,
    PlanOp.ADD: 2,
    PlanOp.PENDING: 3,
    PlanOp.BLOCKED: 4,
}


def build_plan(
    *,
    desired: Sequence[Link],
    observed: Sequence[ObservedLink],
    capabilities: Mapping[str, DeviceCapabilities],
    remove_unmanaged: frozenset[str] = frozenset(),
) -> Plan:
    """Return everything that would happen if this plan were applied, and nothing else.

    `desired` is what the enabled rules compile to; `observed` is what the devices actually
    hold; `capabilities` is keyed by `DeviceHandle.identity` and supplies group capacities.
    `remove_unmanaged` holds the fingerprints of links the user has explicitly chosen to take
    off, which is the only way an unmanaged link is ever written about.
    """
    wanted = {link.fingerprint: link for link in desired}
    present = {entry.fingerprint: entry for entry in observed}
    state = _classify(wanted, present, remove_unmanaged)
    items = [
        PlanItem(op=PlanOp.REMOVE, device_identity=entry.source.identity, link=entry)
        for entry in state.removals
    ]
    items.extend(_planned_adds(wanted, present, state.survivors, capabilities))
    items.sort(key=_ordering)
    return Plan(
        token=_token(wanted, present, remove_unmanaged, capabilities),
        items=tuple(items),
        unmanaged=tuple(sorted(state.unmanaged, key=lambda entry: entry.fingerprint)),
        unchanged_count=state.unchanged,
    )


@dataclass(slots=True)
class _Classification:
    """What each observed entry turned out to be, and what that means for the device."""

    removals: list[ObservedLink] = field(default_factory=list)
    unmanaged: list[ObservedLink] = field(default_factory=list)
    survivors: list[ObservedLink] = field(default_factory=list)
    unchanged: int = 0


def _classify(
    wanted: Mapping[str, Link],
    present: Mapping[str, ObservedLink],
    remove_unmanaged: frozenset[str],
) -> _Classification:
    """Sort what is on the devices into what stays, what goes, and what is only reported.

    The order of the tests is the safety rule. `is_system` is asked first, so no later
    question can reach a lifeline: not an ownership record claiming it, and not an explicit
    selection of it. Then a link a rule wants, which is accounted for and so is neither
    foreign nor removable. Only then ownership, which is what makes a link ours to take back
    off, and finally everything else, which is somebody's own work and is reported untouched.
    A selected unmanaged link is still reported: it is a foreign link that was found, and the
    report is what the user is deciding about.
    """
    state = _Classification()
    for entry in present.values():
        if entry.is_system:
            state.survivors.append(entry)
        elif entry.fingerprint in wanted:
            state.unchanged += 1
            state.survivors.append(entry)
        elif entry.managed_by is not None:
            state.removals.append(entry)
        else:
            state.unmanaged.append(entry)
            if entry.fingerprint in remove_unmanaged:
                state.removals.append(entry)
            else:
                state.survivors.append(entry)
    return state


def _planned_adds(
    wanted: Mapping[str, Link],
    present: Mapping[str, ObservedLink],
    survivors: Sequence[ObservedLink],
    capabilities: Mapping[str, DeviceCapabilities],
) -> list[PlanItem]:
    """Return an add for each wanted link that is missing, blocking what will not fit.

    Adds are considered in fingerprint order, which depends on nothing but the links
    themselves: which one loses the last slot in a group has to be the same answer in every
    process, or the plan token and the dialog would both change for no reason a user can see.

    A group's capacity is counted against the entries that will survive this plan, so a
    removal earlier in the plan really does free the slot. A group no control claims, or a
    device the capabilities do not describe, has an unknown capacity and fails closed: an
    unknown group could be anything, including full.
    """
    used: dict[tuple[str, str], int] = {}
    for entry in survivors:
        key = (entry.source.identity, entry.emitter_group)
        used[key] = used.get(key, 0) + 1

    items: list[PlanItem] = []
    for fingerprint in sorted(wanted):
        if fingerprint in present:
            continue
        link = wanted[fingerprint]
        identity = link.source.identity
        key = (identity, link.emitter_group)
        capacity = _capacity_of(capabilities, identity, link.emitter_group)
        if capacity is None:
            items.append(_blocked(link, Diagnostic("unknown_group", _group_placeholders(link))))
        elif used.get(key, 0) >= capacity:
            items.append(
                _blocked(
                    link,
                    Diagnostic(
                        "group_full",
                        _group_placeholders(link)
                        | {"used": str(used.get(key, 0)), "capacity": str(capacity)},
                    ),
                )
            )
        else:
            used[key] = used.get(key, 0) + 1
            items.append(PlanItem(op=PlanOp.ADD, device_identity=identity, link=link))
    return items


def _blocked(link: Link, reason: Diagnostic) -> PlanItem:
    """Return the item for a link that will not be written, and why."""
    return PlanItem(
        op=PlanOp.BLOCKED, device_identity=link.source.identity, link=link, reason=reason
    )


def _group_placeholders(link: Link) -> dict[str, str]:
    """Return the placeholders every group-level message needs to be actionable."""
    return {
        "group": link.emitter_group,
        "device": link.source.name_at_authoring,
        "target": link.target.handle.name_at_authoring,
    }


def _capacity_of(
    capabilities: Mapping[str, DeviceCapabilities], identity: str, group: str
) -> int | None:
    """Return how many entries this group holds, or None when nothing here knows."""
    device = capabilities.get(identity)
    if device is None:
        return None
    for emitter in device.emitters:
        if group in emitter.group_ids:
            return emitter.capacity
    return None


def _ordering(item: PlanItem) -> tuple[str, int, str]:
    """Return the sort key that makes a plan the same plan every time it is built."""
    return (
        item.device_identity,
        _OP_ORDER[item.op],
        "" if item.link is None else item.link.fingerprint,
    )


def _token(
    wanted: Mapping[str, Link],
    present: Mapping[str, ObservedLink],
    remove_unmanaged: frozenset[str],
    capabilities: Mapping[str, DeviceCapabilities],
) -> str:
    """Return a stable hash of everything the plan was built from, and nothing else.

    Exactly four things decide what a plan does, so exactly four things go into the token:
    the links wanted, the links present together with whether each is a system link and
    whether anyone owns it, the selection of unmanaged links to remove, and the capacity of
    each group involved. Each is sorted, so neither dict ordering nor the order a driver
    listed a device's entries can change the answer, and nothing is read from a clock.

    What is left out matters as much. Device names, rule ids, emitter ids and labels can all
    change without changing a single write, and a token that moved with them would refuse
    plans that were still perfectly good, which teaches users to re-plan reflexively and
    devalues the one refusal that matters. A selection naming a link no device holds is
    dropped for the same reason. Capacities are taken only for the groups this plan touches,
    because those are the only ones it consults.
    """
    groups = sorted(
        {(link.source.identity, link.emitter_group) for link in wanted.values()}
        | {(entry.source.identity, entry.emitter_group) for entry in present.values()}
    )
    parts = (
        [f"desired\x1f{fingerprint}" for fingerprint in sorted(wanted)]
        + [
            f"observed\x1f{fingerprint}\x1f{_ownership(present[fingerprint])}"
            for fingerprint in sorted(present)
        ]
        + [f"remove\x1f{fingerprint}" for fingerprint in sorted(remove_unmanaged & present.keys())]
        + [
            f"capacity\x1f{identity}\x1f{group}\x1f{_capacity_of(capabilities, identity, group)}"
            for identity, group in groups
        ]
    )
    return hashlib.sha256("\x1e".join(parts).encode()).hexdigest()


def _ownership(entry: ObservedLink) -> str:
    """Say what an observed entry is to us, which is what decides what may be done to it."""
    if entry.is_system:
        return "system"
    return "managed" if entry.managed_by is not None else "unmanaged"
