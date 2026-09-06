"""Pure Z-Wave interpretation: association groups in, capability model out.

This module is how Device Links avoids hardcoding device models. It reads the association
group dump a Z-Wave device reports about itself and works out what each of its controls can
do, so the compiler can express "this button controls that light, with dimming" without ever
knowing what a ZEN35 is.

It is pure: no Home Assistant import, no I/O, no clock. It is handed already-parsed data and
returns value types, which is what lets it be tested directly against the fixtures Stage 0
captured from real hardware and reused from `tools/` probe scripts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Final, TypedDict

from custom_components.device_links.models import Emitter, Feature
from custom_components.device_links.profile_db import ProfileEmitter, ProfileEntry

# Command class ids exactly as they appear in a group's `issued_commands`.
BASIC_CC: Final = 32
BINARY_SWITCH_CC: Final = 37
MULTILEVEL_SWITCH_CC: Final = 38
SCENE_ACTIVATION_CC: Final = 43

# The commands within those classes that say something about what a group can carry.
BASIC_SET: Final = 1
BINARY_SWITCH_SET: Final = 1
MULTILEVEL_SET: Final = 1
MULTILEVEL_REPORT: Final = 3
MULTILEVEL_START_LEVEL_CHANGE: Final = 4
MULTILEVEL_STOP_LEVEL_CHANGE: Final = 5
SCENE_ACTIVATION_SET: Final = 1

# Where a Z-Wave control drives from. Association groups are reported per endpoint and every
# control Device Links offers is on the root, so this is the endpoint every Z-Wave emitter
# carries (`models.Emitter.endpoint`). It is 0 rather than None because a Z-Wave association
# really is written from the root endpoint; what a Z-Wave link leaves unset is the *target*
# endpoint, which is a different question and stays None.
ROOT_ENDPOINT: Final = 0

# JSON gives string command class keys and the live driver gives integers, so the map is
# keyed by the normalized integer form and both shapes are accepted at the boundary.
type IssuedCommands = Mapping[str, Sequence[int]] | Mapping[int, Sequence[int]]

_FEATURE_BY_COMMAND: Final[Mapping[tuple[int, int], Feature]] = {
    (BASIC_CC, BASIC_SET): Feature.ON_OFF,
    (BINARY_SWITCH_CC, BINARY_SWITCH_SET): Feature.ON_OFF,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_SET): Feature.LEVEL_SET,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_START_LEVEL_CHANGE): Feature.LEVEL_HOLD,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_STOP_LEVEL_CHANGE): Feature.LEVEL_HOLD,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_REPORT): Feature.STATUS_REPORT,
    (SCENE_ACTIVATION_CC, SCENE_ACTIVATION_SET): Feature.SCENE,
}


def features_of_group(issued: IssuedCommands | None) -> frozenset[Feature]:
    """Return the features a group can carry, given the commands it issues.

    Start and stop level change are one feature, not two: hold-to-dim is a single thing a
    user asks for. A command the map does not know contributes nothing, so an unrecognised
    group offers the user no capability rather than one that would not work.
    """
    if issued is None:
        return frozenset()
    return frozenset(
        feature
        for command_class, commands in issued.items()
        for command in commands
        if (feature := _FEATURE_BY_COMMAND.get((int(command_class), command))) is not None
    )


# How an emitter's groups were decided, reported on every emitter so the UI and the
# diagnostics can say how much of the grouping was inferred.
GROUPING_PROFILE: Final = "profile"
GROUPING_PER_GROUP: Final = "per_group"
GROUPING_PROFILE_DB: Final = "profile_db"

# Trailing separators vendors put between a control's name and the action it performs, so
# that the shared part of "Main Button - Pressed" and "Main Button - Held" reads as
# "Main Button" rather than "Main Button - ".
_LABEL_TRAILING: Final = " \t-/:,.("


# Long Range node ids start here, and `Protocols.ZWAVE_LONG_RANGE` is 1 (Stage 0 Z2).
FIRST_LONG_RANGE_NODE_ID: Final = 256
LONG_RANGE_PROTOCOL: Final = 1

# Group 1 is the lifeline on every Z-Wave device, which is what the fallback below leans on.
LIFELINE_GROUP: Final = "1"

# Which feature speaks for a group that issues commands for more than one. On/off first
# because an association a user made is nearly always about switching, and status report
# last because it is what a group that controls nothing does.
_PRIMARY_FEATURE_ORDER: Final = (
    Feature.ON_OFF,
    Feature.LEVEL_SET,
    Feature.LEVEL_HOLD,
    Feature.SCENE,
    Feature.COLOR,
    Feature.STATUS_REPORT,
)


class AssociationGroup(TypedDict):
    """One association group of one endpoint, as the Z-Wave driver reports it."""

    is_lifeline: bool
    issued_commands: IssuedCommands
    label: str
    max_nodes: int
    multi_channel: bool
    profile: int | None


@dataclass(frozen=True, slots=True)
class _UsableGroup:
    """A non-lifeline group that carries at least one feature, with what it carries."""

    group_id: str
    group: AssociationGroup
    features: frozenset[Feature]


def is_long_range(node_id: int, protocol: int | None) -> bool:
    """Say whether this node joined over Long Range, which fixes it out of associations.

    Two answers to one question, because either can be missing. The protocol the driver
    reports is authoritative when there is one; the node id settles it when there is not,
    because Long Range ids start at 256 and the protocol is fixed at inclusion time and
    never changes afterwards (CLAUDE.md Section 10). Either saying yes is enough: an LR node
    reported as classic would be offered as an association source, and the write would fail
    at the radio with an error the user cannot act on.
    """
    return protocol == LONG_RANGE_PROTOCOL or node_id >= FIRST_LONG_RANGE_NODE_ID


def is_lifeline_group(groups: Mapping[str, AssociationGroup], group_id: str) -> bool:
    """Say whether this group is the device's lifeline, which is never ours to write.

    The device's own report decides, because the lifeline is what it says it is. A group
    the device does not report at all falls back to group 1, which is the lifeline on every
    Z-Wave device ever certified: an unknown group is the case where being wrong means
    removing the association that makes a device report to Home Assistant at all, so the
    fallback answers yes rather than shrugging.
    """
    group = groups.get(group_id)
    if group is None:
        return group_id == LIFELINE_GROUP
    return group["is_lifeline"]


def feature_of_group(group: AssociationGroup) -> Feature:
    """Return the one feature an association entry in this group carries.

    An association is one entry on the device, so it has to become one link, and a link
    names one feature. Every non-lifeline group in the Stage 0 capture issues commands for
    exactly one feature, so this is usually not a choice at all. When a group does issue
    more, the most primary one wins (an on/off group that also dims is an on/off group), and
    when it issues nothing Device Links can use, the entry is reporting rather than
    controlling: that is what a lifeline is, and `STATUS_REPORT` is what it does.

    Splitting a multi-feature group into one link per feature instead would double count it
    against the group's capacity, which the planner counts one entry at a time.
    """
    features = features_of_group(group["issued_commands"])
    return next(
        (feature for feature in _PRIMARY_FEATURE_ORDER if feature in features),
        Feature.STATUS_REPORT,
    )


def derive_emitters(
    groups: Mapping[str, AssociationGroup], *, warnings: list[str] | None = None
) -> list[Emitter]:
    """Return the physical controls a device offers, one emitter per control.

    The lifeline is never an emitter, and a group that carries no usable feature is dropped
    and appended to `warnings` when a collector is given, so an unusable group is reported
    rather than lost. AGI profile is used to group several groups into one control only when
    it demonstrably identifies one, and otherwise the derivation falls back to one emitter
    per group: a conservative split is recoverable, a confidently wrong merge is not.
    """
    usable = _usable_groups(groups, warnings)
    by_profile = _by_profile(usable)
    if _profile_identifies_one_control(by_profile):
        emitters = [_profile_emitter(members) for members in by_profile.values()]
    else:
        emitters = [
            _build_emitter([member], member.group["label"], GROUPING_PER_GROUP) for member in usable
        ]
    return sorted(emitters, key=lambda emitter: int(emitter.group_ids[0]))


def _usable_groups(
    groups: Mapping[str, AssociationGroup], warnings: list[str] | None
) -> list[_UsableGroup]:
    """Return the non-lifeline groups that carry a feature, reporting the ones that do not."""
    usable: list[_UsableGroup] = []
    for group_id, group in groups.items():
        if group["is_lifeline"]:
            continue
        features = features_of_group(group["issued_commands"])
        if not features:
            if warnings is not None:
                warnings.append(
                    f"association group {group_id} ({group['label']!r}) issues no command "
                    f"Device Links can use, so it is not offered as a control: "
                    f"{group['issued_commands']}"
                )
            continue
        usable.append(_UsableGroup(group_id=group_id, group=group, features=features))
    return usable


def _by_profile(usable: Sequence[_UsableGroup]) -> dict[int | None, list[_UsableGroup]]:
    """Partition groups by their AGI profile, keeping the device's own group order."""
    grouped: dict[int | None, list[_UsableGroup]] = {}
    for member in usable:
        grouped.setdefault(member.group["profile"], []).append(member)
    return grouped


