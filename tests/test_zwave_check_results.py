"""Check-result mapping. The values come from Stage 0, not from the documentation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.device_links.backends.zwave_protocol import (
    CheckResult,
    blocked_reason_for,
    is_ok,
)

Z3 = Path(__file__).parent / "fixtures" / "z3_write_roundtrip.json"


def test_ok_is_one_not_zero() -> None:
    """Pinned by Stage 0 Z3 against the live driver. A falsy check would invert this."""
    assert CheckResult.OK == 1
    assert is_ok(1) is True
    assert is_ok(0) is False, "0 is not a valid result and must never read as success"


def test_the_live_check_result_matches_the_enum() -> None:
    observed = json.loads(Z3.read_text())["data"]["check_result"]

    assert CheckResult(observed["value"]).name == observed["name"]


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        (2, "long_range"),
        (3, "long_range"),
        (4, "self_association"),
        (5, "security_class"),
        (6, "security_class"),
        (7, "no_supported_commands"),
    ],
)
def test_every_refusal_maps_to_a_translation_key(value: int, fragment: str) -> None:
    """E7 to E10: each refusal needs a reason the user can act on, not a number."""
    reason = blocked_reason_for(value)

    assert reason is not None
    assert fragment in reason.translation_key


def test_ok_has_no_blocked_reason() -> None:
    assert blocked_reason_for(CheckResult.OK) is None


def test_an_unknown_result_is_blocked_rather_than_allowed() -> None:
    """A future driver value must fail closed. Never write on an unrecognised answer."""
    reason = blocked_reason_for(99)

    assert reason is not None
    assert "unknown" in reason.translation_key


def test_no_value_other_than_ok_is_ever_allowed() -> None:
    """Fail closed, swept rather than sampled: only the pinned OK may return None."""
    allowed = [value for value in range(-1000, 1001) if blocked_reason_for(value) is None]

    assert allowed == [CheckResult.OK]


def test_an_unknown_result_carries_the_value_it_could_not_explain() -> None:
    """The number is useless to the user but it is what a bug report needs."""
    reason = blocked_reason_for(99)

    assert reason is not None
    assert reason.placeholders == {"value": "99"}


def test_every_refusal_in_the_enum_has_its_own_reason() -> None:
    """A new enum member without a mapping would silently read as 'unknown'."""
    reasons = [blocked_reason_for(r) for r in CheckResult if r is not CheckResult.OK]
    keys = {reason.translation_key for reason in reasons if reason is not None}

    assert len(keys) == len(CheckResult) - 1
    assert not any("unknown" in key for key in keys)
