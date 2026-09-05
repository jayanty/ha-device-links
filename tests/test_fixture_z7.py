"""Z7: how a Zooz small button behaves on the wire decides the Off-all compilation.

This item is DEFERRED, not answered. The tests below pin what was actually observed and,
just as importantly, pin the fact that the semantic is still unknown, so that Phase 1
cannot quietly ship an Off-all template for Zooz scene buttons on an assumption.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z7_button_semantics.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z7 fixture not captured yet")

BASIC_COMMAND_CLASS = "32"
MULTILEVEL_SWITCH_COMMAND_CLASS = "38"
BASIC_SET_COMMAND = 1


def _data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())["data"]


@pytest.mark.parametrize("model", ["ZEN35", "ZEN32"])
def test_pressed_groups_issue_basic_set(model: str) -> None:
    """What AGI does tell us: the command class, though not the value."""
    groups = _data()[model]["observed_groups"]
    pressed = {gid: g for gid, g in groups.items() if "Pressed" in g["label"]}

    assert pressed, f"{model} reports no Pressed button groups"
    for group_id, group in pressed.items():
        issued = group["issued_commands"]
        assert BASIC_COMMAND_CLASS in issued, (
            f"{model} group {group_id} no longer issues Basic Set: {issued}"
        )
        assert BASIC_SET_COMMAND in issued[BASIC_COMMAND_CLASS]


@pytest.mark.parametrize("model", ["ZEN35", "ZEN32"])
def test_held_groups_issue_multilevel(model: str) -> None:
    """The Held group is what the `dim` feature adds to a scene-button rule."""
    groups = _data()[model]["observed_groups"]
    held = {gid: g for gid, g in groups.items() if "Held" in g["label"]}

    assert held, f"{model} reports no Held button groups"
    for group_id, group in held.items():
        assert MULTILEVEL_SWITCH_COMMAND_CLASS in group["issued_commands"], (
            f"{model} group {group_id} no longer issues Multilevel Switch"
        )


@pytest.mark.parametrize("model", ["ZEN35", "ZEN32"])
def test_the_semantic_is_explicitly_undetermined(model: str) -> None:
    """Guard against a future contributor treating a guess as a finding.

    When Z7 is finally run, replace this with a test asserting the real semantic. Until
    then this test failing would mean someone recorded an answer without observing one.
    """
    finding = _data()[model]

    assert finding["semantic"] == "undetermined", (
        f"{model} now claims semantic {finding['semantic']!r}. If that was observed on "
        "the wire, replace this test with one pinning the observed behavior and update "
        "docs/stage0-report.md. If it was inferred from a manual, revert it."
    )
    assert finding["observed"] == "not captured"
    assert finding["documented"], "record what the manual says even when unverified"


def test_the_blocker_and_its_resolution_path_are_recorded() -> None:
    """A deferred item is only acceptable if the next person knows how to close it."""
    data = _data()

    assert "group 8" in data["why_not_captured"], (
        "the reason must name why the existing write sandbox cannot answer this"
    )
    assert "Off-all" in data["impact"] or "off all" in data["impact"].lower()
    assert len(data["how_to_resolve"]) >= 3


def test_off_all_on_a_zooz_small_button_is_not_yet_safe_to_compile() -> None:
    """The one consequence Phase 1 must respect.

    If a press toggles rather than always sending OFF, an Off-all button turns the lights
    back on every second press. The compiler must refuse or warn until Z7 is closed.
    """
    impact = _data()["impact"]

    assert "refuse" in impact
    assert "warn" in impact
