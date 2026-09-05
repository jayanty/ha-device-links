"""Z6: the configuration parameters the settings adapters write must exist.

A rule can compile a perfect set of links and still not work if the device's own
parameters contradict it, so the compiler emits parameter writes alongside links
(PRD FR-R4, FR-F2). Each named capability in the profile database maps to a concrete
value id, and this pins those mappings against the live devices.

Captured in the same probe run as the Z2 fixture on 2026-09-05.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z2/Z6 fixture not captured yet")

ZEN35_NODE = 39
INOVELLI_NODE = 37


def _config_values(node_id: int) -> dict[tuple[int, int | None], dict[str, Any]]:
    data = json.loads(FIXTURE.read_text())["data"]
    node = next(n for n in data["nodes"] if n["node_id"] == node_id)
    return {(v["property"], v["property_key"]): v for v in node["config_values"]}


def _assert_writeable(node_id: int, key: tuple[int, int | None], capability: str) -> None:
    values = _config_values(node_id)
    assert key in values, (
        f"node {node_id} does not expose parameter {key} as a value id, so the "
        f"{capability!r} settings adapter has nowhere to write"
    )
    assert values[key]["metadata"]["writeable"] is True, (
        f"node {node_id} parameter {key} is read-only; {capability!r} cannot be applied"
    )


def test_zen35_mirror_hub_commands_adapter_has_a_target() -> None:
    """mirror_hub_commands maps to Zooz parameter 35 bit 4 (PRD Appendix A)."""
    _assert_writeable(ZEN35_NODE, (35, 4), "mirror_hub_commands")

    label = _config_values(ZEN35_NODE)[(35, 4)]["metadata"]["label"]
    assert "Z-Wave" in label, f"parameter 35 bit 4 is {label!r}, not the Z-Wave forwarding bit"


def test_zen35_send_local_to_associations_adapter_has_a_target() -> None:
    """send_local_to_associations maps to Zooz parameter 35 bit 1."""
    _assert_writeable(ZEN35_NODE, (35, 1), "send_local_to_associations")


def test_zen35_report_command_class_adapter_has_a_target() -> None:
    """report_cc maps to Zooz parameter 33, which FR-F2 exposes as a user choice."""
    _assert_writeable(ZEN35_NODE, (33, None), "report_command_class")


def test_zen35_local_control_is_writeable_but_must_not_be_touched_by_default() -> None:
    """Decision D4: the integration never writes parameter 19 unless a rule selects it.

    Node 39 currently has local paddle control of its own load disabled. That is a
    deliberate temporary state of Jayant's, not something to correct.
    """
    _assert_writeable(ZEN35_NODE, (19, None), "local_control")

    assert _config_values(ZEN35_NODE)[(19, None)]["value"] == 0, (
        "node 39 parameter 19 changed. Decision D4 assumed it was 0 (local control "
        "disabled) and that the integration leaves it alone; re-read D4 before acting."
    )


def test_inovelli_mirror_hub_commands_adapter_has_a_target() -> None:
    """mirror_hub_commands maps to Inovelli parameter 59 bit 2, default off."""
    _assert_writeable(INOVELLI_NODE, (59, 2), "mirror_hub_commands")

    value = _config_values(INOVELLI_NODE)[(59, 2)]
    assert "Forward Z-Wave Commands" in value["metadata"]["label"]
    assert value["value"] == 0, (
        "Inovelli parameter 59 bit 2 is no longer off by default. FR-R4 plans this write "
        "for a two-way rule and the loop analysis in FR-R7 assumes one side starts off."
    )


def test_inovelli_send_local_to_associations_adapter_has_a_target() -> None:
    """send_local_to_associations maps to Inovelli parameter 59 bit 1, default on."""
    _assert_writeable(INOVELLI_NODE, (59, 1), "send_local_to_associations")

    assert _config_values(INOVELLI_NODE)[(59, 1)]["value"] == 1, (
        "Inovelli parameter 59 bit 1 is off, so local paddle events are not reaching "
        "association targets and every remote-controls-light rule would appear dead"
    )


def test_inovelli_smart_bulb_mode_adapter_has_a_target() -> None:
    """smart_bulb_mode maps to Inovelli parameter 52, used when a bulb sits behind a remote."""
    _assert_writeable(INOVELLI_NODE, (52, None), "smart_bulb_mode")


def test_inovelli_group_seven_is_gated_by_parameter_130() -> None:
    """The PRD's claim about parameter 130 holds, even though group 7's label differs.

    PRD Section 3.2 called group 7 a 'cycle levels' group gated by parameter 130. The
    device labels the group 'Multilevel Switch Set (Config Button)', but the gating
    parameter is real and is named for the group, so the compiler must still set it
    before planning any link into group 7.
    """
    _assert_writeable(INOVELLI_NODE, (130, None), "group_7_enable")

    assert "Group 7" in _config_values(INOVELLI_NODE)[(130, None)]["metadata"]["label"]
