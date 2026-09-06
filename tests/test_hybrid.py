"""Hybrid legs: what compiles into one, and what one does once it is running.

Two halves, and the second is the one that matters. The compiler half is pure and cheap to
be sure of. The manager half is where a leg becomes a listener inside somebody's Home
Assistant, and the property this file exists to pin down is that a leg dies with its rule:
disabling the rule, switching the profile, deleting the rule and unloading the entry all
have to leave nothing behind, because a leg that outlives its rule fires against a house
whose owner thought they had turned it off.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from zwave_js_server.const import CommandClass

from custom_components.device_links import hybrid as hybrid_module
from custom_components.device_links.compiler import compile_rule
from custom_components.device_links.const import DOMAIN, OPTION_HYBRID_LEGS
from custom_components.device_links.coordinator import RuleState
from custom_components.device_links.hybrid import (
    CENTRAL_SCENE_COMMAND_CLASS,
    INDICATION_MIN_INTERVAL_SECONDS,
    ZWAVE_VALUE_NOTIFICATION,
    HybridLegs,
)
from custom_components.device_links.models import (
    Backend as BackendId,
)
from custom_components.device_links.models import (
    Direction,
    Feature,
    HybridKind,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from custom_components.device_links.repairs import ISSUE_HYBRID_LEGS_FAILING
from tests.conftest import CONTROLLER, MAIN_LIGHTS, a_profile, activate
from tests.factories import capabilities_for, handle
from tests.fakes.zwave import FakeDriver

# Node 36's small button 2, which is the one control on this network that carries both
# facts a hybrid leg needs: a scene number to react to, and an indicator to light.
BUTTON = "g7"
BUTTON_SCENE = 2
BUTTON_INDICATOR = 68

# Its main paddle, which carries neither, and is therefore what a refusal is tested on.
PADDLE = "g2"


def hybrid_rule(
    *kinds: HybridKind,
    features: frozenset[Feature] = frozenset({Feature.ON_OFF}),
    emitter_id: str = BUTTON,
    targets: tuple[RuleTarget, ...] | None = None,
    template: Template = Template.SCENE_BUTTON,
    rule_id: str = "hybrid",
) -> Rule:
    """Return a rule that opts into these HA-executed legs and nothing else."""
    return Rule(
        id=rule_id,
        name="Button 2 does something no radio can",
        template=template,
        backend=BackendId.ZWAVE,
        source=RuleSource(device=handle(CONTROLLER), endpoint=0, emitter_id=emitter_id),
        targets=targets or (RuleTarget(device=handle(MAIN_LIGHTS), endpoint=None),),
        features=features,
        hybrid=frozenset(kinds),
    )


# --------------------------------------------------------------------------------------
# The compiler: what becomes a leg, and what is refused rather than guessed
# --------------------------------------------------------------------------------------


def test_a_rule_cannot_ask_for_on_only_and_off_only_at_once() -> None:
    """The two together are the plain association the user was trying to avoid."""
    with pytest.raises(ValueError, match="on-only and off-only"):
        hybrid_rule(HybridKind.ON_ONLY, HybridKind.OFF_ONLY)


def test_on_only_replaces_the_native_link_rather_than_joining_it() -> None:
    """Writing the group as well would be the intent the user rejected, plus half of it."""
    compiled = compile_rule(
        hybrid_rule(HybridKind.ON_ONLY), capabilities_for(CONTROLLER, MAIN_LIGHTS)
    )

    assert compiled.links == ()
    assert [leg.kind for leg in compiled.hybrid_legs] == [HybridKind.ON_ONLY]
    leg = compiled.hybrid_legs[0]
    assert leg.scene_id == BUTTON_SCENE
    assert leg.target.handle.identity == handle(MAIN_LIGHTS).identity
    assert not compiled.errors


def test_the_features_a_leg_does_not_take_over_still_compile_natively() -> None:
    """A leg takes one feature, not the rule: the rest is still written to the device."""
    compiled = compile_rule(
        hybrid_rule(HybridKind.OFF_ONLY, features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD})),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    assert [link.feature for link in compiled.links] == [Feature.LEVEL_HOLD]
    assert [leg.feature for leg in compiled.hybrid_legs] == [Feature.ON_OFF]


def test_a_control_with_no_scene_number_refuses_the_leg_rather_than_guessing_one() -> None:
    """A leg that fired on the wrong button is worse than a leg that was not made."""
    compiled = compile_rule(
        hybrid_rule(HybridKind.ON_ONLY, emitter_id=PADDLE),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    assert compiled.hybrid_legs == ()
    assert [error.translation_key for error in compiled.errors] == ["hybrid_no_scene"]


def test_a_self_target_is_an_error_without_the_opt_in_and_a_leg_with_it() -> None:
    """Kind (b) is the whole reason `self_association_use_hybrid_leg` names a way out."""
    targets = (
        RuleTarget(device=handle(MAIN_LIGHTS), endpoint=None),
        RuleTarget(device=handle(CONTROLLER), endpoint=None),
    )
    capabilities = capabilities_for(CONTROLLER, MAIN_LIGHTS)

    refused = compile_rule(hybrid_rule(targets=targets), capabilities)
    assert [error.translation_key for error in refused.errors] == [
        "self_association_use_hybrid_leg"
    ]

    allowed = compile_rule(hybrid_rule(HybridKind.SELF_LOAD, targets=targets), capabilities)
    assert not allowed.errors
    assert [leg.kind for leg in allowed.hybrid_legs] == [HybridKind.SELF_LOAD]
    # The other target still gets its ordinary association: only the impossible half moved.
    assert [link.target.handle.identity for link in allowed.links] == [handle(MAIN_LIGHTS).identity]


def test_opting_into_the_own_load_without_naming_the_device_says_so() -> None:
    """A leg with nothing to act on is a checkbox that did nothing, said out loud."""
    compiled = compile_rule(
        hybrid_rule(HybridKind.SELF_LOAD), capabilities_for(CONTROLLER, MAIN_LIGHTS)
    )

    assert compiled.hybrid_legs == ()
    assert "hybrid_self_load_not_targeted" in {
        warning.translation_key for warning in compiled.warnings
    }


def test_the_button_led_leg_carries_the_indicator_the_curated_entry_names() -> None:
    """Kind (c) is Indicator CC, and the id is a curated fact rather than a derivation."""
    compiled = compile_rule(
        hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT})),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    assert [leg.indicator_id for leg in compiled.hybrid_legs] == [BUTTON_INDICATOR]
    # The control cannot send a status report over any group, and that is not reported as a
    # problem: it is precisely why the leg exists.
    assert not compiled.errors
    assert "feature_unavailable_status_report" not in {
        warning.translation_key for warning in compiled.warnings
    }


def test_a_control_with_no_indicator_refuses_the_button_led_leg() -> None:
    """Lighting the wrong button is the failure this refusal exists to prevent."""
    compiled = compile_rule(
        hybrid_rule(
            HybridKind.BUTTON_LED,
            features=frozenset({Feature.STATUS_REPORT}),
            emitter_id=PADDLE,
        ),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    assert compiled.hybrid_legs == ()
    assert [error.translation_key for error in compiled.errors] == ["hybrid_no_button_indication"]


def test_a_press_leg_on_an_unverified_button_warns_before_it_is_saved() -> None:
    """The scene numbers are inferred from three agreeing labels, not observed (T70)."""
    compiled = compile_rule(
        hybrid_rule(HybridKind.ON_ONLY), capabilities_for(CONTROLLER, MAIN_LIGHTS)
    )

    assert "hybrid_scene_unverified" in {warning.translation_key for warning in compiled.warnings}


def test_a_two_way_rule_is_told_the_reverse_leg_still_carries_both() -> None:
    """On-only is about the direction the user authored, and saying otherwise would lie."""
    compiled = compile_rule(
        replace(hybrid_rule(HybridKind.ON_ONLY), direction=Direction.TWO_WAY),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    assert "hybrid_reverse_carries_both" in {
        warning.translation_key for warning in compiled.warnings
    }


def test_a_leg_identity_separates_two_legs_that_differ_only_by_target() -> None:
    """The identity keys the running set, so two legs sharing one would silence one."""
    compiled = compile_rule(
        hybrid_rule(
            HybridKind.OFF_ONLY,
            targets=(
                RuleTarget(device=handle(MAIN_LIGHTS), endpoint=None),
                RuleTarget(device=handle(35), endpoint=None),
            ),
        ),
        capabilities_for(CONTROLLER, MAIN_LIGHTS, 35),
    )

    identities = {leg.identity for leg in compiled.hybrid_legs}
    assert len(identities) == len(compiled.hybrid_legs) == 2


# --------------------------------------------------------------------------------------
# The manager: registration, firing, and dying with the rule
# --------------------------------------------------------------------------------------


@pytest.fixture
async def hybrid_entry(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> MockConfigEntry:
    """Device Links set up with the global hybrid option on, as FR-H1 requires first."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Device Links",
        options={OPTION_HYBRID_LEGS: True},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def a_light(
    hass: HomeAssistant, devices: dict[int, dr.DeviceEntry], node_id: int, state: str = STATE_OFF
) -> str:
    """Register a light on one node's device entry and put it in a state.

    A leg acts on entities rather than on nodes, so a device with nothing Home Assistant
    can turn on is a leg with nothing to do: this is what gives it something.
    """
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "light", "zwave_js", f"light-{node_id}", device_id=devices[node_id].id
    )
    hass.states.async_set(entry.entity_id, state)
    return entry.entity_id


