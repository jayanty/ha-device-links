"""The Z2 fixture must actually answer the questions PRD Section 3 left open.

Captured live on 2026-09-05 from zwave-js 15.28.0 / zwave-js-server 3.10.1 (schema 50)
against Jayant's network. These assertions are what makes the fixture trustworthy input
for the Phase 1 compiler and planner: if a re-capture changes any of them, the compiler's
assumptions changed too and must be revisited.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z2 fixture not captured yet")

# Command class ids that appear in issuedCommands, for readability in assertions.
CC_BASIC = "32"
CC_MULTILEVEL_SWITCH = "38"


def _nodes() -> dict[int, dict[str, Any]]:
    data = json.loads(FIXTURE.read_text())["data"]
    return {node["node_id"]: node for node in data["nodes"]}


def _groups(node_id: int, endpoint: str = "0") -> dict[str, Any]:
    return _nodes()[node_id]["association_groups"][endpoint]


def _associations(node_id: int, endpoint: str = "0") -> dict[str, Any]:
    return _nodes()[node_id]["associations"][endpoint]


def test_every_expected_node_was_captured() -> None:
    captured = _nodes()
    for node_id in (21, 29, 30, 35, 36, 37, 38, 39, 40, 42):
        assert node_id in captured, f"node {node_id} missing from the Z2 fixture"
        assert captured[node_id]["present"] is True, f"node {node_id} was not on the network"


def test_group_one_is_the_lifeline_everywhere() -> None:
    """Safety invariant: lifelines are never removable, so we must always recognise one."""
    for node_id in _nodes():
        assert _groups(node_id)["1"]["is_lifeline"] is True, (
            f"node {node_id} group 1 is not flagged as a lifeline; the hard-protection "
            "rule in CLAUDE.md Section 3 relies on this flag"
        )


def test_no_group_other_than_one_claims_to_be_a_lifeline() -> None:
    """If a device ever flags a second lifeline, removal logic must learn about it."""
    for node_id, node in _nodes().items():
        for endpoint, groups in node["association_groups"].items():
            extra = [gid for gid, g in groups.items() if g["is_lifeline"] and gid != "1"]
            assert not extra, f"node {node_id} endpoint {endpoint} has extra lifelines: {extra}"


def test_every_lifeline_holds_the_controller() -> None:
    """A node whose lifeline lost node 1 would stop reporting to Home Assistant."""
    for node_id in _nodes():
        targets = _associations(node_id)["1"]
        assert {"node_id": 1, "endpoint": None} in targets, (
            f"node {node_id} lifeline does not contain the controller: {targets}"
        )


def test_the_network_has_no_associations_beyond_lifelines() -> None:
    """Recorded starting state. Phase 1 plans are computed against this baseline.

    If this ever fails, someone configured associations outside the integration and the
    Phase 1 acceptance scenarios in PRD Section 15 no longer start from a clean network.
    """
    found: list[str] = []
    for node_id, node in _nodes().items():
        for endpoint, groups in node["associations"].items():
            for group_id, targets in groups.items():
                if group_id != "1" and targets:
                    found.append(f"node {node_id} ep{endpoint} g{group_id} -> {targets}")
    assert not found, f"unexpected non-lifeline associations: {found}"


def test_zen35_button_group_layout_matches_the_prd() -> None:
    """PRD Appendix A: small button N uses groups (3+2N) pressed and (4+2N) held."""
    groups = _groups(36)

    for button, (pressed, held) in {1: (5, 6), 2: (7, 8), 3: (9, 10), 4: (11, 12)}.items():
        assert f"Button {button} - Pressed" in groups[str(pressed)]["label"], (
            f"ZEN35 group {pressed} is {groups[str(pressed)]['label']!r}, "
            f"not button {button} pressed"
        )
        assert f"Button {button} - Held" in groups[str(held)]["label"], (
            f"ZEN35 group {held} is {groups[str(held)]['label']!r}, not button {button} held"
        )

    assert CC_BASIC in groups["7"]["issued_commands"], "button 2 pressed should issue Basic Set"
    assert CC_MULTILEVEL_SWITCH in groups["8"]["issued_commands"], (
        "button 2 held should issue Multilevel Switch"
    )


def test_node_36_group_8_is_the_approved_write_sandbox_and_is_empty() -> None:
    """The only pre-approved Z-Wave write target (CLAUDE.md Section 3, Stage 0 Z3).

    Z3 may only run because this group is unused. If a real design ever puts an entry
    here, the sandbox must move and Jayant must approve the new target.
    """
    group = _groups(36)["8"]

    assert group["is_lifeline"] is False, "the write sandbox must never be a lifeline"
    assert group["label"] == "Button 2 - Held (MultiLevel)"
    assert group["max_nodes"] >= 1
    assert _associations(36)["8"] == [], (
        "node 36 group 8 is no longer empty; do not run Z3 against it"
    )


def test_inovelli_vzw32_group_layout() -> None:
    """PRD Section 3.2 predicted these groups. Group 7's real label differs (see report)."""
    groups = _groups(37)

    assert groups["2"]["label"] == "Basic Set"
    assert groups["3"]["label"] == "Multilevel Switch Set"
    assert groups["4"]["label"] == "Multilevel Switch Start/Stop"
    assert groups["5"]["label"] == "Basic Set Double-tap"
    assert groups["6"]["label"] == "Basic Set Triple-tap"
    assert groups["7"]["label"] == "Multilevel Switch Set (Config Button)", (
        "the PRD called group 7 a 'cycle levels' group gated by parameter 130; the device "
        "reports it as the config button. docs/stage0-report.md records the amendment."
    )


