"""The write sandbox guard must refuse everything it was not explicitly approved for.

These tests are the reason it is safe to run a write probe against Jayant's live house.
They need no radio and no network.
"""

from __future__ import annotations

import pytest
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
