"""Rule entities: whose device page they land on, and what a toggle is allowed to do.

Two failures define this file and neither of them raises.

**A near-miss identifier makes an orphan.** On Home Assistant 2026.8 identifiers are
unique per config entry, so attaching to somebody else's device means registering our own
record carrying the identifiers they registered, and Home Assistant groups the two into
one device. It creates a record for whatever identifiers it is handed, so an identifier
one character out from the `zwave_js` one does not fail: it makes a record that groups
with nothing, and the user is left with a second, empty device beside their switch and
nothing in the log to explain it. "The entity exists" passes in exactly that broken case,
so the tests here count the distinct devices the user would see before and after, and
assert our record carries the identifiers the upstream one already had.

**A rule switch writes to a radio.** Association tables live in the device's NVM, which
has a finite write endurance, so an automation toggling a rule in a loop is not merely
noisy: it wears out hardware somebody paid for. E35 and FR-E1 require at most one toggle
per rule per 30 seconds to be executed and the rest of a burst to be coalesced into the
latest requested state. The tests below prove that with simulated time, because a test
that really waited thirty seconds is a test somebody eventually deletes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from typing import Any

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_links.backends.zigbee2mqtt import ZigbeeBackend
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.rule_toggle import TOGGLE_MIN_INTERVAL_SECONDS
from custom_components.device_links.sensor import RULE_STATES
from tests.conftest import CONTROLLER, MAIN_LIGHTS, ZWAVE_JS_DOMAIN, a_profile, a_rule, activate
from tests.factories import HOME_ID, handle
from tests.fakes.zigbee import build_bridge_from_fixture
from tests.fakes.zwave import FakeDriver

RULE_ID = "bedroom-main"


def p2_format(backend: str) -> str:
    """Return the identifier pattern the P2 capture recorded for one integration."""
    captured = json.loads(
        (Path(__file__).parent / "fixtures" / "p2_device_identifiers.json").read_text()
    )
    pattern: str = captured["data"]["formats"][backend]["pattern"][0]
    return pattern


def zigbee_backend_factory(base_topic: str) -> ZigbeeBackend:
    """Return a Zigbee adapter on one base topic. Constructing it does no I/O."""
    return ZigbeeBackend(client=build_bridge_from_fixture(), base_topic=base_topic)


def entity_id_of(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    """Return the entity a unique-id key names, so no test hard-codes a generated id."""
    unique_id = f"{entry.entry_id}_{key}"
    for registry_entry in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if registry_entry.unique_id == unique_id:
            return registry_entry.entity_id
    raise AssertionError(f"no entity with unique id {unique_id!r}")


def switch_of(hass: HomeAssistant, entry: MockConfigEntry, rule_id: str = RULE_ID) -> str:
    return entity_id_of(hass, entry, f"rule_{rule_id}")


def status_of(hass: HomeAssistant, entry: MockConfigEntry, rule_id: str = RULE_ID) -> str:
    return entity_id_of(hass, entry, f"rule_status_{rule_id}")


async def toggle(hass: HomeAssistant, entity_id: str, *, on: bool) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON if on else SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()


async def let_time_pass(hass: HomeAssistant, seconds: float) -> None:
    """Move Home Assistant's clock, so a rate limiter can be tested without waiting."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


def rule_enabled(entry: MockConfigEntry, rule_id: str = RULE_ID) -> bool:
    profile = entry.runtime_data.coordinator.active_profile
    assert profile is not None
    return next(rule.enabled for rule in profile.rules if rule.id == rule_id)


def visible_devices(hass: HomeAssistant) -> set[frozenset[tuple[str, str]]]:
    """Return one entry per device a user would see, keyed by its identifiers.

    Identifiers are what Home Assistant groups device records by, so this is the count
    that matters: a rule entity attaching correctly adds a record to an existing group,
    and one attaching to a near-miss identifier adds a whole new group, which is the
    second device card the user has to explain to themselves.
    """
    return {frozenset(device.identifiers) for device in dr.async_get(hass).devices.values()}


def group_of(driver: FakeDriver, node_id: int, group: int) -> list[int]:
    """Return what one association group of a node holds right now, as node ids."""
    associations = driver.controller.get_all_associations_sync(node_id)
    return [address.node_id for address in associations[node_id][0].get(group, [])]


# --------------------------------------------------------------------------------------
# Attachment: the failure mode that does not raise
# --------------------------------------------------------------------------------------


