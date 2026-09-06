"""Profile diff: what changes if this becomes that, rule by rule and link by link.

FR-P4. Two profiles, or a profile against a snapshot of what the devices held. It is what
makes a rollback or an import comprehensible before it is applied: "import this file" and
"go back to Tuesday" are both a user handing over their whole configuration on trust, and a
diff is the only thing that turns either into a decision.

It is pure, and that is what lets it be the same answer everywhere. Rules and capabilities
in, a description out; no Home Assistant, no I/O, no clock.

**Two levels, because two questions are being asked.** Rule by rule answers "what did I
change": a rule added, a rule gone, a rule whose targets moved. Link by link answers "what
will be written": the same rule can be edited in a way that produces identical links (a
rename) or left alone and produce different ones (its device was swapped, its target gained
an endpoint). Showing only the first would let a rename read as a change to a house;
showing only the second would leave a user reading fingerprints.

**A snapshot has no rules in it.** It is what a set of devices held at a moment, so it can
only be compared link by link, and only over the devices it covers: a device the snapshot
never recorded is not a device the snapshot says is empty (`Snapshot.devices` is exactly
this distinction), and diffing against silence would propose removing everything on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from custom_components.device_links.compiler import compile_rule
from custom_components.device_links.models import (
    DeviceCapabilities,
    Link,
    Profile,
    Rule,
)
from custom_components.device_links.yaml_io import rule_to_data


class ChangeKind(StrEnum):
    """What happened to one rule or one link between the two sides."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class LinkChange:
    """One link that would be written or taken off, with which side it came from."""

    kind: ChangeKind
    link: Link


@dataclass(frozen=True, slots=True)
class RuleDiff:
    """One rule as it is on each side, and everything that differs about it.

    `fields` names the parts of the rule that are not the same, in the file's own
    vocabulary (`name`, `targets`, `features`, `hybrid`), so the panel can say what changed
    without either side having to describe a rule twice. It is empty for a rule that was
    added or removed, because "everything" is not a useful list.
    """

    rule_id: str
    name: str
    kind: ChangeKind
    fields: tuple[str, ...] = ()
    links_added: tuple[Link, ...] = ()
    links_removed: tuple[Link, ...] = ()
    links_unchanged: int = 0

    @property
    def writes_nothing_new(self) -> bool:
        """Say whether this rule's change costs no device write at all.

        A rename is the case this exists for: the rule is different, the links are
        identical, and a user deciding whether to apply an import needs to be told that
        this one is free rather than left to compare two lists of fingerprints.
        """
        return not self.links_added and not self.links_removed


