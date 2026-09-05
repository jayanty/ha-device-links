"""P1: the Home Assistant web components the panel is specified to use must exist.

PRD Section 7.1 builds the panel out of Home Assistant's own components so it inherits
theme, dark mode, typography, and dialog behavior. If one of them is not on the running
version, the panel has to degrade gracefully, and Phase 1 needs to know which ones before
it writes the UI rather than after.

Detection is by string literal, not by customElements.define: Home Assistant registers
elements with Lit's @customElement decorator, which minifies away from a literal define
call. Scanning for the call finds almost nothing and is a false negative. See
tools/probe_frontend.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "p1_frontend_components.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="P1 fixture not captured yet")

# Every component PRD Section 7.1 names, minus the tab component, which is handled
# separately because the PRD already expected it to vary by version.
REQUIRED_BY_THE_UI_SPEC = (
    "ha-top-app-bar-fixed",
    "ha-menu-button",
    "ha-card",
    "ha-data-table",
    "ha-dialog",
    "ha-form",
    "ha-alert",
    "ha-button",
    "ha-icon-button",
    "ha-switch",
    "ha-select",
    "ha-list-item",
    "ha-expansion-panel",
    "ha-chip-set",
    "ha-assist-chip",
    "ha-spinner",
    "ha-markdown",
    "ha-svg-icon",
)


def _data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())["data"]


def test_the_scan_actually_read_the_frontend() -> None:
    """Guard against a silent false negative from a scan that found nothing.

    A first attempt at this probe searched for customElements.define and reported every
    component missing. A scan that sees almost no ha-* tags is broken, not informative.
    """
    data = _data()

    assert data["js_files_scanned"] > 1000, "the frontend bundle was not found or not read"
    assert data["distinct_ha_tags_seen"] > 300, (
        f"only {data['distinct_ha_tags_seen']} ha-* tags seen; the detection method is "
        "producing false negatives and its results cannot be trusted"
    )


@pytest.mark.parametrize("component", REQUIRED_BY_THE_UI_SPEC)
def test_each_component_the_ui_spec_requires_is_present(component: str) -> None:
    present = _data()["present"]

    assert component in present, f"{component} was not probed"
    assert present[component] is True, (
        f"{component} is not in the 2026.8.3 frontend. PRD Section 7.1 specifies it, so "
        "either the panel needs a documented fallback or the spec needs amending."
    )


def test_the_tab_component_question_has_a_definite_answer() -> None:
    """PRD Section 7.1 hedged between ha-tabs and ha-tab-group. Only one exists."""
    data = _data()

    assert data["present"]["ha-tabs"] is False, (
        "ha-tabs is back. The runtime detection in PRD Section 7.1 should then choose "
        "between them rather than assuming ha-tab-group."
    )
    assert data["present"]["ha-tab-group"] is True, (
        "neither ha-tabs nor ha-tab-group exists; the panel shell needs redesigning"
    )
    assert data["verdict"]["tab_component"] == "ha-tab-group"


def test_the_runtime_half_is_recorded_as_still_pending() -> None:
    """Static presence is not proof of runtime registration, and the report must say so."""
    status = _data()["verdict"]["runtime_spike_status"]

    assert "restart" in status
    assert "queued" in status or "pending" in status
