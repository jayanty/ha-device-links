"""The services: the scriptable surface, and the two rules that keep it safe.

Two properties are worth more than the rest of this file.

**Bad input is a `ServiceValidationError` and a backend failure is a `HomeAssistantError`,
both translated.** An automation that names a rule that no longer exists gets told which
rule, in its own language, rather than a traceback in the log and nothing in the UI.

**`import_profile` never writes to a device.** It changes what should be true and hands
back a plan. A YAML file that names devices this network does not have is refused whole
(E38), naming every device and the rules that want them, because the alternative is an
import that quietly drops half a profile and reports success.

The raw services are the expert tools of Decision D14. They are not registered at all
unless the option is on, and when they are on they still refuse to touch a lifeline: the
assertion for that is the fake driver's own write counter, not anything our code reports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.exceptions import FailedZWaveCommand
from zwave_js_server.model.association import AssociationAddress

from custom_components.device_links.const import DOMAIN, OPTION_ENABLE_RAW_SERVICES
from custom_components.device_links.executor import JobRunningError
from custom_components.device_links.services import (
    CORE_SERVICES,
    RAW_SERVICES,
    SERVICE_ACTIVATE_PROFILE,
    SERVICE_APPLY,
    SERVICE_EXPORT_PROFILE,
    SERVICE_IMPORT_PROFILE,
    SERVICE_SET_RULE_ENABLED,
    SERVICE_VERIFY,
    SERVICE_ZWAVE_ADD_ASSOCIATION,
    SERVICE_ZWAVE_GET_ASSOCIATIONS,
    SERVICE_ZWAVE_REMOVE_ASSOCIATION,
)
from custom_components.device_links.yaml_io import dump_profile, parse_profile
from tests.conftest import CONTROLLER, LOBBY, MAIN_LIGHTS, a_profile, a_rule, activate
from tests.fakes.zwave import FakeDriver

HOME = a_profile(a_rule(), profile_id="home", name="Home")
AWAY = a_profile(
    a_rule("away-lobby", emitter_id="g5", target_node=LOBBY), profile_id="away", name="Away"
)


async def call(
    hass: HomeAssistant, service: str, data: dict[str, Any] | None = None, **kwargs: Any
) -> Any:
    """Call one of our services and let the exceptions out."""
    result = await hass.services.async_call(DOMAIN, service, data or {}, blocking=True, **kwargs)
    await hass.async_block_till_done()
    return result


def device_id_of(hass: HomeAssistant, devices: dict[int, dr.DeviceEntry], node: int) -> str:
    """Return the Home Assistant device id of one fixture node."""
    return devices[node].id


def load_services_yaml() -> dict[str, Any]:
    """Return `services.yaml` as data, for the drift checks here and in Task 7."""
    import yaml  # noqa: PLC0415

    path = Path(__file__).parent.parent / "custom_components" / "device_links" / "services.yaml"
    loaded: dict[str, Any] = yaml.safe_load(path.read_text())
    return loaded


# --------------------------------------------------------------------------------------
# Registration (quality-scale rule action-setup)
# --------------------------------------------------------------------------------------


async def test_services_are_registered_without_a_config_entry(hass: HomeAssistant) -> None:
    """`action-setup`: registered in `async_setup`, so automations validate at load.

    A service that only exists once an entry is loaded makes every automation using it
    fail validation while the integration is retrying its setup, which is exactly when a
    user is already looking at something that does not work.
    """
    assert await async_setup_component(hass, DOMAIN, {})

    for service in CORE_SERVICES:
        assert hass.services.has_service(DOMAIN, service), service


async def test_the_raw_services_are_not_registered_by_default(hass: HomeAssistant) -> None:
    """Decision D14: the expert tools are off until somebody turns them on."""
    assert await async_setup_component(hass, DOMAIN, {})

    for service in RAW_SERVICES:
        assert not hass.services.has_service(DOMAIN, service), service


@pytest.mark.parametrize("service", sorted(CORE_SERVICES))
async def test_every_service_says_so_when_no_entry_is_loaded(
    hass: HomeAssistant, service: str
) -> None:
    """`action-setup` again: the service exists and explains itself, translated."""
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, service, _minimum_valid_data(service), **_response_kwargs(service))

    assert error.value.translation_key == "not_loaded"
    assert error.value.translation_domain == DOMAIN


def _minimum_valid_data(service: str) -> dict[str, Any]:
    """Return input that passes the schema, so the refusal is about the entry."""
    return {
        SERVICE_SET_RULE_ENABLED: {"rule_id": "bedroom-main", "enabled": True},
        SERVICE_ACTIVATE_PROFILE: {"profile_id": "home"},
        SERVICE_IMPORT_PROFILE: {"yaml": "version: 1\n"},
    }.get(service, {})


def _response_kwargs(service: str) -> dict[str, Any]:
    """Return `return_response=True` for the services that only answer with one."""
    if service in {SERVICE_EXPORT_PROFILE, SERVICE_IMPORT_PROFILE}:
        return {"return_response": True}
    return {}


async def test_the_raw_services_appear_when_the_option_is_on(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """They come and go with the option, so turning it off really takes them away."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Device Links",
        options={OPTION_ENABLE_RAW_SERVICES: True},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for service in RAW_SERVICES:
        assert hass.services.has_service(DOMAIN, service), service

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    for service in RAW_SERVICES:
        assert not hass.services.has_service(DOMAIN, service), service


