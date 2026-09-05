"""The write sandbox guard must refuse everything it was not explicitly approved for.

These tests are the reason it is safe to run a write probe against Jayant's live house.
They need no radio and no network.
"""

from __future__ import annotations

import pytest
from tools.probe_zwave_led import SandboxViolationError as LedSandboxViolationError
from tools.probe_zwave_led import (
    assert_indicator_target_in_sandbox,
    assert_led_target_in_sandbox,
)
from tools.probe_zwave_write import (
    SandboxViolationError,
    assert_group_was_empty,
    assert_in_sandbox,
)


def test_the_approved_write_is_allowed() -> None:
    """Node 36 group 8 target node 1, and only that, is approved."""
    assert_in_sandbox(36, 8, 1)


@pytest.mark.parametrize(
    ("node", "group", "target", "why"),
    [
        (36, 1, 1, "the lifeline, which is hard-protected and never writable"),
        (36, 2, 1, "a group the bedroom design actually uses"),
        (37, 8, 1, "a different node"),
        (36, 8, 37, "a different target device"),
        (39, 8, 1, "Bedside Light R, never approved"),
        (36, 7, 1, "button 2 pressed, adjacent to the sandbox but not it"),
        (36, 9, 1, "button 3 pressed, adjacent to the sandbox but not it"),
    ],
)
def test_everything_else_is_refused(node: int, group: int, target: int, why: str) -> None:
    with pytest.raises(SandboxViolationError, match="REFUSED"):
        assert_in_sandbox(node, group, target)


def test_an_empty_group_may_be_written() -> None:
    assert_group_was_empty([])


def test_a_group_someone_else_is_using_is_refused() -> None:
    """Restoration is only provable when we know the group started empty."""
    with pytest.raises(SandboxViolationError, match="not empty"):
        assert_group_was_empty([{"node_id": 42, "endpoint": None}])


class TestZ8LedSandbox:
    """Z8 writes to node 36 button 2 only, by either LED mechanism."""

    def test_the_approved_parameter_write_is_allowed(self) -> None:
        assert_led_target_in_sandbox(36, 3)

    @pytest.mark.parametrize(
        ("node", "parameter", "why"),
        [
            (36, 2, "button 1's LED, not approved"),
            (36, 4, "button 3's LED, not approved"),
            (36, 19, "load control, which Decision D4 says never to touch"),
            (39, 3, "Bedside Light R, never approved"),
            (30, 3, "the hallway ZEN35, never approved"),
        ],
    )
    def test_other_parameter_writes_are_refused(self, node: int, parameter: int, why: str) -> None:
        with pytest.raises(LedSandboxViolationError, match="REFUSED"):
            assert_led_target_in_sandbox(node, parameter)

    def test_the_approved_indicator_write_is_allowed(self) -> None:
        assert_indicator_target_in_sandbox(36, 68)

    @pytest.mark.parametrize(
        ("node", "indicator"),
        [(36, 67), (36, 69), (36, 70), (36, 71), (39, 68)],
    )
    def test_other_indicator_writes_are_refused(self, node: int, indicator: int) -> None:
        with pytest.raises(LedSandboxViolationError, match="REFUSED"):
            assert_indicator_target_in_sandbox(node, indicator)
