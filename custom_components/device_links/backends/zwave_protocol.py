"""Pure Z-Wave interpretation: association groups in, capability model out.

This module is how Device Links avoids hardcoding device models. It reads the association
group dump a Z-Wave device reports about itself and works out what each of its controls can
do, so the compiler can express "this button controls that light, with dimming" without ever
knowing what a ZEN35 is.

It is pure: no Home Assistant import, no I/O, no clock. It is handed already-parsed data and
returns value types, which is what lets it be tested directly against the fixtures Stage 0
captured from real hardware and reused from `tools/` probe scripts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from custom_components.device_links.models import Feature

# Command class ids exactly as they appear in a group's `issued_commands`.
BASIC_CC: Final = 32
BINARY_SWITCH_CC: Final = 37
MULTILEVEL_SWITCH_CC: Final = 38
SCENE_ACTIVATION_CC: Final = 43

# The commands within those classes that say something about what a group can carry.
BASIC_SET: Final = 1
BINARY_SWITCH_SET: Final = 1
MULTILEVEL_SET: Final = 1
MULTILEVEL_REPORT: Final = 3
MULTILEVEL_START_LEVEL_CHANGE: Final = 4
MULTILEVEL_STOP_LEVEL_CHANGE: Final = 5
SCENE_ACTIVATION_SET: Final = 1

# JSON gives string command class keys and the live driver gives integers, so the map is
# keyed by the normalized integer form and both shapes are accepted at the boundary.
type IssuedCommands = Mapping[str, Sequence[int]] | Mapping[int, Sequence[int]]

_FEATURE_BY_COMMAND: Final[Mapping[tuple[int, int], Feature]] = {
    (BASIC_CC, BASIC_SET): Feature.ON_OFF,
    (BINARY_SWITCH_CC, BINARY_SWITCH_SET): Feature.ON_OFF,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_SET): Feature.LEVEL_SET,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_START_LEVEL_CHANGE): Feature.LEVEL_HOLD,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_STOP_LEVEL_CHANGE): Feature.LEVEL_HOLD,
    (MULTILEVEL_SWITCH_CC, MULTILEVEL_REPORT): Feature.STATUS_REPORT,
    (SCENE_ACTIVATION_CC, SCENE_ACTIVATION_SET): Feature.SCENE,
}


def features_of_group(issued: IssuedCommands | None) -> frozenset[Feature]:
    """Return the features a group can carry, given the commands it issues.

    Start and stop level change are one feature, not two: hold-to-dim is a single thing a
    user asks for. A command the map does not know contributes nothing, so an unrecognised
    group offers the user no capability rather than one that would not work.
    """
    if issued is None:
        return frozenset()
    return frozenset(
        feature
        for command_class, commands in issued.items()
        for command in commands
        if (feature := _FEATURE_BY_COMMAND.get((int(command_class), command))) is not None
    )