async def test_turning_the_option_on_registers_them_without_a_restart(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """An option nobody can turn on without restarting is an option nobody turns on."""
    assert not hass.services.has_service(DOMAIN, SERVICE_ZWAVE_ADD_ASSOCIATION)

    hass.config_entries.async_update_entry(
        device_links_entry, options={OPTION_ENABLE_RAW_SERVICES: True}
    )
    await hass.async_block_till_done()

    assert hass.services.has_service(DOMAIN, SERVICE_ZWAVE_ADD_ASSOCIATION)


# --------------------------------------------------------------------------------------
# apply and verify
# --------------------------------------------------------------------------------------


async def test_apply_writes_the_active_profile_and_reports_what_happened(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count

    response = await call(hass, SERVICE_APPLY, {}, return_response=True)

    assert zwave_driver.controller.write_count > writes_before
    assert response["status"] == "completed"
    assert response["job_id"]
    assert response["results"]["applied"] > 0


async def test_apply_scoped_to_one_rule_applies_only_that_rule(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    both = a_profile(a_rule(), a_rule("lobby", emitter_id="g5", target_node=LOBBY))
    activate(device_links_entry, both)
    await hass.async_block_till_done()

    response = await call(hass, SERVICE_APPLY, {"rule_ids": ["lobby"]}, return_response=True)

    jobs = device_links_entry.runtime_data.coordinator.state.jobs
    assert response["job_id"] == jobs[-1].id
    assert jobs[-1].scope == "rules:lobby"


async def test_apply_scoped_to_a_device_names_that_device(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    await call(
        hass,
        SERVICE_APPLY,
        {"device_id": [device_id_of(hass, zwave_js_devices, CONTROLLER)]},
        return_response=True,
    )

    jobs = device_links_entry.runtime_data.coordinator.state.jobs
    assert f":{CONTROLLER}" in jobs[-1].scope


async def test_apply_with_an_unknown_rule_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_APPLY, {"rule_ids": ["no-such-rule"]}, return_response=True)

    assert error.value.translation_key == "unknown_rule"
    assert error.value.translation_placeholders["rule"] == "no-such-rule"
    assert zwave_driver.controller.write_count == writes_before


async def test_apply_with_an_unknown_profile_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_APPLY, {"profile_id": "nope"}, return_response=True)

    assert error.value.translation_key == "unknown_profile"


async def test_apply_of_a_profile_that_is_not_the_active_one_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Decision D10. One profile is in force, and applying another would switch the house.

    A service that quietly activated whatever it was pointed at would make "apply the Away
    profile" a whole-house change nobody asked for, from an automation that looks like it
    is only writing what is already true.
    """
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_APPLY, {"profile_id": "away"}, return_response=True)

    assert error.value.translation_key == "profile_not_active"


async def test_apply_with_an_unknown_device_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_APPLY, {"device_id": ["nope"]}, return_response=True)

    assert error.value.translation_key == "unknown_device"


async def test_a_backend_failure_is_a_translated_home_assistant_error(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`action-exceptions`: a refusal from the runner reaches the caller translated (E16)."""
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    async def _busy(*args: Any, **kwargs: Any) -> None:
        raise JobRunningError(
            "an apply is already running",
            translation_domain=DOMAIN,
            translation_key="job_running",
        )

    monkeypatch.setattr(device_links_entry.runtime_data.runner, "async_apply", _busy)

    with pytest.raises(HomeAssistantError) as error:
        await call(hass, SERVICE_APPLY, {}, return_response=True)

    assert error.value.translation_key == "job_running"


async def test_apply_with_nothing_to_do_reports_that_and_starts_no_job(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    await call(hass, SERVICE_APPLY, {}, return_response=True)

    response = await call(hass, SERVICE_APPLY, {}, return_response=True)

    assert response["job_id"] is None
    assert len(device_links_entry.runtime_data.coordinator.state.jobs) == 1


async def test_apply_leaves_an_unmanaged_link_alone_unless_it_is_named(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    zwave_driver: FakeDriver,
) -> None:
    """CLAUDE.md Section 3 rule 5: per-link opt-in, by fingerprint, or not at all."""
    controller = zwave_driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=CONTROLLER, endpoint=0),
        7,
        [AssociationAddress(controller, node_id=LOBBY, endpoint=None)],
    )
    activate(device_links_entry, HOME)
    await device_links_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    await call(hass, SERVICE_APPLY, {}, return_response=True)

    still_there = controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0][7]
    assert [address.node_id for address in still_there] == [LOBBY]