async def test_a_rule_switch_lands_on_the_existing_device_and_creates_no_new_one(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """FR-E1: the entity attaches to the `zwave_js` device entry that already exists.

    Counted rather than looked up, because the failure this guards against is silent: a
    near-miss identifier creates a second, empty device rather than raising, and every
    assertion of the form "the entity exists" passes in exactly that broken case.
    """
    registry = dr.async_get(hass)
    before = visible_devices(hass)
    upstream = registry.async_get_device(identifiers={(ZWAVE_JS_DOMAIN, f"{HOME_ID}-{CONTROLLER}")})
    assert upstream is not None, "the fixture did not register the source device"

    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    assert visible_devices(hass) == before, (
        "a rule entity made a device of its own rather than attaching to one; the "
        "identifiers it used do not match what zwave_js registered, so the user now has "
        f"two entries for one switch. New: {visible_devices(hass) - before}"
    )
    switch = er.async_get(hass).async_get(switch_of(hass, device_links_entry))
    assert switch is not None
    attached = registry.async_get(switch.device_id)
    assert attached is not None
    assert attached.identifiers == upstream.identifiers, (
        "the rule switch is not on the source device: its device record carries "
        f"{attached.identifiers} rather than {upstream.identifiers}"
    )
    assert attached.name == upstream.name


async def test_a_rule_status_sensor_lands_on_the_same_device(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    switch = registry.async_get(switch_of(hass, device_links_entry))
    status = registry.async_get(status_of(hass, device_links_entry))

    assert status is not None
    assert status.device_id == switch.device_id


async def test_a_rule_whose_source_device_is_not_in_the_registry_gets_no_entity(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_entry: MockConfigEntry,
) -> None:
    """No device registry entry means no honest place to put it, so it is not created.

    This is the guard that makes the orphan impossible rather than merely unlikely: the
    only identifier ever handed to Home Assistant is one the registry already holds.
    """
    from custom_components.device_links.const import DOMAIN  # noqa: PLC0415

    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    devices_before = visible_devices(hass)

    activate(entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    assert visible_devices(hass) == devices_before
    assert not [
        registry_entry
        for registry_entry in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if registry_entry.unique_id.endswith(f"rule_{RULE_ID}")
    ]


async def test_removing_the_source_device_removes_its_rule_entities(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """stale-devices: an entity on a device that is gone is a row nobody can act on."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)
    upstream = dr.async_get(hass).async_get_device(
        identifiers={(ZWAVE_JS_DOMAIN, f"{HOME_ID}-{CONTROLLER}")}
    )
    assert upstream is not None

    dr.async_get(hass).async_remove_device(upstream.id)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(switch) is None
    assert hass.states.get(switch) is None
    assert not [
        device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), device_links_entry.entry_id
        )
        if (ZWAVE_JS_DOMAIN, f"{HOME_ID}-{CONTROLLER}") in device.identifiers
    ], "our own record for the removed device was left behind as an empty device page"


async def test_unloading_removes_our_entities_and_leaves_the_upstream_device_alone(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """This closes the unload half of Stage 0 item P2.

    P2's capture pinned the identifier formats and proved attachment is possible. What it
    could not show, because nothing had been built to unload, is that taking Device Links
    away leaves the `zwave_js` device entry exactly as it was: same device, same
    identifiers, still owned by zwave_js, with only our entities gone. A device that
    disappeared with us would take every automation and dashboard card referring to that
    switch with it.
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    identifiers = {(ZWAVE_JS_DOMAIN, f"{HOME_ID}-{CONTROLLER}")}
    before = registry.async_get_device(identifiers=identifiers)
    assert before is not None
    assert before.primary_config_entry != device_links_entry.entry_id
    switch = switch_of(hass, device_links_entry)
    devices_before = visible_devices(hass)

    await hass.config_entries.async_unload(device_links_entry.entry_id)
    await hass.async_block_till_done()

    after = registry.async_get_device(identifiers=identifiers)
    assert after is not None, "unloading Device Links took the user's own device with it"
    assert after.id == before.id
    assert after.identifiers == before.identifiers
    assert after.primary_config_entry == before.primary_config_entry
    assert after.name == before.name
    assert visible_devices(hass) == devices_before, "unloading changed the device list"
    assert hass.states.get(switch).attributes.get("restored") is True, (
        "the rule switch is still being provided after the entry was unloaded"
    )


def test_the_zwave_identifier_matches_the_format_the_p2_capture_recorded(
    zwave_driver: FakeDriver,
) -> None:
    """Pin the string that decides whether attachment lands or makes an orphan.

    Everything else here is tested against a fixture-built registry, so this is the one
    assertion that ties what the code produces to what was read off Jayant's real
    Home Assistant: the short `<home id>-<node id>` form, in the `zwave_js` namespace.

    Asked of the adapter, because the adapter is where the derivation lives since T57.
    """
    from custom_components.device_links.backends.zwave import ZWaveBackend  # noqa: PLC0415

    captured = p2_format("zwave_js")
    backend = ZWaveBackend(driver=zwave_driver, profiles=None)
    identifier = backend.registry_identifier(handle(CONTROLLER))

    assert identifier is not None
    domain, value = identifier
    assert domain == ZWAVE_JS_DOMAIN
    assert captured == "<home_id>-<node_id>", "the captured format changed; re-check P2"
    assert value == f"{HOME_ID}-{CONTROLLER}"


def test_the_zigbee_identifier_carries_the_configured_base_topic() -> None:
    """T57: a Zigbee device is an `mqtt` device, filed under the base topic it publishes on.

    The P2 capture masked the IEEE address and left the shape, so the shape is what is
    pinned here, against a realistic address rather than the redacted one the G1 fixture
    carries. The second half is the reason this is the adapter's answer at all: the base
    topic is configurable, and a second instance registers different identifiers (E25).
    """
    ieee = "0x00124b002e1dfd4a"
    device = replace(handle(CONTROLLER), backend=BackendId.ZIGBEE2MQTT, protocol_id=ieee)

    assert p2_format("mqtt") == "<base_topic>_0x<ieee>", "the captured format changed"
    assert zigbee_backend_factory("zigbee2mqtt").registry_identifier(device) == (
        "mqtt",
        f"zigbee2mqtt_{ieee}",
    )
    assert zigbee_backend_factory("attic/z2m").registry_identifier(device) == (
        "mqtt",
        f"attic/z2m_{ieee}",
    )


def test_a_managed_zigbee_group_is_an_address_rather_than_a_device() -> None:
    """Nothing registers an `mqtt` device for a Zigbee group, so there is nothing to open."""
    group = replace(handle(CONTROLLER), backend=BackendId.ZIGBEE2MQTT, protocol_id="group:7")

    assert zigbee_backend_factory("zigbee2mqtt").registry_identifier(group) is None


def test_a_handle_whose_address_is_malformed_is_not_attachable(
    zwave_driver: FakeDriver,
) -> None:
    """Guessing at an address that is not shaped like one is how the orphan is made."""
    from custom_components.device_links.backends.zwave import ZWaveBackend  # noqa: PLC0415

    malformed = replace(handle(CONTROLLER), protocol_id="no-separator")

    assert ZWaveBackend(driver=zwave_driver, profiles=None).registry_identifier(malformed) is None


def test_a_protocol_with_no_loaded_backend_is_not_attachable(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Matter is Phase 3, so a Matter handle resolves to no device and says so quietly."""
    from custom_components.device_links.rule_entity import (  # noqa: PLC0415
        async_upstream_device,
    )

    matter = replace(handle(CONTROLLER), backend=BackendId.MATTER, protocol_id="5")

    assert async_upstream_device(hass, device_links_entry, matter) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# What a toggle does
# --------------------------------------------------------------------------------------


async def test_turning_a_rule_switch_off_disables_the_rule_and_removes_its_links(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Asserted against the coordinator and the device, not just against the entity."""
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()

    assert MAIN_LIGHTS in group_of(zwave_driver, CONTROLLER, 2)

    await toggle(hass, switch_of(hass, device_links_entry), on=False)

    assert rule_enabled(device_links_entry) is False
    assert MAIN_LIGHTS not in group_of(zwave_driver, CONTROLLER, 2), (
        "the rule was disabled but its association is still on the device"
    )
    assert hass.states.get(switch_of(hass, device_links_entry)).state == STATE_OFF


async def test_turning_a_rule_switch_back_on_re_enables_it_and_writes_its_links(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, a_profile(a_rule(enabled=False)))
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)

    assert hass.states.get(switch).state == STATE_OFF

    await toggle(hass, switch, on=True)

    assert rule_enabled(device_links_entry) is True
    assert MAIN_LIGHTS in group_of(zwave_driver, CONTROLLER, 2)
    assert hass.states.get(switch).state == STATE_ON


# --------------------------------------------------------------------------------------
# Rate limiting (E35)
# --------------------------------------------------------------------------------------


async def test_a_burst_of_toggles_produces_one_apply_carrying_the_final_state(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Five toggles in ten seconds, one apply, and the attribute says why.

    The association table this writes lives in the device's NVM and has a finite write
    endurance, so an automation toggling a rule in a loop is not merely noisy. One apply
    per rule per 30 seconds is the cap, and what it carries is the state the user last
    asked for, not the first one they clicked.
    """
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)
    jobs_before = len(runtime.coordinator.state.jobs)

    for second, wanted_on in enumerate([False, True, False, True, False]):
        await toggle(hass, switch, on=wanted_on)
        await let_time_pass(hass, 2 * (second + 1))

    assert len(runtime.coordinator.state.jobs) - jobs_before == 1, (
        "more than one apply reached the radio inside the rate limit window"
    )
    assert rule_enabled(device_links_entry) is False
    assert MAIN_LIGHTS not in group_of(zwave_driver, CONTROLLER, 2)
    assert hass.states.get(switch).attributes["rate_limited"] is True


async def test_a_coalesced_toggle_is_applied_once_the_window_has_passed(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Coalescing defers the latest requested state, it does not throw it away.

    Off then on inside the window: the off is applied at once, the on waits, and when the
    window closes the rule is on and its link is back. Dropping the second request would
    leave the user's switch showing one thing and their house doing another.
    """
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)
    jobs_before = len(runtime.coordinator.state.jobs)

    await toggle(hass, switch, on=False)
    await toggle(hass, switch, on=True)

    assert len(runtime.coordinator.state.jobs) - jobs_before == 1
    assert rule_enabled(device_links_entry) is False, "the deferred request was applied early"
    assert hass.states.get(switch).state == STATE_ON, (
        "the switch must show what the user asked for, or they will click it again"
    )

    await let_time_pass(hass, TOGGLE_MIN_INTERVAL_SECONDS + 1)

    assert len(runtime.coordinator.state.jobs) - jobs_before == 2
    assert rule_enabled(device_links_entry) is True
    assert MAIN_LIGHTS in group_of(zwave_driver, CONTROLLER, 2)
    assert hass.states.get(switch).attributes["rate_limited"] is False


async def test_a_burst_that_ends_where_it_started_costs_no_second_write(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Nothing is applied when the window closes on the state that was already applied."""
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)
    jobs_before = len(runtime.coordinator.state.jobs)

    await toggle(hass, switch, on=False)
    await toggle(hass, switch, on=True)
    await toggle(hass, switch, on=False)
    await let_time_pass(hass, TOGGLE_MIN_INTERVAL_SECONDS + 1)

    assert len(runtime.coordinator.state.jobs) - jobs_before == 1
    assert rule_enabled(device_links_entry) is False
    assert hass.states.get(switch).attributes["rate_limited"] is False


async def test_the_limiter_is_shared_rather_than_living_on_the_entity(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A service call and a WebSocket command enable rules too, so the entity cannot own it.

    A limiter that only existed on the switch would be bypassed by every other caller,
    which is every caller an automation would actually use. This asserts the shared object
    is what enforces it, so Tasks 4 and 5 have nothing to reimplement.
    """
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()
    jobs_before = len(runtime.coordinator.state.jobs)

    await runtime.toggles.async_request(RULE_ID, enabled=False)
    await runtime.toggles.async_request(RULE_ID, enabled=True)
    await hass.async_block_till_done()

    assert len(runtime.coordinator.state.jobs) - jobs_before == 1
    assert runtime.toggles.is_rate_limited(RULE_ID) is True


async def test_a_pending_toggle_does_not_survive_an_unload(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A timer that outlives the entry fires at a runner that has been shut down."""
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()
    await runtime.toggles.async_request(RULE_ID, enabled=False)
    await runtime.toggles.async_request(RULE_ID, enabled=True)
    jobs_before = len(runtime.coordinator.state.jobs)

    await hass.config_entries.async_unload(device_links_entry.entry_id)
    await hass.async_block_till_done()
    await let_time_pass(hass, TOGGLE_MIN_INTERVAL_SECONDS + 1)

    assert len(runtime.coordinator.state.jobs) == jobs_before, (
        "a deferred toggle applied after the config entry was unloaded"
    )


async def test_a_deferred_toggle_interrupted_by_an_unload_arms_nothing_new(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one timer `async_shutdown` cannot cancel is the one that starts after it.

    A deferred toggle whose window closes just as the entry unloads is inside an await when
    the shutdown runs, and it would then open the next window from the far side of it: a
    timer nothing is left to cancel, firing at a coordinator that has been discarded, and
    surviving a reload. That is the leak this module's docstring rules out, so it is worth
    a white-box test rather than a hopeful one.
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    runtime = device_links_entry.runtime_data
    toggles = runtime.toggles
    await toggles.async_request(RULE_ID, enabled=False)
    await toggles.async_request(RULE_ID, enabled=True)
    assert toggles.is_rate_limited(RULE_ID)

    async def _unload_mid_apply(*args: object, **kwargs: object) -> None:
        toggles.async_shutdown()

    monkeypatch.setattr(runtime.runner, "async_apply", _unload_mid_apply)
    await let_time_pass(hass, TOGGLE_MIN_INTERVAL_SECONDS + 1)

    assert toggles._cooldowns == {}


async def test_a_toggle_that_arrives_during_an_unload_does_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A service call already scheduled when the unload began must not start a job."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    runtime = device_links_entry.runtime_data
    runtime.toggles.async_shutdown()
    jobs_before = len(runtime.coordinator.state.jobs)

    await runtime.toggles.async_request(RULE_ID, enabled=False)

    assert len(runtime.coordinator.state.jobs) == jobs_before
    assert runtime.coordinator.is_rule_enabled(RULE_ID, default=True) is True


# --------------------------------------------------------------------------------------
# What the entities say
# --------------------------------------------------------------------------------------


async def test_the_rule_status_sensor_is_diagnostic_and_disabled_by_default(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """One extra state row per rule is a lot on a house with forty of them."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    status = er.async_get(hass).async_get(status_of(hass, device_links_entry))

    assert status is not None
    assert status.entity_category is EntityCategory.DIAGNOSTIC
    assert status.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_the_rule_status_sensor_reports_one_of_the_documented_states(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity(status_of(hass, device_links_entry), disabled_by=None)
    await hass.config_entries.async_reload(device_links_entry.entry_id)
    await hass.async_block_till_done()
    # The profile is re-activated because the store's write is delayed by design, so a
    # reload inside a test starts from an empty one. Nothing about the sensor depends on
    # that; it just has to have a rule to be about.
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    status = hass.states.get(status_of(hass, device_links_entry))

    assert status is not None
    assert status.state in set(RULE_STATES)
    assert status.attributes["options"] == list(RULE_STATES)


async def test_the_switch_reports_the_rule_as_on_and_the_house_as_drifted(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """The switch position is the user's intent; the attributes are the house's truth.

    Reporting `off` for a drifted rule would say the user turned it off, which is false
    and would make an automation reading the switch act on a decision nobody took.
    Reporting `on` with nothing else would claim the links are there. So the position
    follows the rule and `status`, `links_total` and `links_in_sync` say what is really on
    the device, which is the pair a person can act on.
    """
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)

    assert hass.states.get(switch).attributes["status"] == "in_sync"
    assert hass.states.get(switch).attributes["links_in_sync"] == 3

    from tests.test_entities_hub import remove_by_hand  # noqa: PLC0415

    await remove_by_hand(zwave_driver, source=CONTROLLER, group=2, target=MAIN_LIGHTS)
    await runtime.coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(switch)
    assert state.state == STATE_ON, "a drifted rule is still an enabled rule"
    assert state.attributes["status"] == "drift"
    assert state.attributes["links_in_sync"] < state.attributes["links_total"]


async def test_a_rule_whose_devices_cannot_be_read_goes_unavailable(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`unknown` is not a switch position, so the honest answer is to say nothing.

    Reporting `on` would claim the links are as the rule asks while nobody can see the
    device, and reporting `off` would claim the user turned the rule off. Unavailable is
    the state Home Assistant has for "we cannot say" (quality-scale rule
    entity-unavailable).
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)

    from tests.test_entities_hub import stop_the_backend_answering  # noqa: PLC0415

    await stop_the_backend_answering(hass, device_links_entry, monkeypatch)

    assert hass.states.get(switch).state == STATE_UNAVAILABLE


async def test_a_rule_added_to_the_active_profile_gets_its_entities(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Rules are authored in the panel while the integration is running."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    activate(
        device_links_entry,
        a_profile(a_rule(), a_rule("second", emitter_id="g5", target_node=35)),
    )
    await hass.async_block_till_done()

    assert hass.states.get(switch_of(hass, device_links_entry, "second")) is not None


async def test_a_rule_removed_from_the_active_profile_loses_its_entities(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A switch for a rule that no longer exists is a control that does nothing."""
    activate(
        device_links_entry,
        a_profile(a_rule(), a_rule("second", emitter_id="g5", target_node=35)),
    )
    await hass.async_block_till_done()
    second = switch_of(hass, device_links_entry, "second")

    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    assert hass.states.get(second) is None
    assert hass.states.get(switch_of(hass, device_links_entry)) is not None


# --------------------------------------------------------------------------------------
# The edges the limiter and the entities have to survive
# --------------------------------------------------------------------------------------


async def test_toggling_a_rule_that_is_not_in_the_active_profile_does_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Services and WebSocket commands can name any rule id, including one that is gone."""
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    writes_before = zwave_driver.controller.write_count

    await runtime.toggles.async_request("no-such-rule", enabled=False)

    assert zwave_driver.controller.write_count == writes_before
    assert not runtime.coordinator.state.jobs


async def test_a_toggle_that_arrives_while_a_job_runs_keeps_the_intent_and_says_so(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """E16 refuses a second apply. The rule still records what the user asked for.

    Raising instead would hand the caller a failure whose only remedy is pressing Apply,
    which is what the rule's own status sensor is already telling them to do.
    """
    from custom_components.device_links.executor import JobRunner, JobRunningError  # noqa: PLC0415

    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()

    async def refuse(*args: object, **kwargs: object) -> None:
        raise JobRunningError("an apply is already running")

    monkeypatch.setattr(JobRunner, "async_apply", refuse)

    await runtime.toggles.async_request(RULE_ID, enabled=False)

    assert rule_enabled(device_links_entry) is False
    assert "could not be written now" in caplog.text


async def test_a_toggle_with_nothing_to_write_costs_no_job(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Disabling a rule that was never applied has nothing to remove."""
    activate(device_links_entry, a_profile(a_rule()))
    runtime = device_links_entry.runtime_data

    await runtime.toggles.async_request(RULE_ID, enabled=False)

    assert rule_enabled(device_links_entry) is False
    assert not runtime.coordinator.state.jobs, "an empty plan produced a job anyway"


async def test_a_device_on_a_backend_with_no_identifier_format_is_not_attachable(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Zigbee and Matter handles carry no derivable registry identifier yet."""
    from dataclasses import replace  # noqa: PLC0415

    from custom_components.device_links.models import Backend as BackendId  # noqa: PLC0415
    from custom_components.device_links.rule_entity import async_upstream_device  # noqa: PLC0415

    zigbee = replace(handle(CONTROLLER), backend=BackendId.ZIGBEE2MQTT)

    assert async_upstream_device(hass, device_links_entry, zigbee) is None


async def test_the_status_sensor_says_applying_while_a_job_is_writing_that_rule(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A rule mid-write is neither in sync nor drifted, and saying either would be wrong."""
    from custom_components.device_links.models import Backend as BackendId  # noqa: PLC0415

    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity(status_of(hass, device_links_entry), disabled_by=None)
    await hass.config_entries.async_reload(device_links_entry.entry_id)
    await hass.async_block_till_done()
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    runtime = device_links_entry.runtime_data
    backend = runtime.backends[BackendId.ZWAVE]
    seen: list[frozenset[str]] = []
    original = backend.async_add_link

    async def watch(link: object) -> object:
        seen.append(runtime.runner.active_rule_ids)
        return await original(link)

    backend.async_add_link = watch  # type: ignore[method-assign]
    await runtime.runner.async_apply(await runtime.coordinator.async_plan())
    await hass.async_block_till_done()

    assert seen, "the job wrote nothing, so nothing was ever being applied"
    assert all(RULE_ID in rule_ids for rule_ids in seen)
    assert runtime.runner.active_rule_ids == frozenset(), "a finished job is still applying"
    # The state written last during a job is the one written from inside it, when the job
    # was still running. Without an update on the way out, the sensor is left saying
    # `applying` until something unrelated happens to change.
    assert hass.states.get(status_of(hass, device_links_entry)).state == "in_sync"


async def test_clearing_the_active_profile_takes_every_rule_entity_with_it(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """No active profile means no rules, and a switch for no rule is a control that lies."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    switch = switch_of(hass, device_links_entry)

    activate(device_links_entry)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(switch) is None
    # A rule entity being torn down still asks the coordinator what its rule says, and the
    # only honest answer for a rule that has gone is the last one the entity knew.
    coordinator = device_links_entry.runtime_data.coordinator
    assert coordinator.is_rule_enabled(RULE_ID, default=True) is True
    assert coordinator.is_rule_enabled(RULE_ID, default=False) is False
