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
from typing import Final, TypedDict

from custom_components.device_links.models import Emitter, Feature

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

# Trailing separators vendors put between a control's name and the action it performs, so
# that the shared part of "Main Button - Pressed" and "Main Button - Held" reads as
# "Main Button" rather than "Main Button - ".
_LABEL_TRAILING: Final = " \t-/:,.("


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
            _emitter([member], member.group["label"], GROUPING_PER_GROUP) for member in usable
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
    return _emitter(ordered, shared or ordered[0].group["label"], GROUPING_PROFILE)


def _emitter(ordered: Sequence[_UsableGroup], label: str, grouping: str) -> Emitter:
    """Assemble an emitter from its groups, lowest group id first.

    Capacity and endpoint support are the worst case across the groups, because a rule using
    all of them is limited by the tightest one.
    """
    return Emitter(
        emitter_id=f"g{ordered[0].group_id}",
        label=label,
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