async def test_apply_removes_an_unmanaged_link_that_was_named_by_fingerprint(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    zwave_driver: FakeDriver,
) -> None:
    controller = zwave_driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=CONTROLLER, endpoint=0),
        7,
        [AssociationAddress(controller, node_id=LOBBY, endpoint=None)],
    )
    activate(device_links_entry, HOME)
    coordinator = device_links_entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    plan = await coordinator.async_plan()
    fingerprint = next(link.fingerprint for link in plan.unmanaged if link.emitter_group == "7")

    await call(hass, SERVICE_APPLY, {"remove_unmanaged": [fingerprint]}, return_response=True)

    assert controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0][7] == []


async def test_verify_reads_the_devices_deeply_and_writes_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count
    refreshes_before = zwave_driver.controller.refresh_count

    response = await call(hass, SERVICE_VERIFY, {}, return_response=True)

    assert zwave_driver.controller.write_count == writes_before
    assert zwave_driver.controller.refresh_count > refreshes_before
    assert response["rules"]["bedroom-main"] in {"pending", "in_sync", "drift"}


async def test_verify_scoped_to_one_rule_reads_only_that_rule_s_devices(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """One device, not two: an association table lives on the device that writes it.

    A rule names a source and a target, and every entry the rule is about is held by the
    source. Reading the target as well would spend radio time on a device that has nothing
    to say about this rule.
    """
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()

    response = await call(
        hass, SERVICE_VERIFY, {"rule_ids": ["bedroom-main"]}, return_response=True
    )

    assert response["devices"] == 1
    assert set(response["rules"]) == {"bedroom-main"}


# --------------------------------------------------------------------------------------
# set_rule_enabled and activate_profile
# --------------------------------------------------------------------------------------


async def test_set_rule_enabled_disables_the_rule_and_removes_its_links(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    await call(hass, SERVICE_APPLY, {}, return_response=True)
    controller = zwave_driver.controller
    assert controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0][2]

    await call(hass, SERVICE_SET_RULE_ENABLED, {"rule_id": "bedroom-main", "enabled": False})

    assert controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0][2] == []
    coordinator = device_links_entry.runtime_data.coordinator
    assert coordinator.is_rule_enabled("bedroom-main", default=True) is False


