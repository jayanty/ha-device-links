"""Emitter derivation, including the models where AGI profile cannot be trusted.

Stage 0 found that profile groups correctly on the ZEN35, gives every Inovelli group a
distinct profile even though three of them are one paddle, and is null for ZEN37 group 7.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from custom_components.device_links.backends.zwave_protocol import derive_emitters
from custom_components.device_links.models import Feature

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"


def _groups(node_id: int) -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text())["data"]
    node = next(n for n in data["nodes"] if n["node_id"] == node_id)
    return node["association_groups"]["0"]


def _group(
    label: str,
    issued: dict[str, list[int]],
    profile: int | None,
    *,
    max_nodes: int = 10,
    multi_channel: bool = True,
) -> dict[str, Any]:
    """Build one synthetic group, for the hardware shapes the fixture does not contain."""
    return {
        "is_lifeline": False,
        "issued_commands": issued,
        "label": label,
        "max_nodes": max_nodes,
        "multi_channel": multi_channel,
        "profile": profile,
    }


def test_the_lifeline_never_becomes_an_emitter() -> None:
    """Hard safety rule: the lifeline is not a control the user can pick."""
    emitters = derive_emitters(_groups(36))

    assert all("1" not in e.group_ids for e in emitters)
    assert all(not e.is_lifeline for e in emitters)


def test_zen35_profile_grouping_produces_one_emitter_per_physical_button() -> None:
    """The ZEN35 is the model where AGI profile does the right thing."""
    emitters = {e.emitter_id: e for e in derive_emitters(_groups(36))}

    assert len(emitters) == 5, f"expected main button plus 4 buttons, got {sorted(emitters)}"

    main = next(e for e in emitters.values() if "Main" in e.label)
    assert main.actions[Feature.ON_OFF] == "2"
    assert main.actions[Feature.LEVEL_SET] == "3"
    assert main.actions[Feature.LEVEL_HOLD] == "4"

    button_two = next(e for e in emitters.values() if "Button 2" in e.label)
    assert button_two.actions[Feature.ON_OFF] == "7"
    assert button_two.actions[Feature.LEVEL_HOLD] == "8"
    assert Feature.LEVEL_SET not in button_two.actions


def test_inovelli_profile_grouping_is_rejected_and_falls_back() -> None:
    """Every Inovelli group has its own profile, so profile grouping is meaningless here.

    Grouping by it would split one paddle into three emitters and make the Remote template
    impossible. Without a curated override the derivation must fall back to one emitter per
    group and say so, rather than producing a confidently wrong grouping.
    """
    emitters = derive_emitters(_groups(37))

    assert len(emitters) == 6, "expected one emitter per non-lifeline group in fallback mode"
    assert all(e.grouping == "per_group" for e in emitters)
    assert all(len(e.group_ids) == 1 for e in emitters)


def test_zen37_null_profile_does_not_lose_a_button() -> None:
    """ZEN37 group 7 has a null profile. No button may be silently dropped."""
    groups = _groups(40)
    emitters = derive_emitters(groups)

    covered = {group_id for emitter in emitters for group_id in emitter.group_ids}
    expected = {gid for gid, g in groups.items() if not g["is_lifeline"]}

    assert covered == expected, f"groups lost during derivation: {expected - covered}"


def test_capacity_is_the_smallest_capacity_of_the_groups_it_uses() -> None:
    """A rule using two groups is limited by the tighter one (FR-R6)."""
    zen35 = next(e for e in derive_emitters(_groups(36)) if "Main" in e.label)
    zen37 = derive_emitters(_groups(40))[0]

    assert zen35.capacity == 10
    assert zen37.capacity == 5, "the ZEN37 holds 5 targets per group, not 10"


def test_every_emitter_reports_whether_it_can_target_an_endpoint() -> None:
    """E11: a group without multi-channel support cannot address a target endpoint."""
    for emitter in derive_emitters(_groups(36)):
        assert emitter.supports_endpoint_targets is True


def test_emitter_ids_are_stable_and_derived_from_groups() -> None:
    """Rules store emitter ids, so they must not move when a device is re-read."""
    first = derive_emitters(_groups(36))
    second = derive_emitters(_groups(36))

    assert [e.emitter_id for e in first] == [e.emitter_id for e in second]
    for emitter in first:
        assert emitter.emitter_id.startswith("g"), emitter.emitter_id


def test_zen35_emitter_labels_are_trimmed_to_the_shared_button_name() -> None:
    """Labels reach the user in the picker, so a sloppy trim is a visible defect."""
    emitters = derive_emitters(_groups(36))

    assert [e.label for e in emitters] == [
        "Main Button",
        "Button 1",
        "Button 2",
        "Button 3",
        "Button 4",
    ]


def test_emitters_are_ordered_by_their_lowest_group() -> None:
    """Deterministic order, so the picker and the diagnostics never shuffle."""
    assert [e.emitter_id for e in derive_emitters(_groups(36))] == [
        "g2",
        "g5",
        "g7",
        "g9",
        "g11",
    ]
    assert [e.emitter_id for e in derive_emitters(_groups(40))] == [
        "g2",
        "g3",
        "g4",
        "g5",
        "g6",
        "g7",
        "g8",
        "g9",
    ]


def test_a_profile_covering_two_groups_with_the_same_feature_is_not_a_control() -> None:
    """Two On/Off groups under one profile means the profile is not one physical button.

    The ZEN37 is nearly this shape already: its groups 2 and 3 both issue Basic Set, and only
    the null profile on group 7 rejects it first. Profile grouping must refuse this on its
    own merits, not by accident.
    """
    groups = {
        "2": _group("Row - Left", {"32": [1]}, 8193),
        "3": _group("Row - Right", {"32": [1]}, 8193),
    }

    emitters = derive_emitters(groups)

    assert [e.grouping for e in emitters] == ["per_group", "per_group"]
    assert [e.label for e in emitters] == ["Row - Left", "Row - Right"]


def test_a_profile_group_without_a_shared_prefix_falls_back_to_its_lowest_label() -> None:
    """A label is better than the empty string when the members share no prefix."""
    groups = {
        "2": _group("Turn on", {"32": [1]}, 8193),
        "3": _group("Dim it", {"38": [1]}, 8193),
    }

    emitters = derive_emitters(groups)

    assert [e.grouping for e in emitters] == ["profile"]
    assert emitters[0].label == "Turn on"
    assert emitters[0].group_ids == ("2", "3")


def test_a_group_that_carries_nothing_is_dropped_and_reported() -> None:
    """Unknown future hardware must not produce an emitter the user cannot use."""
    groups = {
        "2": _group("Notifications", {"113": [5]}, 8193),
        "3": _group("Paddle - On/Off", {"32": [1]}, 8194),
        "4": _group("Paddle - Dim", {"38": [4]}, 8194),
    }
    warnings: list[str] = []

    emitters = derive_emitters(groups, warnings=warnings)

    assert [e.emitter_id for e in emitters] == ["g3"]
    assert [e.emitter_id for e in derive_emitters(groups)] == ["g3"], "same without a collector"
    assert len(warnings) == 1
    assert "2" in warnings[0]
    assert "Notifications" in warnings[0]


def test_endpoint_targeting_needs_every_group_of_the_emitter_to_support_it() -> None:
    """One group without multi-channel is enough to make the whole emitter unable to."""
    groups = {
        "2": _group("Paddle - On/Off", {"32": [1]}, 8193),
        "3": _group("Paddle - Dim", {"38": [4]}, 8193, multi_channel=False, max_nodes=5),
    }

    emitter = derive_emitters(groups)[0]

    assert emitter.supports_endpoint_targets is False
    assert emitter.capacity == 5
