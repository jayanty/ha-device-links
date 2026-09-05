"""Z3: the Z-Wave association write path works, and it left the device as it was found.

Executed against Jayant's live node 36 on 2026-09-05 with explicit approval, in the one
sandbox recorded in CLAUDE.md Section 3: group 8, "Button 2 - Held", which the bedroom
design leaves unused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z3_write_roundtrip.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z3 not executed yet")


def _data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())["data"]


def test_the_write_landed_and_was_then_undone() -> None:
    data = _data()

    assert data["before"] == [], "group 8 was expected to be unused before the probe"
    assert data["after_add_cached"] == [{"node_id": 1, "endpoint": None}], "the add did not land"
    assert data["after_remove"] == data["before"], "the device was not restored"
    assert data["restored"] is True


def test_the_lifeline_was_never_touched() -> None:
    """The hardest safety rule in the project, checked on the one run that wrote."""
    assert _data()["lifeline_after"] == [{"node_id": 1, "endpoint": None}]


def test_association_check_result_ok_is_one_not_zero() -> None:
    """A truthiness check against this enum would be a silent, dangerous bug.

    AssociationCheckResult.OK is 1, and every refusal reason is 2 through 7. Code that
    writes `if not check:` would treat OK as failure, and code that writes `if check:`
    would treat every refusal as success. Compare to OK explicitly, always.
    """
    check = _data()["check_result"]

    assert check["name"] == "OK"
    assert check["value"] == 1, "the OK sentinel moved; re-read every comparison against it"


def test_timing_was_recorded_for_the_executor_budget() -> None:
    """FR-A2 sets timeouts and retry backoff, and needs real numbers rather than guesses."""
    timing = _data()["timing_ms"]

    assert timing["add"] > 0
    assert timing["remove"] > 0
    assert timing["add"] < 5000, "an add on a listening node should be fast"
    assert timing["remove"] < 5000


def test_deep_verify_cannot_be_refresh_then_read() -> None:
    """The Z3 finding that changes an FR: refresh_cc_values is fire and forget.

    PRD FR-B4 describes deep verify as refreshing the Association CC values from the
    device and then reading. The driver sends refresh_cc_values with
    wait_for_result=False, so it returns before the device answers and an immediate read
    still sees the previous cache. Phase 1 must refresh, then wait for the resulting
    value-updated events or poll with a bounded timeout, before comparing.
    """
    finding = _data()["deep_verify_finding"]

    assert "wait_for_result=False" in finding["sends"]
    assert finding["measured_ms"] < 10, (
        "refresh_cc_values took long enough to look synchronous. If the driver started "
        "waiting for the device, FR-B4 can be implemented as the PRD originally described "
        "and this test should be replaced with one that pins the new behavior."
    )


def test_the_driver_cache_reflected_the_write_without_a_refresh() -> None:
    """Writes we make ourselves are visible immediately; external edits are the risk.

    This is why drift detection subscribes to value-updated events rather than trusting
    a plain read (FR-B3), and why verification after our own apply is cheap.
    """
    data = _data()

    assert data["cache_updated_without_refresh"] is True
    assert data["after_add_cached"] == data["after_add_refreshed"]