async def test_set_rule_enabled_goes_through_the_rate_limiter(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """E35. The service is the caller an automation loop would actually use.

    Association tables live in device NVM with a finite write endurance, so a service that
    reached the runner directly would reintroduce exactly the bypass the limiter exists to
    prevent, and it would do it for the one caller that can be run in a loop.
    """
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    toggles = device_links_entry.runtime_data.toggles

    for enabled in (False, True, False, True, False):
        await call(hass, SERVICE_SET_RULE_ENABLED, {"rule_id": "bedroom-main", "enabled": enabled})

    assert toggles.is_rate_limited("bedroom-main") is True
    assert toggles.requested_state("bedroom-main") is False
    assert len(device_links_entry.runtime_data.coordinator.state.jobs) <= 1


async def test_set_rule_enabled_with_an_unknown_rule_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_SET_RULE_ENABLED, {"rule_id": "ghost", "enabled": False})

    assert error.value.translation_key == "unknown_rule"


async def test_activate_profile_switches_without_writing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """FR-E1, same rule as the select: activating opens a plan, it does not apply one."""
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count

    await call(hass, SERVICE_ACTIVATE_PROFILE, {"profile_id": "away"})

    assert zwave_driver.controller.write_count == writes_before
    coordinator = device_links_entry.runtime_data.coordinator
    assert coordinator.active_profile is not None
    assert coordinator.active_profile.id == "away"
    assert device_links_entry.runtime_data.pending_plan is not None


async def test_activate_profile_applies_when_it_is_asked_to(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count

    await call(hass, SERVICE_ACTIVATE_PROFILE, {"profile_id": "away", "apply": True})

    assert zwave_driver.controller.write_count > writes_before


async def test_activate_profile_with_an_unknown_profile_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_ACTIVATE_PROFILE, {"profile_id": "ghost"})

    assert error.value.translation_key == "unknown_profile"


# --------------------------------------------------------------------------------------
# export and import
# --------------------------------------------------------------------------------------


