"""The profile select, the two buttons, and the events automations are built on.

One assertion here matters more than the rest. **Switching the active profile must not
write to a device.** A select box is a control people try in order to find out what it
does, and this one names sets of rules that add and remove associations across a whole
house. If picking one applied it, the way a user discovers what "Away" means is by having
it happen to them, at whatever time of day they were curious. FR-E1 makes the switch open
a plan instead, and auto-apply an option that is off by default, so the test asserts on the
fake driver's write counter rather than on anything our own code reports.

The events are the other half of the automation surface (FR-E2). Every payload here is
asserted to survive `json.dumps`, because the recorder and every automation that consumes
one goes through JSON, and a payload carrying an enum or a dataclass fails at the moment
somebody's automation fires rather than at the moment it was written.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_links.const import (
    EVENT_DRIFT_DETECTED,
    EVENT_JOB_FINISHED,
    EVENT_PENDING_WAKEUP,
    OPTION_AUTO_APPLY_ON_PROFILE_SWITCH,
)
from tests.conftest import CONTROLLER, LOBBY, MAIN_LIGHTS, a_profile, a_rule, activate
from tests.fakes.zwave import FakeDriver
from tests.test_entities_hub import remove_by_hand
from tests.test_rule_entities import entity_id_of

SELECT = "select.device_links_active_profile"
APPLY = "button.device_links_apply_active_profile"
VERIFY = "button.device_links_verify"

HOME = a_profile(a_rule(), profile_id="home", name="Home")
AWAY = a_profile(
    a_rule("away-lobby", emitter_id="g5", target_node=LOBBY), profile_id="away", name="Away"
)


def recorded(hass: HomeAssistant, event_type: str) -> list[dict[str, Any]]:
    """Start recording one event type and return the list it accumulates into."""
    events: list[dict[str, Any]] = []

    def _record(event: Event[dict[str, Any]]) -> None:
        events.append(dict(event.data))

    hass.bus.async_listen(event_type, _record)
    return events


def assert_json_serializable(payload: dict[str, Any]) -> None:
    """Every event payload crosses the recorder and the automation engine as JSON."""
    json.dumps(payload)


async def press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: SELECT, ATTR_OPTION: option},
        blocking=True,
    )
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# The select
# --------------------------------------------------------------------------------------


async def test_the_select_lists_the_profiles_and_shows_the_active_one(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()

    state = hass.states.get(SELECT)

    assert state is not None
    assert state.attributes["options"] == ["Away", "Home"]
    assert state.state == "Home"
    assert er.async_get(hass).async_get(SELECT).entity_category is EntityCategory.CONFIG


async def test_selecting_a_profile_activates_it(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()

    await select(hass, "Away")

    coordinator = device_links_entry.runtime_data.coordinator
    assert coordinator.active_profile is not None
    assert coordinator.active_profile.id == "away"
    assert hass.states.get(SELECT).state == "Away"


async def test_switching_a_profile_opens_a_plan_and_writes_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """FR-E1. A select box is a control people try in order to find out what it does.

    This one names whole sets of associations across a house, so an auto-apply on switch
    means the way a user learns what "Away" does is by having it happen to them. Asserted
    on the fake driver's own write counter, because what must not happen is a radio write,
    not merely a job of ours.
    """
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count

    await select(hass, "Away")

    assert zwave_driver.controller.write_count == writes_before, (
        "switching the active profile wrote to a device"
    )
    assert not device_links_entry.runtime_data.coordinator.state.jobs
    plan = device_links_entry.runtime_data.pending_plan
    assert plan is not None, "no plan was opened, so the user has nothing to confirm"
    assert not plan.is_empty


async def test_switching_a_profile_applies_when_the_option_is_on(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, Any],
    zwave_driver: FakeDriver,
) -> None:
    """The option exists so somebody can ask for it, and it is off unless they do."""
    from custom_components.device_links.const import DOMAIN  # noqa: PLC0415

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Device Links",
        options={OPTION_AUTO_APPLY_ON_PROFILE_SWITCH: True},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    activate(entry, HOME, AWAY)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count

    await select(hass, "Away")

    assert zwave_driver.controller.write_count > writes_before
    assert entry.runtime_data.coordinator.state.jobs


async def test_selecting_an_option_that_names_no_profile_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """The list can go stale between a user opening it and picking from it.

    Home Assistant validates the option against `options` before the entity sees it, so
    the service path never reaches our own check. That check is still what protects a
    profile deleted between the list being built and the selection landing, so it is
    called here directly rather than left as something nothing exercises.
    """
    from homeassistant.components.select import DATA_COMPONENT  # noqa: PLC0415
    from homeassistant.exceptions import ServiceValidationError  # noqa: PLC0415

    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()
    entity = hass.data[DATA_COMPONENT].get_entity(SELECT)

    with pytest.raises(ServiceValidationError):
        await select(hass, "Holiday")

    with pytest.raises(ServiceValidationError, match="Holiday"):
        await entity.async_select_option("Holiday")

    coordinator = device_links_entry.runtime_data.coordinator
    assert coordinator.async_activate_profile("no-such-profile") is False
    assert coordinator.active_profile.id == "home", "a bad id changed the active profile"


async def test_the_select_has_nothing_to_show_when_there_are_no_profiles(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A fresh install has no profiles, and the select must still have a state."""
    state = hass.states.get(SELECT)

    assert state is not None
    assert state.attributes["options"] == []
    assert state.state in {"unknown", "None"}