def _profile_identifies_one_control(
    by_profile: Mapping[int | None, Sequence[_UsableGroup]],
) -> bool:
    """Say whether the AGI profile really names a physical control on this device.

    Stage 0 found profile trustworthy on only one of three models, so it has to earn its use
    three times over: every group has a profile (the ZEN37 has a null one), some profile
    covers more than one group (every Inovelli group has its own, so grouping by it would
    split one paddle into three), and no profile covers two groups carrying the same feature
    (two On/Off groups under one profile means the profile is naming a row, not a button).
    """
    if None in by_profile:
        return False
    if not any(len(members) > 1 for members in by_profile.values()):
        return False
    return all(_features_are_disjoint(members) for members in by_profile.values())


def _features_are_disjoint(members: Sequence[_UsableGroup]) -> bool:
    """Say whether no two of these groups offer the same feature."""
    seen: set[Feature] = set()
    for member in members:
        if seen & member.features:
            return False
        seen |= member.features
    return True


def _profile_emitter(members: Sequence[_UsableGroup]) -> Emitter:
    """Build one emitter from the several groups a single profile covers."""
    ordered = sorted(members, key=lambda member: int(member.group_id))
    shared = _shared_label([member.group["label"] for member in ordered])
    return _build_emitter(ordered, shared or ordered[0].group["label"], GROUPING_PROFILE)


