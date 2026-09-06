"""Feature classification, checked against every group Stage 0 actually captured."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.device_links.backends.zwave_protocol import (
    FIRST_LONG_RANGE_NODE_ID,
    LONG_RANGE_PROTOCOL,
    feature_of_group,
    features_of_group,
    is_lifeline_group,
    is_long_range,
)
from custom_components.device_links.models import Feature

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"


def _groups(node_id: int) -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text())["data"]
    node = next(n for n in data["nodes"] if n["node_id"] == node_id)
    return node["association_groups"]["0"]


def test_basic_set_is_on_off() -> None:
    assert features_of_group({"32": [1]}) == frozenset({Feature.ON_OFF})


def test_binary_switch_set_is_also_on_off() -> None:
    """Not every device uses Basic Set; the classifier must not assume it does."""
    assert features_of_group({"37": [1]}) == frozenset({Feature.ON_OFF})


def test_multilevel_set_is_level_set() -> None:
    assert features_of_group({"38": [1]}) == frozenset({Feature.LEVEL_SET})


def test_start_level_change_is_level_hold() -> None:
    assert features_of_group({"38": [4]}) == frozenset({Feature.LEVEL_HOLD})


def test_start_and_stop_together_are_still_just_level_hold() -> None:
    """Inovelli group 4 issues both. Hold-to-dim is one feature, not two."""
    assert features_of_group({"38": [4, 5]}) == frozenset({Feature.LEVEL_HOLD})


def test_multilevel_report_is_a_status_report_not_a_control() -> None:
    """Lifeline issues 38 command 3. Treating a report as control would be a real bug."""
    assert features_of_group({"38": [3]}) == frozenset({Feature.STATUS_REPORT})


def test_scene_activation_is_scene() -> None:
    assert features_of_group({"43": [1]}) == frozenset({Feature.SCENE})


def test_an_unknown_command_class_yields_no_features() -> None:
    """Better to offer nothing than to offer something that does not work."""
    assert features_of_group({"113": [5]}) == frozenset()


def test_an_empty_or_absent_issued_map_yields_no_features() -> None:
    assert features_of_group({}) == frozenset()
    assert features_of_group(None) == frozenset()


def test_integer_command_class_keys_classify_the_same_as_string_keys() -> None:
    """JSON hands us string keys, the live driver hands us integers. Both are real."""
    assert features_of_group({32: [1]}) == features_of_group({"32": [1]})
    assert features_of_group({38: [4, 5]}) == frozenset({Feature.LEVEL_HOLD})


@pytest.mark.parametrize("node_id", [36, 37, 40])
def test_every_non_lifeline_group_on_real_hardware_classifies(node_id: int) -> None:
    """A real group that produces no features is an emitter the user cannot use."""
    unclassified = []
    for group_id, group in _groups(node_id).items():
        if group["is_lifeline"]:
            continue
        if not features_of_group(group["issued_commands"]):
            unclassified.append(f"g{group_id} {group['label']!r} {group['issued_commands']}")

    assert not unclassified, f"node {node_id} has groups the classifier cannot use: {unclassified}"


def test_the_lifeline_classifies_as_report_only() -> None:
    """Safety: the lifeline must never look like something a user can control with."""
    lifeline = _groups(36)["1"]
    features = features_of_group(lifeline["issued_commands"])

    assert Feature.ON_OFF not in features
    assert Feature.LEVEL_SET not in features
    assert Feature.LEVEL_HOLD not in features


def test_a_node_the_driver_calls_long_range_is_long_range() -> None:
    assert is_long_range(41, LONG_RANGE_PROTOCOL) is True


def test_a_long_range_node_id_is_long_range_even_with_no_protocol_reported() -> None:
    """CLAUDE.md Section 10: ids from 256 up are Long Range, fixed at inclusion time."""
    assert is_long_range(FIRST_LONG_RANGE_NODE_ID, None) is True


def test_a_classic_node_is_not_long_range() -> None:
    assert is_long_range(36, 0) is False


def test_the_device_decides_which_of_its_groups_is_the_lifeline() -> None:
    groups = _groups(36)

    assert is_lifeline_group(groups, "1") is True
    assert is_lifeline_group(groups, "2") is False


def test_a_group_the_device_does_not_report_falls_back_to_group_one() -> None:
    """Being wrong here costs a device its only way of reporting to Home Assistant."""
    assert is_lifeline_group({}, "1") is True
    assert is_lifeline_group({}, "7") is False


@pytest.mark.parametrize(
    ("group_id", "expected"),
    [("1", Feature.STATUS_REPORT), ("2", Feature.ON_OFF), ("4", Feature.LEVEL_HOLD)],
)
def test_a_group_carries_the_feature_its_issued_commands_say(
    group_id: str, expected: Feature
) -> None:
    assert feature_of_group(_groups(36)[group_id]) is expected


def test_a_group_that_issues_nothing_usable_reports_rather_than_controls() -> None:
    """Node 40's lifeline issues battery and notification reports and nothing else."""
    assert feature_of_group(_groups(40)["1"]) is Feature.STATUS_REPORT


def test_the_most_primary_feature_speaks_for_a_group_that_carries_several() -> None:
    """One entry on the device is one link, so a multi-feature group has to pick one."""
    both: Any = {"is_lifeline": False, "issued_commands": {32: [1], 38: [1]}}

    assert feature_of_group(both) is Feature.ON_OFF
