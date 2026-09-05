"""Feature classification, checked against every group Stage 0 actually captured."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.device_links.backends.zwave_protocol import features_of_group
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