def _build_emitter(ordered: Sequence[_UsableGroup], label: str, grouping: str) -> Emitter:
    """Assemble an emitter from its groups, lowest group id first.

    Capacity and endpoint support are the worst case across the groups, because a rule using
    all of them is limited by the tightest one.
    """
    return Emitter(
        emitter_id=f"g{ordered[0].group_id}",
        label=label,
        endpoint=ROOT_ENDPOINT,
        group_ids=tuple(member.group_id for member in ordered),
        actions={
            feature: member.group_id for member in ordered for feature in sorted(member.features)
        },
        capacity=min(member.group["max_nodes"] for member in ordered),
        supports_endpoint_targets=all(member.group["multi_channel"] for member in ordered),
        is_lifeline=False,
        grouping=grouping,
    )


def _shared_label(labels: Sequence[str]) -> str:
    """Return the longest common prefix of these labels, or "" when they share nothing."""
    prefix = labels[0]
    for label in labels[1:]:
        while not label.startswith(prefix):
            prefix = prefix[:-1]
    return prefix.rstrip(_LABEL_TRAILING)


def resolve_emitters(
    groups: Mapping[str, AssociationGroup],
    entry: ProfileEntry | None = None,
    *,
    warnings: list[str] | None = None,
) -> list[Emitter]:
    """Return a device's controls, preferring a curated entry over the generic derivation.

    This is the top of the three tiers: a curated entry keyed by fingerprint, then AGI
    profile when it partitions cleanly, then one emitter per group. The curated entry decides
    the grouping, because that is the whole reason it exists, but it never restates the facts
    the hardware already reports: capacity and endpoint support are read off the groups the
    entry names, so a firmware with a smaller group capacity is honoured rather than
    overridden by a number somebody typed once.

    An entry that contradicts the device is not partially believed. If any group it names is
    missing, is the lifeline, or does not issue the command the entry claims for it, the
    whole entry is set aside and the generic derivation stands, with the contradiction
    appended to `warnings`. An entry that does not describe this device has already been
    shown to be wrong about it, so trusting the rest of its group numbers would be trusting a
    coincidence, and its group numbers are what reach the radio.
    """
    derived = derive_emitters(groups, warnings=warnings)
    if entry is None:
        return derived
    conflicts = _entry_conflicts(entry, groups)
    if conflicts:
        if warnings is not None:
            warnings.extend(conflicts)
        return derived
    derived_ids = {frozenset(emitter.group_ids): emitter.emitter_id for emitter in derived}
    curated = [_curated_emitter(emitter, groups, derived_ids) for emitter in entry.emitters]
    return sorted(curated, key=lambda emitter: int(emitter.group_ids[0]))