def press(hass: HomeAssistant, devices: dict[int, dr.DeviceEntry], scene: int) -> None:
    """Fire the value notification a Central Scene button press produces."""
    hass.bus.async_fire(
        ZWAVE_VALUE_NOTIFICATION,
        {
            "device_id": devices[CONTROLLER].id,
            "command_class": CENTRAL_SCENE_COMMAND_CLASS,
            "property": "scene",
            "property_key": scene,
            "property_key_name": f"{scene:03d}",
            "value": "KeyPressed",
        },
    )


async def _after_the_rate_limit(hass: HomeAssistant) -> None:
    """Let the write hygiene timer fire, which is where a coalesced value is sent."""
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=INDICATION_MIN_INTERVAL_SECONDS + 1)
    )
    await hass.async_block_till_done()


def legs_of(entry: MockConfigEntry) -> HybridLegs:
    """Return the manager this entry built."""
    hybrid: HybridLegs = entry.runtime_data.hybrid
    return hybrid


async def test_no_leg_is_registered_while_the_global_option_is_off(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """FR-H1's first gate: a rule may carry the opt-in and still be inert (D3)."""
    activate(device_links_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    hybrid = legs_of(device_links_entry)
    assert not hybrid.allowed
    assert hybrid.running == ()


async def test_a_press_turns_the_target_off_through_one_service_call(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """The whole of kind (a): Home Assistant is the wire the association cannot be."""
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()
    assert len(legs_of(hybrid_entry).running) == 1

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    assert [call.data["entity_id"] for call in calls] == [[light]]
    assert legs_of(hybrid_entry).status_for("hybrid").fired == 1


async def test_a_press_on_another_button_of_the_same_device_does_nothing(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A filter on the device alone would fire every leg on a five-button controller."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    press(hass, zwave_js_devices, BUTTON_SCENE + 1)
    await hass.async_block_till_done()

    assert calls == []


async def test_a_burst_of_identical_presses_produces_one_command(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """FR-H2's de-duplication, on the leading edge so the light still responds at once."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    for _ in range(4):
        press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    assert len(calls) == 1


async def test_the_own_load_leg_acts_on_the_controller_rather_than_the_target(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """Kind (b) exists because a node cannot be in its own association group."""
    own_load = a_light(hass, zwave_js_devices, CONTROLLER, STATE_ON)
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(
        hybrid_entry,
        a_profile(
            hybrid_rule(
                HybridKind.SELF_LOAD,
                targets=(
                    RuleTarget(device=handle(MAIN_LIGHTS), endpoint=None),
                    RuleTarget(device=handle(CONTROLLER), endpoint=None),
                ),
                template=Template.OFF_ALL,
            )
        ),
    )
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    assert [call.data["entity_id"] for call in calls] == [[own_load]]


async def test_the_button_led_leg_writes_the_indicator_and_puts_it_back(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """Kind (c) on Indicator CC, and the restore that makes disabling it honest.

    Nothing here writes a configuration parameter, which is the point of the Z8 finding: a
    parameter write is a flash write, and a leg that mirrors a light does it every time
    that light changes.
    """
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    rule = hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))
    activate(hybrid_entry, a_profile(rule))
    await hass.async_block_till_done()

    backend = hybrid_entry.runtime_data.coordinator.backend_for(handle(CONTROLLER))
    assert backend is not None
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is True

    # A light ramping through its levels emits a state change per step, and every one of
    # them says the same thing to a binary indicator, so they are deduplicated to nothing.
    for level in (50, 80, 100):
        hass.states.async_set(light, STATE_ON, {"brightness": level})
    await hass.async_block_till_done()

    # The next real change lands inside the rate limit, so it is coalesced into a write
    # that happens when the limit expires rather than sent as a second radio frame. The
    # change after it lands while that timer is pending, and is picked up by it.
    hass.states.async_set(light, STATE_OFF)
    hass.states.async_set(light, STATE_ON)
    hass.states.async_set(light, STATE_OFF)
    await hass.async_block_till_done()
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is True
    await _after_the_rate_limit(hass)
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is False

    # Disabling the rule retires the leg, which puts the indicator back where it was.
    hass.states.async_set(light, STATE_ON)
    await _after_the_rate_limit(hass)
    hybrid_entry.runtime_data.coordinator.async_set_rule_enabled(rule.id, enabled=False)
    await hass.async_block_till_done()
    assert legs_of(hybrid_entry).running == ()
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is False


async def test_a_leg_dies_when_its_rule_is_disabled_and_comes_back_when_it_is_enabled(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A leg that outlives its rule fires against a house nobody armed."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    coordinator = hybrid_entry.runtime_data.coordinator
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    coordinator.async_set_rule_enabled("hybrid", enabled=False)
    await hass.async_block_till_done()
    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()
    assert calls == []

    coordinator.async_set_rule_enabled("hybrid", enabled=True)
    await hass.async_block_till_done()
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_a_leg_dies_when_the_profile_is_switched(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """The other profile does not ask for this leg, so nothing may still be listening."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    coordinator = hybrid_entry.runtime_data.coordinator
    activate(
        hybrid_entry,
        a_profile(hybrid_rule(HybridKind.OFF_ONLY)),
        a_profile(profile_id="guest", name="Guest"),
    )
    await hass.async_block_till_done()
    assert len(legs_of(hybrid_entry).running) == 1

    coordinator.async_activate_profile("guest")
    await hass.async_block_till_done()

    assert legs_of(hybrid_entry).running == ()
    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()
    assert calls == []


async def test_a_leg_dies_when_the_entry_is_unloaded(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A listener that survives an unload survives a reload as a second copy of itself."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    await hass.config_entries.async_unload(hybrid_entry.entry_id)
    await hass.async_block_till_done()
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    assert calls == []


async def test_home_assistant_starting_registers_the_legs_again(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """FR-H2 registers on start as well, because the entities may not exist before it."""
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()
    assert [call.data["entity_id"] for call in calls] == [[light]]


async def test_a_firing_that_fails_is_counted_and_raises_an_issue_above_the_threshold(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leg firing at 3am has no dialog to report into, so it counts and it Repairs.

    The debounce is taken out for this one: it is measured against a monotonic clock that
    Home Assistant's own time travel does not move, and what is being tested here is five
    firings rather than the swallowing of a burst, which has its own test above.
    """
    monkeypatch.setattr(hybrid_module, "PRESS_DEBOUNCE_SECONDS", 0.0)
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    def _refuse(_call: Any) -> None:
        raise ValueError("the light is not answering")

    hass.services.async_register("homeassistant", "turn_off", _refuse)
    for _ in range(5):
        press(hass, zwave_js_devices, BUTTON_SCENE)
        await hass.async_block_till_done()

    status = legs_of(hybrid_entry).status_for("hybrid")
    assert status.errors == status.fired == 5
    assert status.last_fired is not None
    assert (DOMAIN, ISSUE_HYBRID_LEGS_FAILING) in ir.async_get(hass).issues


async def test_the_status_and_health_sensors_report_the_counters(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """FR-H2 puts the counts on the rule's own sensor and the aggregate on Health."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()
    hass.services.async_register("homeassistant", "turn_off", lambda _call: None)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    health = hass.states.get("sensor.device_links_health")
    assert health is not None
    assert health.attributes["hybrid"] == {
        "allowed": True,
        "hybrid_legs": 1,
        "hybrid_fired": 1,
        "hybrid_errors": 0,
        "hybrid_last_fired": legs_of(hybrid_entry).totals.last_fired,
    }


async def test_a_rule_that_is_only_hybrid_reads_in_sync_rather_than_blocked(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry
) -> None:
    """A rule with nothing on a device has nothing to be out of sync with (E4)."""
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    assert hybrid_entry.runtime_data.coordinator.drift_state()["hybrid"] is RuleState.IN_SYNC


async def test_the_same_rule_reads_blocked_when_the_option_is_off(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """The other half of the same question: nothing is running, so nothing is in sync."""
    activate(device_links_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    assert device_links_entry.runtime_data.coordinator.drift_state()["hybrid"] is (
        RuleState.BLOCKED
    )


# --------------------------------------------------------------------------------------
# The edges: what a leg does when it cannot do what it was asked
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "why"),
    [
        ({"command_class": 32}, "a Basic Set is not a button press"),
        ({"value": "KeyHeldDown"}, "a hold is not a press, and would fire three times"),
        ({"property_key": 9, "property_key_name": "009"}, "another button on the same device"),
        ({"device_id": "somebody-else"}, "the same button number on another controller"),
    ],
)
async def test_a_notification_that_is_not_this_button_being_pressed_does_nothing(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    data: dict[str, Any],
    why: str,
) -> None:
    """Every one of these would be a leg firing on something the user did not do."""
    assert why
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    hass.bus.async_fire(
        ZWAVE_VALUE_NOTIFICATION,
        {
            "device_id": zwave_js_devices[CONTROLLER].id,
            "command_class": CENTRAL_SCENE_COMMAND_CLASS,
            "property_key": BUTTON_SCENE,
            "property_key_name": f"{BUTTON_SCENE:03d}",
            "value": "KeyPressed",
            **data,
        },
    )
    await hass.async_block_till_done()

    assert calls == []


async def test_a_notification_with_only_the_padded_scene_name_still_matches(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """Which of the two fields carries the number has changed between zwave-js versions."""
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    hass.bus.async_fire(
        ZWAVE_VALUE_NOTIFICATION,
        {
            "device_id": zwave_js_devices[CONTROLLER].id,
            "command_class": CENTRAL_SCENE_COMMAND_CLASS,
            "property_key": "Scene 002",
            "property_key_name": f"{BUTTON_SCENE:03d}",
            "value": "KeyPressed",
        },
    )
    await hass.async_block_till_done()

    assert [call.data["entity_id"] for call in calls] == [[light]]


async def test_a_press_with_nothing_to_act_on_is_counted_as_an_error(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A device with no load entity is a leg that can do nothing, and it says so.

    No light is registered here on purpose. A leg firing at three in the morning has
    nowhere to report into, so a firing that could do nothing is counted rather than
    silently skipped: the counter is the whole report.
    """
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    status = legs_of(hybrid_entry).status_for("hybrid")
    assert status.fired == status.errors == 1


async def test_a_service_call_that_fails_once_is_retried_and_counted_as_a_success(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """FR-H2's one retry. Two tries and no more: a press has a moment to be for."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    attempts: list[Any] = []

    def _flaky(call: Any) -> None:
        attempts.append(call)
        if len(attempts) == 1:
            raise ValueError("the mesh was busy")

    hass.services.async_register("homeassistant", "turn_off", _flaky)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    assert len(attempts) == 2
    status = legs_of(hybrid_entry).status_for("hybrid")
    assert (status.fired, status.errors) == (1, 0)


async def test_a_button_led_leg_whose_target_has_no_entity_writes_nothing(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry
) -> None:
    """Nothing to watch means nothing to mirror, and nothing to put back afterwards."""
    rule = hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))
    activate(hybrid_entry, a_profile(rule))
    await hass.async_block_till_done()

    backend = hybrid_entry.runtime_data.coordinator.backend_for(handle(CONTROLLER))
    assert backend is not None
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is False

    # Retiring it restores nothing, because nothing was recorded: a leg that never wrote
    # has no "before" to put back, and inventing one would be this integration deciding
    # what somebody's button looked like.
    hybrid_entry.runtime_data.coordinator.async_set_rule_enabled(rule.id, enabled=False)
    await hass.async_block_till_done()
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is False


async def test_a_device_that_does_not_report_its_indicator_is_counted_as_an_error(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """A curated indicator id the device has never reported is a write with nowhere to go."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    node = zwave_driver.controller.nodes[CONTROLLER]
    for value_id, value in list(node.values.items()):
        if int(value.command_class) == CommandClass.INDICATOR:
            del node.values[value_id]
    activate(
        hybrid_entry,
        a_profile(hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))),
    )
    await hass.async_block_till_done()

    status = legs_of(hybrid_entry).status_for("hybrid")
    assert status.errors == status.fired == 1


async def test_a_press_whose_target_has_no_device_record_is_counted_as_an_error(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """The target left the registry, so there is nothing named to turn off."""
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()
    dr.async_get(hass).async_remove_device(zwave_js_devices[MAIN_LIGHTS].id)

    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    assert legs_of(hybrid_entry).status_for("hybrid").errors == 1


async def test_a_leg_on_a_device_home_assistant_has_no_record_of_registers_nothing(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A press can never be recognised for a device with no registry entry to filter on."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    dr.async_get(hass).async_remove_device(zwave_js_devices[CONTROLLER].id)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    # The leg is running, and it is listening for nothing: registering a filter on a device
    # id we do not have would mean firing on every press in the house.
    assert len(legs_of(hybrid_entry).running) == 1
    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    hass.bus.async_fire(
        ZWAVE_VALUE_NOTIFICATION,
        {
            "device_id": "gone",
            "command_class": CENTRAL_SCENE_COMMAND_CLASS,
            "property_key": BUTTON_SCENE,
            "value": "KeyPressed",
        },
    )
    await hass.async_block_till_done()
    assert calls == []


async def test_retiring_a_leg_mid_coalesce_cancels_the_write_it_was_waiting_to_make(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A timer that outlives its leg writes to a device after the rule was turned off."""
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    rule = hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))
    activate(hybrid_entry, a_profile(rule))
    await hass.async_block_till_done()
    backend = hybrid_entry.runtime_data.coordinator.backend_for(handle(CONTROLLER))
    assert backend is not None
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is True

    # Inside the rate limit, so the write is pending on a timer rather than sent.
    hass.states.async_set(light, STATE_OFF)
    await hass.async_block_till_done()
    hybrid_entry.runtime_data.coordinator.async_set_rule_enabled(rule.id, enabled=False)
    await hass.async_block_till_done()
    await _after_the_rate_limit(hass)

    # The restore ran and the cancelled write did not, so the indicator is where it began.
    assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is False


async def test_a_backend_that_raises_while_writing_is_counted_rather_than_escaping(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """A leg fires from a bus callback, where a raised exception takes the callback with it."""
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(
        hybrid_entry,
        a_profile(hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))),
    )
    await hass.async_block_till_done()
    before = legs_of(hybrid_entry).status_for("hybrid").errors

    # The node leaves the network between the registration and the next state change,
    # which is what an exclusion or a failed node looks like from inside the adapter.
    del zwave_driver.controller.nodes[CONTROLLER]
    hass.states.async_set(light, STATE_OFF)
    await _after_the_rate_limit(hass)

    assert legs_of(hybrid_entry).status_for("hybrid").errors == before + 1


async def test_a_leg_leaves_a_devices_configuration_entities_alone(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A config switch is in a load's domain and is not a load.

    A Zooz switch exposes its smart bulb mode as a `switch` in the config category. A leg
    that turned that off every time somebody pressed a scene button would be a far stranger
    fault than the one legs exist to fix, and it would look like the device forgetting its
    own settings.
    """
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    registry = er.async_get(hass)
    config = registry.async_get_or_create(
        "switch",
        "zwave_js",
        "smart-bulb-mode",
        device_id=zwave_js_devices[MAIN_LIGHTS].id,
        entity_category=EntityCategory.CONFIG,
    )
    hass.states.async_set(config.entity_id, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    calls: list[Any] = []
    hass.services.async_register("homeassistant", "turn_off", calls.append)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    assert [call.data["entity_id"] for call in calls] == [[light]]


async def test_the_plan_lists_the_legs_and_leaves_them_out_of_the_work(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry
) -> None:
    """PRD Section 6.7: the plan lists a leg under HA-executed rather than as a write.

    Not in the token and not in the counts, because a leg starts when its rule is saved and
    enabled and pressing Apply does not touch it. Listed anyway, because a user confirming
    a plan should not have to find out afterwards that half of a rule is HA-executed.
    """
    from custom_components.device_links.serialize import Serializer  # noqa: PLC0415

    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()
    coordinator = hybrid_entry.runtime_data.coordinator

    payload = Serializer(hass, hybrid_entry).plan(  # type: ignore[arg-type]
        await coordinator.async_plan(), frozenset()
    )

    assert [leg["kind"] for leg in payload["hybrid_legs"]] == ["off_only"]
    assert payload["counts"]["add"] == 0
    # A plan that is about devices rather than about rules lists none: a rollback and a
    # swap change no listener, so legs beside either would be padding.
    assert (
        Serializer(hass, hybrid_entry).plan(await coordinator.async_plan())["hybrid_legs"] == []  # type: ignore[arg-type]
    )


async def test_the_plan_lists_no_leg_while_the_option_is_off(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Nothing is running, so listing one would describe something that is not happening."""
    from custom_components.device_links.serialize import Serializer  # noqa: PLC0415

    activate(device_links_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()
    coordinator = device_links_entry.runtime_data.coordinator

    payload = Serializer(hass, device_links_entry).plan(  # type: ignore[arg-type]
        await coordinator.async_plan(), frozenset()
    )

    assert payload["hybrid_legs"] == []


# --------------------------------------------------------------------------------------
# What a fresh-eyes review found, and the tests that would have caught it
# --------------------------------------------------------------------------------------


def test_a_two_way_rule_still_writes_the_reverse_leg_when_a_hybrid_leg_takes_on_off() -> None:
    """The warning says the reverse still carries both, so the reverse has to exist.

    Taking on/off out of the feature set for the forward leg also emptied it for the
    reverse, so a two-way on-only rule compiled one leg and no links at all, while telling
    the user that the direction they did not author still carried on and off. The warning
    was the only thing standing where a link should have been.
    """
    compiled = compile_rule(
        replace(hybrid_rule(HybridKind.ON_ONLY), direction=Direction.TWO_WAY),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    reverse = [
        link for link in compiled.links if link.source.identity != handle(CONTROLLER).identity
    ]
    assert [link.feature for link in reverse] == [Feature.ON_OFF]
    assert "hybrid_reverse_carries_both" in {
        warning.translation_key for warning in compiled.warnings
    }


def test_a_button_led_leg_is_refused_for_a_rule_with_more_than_one_target() -> None:
    """One button has one light on it, and two legs would fight over it forever.

    Each leg watches its own target and writes the same indicator, so the LED would flip on
    every change of either light and settle on whichever wrote last. There is no state the
    two of them agree on and no warning that would make it acceptable.
    """
    compiled = compile_rule(
        hybrid_rule(
            HybridKind.BUTTON_LED,
            features=frozenset({Feature.STATUS_REPORT}),
            targets=(
                RuleTarget(device=handle(MAIN_LIGHTS), endpoint=None),
                RuleTarget(device=handle(35), endpoint=None),
            ),
        ),
        capabilities_for(CONTROLLER, MAIN_LIGHTS, 35),
    )

    assert compiled.hybrid_legs == ()
    assert [error.translation_key for error in compiled.errors] == ["hybrid_button_led_one_target"]


def test_an_opt_in_that_acts_on_no_feature_this_rule_asks_for_says_so() -> None:
    """A tick box that silently does nothing is worse than one that was never offered.

    The editor offers a control's opt-ins from what the control can carry rather than from
    what the rule wants, so "keep this button's LED in sync" can be ticked on a rule with
    no status report in it. That rule saved clean and did nothing at all.
    """
    compiled = compile_rule(
        hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.ON_OFF})),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    assert compiled.hybrid_legs == ()
    assert not compiled.errors
    assert "hybrid_opt_in_unused" in {warning.translation_key for warning in compiled.warnings}


def test_hold_to_dim_is_not_reported_as_unavailable_when_a_leg_carries_the_on_off() -> None:
    """A feature a leg took over is the answer, so warning about it reports the answer."""
    compiled = compile_rule(
        hybrid_rule(HybridKind.ON_ONLY, features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD})),
        capabilities_for(CONTROLLER, MAIN_LIGHTS),
    )

    assert "level_hold_without_on_off" not in {
        warning.translation_key for warning in compiled.warnings
    }


async def test_the_button_led_restore_survives_being_turned_off_and_on_again(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """The value put back is the user's own, not the one the leg last wrote.

    The restore used to go through the same path as an ordinary write, which records what
    it finds before writing. By then the leg had already popped its record, so the restore
    recorded its own value as the user's. One more enable-and-disable and the LED was left
    showing a state nobody chose, with nothing left that would ever change it.
    """
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    rule = hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))
    coordinator = hybrid_entry.runtime_data.coordinator
    backend = coordinator.backend_for(handle(CONTROLLER))
    assert backend is not None

    for _cycle in (1, 2):
        activate(hybrid_entry, a_profile(rule))
        await hass.async_block_till_done()
        assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is True
        coordinator.async_set_rule_enabled(rule.id, enabled=False)
        await hass.async_block_till_done()
        # False is what the fixture device reported before any leg touched it, and it is
        # what has to come back every time, not only the first.
        assert await backend.async_read_indication(handle(CONTROLLER), BUTTON) is False
        assert light


async def test_a_leg_that_moves_to_another_rule_is_counted_against_that_rule(
    hass: HomeAssistant, hybrid_entry: MockConfigEntry, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """A leg's identity leaves the rule out, so the running set has to be told when it moves.

    Delete the rule and write the same leg under another id, and the listeners are still
    exactly right: same device, same button, same target. What was wrong was the
    bookkeeping, which went on crediting a rule that no longer existed.
    """
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY, rule_id="first")))
    await hass.async_block_till_done()

    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY, rule_id="second")))
    await hass.async_block_till_done()
    hass.services.async_register("homeassistant", "turn_off", lambda _call: None)
    press(hass, zwave_js_devices, BUTTON_SCENE)
    await hass.async_block_till_done()

    hybrid = legs_of(hybrid_entry)
    assert hybrid.status_for("second").fired == 1
    assert hybrid.status_for("second").legs == 1
    # And the rule that has gone is forgotten rather than left summing into the total.
    assert hybrid.status_for("first").fired == 0
    assert hybrid.totals.fired == 1