def test_zen37_remote_layout_is_not_what_the_prd_expected() -> None:
    """Appendix A guessed a Basic/Multilevel pair per button. The device disagrees.

    The real layout pairs buttons for on/off and dimming, and gives each button its own
    toggle group. The compiler's emitter model must be driven by these labels and issued
    commands, not by a per-button-pair assumption.
    """
    groups = _groups(40)

    assert len(groups) == 9, f"ZEN37 reports {len(groups)} groups, expected 9"
    assert groups["2"]["label"] == "On/Off Control (Button 1 & 2)"
    assert groups["4"]["label"] == "Dimmer Control (Button 1 & 2)"
    assert groups["6"]["label"] == "Toggle Control (Button 1)"
    assert groups["9"]["label"] == "Toggle Control (Button 4)"

    for group_id, group in groups.items():
        assert group["max_nodes"] == 5, (
            f"ZEN37 group {group_id} holds {group['max_nodes']} nodes, not 5; capacity "
            "checks in FR-R6 use this and it is half the ZEN35's 10"
        )


def test_sleeping_nodes_still_report_their_groups() -> None:
    """Node 40 is a battery remote and was asleep, yet reads succeeded from the cache.

    This is why FR-B4 needs an explicit deep verify: a plain read of a sleeping node
    returns the driver's cached view, which can be arbitrarily stale.
    """
    node = _nodes()[40]

    assert node["status"] == 1, "node 40 was expected to be asleep during capture"
    assert node["association_groups"]["0"], "a sleeping node still returned cached groups"


def test_no_captured_node_is_long_range() -> None:
    """PRD 3.4: LR nodes cannot use associations at all. This network is all classic."""
    for node_id, node in _nodes().items():
        assert node["node_id"] < 256, f"node {node_id} has a Long Range node id"
        assert node["protocol"] == 0, (
            f"node {node_id} reports protocol {node['protocol']}, not Z-Wave Classic (0). "
            "Long Range devices cannot be association sources or targets."
        )


def test_the_fixture_carries_no_home_id() -> None:
    """The fixture is committed to a public repository."""
    data = json.loads(FIXTURE.read_text())["data"]
    assert data["server"]["home_id"] == "<redacted>"
