"""Z8: decides how hybrid leg kind (c) drives scene-controller button LEDs (Decision D6).

Executed against node 36 button 2 on 2026-09-05 with Jayant's approval. Button 2 is
unassigned in the bedroom design (Decision D15), which is why it is the safe one to
disturb. Both mechanisms were measured and both recorded values were restored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z8_led_path.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z8 not executed yet")

ZEN35_BUTTONS = 5


def _data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())["data"]


def test_the_configuration_parameter_was_restored() -> None:
    """A parameter write lands in NVM, so leaving it changed would be a real edit."""
    data = _data()

    assert data["param_before"] == data["param_after_restore"], "LED mode was not restored"
    assert data["param_after_write"] != data["param_before"], "the write did not take effect"
    assert data["param_restored"] is True


def test_the_indicator_value_was_restored() -> None:
    data = _data()

    assert data["indicator_before"] == data["indicator_after_restore"]
    assert data["indicator_after_write"] != data["indicator_before"]
    assert data["indicator_restored"] is True


def test_indicator_cc_addresses_each_button_individually() -> None:
    """The finding that decides D6, and that amends PRD Section 3.2.

    The PRD concluded no path exists to make a small button's LED follow a remote device,
    because the LED-mode parameters only track the device's own load. Indicator CC turns
    out to provide exactly the per-button addressing the PRD assumed was missing.
    """
    data = _data()

    assert data["indicator_cc_supported"] is True
    ids = [entry["indicator_id"] for entry in data["indicator_ids"]]
    assert ids == [67, 68, 69, 70, 71], f"per-button indicator ids changed: {ids}"
    assert len(ids) == ZEN35_BUTTONS

    labels = [entry["label"] for entry in data["indicator_ids"]]
    assert labels[1] == "Button 2 indication", "indicator 68 is no longer button 2"

    for entry in data["indicator_ids"]:
        assert entry["writeable"] is True, f"indicator {entry['indicator_id']} is read-only"


def test_d6_resolves_to_indicator_cc() -> None:
    """Recorded so Phase 2 implements the leg without re-deriving the decision."""
    verdict = _data()["d6_verdict"]

    assert verdict["mechanism"] == "indicator_cc"
    assert verdict["reason"]
    assert verdict["amends_prd"]


def test_indicator_cc_is_not_slower_than_the_parameter_path() -> None:
    """The NVM-safe option would still lose if it were noticeably laggier."""
    timing = _data()["timing_ms"]

    assert timing["indicator_write"] <= timing["param_write"] * 2, (
        f"Indicator CC write ({timing['indicator_write']} ms) is much slower than the "
        f"parameter write ({timing['param_write']} ms); revisit D6"
    )
    assert timing["indicator_write"] < 1000, "an LED update this slow would feel broken"