@dataclass(frozen=True, slots=True)
class ProfileDiff:
    """Everything that differs between two sides, at both levels.

    `rules` is empty when the right-hand side is a snapshot, which has no rules in it; the
    link-level answer is the whole of what a snapshot can be compared on.
    """

    rules: tuple[RuleDiff, ...] = ()
    links: tuple[LinkChange, ...] = ()
    devices: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Say whether the two sides describe the same thing."""
        return not any(rule.kind is not ChangeKind.UNCHANGED for rule in self.rules) and not any(
            change.kind is not ChangeKind.UNCHANGED for change in self.links
        )

    def counts(self) -> dict[str, int]:
        """Return how many rules and links fall into each kind, for a summary line."""
        counts = {f"rules_{kind}": 0 for kind in ChangeKind}
        counts.update({f"links_{kind}": 0 for kind in ChangeKind})
        for rule in self.rules:
            counts[f"rules_{rule.kind}"] += 1
        for change in self.links:
            counts[f"links_{change.kind}"] += 1
        return counts


def diff_profiles(
    before: Profile, after: Profile, capabilities: Mapping[str, DeviceCapabilities]
) -> ProfileDiff:
    """Return everything that differs between two profiles, at both levels.

    Both sides are compiled against the **same** capabilities, which are the devices as
    they are now. That is deliberate and it is the only honest choice: a profile is a
    statement of intent and what it produces depends on the hardware it meets, so comparing
    one compiled against last week's network with one compiled against today's would
    attribute a device's change to the user's edit.

    Rules are matched by id, which is what makes a rename a change rather than a deletion
    and an addition.
    """
    left = {rule.id: rule for rule in before.rules}
    right = {rule.id: rule for rule in after.rules}
    compiled_left = _links_by_rule(before.rules, capabilities)
    compiled_right = _links_by_rule(after.rules, capabilities)

    rules = tuple(
        _rule_diff(
            rule_id,
            left.get(rule_id),
            right.get(rule_id),
            compiled_left.get(rule_id, ()),
            compiled_right.get(rule_id, ()),
        )
        for rule_id in _ordered_ids(before.rules, after.rules)
    )
    return ProfileDiff(
        rules=rules,
        links=_link_changes(
            [link for links in compiled_left.values() for link in links],
            [link for links in compiled_right.values() for link in links],
        ),
    )


def diff_against_links(
    profile: Profile,
    recorded: Sequence[Link],
    capabilities: Mapping[str, DeviceCapabilities],
    *,
    devices: Sequence[str],
) -> ProfileDiff:
    """Return what differs between a profile and a set of links somebody recorded.

    This is the snapshot comparison, and `devices` is what keeps it honest: only the
    devices the snapshot actually covers take part. A device the snapshot never recorded is
    not a device it says was empty, and comparing against its silence would report every
    link on it as something the profile added.

    No rules come back, because a snapshot has none. It is a photograph of hardware.
    """
    covered = frozenset(devices)
    wanted = [
        link
        for rule in profile.rules
        if rule.enabled
        for link in compile_rule(rule, capabilities).links
        if link.source.identity in covered
    ]
    return ProfileDiff(
        links=_link_changes([link for link in recorded if link.source.identity in covered], wanted),
        devices=tuple(sorted(covered)),
    )


def _ordered_ids(before: Sequence[Rule], after: Sequence[Rule]) -> list[str]:
    """Return every rule id once, in the right-hand side's order then the left's leftovers.

    The right-hand side is what the user is moving towards, so its order is the one they
    are reading; the rules that only exist on the left are what would go, and they come
    after in their own order rather than being interleaved by id.
    """
    ordered = [rule.id for rule in after]
    seen = set(ordered)
    ordered.extend(rule.id for rule in before if rule.id not in seen)
    return ordered


def _links_by_rule(
    rules: Iterable[Rule], capabilities: Mapping[str, DeviceCapabilities]
) -> dict[str, tuple[Link, ...]]:
    """Return what each rule would put on the devices, by rule id.

    Disabled rules compile to nothing, which is right here: a diff is about what would be
    written, and a rule somebody has switched off writes nothing on either side.
    """
    return {rule.id: compile_rule(rule, capabilities).links for rule in rules}


def _rule_diff(
    rule_id: str,
    before: Rule | None,
    after: Rule | None,
    links_before: Sequence[Link],
    links_after: Sequence[Link],
) -> RuleDiff:
    """Return one rule's row of the diff, whichever sides it exists on."""
    # The id came from one of the two lists, so at least one side has the rule; the
    # fallback is what makes that a value rather than a claim about it.
    present = after or before
    if present is None:  # pragma: no cover
        raise ValueError(f"rule {rule_id} is on neither side of this diff")
    kind = _kind(before, after)
    added = tuple(_missing(links_after, links_before))
    removed = tuple(_missing(links_before, links_after))
    unchanged = len(links_after) - len(added)
    return RuleDiff(
        rule_id=rule_id,
        name=present.name,
        kind=kind,
        # Only for a rule that is on both sides, which is what `CHANGED` means, and what
        # narrows the two optionals to values without a second check saying so.
        fields=(
            _changed_fields(before, after)
            if kind is ChangeKind.CHANGED and before is not None and after is not None
            else ()
        ),
        links_added=added,
        links_removed=removed,
        links_unchanged=unchanged,
    )


def _kind(before: Rule | None, after: Rule | None) -> ChangeKind:
    """Return what happened to one rule between the two sides."""
    if before is None:
        return ChangeKind.ADDED
    if after is None:
        return ChangeKind.REMOVED
    return ChangeKind.UNCHANGED if before == after else ChangeKind.CHANGED


def _changed_fields(before: Rule, after: Rule) -> tuple[str, ...]:
    """Return the names of the rule fields that differ, in the file's own vocabulary.

    Compared through `rule_to_data` rather than field by field on the dataclass, so the
    names a user is shown are the names their exported file uses, and a device handle is
    compared by the identity a rule refers to it by rather than by a name that a rename
    would change.
    """
    left = rule_to_data(before)
    right = rule_to_data(after)
    return tuple(sorted(key for key in {*left, *right} if left.get(key) != right.get(key)))


def _missing(wanted: Sequence[Link], present: Sequence[Link]) -> list[Link]:
    """Return the links of the first list that the second does not hold."""
    fingerprints = {link.fingerprint for link in present}
    return [link for link in wanted if link.fingerprint not in fingerprints]


def _link_changes(before: Sequence[Link], after: Sequence[Link]) -> tuple[LinkChange, ...]:
    """Return every link of either side, once, with what would happen to it.

    Sorted by fingerprint, which is a stable order that groups a device's own entries
    together: the fingerprint starts with the backend and the source device, so a reader
    sees one device's changes in one place without the diff having to group them.
    """
    left = {link.fingerprint: link for link in before}
    right = {link.fingerprint: link for link in after}
    changes: list[LinkChange] = []
    for fingerprint in sorted({*left, *right}):
        if fingerprint not in left:
            changes.append(LinkChange(kind=ChangeKind.ADDED, link=right[fingerprint]))
        elif fingerprint not in right:
            changes.append(LinkChange(kind=ChangeKind.REMOVED, link=left[fingerprint]))
        else:
            changes.append(LinkChange(kind=ChangeKind.UNCHANGED, link=right[fingerprint]))
    return tuple(changes)


__all__ = [
    "ChangeKind",
    "LinkChange",
    "ProfileDiff",
    "RuleDiff",
    "diff_against_links",
    "diff_profiles",
]
