"""Loop analysis: the cycles worth flagging, and the far larger number that are not.

FR-R7 and E30. The value of this analysis is entirely in what it stays quiet about. A
two-way rule is a cycle in the control graph and is also the Virtual 3-way template, which
is one of the six things this product is for, so a check that flagged every cycle would fire
on the most ordinary rule anybody writes and be switched off within a week.

What it flags is a cycle every node of which repeats what it receives, which is a room that
will not settle.
"""

from __future__ import annotations

from dataclasses import replace

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_links.compiler import CompiledRule, compile_rule
from custom_components.device_links.loops import find_loops, forwarding_devices
from custom_components.device_links.models import (
    Direction,
    MirrorChoice,
    Profile,
    Rule,
)
from tests.conftest import CONTROLLER, LOBBY, MAIN_LIGHTS, a_profile, a_rule, activate
from tests.factories import capabilities_for, handle

CAPABILITIES = capabilities_for(CONTROLLER, MAIN_LIGHTS, LOBBY)


def compiled_of(*rules: Rule) -> dict[str, CompiledRule]:
    """Compile these rules the way the coordinator does, with `enabled` forced on."""
    return {rule.id: compile_rule(rule.with_enabled(True), CAPABILITIES) for rule in rules}


def two_way(rule_id: str, source: int, target: int, mirror: MirrorChoice) -> Rule:
    """Return a two-way rule between two nodes, with a mirror choice on its source."""
    base = a_rule(rule_id, source_node=source, target_node=target)
    return replace(base, direction=Direction.TWO_WAY, mirror_source=mirror)


# --------------------------------------------------------------------------------------
# What is not a loop
# --------------------------------------------------------------------------------------


def test_a_two_way_rule_with_nobody_forwarding_is_not_a_loop() -> None:
    """The Virtual 3-way template. A cycle, and not a loop, and the commonest rule there is."""
    rule = two_way("pair", CONTROLLER, MAIN_LIGHTS, MirrorChoice.LEAVE)

    assert find_loops(compiled_of(rule), [rule], forwarding=frozenset()) == ()


def test_a_two_way_rule_with_one_side_forwarding_is_not_a_loop() -> None:
    """A command that reaches a device which does not relay stops there, which is the point."""
    rule = two_way("pair", CONTROLLER, MAIN_LIGHTS, MirrorChoice.ON)

    loops = find_loops(compiled_of(rule), [rule], forwarding=forwarding_devices([rule]))

    assert loops == ()


def test_a_one_way_chain_of_forwarding_devices_is_not_a_loop() -> None:
    """Forwarding is only half of it: a chain with no way back cannot go round."""
    first = a_rule("first", source_node=CONTROLLER, target_node=MAIN_LIGHTS)
    second = a_rule("second", source_node=MAIN_LIGHTS, emitter_id="paddle", target_node=LOBBY)
    rules = [
        replace(first, mirror_source=MirrorChoice.ON),
        replace(second, mirror_source=MirrorChoice.ON),
    ]

    loops = find_loops(compiled_of(*rules), rules, forwarding=forwarding_devices(rules))

    assert loops == ()


def test_a_disabled_rule_contributes_nothing() -> None:
    """A rule somebody has already switched off is not a loop anybody has to be warned about."""
    rules = [
        two_way("pair", CONTROLLER, MAIN_LIGHTS, MirrorChoice.ON).with_enabled(False),
    ]
    forwarding = frozenset({handle(CONTROLLER).identity, handle(MAIN_LIGHTS).identity})

    assert find_loops(compiled_of(*rules), rules, forwarding=forwarding) == ()


# --------------------------------------------------------------------------------------
# What is
# --------------------------------------------------------------------------------------


def test_a_two_way_rule_with_mirroring_on_both_sides_is_a_loop() -> None:
    """FR-R7's acceptance criterion, said the way the requirement says it."""
    rule = two_way("pair", CONTROLLER, MAIN_LIGHTS, MirrorChoice.ON)
    # The other side's mirror is on already, which the rule cannot say and the device can.
    forwarding = forwarding_devices(
        [rule], {handle(MAIN_LIGHTS).identity: {"mirror_hub_commands": 1}}
    )

    loops = find_loops(compiled_of(rule), [rule], forwarding=forwarding)

    assert len(loops) == 1
    assert loops[0].identity == tuple(
        sorted((handle(CONTROLLER).identity, handle(MAIN_LIGHTS).identity))
    )
    assert loops[0].rule_ids == ("pair",)
    assert loops[0].rule_names == (rule.name,)


def test_two_rules_that_each_mirror_close_a_loop_between_them() -> None:
    """A loop can span rules, which is exactly why the compiler cannot answer this."""
    rules = [
        replace(
            a_rule("there", source_node=CONTROLLER, target_node=MAIN_LIGHTS),
            mirror_source=MirrorChoice.ON,
        ),
        replace(
            a_rule("back", source_node=MAIN_LIGHTS, emitter_id="paddle", target_node=CONTROLLER),
            mirror_source=MirrorChoice.ON,
        ),
    ]

    loops = find_loops(compiled_of(*rules), rules, forwarding=forwarding_devices(rules))

    assert len(loops) == 1
    assert loops[0].rule_ids == ("back", "there")