# --------------------------------------------------------------------------------------
# The buttons
# --------------------------------------------------------------------------------------


async def test_the_buttons_exist_and_are_config_entities(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)

    for entity_id in (APPLY, VERIFY):
        entry = registry.async_get(entity_id)
        assert entry is not None, f"{entity_id} was not created"
        assert entry.entity_category is EntityCategory.CONFIG
        assert entry.disabled_by is None


async def test_pressing_apply_writes_the_active_profile(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count

    await press(hass, APPLY)

    assert zwave_driver.controller.write_count > writes_before
    assert device_links_entry.runtime_data.coordinator.state.jobs


async def test_pressing_verify_reads_the_devices_and_writes_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Verify is the read-only reproduction CLAUDE.md points a debugging session at."""
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count
    refreshes_before = zwave_driver.controller.refresh_count

    await press(hass, VERIFY)

    assert zwave_driver.controller.write_count == writes_before, "verify wrote to a device"
    assert zwave_driver.controller.refresh_count > refreshes_before, (
        "verify did not ask any device to re-report, so it confirmed nothing"
    )


async def test_pressing_apply_with_nothing_to_do_is_not_an_error(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Apply on a converged network is what a user presses to check it is converged."""
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    await press(hass, APPLY)
    jobs = len(device_links_entry.runtime_data.coordinator.state.jobs)

    await press(hass, APPLY)

    assert len(device_links_entry.runtime_data.coordinator.state.jobs) == jobs


# --------------------------------------------------------------------------------------
# The events (FR-E2)
# --------------------------------------------------------------------------------------


async def test_a_finished_job_fires_an_event_with_a_summary(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    events = recorded(hass, EVENT_JOB_FINISHED)

    await press(hass, APPLY)

    assert len(events) == 1
    payload = events[0]
    assert_json_serializable(payload)
    assert payload["scope"] == "all"
    assert payload["status"] == "completed"
    assert payload["job_id"]
    assert payload["results"]["applied"] == payload["total"]
    assert payload["rule_ids"] == ["bedroom-main"]


async def test_drift_fires_an_event_naming_the_rules_that_drifted(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    await press(hass, APPLY)
    events = recorded(hass, EVENT_DRIFT_DETECTED)

    await remove_by_hand(zwave_driver, source=CONTROLLER, group=2, target=MAIN_LIGHTS)
    await device_links_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1
    assert_json_serializable(events[0])
    assert events[0] == {"profile_id": "home", "rule_ids": ["bedroom-main"]}


async def test_drift_that_is_already_reported_does_not_fire_again(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """An event per refresh would fire every two seconds for as long as drift lasts.

    Nobody can write an automation on that: it would notify on a loop until somebody fixed
    the link, which teaches people to ignore the notification.
    """
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    await press(hass, APPLY)
    events = recorded(hass, EVENT_DRIFT_DETECTED)
    coordinator = device_links_entry.runtime_data.coordinator

    await remove_by_hand(zwave_driver, source=CONTROLLER, group=2, target=MAIN_LIGHTS)
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(events) == 1


async def test_a_queued_write_to_a_sleeping_node_fires_a_pending_wakeup_event(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E5: the user has to be told to go and press a button on a battery remote.

    The write really is queued against the fake, so what is faked here is only the
    adapter's answer, which is the one thing Stage 0 item Z4 was never approved to
    observe (open item J1).
    """
    from custom_components.device_links.backends.base import (  # noqa: PLC0415
        LinkResult,
        LinkResultStatus,
    )
    from custom_components.device_links.models import Backend as BackendId  # noqa: PLC0415

    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    backend = device_links_entry.runtime_data.backends[BackendId.ZWAVE]

    async def queued(link: object) -> LinkResult:
        return LinkResult(status=LinkResultStatus.PENDING_WAKEUP)

    monkeypatch.setattr(backend, "async_add_link", queued)
    events = recorded(hass, EVENT_PENDING_WAKEUP)

    await press(hass, APPLY)

    assert events, "nothing told the user a write is waiting on a device to wake up"
    for payload in events:
        assert_json_serializable(payload)
        assert payload["rule_id"] == "bedroom-main"
        assert payload["device_identity"].endswith(f":{CONTROLLER}")
        assert payload["device_id"], "no Home Assistant device id, so no deep link"


async def test_no_event_fires_after_the_entry_is_unloaded(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """A bus listener that outlives its config entry survives a reload and fires twice."""
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    await press(hass, APPLY)
    coordinator = device_links_entry.runtime_data.coordinator
    events = recorded(hass, EVENT_DRIFT_DETECTED)

    await hass.config_entries.async_unload(device_links_entry.entry_id)
    await hass.async_block_till_done()
    await remove_by_hand(zwave_driver, source=CONTROLLER, group=2, target=MAIN_LIGHTS)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not events


async def test_the_hub_entities_all_live_on_the_hub_device(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A button or a select on a light's device page would be nonsense."""
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

    from custom_components.device_links.const import DOMAIN  # noqa: PLC0415

    hub = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, device_links_entry.entry_id)})
    registry = er.async_get(hass)

    for entity_id in (SELECT, APPLY, VERIFY):
        assert registry.async_get(entity_id).device_id == hub.id


async def test_every_hub_control_has_a_unique_id_from_the_entry(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    for key, entity_id in (
        ("active_profile", SELECT),
        ("apply_active_profile", APPLY),
        ("verify", VERIFY),
    ):
        assert entity_id_of(hass, device_links_entry, key) == entity_id