async def test_export_profile_returns_yaml_that_parses_back(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    response = await call(hass, SERVICE_EXPORT_PROFILE, {}, return_response=True)

    assert response["profile_id"] == "home"
    assert parse_profile(response["yaml"]).id == "home"


async def test_export_profile_can_name_a_profile_that_is_not_active(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()

    response = await call(
        hass, SERVICE_EXPORT_PROFILE, {"profile_id": "away"}, return_response=True
    )

    assert response["profile_id"] == "away"


async def test_export_profile_with_no_active_profile_is_refused(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_EXPORT_PROFILE, {}, return_response=True)

    assert error.value.translation_key == "no_active_profile"


async def test_import_profile_updates_desired_state_and_writes_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """FR-P2 and E38: import changes what should be true, and never touches a radio."""
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count
    text = dump_profile(AWAY)

    response = await call(hass, SERVICE_IMPORT_PROFILE, {"yaml": text}, return_response=True)

    assert zwave_driver.controller.write_count == writes_before
    assert response["profile_id"] == "away"
    assert response["rules"] == 1
    assert response["is_active"] is False
    assert response["plan"] is None
    stored = device_links_entry.runtime_data.coordinator.state.profiles
    assert {profile.id for profile in stored} == {"home", "away"}


async def test_importing_over_the_active_profile_returns_the_plan_it_implies(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    writes_before = zwave_driver.controller.write_count
    changed = a_profile(a_rule(emitter_id="g5", target_node=LOBBY), profile_id="home", name="Home")

    response = await call(
        hass, SERVICE_IMPORT_PROFILE, {"yaml": dump_profile(changed)}, return_response=True
    )

    assert zwave_driver.controller.write_count == writes_before
    assert response["is_active"] is True
    assert response["plan"]["token"]
    assert response["plan"]["adds"] > 0


async def test_import_of_malformed_yaml_is_refused_and_changes_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as error:
        await call(
            hass,
            SERVICE_IMPORT_PROFILE,
            {"yaml": "version: 1\nprofile: []\n"},
            return_response=True,
        )

    assert error.value.translation_key == "profile_invalid"
    assert error.value.translation_placeholders["error"]
    stored = device_links_entry.runtime_data.coordinator.state.profiles
    assert {profile.id for profile in stored} == {"home"}


async def test_import_naming_devices_this_network_does_not_have_is_refused_whole(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """E38. Dropping the rules that cannot be resolved is the one answer nobody wants.

    An import that silently kept half a profile would report success and leave a house
    half-described, and the rules it dropped are exactly the ones the user would go
    looking for later.
    """
    activate(device_links_entry, HOME)
    await hass.async_block_till_done()
    text = dump_profile(HOME).replace("3538613642:37", "3538613642:222")

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, SERVICE_IMPORT_PROFILE, {"yaml": text}, return_response=True)

    assert error.value.translation_key == "import_unknown_devices"
    assert "3538613642:222" in error.value.translation_placeholders["devices"]
    assert "bedroom-main" in error.value.translation_placeholders["rules"]


# --------------------------------------------------------------------------------------
# The raw services (Decision D14)
# --------------------------------------------------------------------------------------


@pytest.fixture
async def raw_services_entry(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> MockConfigEntry:
    """Turn the expert tools on for the entry the other tests already set up."""
    hass.config_entries.async_update_entry(
        device_links_entry, options={OPTION_ENABLE_RAW_SERVICES: True}
    )
    await hass.async_block_till_done()
    return device_links_entry


async def test_raw_get_associations_reports_what_the_device_holds(
    hass: HomeAssistant,
    raw_services_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    response = await call(
        hass,
        SERVICE_ZWAVE_GET_ASSOCIATIONS,
        {"device_id": device_id_of(hass, zwave_js_devices, CONTROLLER)},
        return_response=True,
    )

    groups = {group["group"]: group for group in response["groups"]}
    assert groups["1"]["is_lifeline"] is True
    assert groups["1"]["entries"][0]["node_id"] == 1
    assert groups["2"]["entries"] == []


async def test_raw_add_and_remove_reach_the_device(
    hass: HomeAssistant,
    raw_services_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    data = {
        "device_id": device_id_of(hass, zwave_js_devices, CONTROLLER),
        "group": 7,
        "target_device_id": device_id_of(hass, zwave_js_devices, LOBBY),
    }

    await call(hass, SERVICE_ZWAVE_ADD_ASSOCIATION, data, return_response=True)

    held = zwave_driver.controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0][7]
    assert [address.node_id for address in held] == [LOBBY]

    await call(hass, SERVICE_ZWAVE_REMOVE_ASSOCIATION, data, return_response=True)

    assert zwave_driver.controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0][7] == []


@pytest.mark.parametrize(
    "service", [SERVICE_ZWAVE_ADD_ASSOCIATION, SERVICE_ZWAVE_REMOVE_ASSOCIATION]
)
async def test_the_raw_services_refuse_to_touch_a_lifeline(
    hass: HomeAssistant,
    raw_services_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
    service: str,
) -> None:
    """S11 and CLAUDE.md Section 3 rule 4, asserted on the radio rather than on our word."""
    writes_before = zwave_driver.controller.write_count

    with pytest.raises(ServiceValidationError) as error:
        await call(
            hass,
            service,
            {
                "device_id": device_id_of(hass, zwave_js_devices, CONTROLLER),
                "group": 1,
                "target_device_id": device_id_of(hass, zwave_js_devices, MAIN_LIGHTS),
            },
            return_response=True,
        )

    assert error.value.translation_key == "lifeline_is_protected"
    assert zwave_driver.controller.write_count == writes_before
    lifeline = zwave_driver.controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0][1]
    assert [address.node_id for address in lifeline] == [1]


async def test_a_raw_service_refuses_a_device_it_cannot_resolve(
    hass: HomeAssistant,
    raw_services_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    with pytest.raises(ServiceValidationError) as error:
        await call(
            hass,
            SERVICE_ZWAVE_ADD_ASSOCIATION,
            {
                "device_id": "not-a-device",
                "group": 7,
                "target_device_id": device_id_of(hass, zwave_js_devices, LOBBY),
            },
            return_response=True,
        )

    assert error.value.translation_key == "unknown_device"


async def test_a_raw_add_the_device_refuses_is_a_home_assistant_error(
    hass: HomeAssistant,
    raw_services_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """A device cannot be in its own association group (CLAUDE.md Section 10)."""
    with pytest.raises(HomeAssistantError) as error:
        await call(
            hass,
            SERVICE_ZWAVE_ADD_ASSOCIATION,
            {
                "device_id": device_id_of(hass, zwave_js_devices, CONTROLLER),
                "group": 7,
                "target_device_id": device_id_of(hass, zwave_js_devices, CONTROLLER),
            },
            return_response=True,
        )

    assert error.value.translation_key == "self_association"


# --------------------------------------------------------------------------------------
# services.yaml
# --------------------------------------------------------------------------------------


def test_services_yaml_and_the_code_agree_in_both_directions() -> None:
    """A drifted `services.yaml` is a bug the user meets in the developer tools UI.

    Both directions, because each failure is its own kind of wrong: a service missing from
    the file has no fields and no descriptions in the UI, and a service in the file that
    the code does not register is one a user fills in and cannot call.
    """
    from custom_components.device_links.services import SERVICE_SCHEMAS  # noqa: PLC0415

    documented = load_services_yaml()

    assert set(documented) == set(SERVICE_SCHEMAS)
    for service, schema in SERVICE_SCHEMAS.items():
        fields = set(documented[service].get("fields", {}))
        assert fields == {str(key) for key in schema.schema}, service


async def test_a_raw_call_naming_a_group_no_control_uses_is_refused(
    hass: HomeAssistant,
    raw_services_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """The feature a link carries is what its group issues, so an unknown group has none.

    Writing one anyway would put an entry in the observed model claiming something the
    device does not do, and the message names the groups that do exist so the caller can
    correct the number rather than guess again.
    """
    with pytest.raises(ServiceValidationError) as error:
        await call(
            hass,
            SERVICE_ZWAVE_ADD_ASSOCIATION,
            {
                "device_id": device_id_of(hass, zwave_js_devices, CONTROLLER),
                "group": 99,
                "target_device_id": device_id_of(hass, zwave_js_devices, LOBBY),
            },
            return_response=True,
        )

    assert error.value.translation_key == "group_not_offered"
    assert "2" in error.value.translation_placeholders["groups"]


async def test_a_raw_write_the_radio_refuses_is_a_translated_home_assistant_error(
    hass: HomeAssistant,
    raw_services_entry: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """E13 through the expert tool: the failure reaches the caller as a sentence."""
    zwave_driver.controller.raise_on_write = FailedZWaveCommand(
        "controller.add_associations", 100, "transmit failed"
    )

    with pytest.raises(HomeAssistantError) as error:
        await call(
            hass,
            SERVICE_ZWAVE_ADD_ASSOCIATION,
            {
                "device_id": device_id_of(hass, zwave_js_devices, CONTROLLER),
                "group": 7,
                "target_device_id": device_id_of(hass, zwave_js_devices, LOBBY),
            },
            return_response=True,
        )

    assert error.value.translation_key == "link_write_failed"