async def test_a_leg_that_fails_while_it_registers_does_not_register_itself_again(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """Registering a leg reaches a device, and reaching a device can come back here.

    A button LED is lit to match its light the moment the leg starts watching it. That
    write can fail, a failure counts, counting tells the entities, and the entities are
    told through the coordinator, which is what asks this manager to re-sync. A leg that
    was not in the running map until after its listeners were wired was started again by
    that re-sync, and again, until the test ran out of patience.
    """
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    node = zwave_driver.controller.nodes[CONTROLLER]
    for value_id, value in list(node.values.items()):
        if int(value.command_class) == CommandClass.INDICATOR:
            del node.values[value_id]
    activate(
        hybrid_entry,
        a_profile(hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))),
    )
    await hass.async_block_till_done()

    assert legs_of(hybrid_entry).status_for("hybrid").fired == 1


async def test_the_repairs_issue_clears_once_the_legs_are_working_again(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rate is measured over the last few firings, so a fault that stops is forgotten.

    Measured over the life of the entry instead, a light that was unplugged for an hour
    would leave the issue up until the user had pressed the button a dozen more times, and
    the message would say "4 of the last 4" throughout.
    """
    monkeypatch.setattr(hybrid_module, "PRESS_DEBOUNCE_SECONDS", 0.0)
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(hybrid_entry, a_profile(hybrid_rule(HybridKind.OFF_ONLY)))
    await hass.async_block_till_done()

    working = False

    def _sometimes(_call: Any) -> None:
        if not working:
            raise ValueError("the light is not answering")

    hass.services.async_register("homeassistant", "turn_off", _sometimes)
    for _ in range(5):
        press(hass, zwave_js_devices, BUTTON_SCENE)
        await hass.async_block_till_done()
    assert (DOMAIN, ISSUE_HYBRID_LEGS_FAILING) in ir.async_get(hass).issues

    working = True
    for _ in range(16):
        press(hass, zwave_js_devices, BUTTON_SCENE)
        await hass.async_block_till_done()

    assert (DOMAIN, ISSUE_HYBRID_LEGS_FAILING) not in ir.async_get(hass).issues


async def test_a_value_that_flips_and_comes_back_inside_the_rate_limit_sends_nothing(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """FR-H2's write hygiene, counted in frames rather than in intentions.

    Deduplicating against what was last **wanted** is not enough: a light that goes off and
    comes back on inside the rate limit is wanted twice and needs sending zero times, and
    the coalesced write at the end of the window would otherwise send a value the device
    already had. Each of these is a radio frame, which is the whole reason the rule exists.
    """
    light = a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    activate(
        hybrid_entry,
        a_profile(hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))),
    )
    await hass.async_block_till_done()
    assert zwave_driver.controller.written_indicators == [(BUTTON_INDICATOR, True)]

    hass.states.async_set(light, STATE_OFF)
    hass.states.async_set(light, STATE_ON)
    await _after_the_rate_limit(hass)

    assert zwave_driver.controller.written_indicators == [(BUTTON_INDICATOR, True)]


async def test_a_restore_that_the_device_refuses_is_logged_and_not_raised(
    hass: HomeAssistant,
    hybrid_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """Retiring a leg is a tidy-up, and a tidy-up that raised would take an unload with it."""
    a_light(hass, zwave_js_devices, MAIN_LIGHTS, STATE_ON)
    rule = hybrid_rule(HybridKind.BUTTON_LED, features=frozenset({Feature.STATUS_REPORT}))
    activate(hybrid_entry, a_profile(rule))
    await hass.async_block_till_done()

    # The node leaves the network between the leg being registered and being turned off,
    # which is what an exclusion looks like from inside the adapter.
    del zwave_driver.controller.nodes[CONTROLLER]
    hybrid_entry.runtime_data.coordinator.async_set_rule_enabled(rule.id, enabled=False)
    await hass.async_block_till_done()

    assert legs_of(hybrid_entry).running == ()