def _entry_conflicts(entry: ProfileEntry, groups: Mapping[str, AssociationGroup]) -> list[str]:
    """Return every way this entry disagrees with what the device reports about itself."""
    conflicts: list[str] = []
    for emitter in entry.emitters:
        for feature, group_id in sorted(emitter.actions.items()):
            named = f"profile entry maps {emitter.emitter_id}.{feature} to group {group_id}"
            group = groups.get(group_id)
            if group is None:
                conflicts.append(f"{named}, which this device does not report")
            elif group["is_lifeline"]:
                conflicts.append(f"{named}, which this device reports as its lifeline")
            elif feature not in features_of_group(group["issued_commands"]):
                conflicts.append(
                    f"{named}, which issues {group['issued_commands']} and so cannot carry it"
                )
    return conflicts


def _curated_emitter(
    emitter: ProfileEmitter,
    groups: Mapping[str, AssociationGroup],
    derived_ids: Mapping[frozenset[str], str],
) -> Emitter:
    """Build one emitter from a curated entry, over the groups the device reports.

    A curated emitter that covers exactly the groups one derived emitter covers is the same
    control described twice, so it keeps the derived id: adding a curated entry for a model
    whose grouping was already right must not rename controls out from under the rules
    already written against them. A curated emitter that regroups is a control the derivation
    never offered, so it is named by the entry.
    """
    group_ids = tuple(sorted(set(emitter.actions.values()), key=int))
    members = [groups[group_id] for group_id in group_ids]
    return Emitter(
        emitter_id=derived_ids.get(frozenset(group_ids), emitter.emitter_id),
        label=emitter.label,
        endpoint=ROOT_ENDPOINT,
        group_ids=group_ids,
        actions=dict(emitter.actions),
        capacity=(
            min(member["max_nodes"] for member in members)
            if emitter.capacity_override is None
            else emitter.capacity_override
        ),
        supports_endpoint_targets=all(member["multi_channel"] for member in members),
        is_lifeline=False,
        grouping=GROUPING_PROFILE_DB,
        semantics=emitter.semantics,
    )


class CheckResult(IntEnum):
    """What the driver answers when asked whether an association may be written.

    The values are pinned by Stage 0 item Z3 against the live driver, not by the
    documentation. `OK` is 1, so a truthiness test would read every refusal as success and
    every success as failure.
    """

    OK = 1
    FORBIDDEN_DESTINATION_IS_LONG_RANGE = 2
    FORBIDDEN_SOURCE_IS_LONG_RANGE = 3
    FORBIDDEN_SELF_ASSOCIATION = 4
    FORBIDDEN_SECURITY_CLASS_MISMATCH = 5
    FORBIDDEN_DESTINATION_SECURITY_CLASS_NOT_GRANTED = 6
    FORBIDDEN_NO_SUPPORTED_CCS = 7


@dataclass(frozen=True, slots=True)
class BlockedReason:
    """Why a link cannot be written, as something the user can act on.

    `translation_key` names the message in `strings.json`; `placeholders` fills it in.
    """

    translation_key: str
    placeholders: Mapping[str, str]


_BLOCKED_REASONS: Final[Mapping[int, BlockedReason]] = {
    CheckResult.FORBIDDEN_DESTINATION_IS_LONG_RANGE: BlockedReason("target_is_long_range", {}),
    CheckResult.FORBIDDEN_SOURCE_IS_LONG_RANGE: BlockedReason("source_is_long_range", {}),
    CheckResult.FORBIDDEN_SELF_ASSOCIATION: BlockedReason("self_association", {}),
    CheckResult.FORBIDDEN_SECURITY_CLASS_MISMATCH: BlockedReason("security_class_mismatch", {}),
    CheckResult.FORBIDDEN_DESTINATION_SECURITY_CLASS_NOT_GRANTED: BlockedReason(
        "target_security_class_not_granted", {}
    ),
    CheckResult.FORBIDDEN_NO_SUPPORTED_CCS: BlockedReason("no_supported_commands", {}),
}


def is_ok(value: int) -> bool:
    """Say whether the driver allowed the association, comparing to OK explicitly."""
    return value == CheckResult.OK


def blocked_reason_for(value: int) -> BlockedReason | None:
    """Return why the driver refused this association, or None when it allowed it.

    Only the pinned OK value returns None. Anything the enum does not know, including a
    value a future driver invents, returns the unknown reason, so an unrecognised answer
    fails closed and nothing is written on it.
    """
    if is_ok(value):
        return None
    reason = _BLOCKED_REASONS.get(value)
    if reason is None:
        return BlockedReason("unknown_check_result", {"value": str(value)})
    return reason