def test_a_three_device_ring_is_reported_once_with_every_rule_that_makes_it() -> None:
    """One loop, not three: a cycle has no first node, and three warnings say one thing."""
    rules = [
        replace(
            a_rule("a", source_node=CONTROLLER, target_node=MAIN_LIGHTS),
            mirror_source=MirrorChoice.ON,
        ),
        replace(
            a_rule("b", source_node=MAIN_LIGHTS, emitter_id="paddle", target_node=LOBBY),
            mirror_source=MirrorChoice.ON,
        ),
        replace(
            a_rule("c", source_node=LOBBY, emitter_id="paddle", target_node=CONTROLLER),
            mirror_source=MirrorChoice.ON,
        ),
    ]

    loops = find_loops(compiled_of(*rules), rules, forwarding=forwarding_devices(rules))

    assert len(loops) == 1
    assert len(loops[0].devices) == 3
    assert loops[0].rule_ids == ("a", "b", "c")


def test_a_forwarding_device_that_drives_into_a_loop_is_not_part_of_it() -> None:
    """A device that feeds a loop is not on it, and saying it was would send a user to it.

    The graph walk has to notice that it has already finished the loop it is now pointing
    into, rather than folding the feeder in or looking for it a second time.
    """
    rules = [
        replace(
            a_rule("there", source_node=LOBBY, emitter_id="paddle", target_node=CONTROLLER),
            mirror_source=MirrorChoice.ON,
        ),
        replace(
            a_rule("back", source_node=CONTROLLER, emitter_id="g5", target_node=LOBBY),
            mirror_source=MirrorChoice.ON,
        ),
        replace(
            a_rule("feeder", source_node=MAIN_LIGHTS, emitter_id="paddle", target_node=LOBBY),
            mirror_source=MirrorChoice.ON,
        ),
    ]

    loops = find_loops(compiled_of(*rules), rules, forwarding=forwarding_devices(rules))

    assert len(loops) == 1
    assert loops[0].identity == tuple(sorted((handle(LOBBY).identity, handle(CONTROLLER).identity)))
    assert loops[0].rule_ids == ("back", "there")


def test_a_device_that_forwards_because_somebody_else_set_it_still_counts() -> None:
    """The case the desired state cannot see: half the loop was there before the rule."""
    rules = [
        a_rule("there", source_node=CONTROLLER, target_node=MAIN_LIGHTS),
        a_rule("back", source_node=MAIN_LIGHTS, emitter_id="paddle", target_node=CONTROLLER),
    ]
    observed = {
        handle(CONTROLLER).identity: {"mirror_hub_commands": 1},
        handle(MAIN_LIGHTS).identity: {"mirror_hub_commands": 1},
    }

    loops = find_loops(compiled_of(*rules), rules, forwarding=forwarding_devices(rules, observed))

    assert len(loops) == 1


def test_a_mirror_setting_that_reads_zero_is_not_forwarding() -> None:
    """Off is off. A setting that was read and is not on is the commonest answer there is."""
    rules = [a_rule("there", source_node=CONTROLLER, target_node=MAIN_LIGHTS)]
    observed = {handle(CONTROLLER).identity: {"mirror_hub_commands": 0}}

    assert forwarding_devices(rules, observed) == frozenset()


# --------------------------------------------------------------------------------------
# Through the coordinator and the API, which is where a user meets it
# --------------------------------------------------------------------------------------


@pytest.fixture
def looping(device_links_entry: MockConfigEntry) -> Profile:
    """A profile whose two rules point at each other, both sides mirroring."""
    profile = a_profile(
        replace(
            a_rule("there", source_node=CONTROLLER, target_node=MAIN_LIGHTS),
            mirror_source=MirrorChoice.ON,
        ),
        replace(
            a_rule("back", source_node=MAIN_LIGHTS, emitter_id="paddle", target_node=CONTROLLER),
            mirror_source=MirrorChoice.ON,
        ),
    )
    activate(device_links_entry, profile)
    return profile


async def test_the_coordinator_finds_the_loop_the_active_profile_makes(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, looping: Profile
) -> None:
    """The scope decision: the active profile, whole, across every backend."""
    await hass.async_block_till_done()

    loops = device_links_entry.runtime_data.coordinator.find_loops()

    assert len(loops) == 1
    assert loops[0].rule_ids == ("back", "there")


async def test_a_draft_rule_is_folded_in_so_the_warning_arrives_before_the_save(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """FR-R7 says "before save", and this is the whole of what that means."""
    activate(
        device_links_entry,
        a_profile(
            replace(
                a_rule("there", source_node=CONTROLLER, target_node=MAIN_LIGHTS),
                mirror_source=MirrorChoice.ON,
            )
        ),
    )
    await hass.async_block_till_done()
    coordinator = device_links_entry.runtime_data.coordinator
    assert coordinator.find_loops() == ()

    draft = replace(
        a_rule("back", source_node=MAIN_LIGHTS, emitter_id="paddle", target_node=CONTROLLER),
        mirror_source=MirrorChoice.ON,
    )

    assert len(coordinator.find_loops(draft)) == 1


async def test_editing_the_rule_that_closes_a_loop_shows_the_loop_going_away(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, looping: Profile
) -> None:
    """A draft replaces the stored rule of the same id, so a fix reads as a fix."""
    await hass.async_block_till_done()
    coordinator = device_links_entry.runtime_data.coordinator
    fixed = replace(
        next(rule for rule in looping.rules if rule.id == "back"),
        mirror_source=MirrorChoice.LEAVE,
    )

    assert coordinator.find_loops(fixed) == ()
