"""The admin WebSocket API: the surface the panel is built on, and its gate.

**Every command requires an admin user.** After this phase a WebSocket message can drive
the executor into a real Z-Wave write on somebody's house, so the gate is tested for every
command rather than for the three the plan names, with a message that would otherwise
succeed. A test that only covered `plan`, `apply` and `profiles/update` would pass while a
new command shipped ungated.

**A subscription dies with its connection.** `jobs/subscribe` adds listeners to the
coordinator and to the bus, and a listener that outlives its connection fires at a closed
socket, survives a reload and is the leak nobody finds. The assertion is the coordinator's
own listener count, before and after, which is a fact about what is registered rather than
a fact about what happened to be sent.

The shape of what `plan` returns is the shape of the panel: grouped by device, with adds,
removes, blocked-with-reasons and unmanaged-with-fingerprints in separate lists, so the
panel renders sections rather than filtering a flat list. Phase 1E builds against it, so it
is asserted here in full.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.websocket_api.const import (
    ERR_HOME_ASSISTANT_ERROR,
    ERR_UNAUTHORIZED,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from zwave_js_server.model.association import AssociationAddress

from custom_components.device_links.websocket import (
    COMMANDS,
    DEFERRED_COMMANDS,
)
from custom_components.device_links.yaml_io import dump_profile, profile_to_data, rule_to_data
from tests.conftest import CONTROLLER, LOBBY, MAIN_LIGHTS, a_profile, a_rule, activate
from tests.fakes.zwave import FakeDriver

HOME = a_profile(a_rule(), profile_id="home", name="Home")
AWAY = a_profile(
    a_rule("away-lobby", emitter_id="g5", target_node=LOBBY), profile_id="away", name="Away"
)

# PRD Section 8.7, verbatim, so a command that is neither implemented nor deliberately
# deferred fails this file rather than being noticed in Phase 1E.
PRD_COMMANDS = {
    "profiles/list",
    "profiles/get",
    "profiles/create",
    "profiles/update",
    "profiles/delete",
    "profiles/activate",
    "profiles/duplicate",
    "profiles/export",
    "profiles/import",
    "rules/validate",
    "rules/upsert",
    "rules/delete",
    "rules/set_enabled",
    "devices/list",
    "devices/get",
    "devices/refresh",
    "templates/list",
    "plan",
    "apply",
    "jobs/list",
    "jobs/get",
    "jobs/cancel",
    "jobs/subscribe",
    "verify",
    "unmanaged/adopt",
    "unmanaged/ignore",
    "unmanaged/remove",
    "swap/candidates",
    "swap/preview",
    "swap/apply",
    "snapshots/list",
    "snapshots/rollback",
}


async def send(client: Any, command: str, **data: Any) -> dict[str, Any]:
    """Send one command and return the reply, whether it succeeded or not."""
    await client.send_json_auto_id({"type": f"device_links/{command}", **data})
    result: dict[str, Any] = await client.receive_json()
    return result


async def ok(client: Any, command: str, **data: Any) -> Any:
    """Send one command, insist it succeeded, and return its result."""
    message = await send(client, command, **data)
    assert message["success"], message
    return message["result"]


def minimum_message(command: str, device_id: str) -> dict[str, Any]:
    """Return a message for each command that would work but for the admin check.

    The gate has to be tested with input that passes schema validation, because a message
    the schema rejects is refused before the handler is reached and would make an ungated
    command look guarded.
    """
    rule = {**rule_to_data(a_rule()), "id": "gate-check"}
    return {
        "profiles/get": {"profile_id": "home"},
        "profiles/create": {"profile": {"id": "new", "name": "New", "rules": []}},
        "profiles/update": {"profile": {"id": "home", "name": "Home", "rules": []}},
        "profiles/delete": {"profile_id": "home"},
        "profiles/activate": {"profile_id": "home"},
        "profiles/duplicate": {"profile_id": "home"},
        "profiles/import": {"yaml": dump_profile(AWAY)},
        "rules/validate": {"rule": rule},
        "rules/upsert": {"rule": rule},
        "rules/delete": {"rule_id": "bedroom-main"},
        "rules/set_enabled": {"rule_id": "bedroom-main", "enabled": False},
        "devices/get": {"device_id": device_id},
        "devices/refresh": {"device_id": device_id},
        "apply": {"plan_token": "whatever"},
        "jobs/get": {"job_id": "whatever"},
        "unmanaged/ignore": {"fingerprints": ["whatever"], "ignored": True},
        "unmanaged/remove": {"fingerprints": ["whatever"]},
    }.get(command, {})


@pytest.fixture
def slow_verify(zwave_driver: FakeDriver) -> None:
    """Make a device take a moment to answer its deep verify.

    A job against the fakes is otherwise over before the next WebSocket message arrives,
    which would make "a second apply while one is running" a test of scheduling luck. The
    delay is on the read the executor does after its writes, so the job is genuinely still
    running rather than artificially held open.
    """
    zwave_driver.controller.refresh_delay_seconds = 0.3


@pytest.fixture
async def api(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    device_links_entry: MockConfigEntry,
) -> Any:
    """Return an admin WebSocket client against a set-up integration holding one profile."""
    activate(device_links_entry, HOME, AWAY)
    await hass.async_block_till_done()
    return await hass_ws_client(hass)


# --------------------------------------------------------------------------------------
# Registration and the admin gate (E32)
# --------------------------------------------------------------------------------------


async def test_every_command_of_prd_8_7_is_implemented_or_deliberately_deferred() -> None:
    """A command that is neither is one Phase 1E would find missing, at the worst moment."""
    assert COMMANDS.keys() | DEFERRED_COMMANDS == PRD_COMMANDS
    assert not COMMANDS.keys() & DEFERRED_COMMANDS


async def test_the_commands_are_registered_under_our_domain(hass: HomeAssistant, api: Any) -> None:
    from homeassistant.components.websocket_api import const  # noqa: PLC0415

    handlers = hass.data[const.DOMAIN]

    for command in COMMANDS:
        assert f"device_links/{command}" in handlers, command


@pytest.mark.parametrize("command", sorted(COMMANDS))
async def test_every_command_requires_an_admin_user(
    hass: HomeAssistant,
    api: Any,
    hass_admin_user: Any,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    command: str,
) -> None:
    """E32. A non-admin gets Home Assistant's own unauthorized error and nothing else."""
    hass_admin_user.groups = []

    message = await send(api, command, **minimum_message(command, zwave_js_devices[LOBBY].id))

    assert message["success"] is False, command
    assert message["error"]["code"] == ERR_UNAUTHORIZED, command


async def test_an_error_carries_a_code_a_message_and_a_translation_key(api: Any) -> None:
    message = await send(api, "profiles/get", profile_id="ghost")

    assert message["error"]["code"] == ERR_HOME_ASSISTANT_ERROR
    assert message["error"]["message"]
    assert message["error"]["translation_key"] == "unknown_profile"
    assert message["error"]["translation_domain"] == "device_links"


# --------------------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------------------


async def test_plan_returns_the_work_grouped_by_device(
    hass: HomeAssistant, api: Any, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """The shape Phase 1E renders: one section per device, one list per kind of work."""
    result = await ok(api, "plan")

    assert result["token"]
    assert result["is_empty"] is False
    assert result["counts"]["add"] == 3
    device = next(
        entry for entry in result["devices"] if entry["identity"].endswith(f":{CONTROLLER}")
    )
    assert device["device_id"] == zwave_js_devices[CONTROLLER].id
    assert device["name"] == "Bedroom Scene Controller"
    assert device["available"] is True
    assert len(device["add"]) == 3
    assert device["remove"] == []
    assert device["blocked"] == []
    link = device["add"][0]["link"]
    assert link["fingerprint"]
    assert link["source"]["device_id"] == zwave_js_devices[CONTROLLER].id
    assert link["target"]["device_id"] == zwave_js_devices[MAIN_LIGHTS].id
    assert link["rule_id"] == "bedroom-main"
    assert link["rule_name"] == HOME.rules[0].name
    assert link["feature"] in {"on_off", "level_set", "level_hold"}
    json.dumps(result)


async def test_plan_reports_unmanaged_links_per_device_with_their_fingerprints(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Decision D9: reported, never in the work, and identified by what the user ticks."""
    controller = zwave_driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=CONTROLLER, endpoint=0),
        7,
        [AssociationAddress(controller, node_id=LOBBY, endpoint=None)],
    )
    await device_links_entry.runtime_data.coordinator.async_refresh()

    result = await ok(api, "plan")

    device = next(
        entry for entry in result["devices"] if entry["identity"].endswith(f":{CONTROLLER}")
    )
    assert len(device["unmanaged"]) == 1
    unmanaged = device["unmanaged"][0]
    assert unmanaged["emitter_group"] == "7"
    assert unmanaged["ignored"] is False
    assert unmanaged["fingerprint"] not in [item["link"]["fingerprint"] for item in device["add"]]


async def test_plan_can_be_scoped_to_one_rule(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    activate(
        device_links_entry, a_profile(a_rule(), a_rule("lobby", emitter_id="g5", target_node=LOBBY))
    )
    await hass.async_block_till_done()

    result = await ok(api, "plan", rule_ids=["lobby"])

    assert {item["link"]["rule_id"] for device in result["devices"] for item in device["add"]} == {
        "lobby"
    }


async def test_plan_with_a_device_it_cannot_resolve_is_refused(api: Any) -> None:
    message = await send(api, "plan", device_ids=["nope"])

    assert message["error"]["translation_key"] == "unknown_device"


# --------------------------------------------------------------------------------------
# apply, verify, jobs
# --------------------------------------------------------------------------------------


async def test_apply_runs_the_plan_the_token_names(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    plan = await ok(api, "plan")
    writes_before = zwave_driver.controller.write_count

    result = await ok(api, "apply", plan_token=plan["token"])
    await hass.async_block_till_done(wait_background_tasks=True)

    assert zwave_driver.controller.write_count > writes_before
    jobs = device_links_entry.runtime_data.coordinator.state.jobs
    assert jobs[-1].id == result["job_id"]
    assert jobs[-1].status == "completed"


async def test_apply_refuses_a_stale_plan_token(api: Any, zwave_driver: FakeDriver) -> None:
    """FR-A3. A token that does not match is a plan built against a network that has moved."""
    writes_before = zwave_driver.controller.write_count

    message = await send(api, "apply", plan_token="a-token-from-another-plan")

    assert message["error"]["translation_key"] == "plan_out_of_date"
    assert zwave_driver.controller.write_count == writes_before


async def test_a_second_apply_while_one_is_running_is_refused(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry, slow_verify: None
) -> None:
    """E16, and the check that makes the answer arrive at the caller rather than in a log."""
    plan = await ok(api, "plan")
    await ok(api, "apply", plan_token=plan["token"])

    message = await send(api, "apply", plan_token=plan["token"])

    assert message["error"]["translation_key"] == "job_running"
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_verify_reads_the_devices_and_writes_nothing(
    hass: HomeAssistant, api: Any, zwave_driver: FakeDriver
) -> None:
    writes_before = zwave_driver.controller.write_count
    refreshes_before = zwave_driver.controller.refresh_count

    result = await ok(api, "verify")

    assert zwave_driver.controller.write_count == writes_before
    assert zwave_driver.controller.refresh_count > refreshes_before
    assert result["devices"] > 0


async def test_jobs_list_and_get_report_what_ran(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    plan = await ok(api, "plan")
    applied = await ok(api, "apply", plan_token=plan["token"])
    await hass.async_block_till_done(wait_background_tasks=True)

    jobs = await ok(api, "jobs/list")
    job = await ok(api, "jobs/get", job_id=applied["job_id"])

    assert [entry["id"] for entry in jobs["jobs"]] == [applied["job_id"]]
    assert job["status"] == "completed"
    assert job["results"][0]["fingerprint"]
    assert job["results"][0]["status"] == "applied"


async def test_jobs_get_with_an_unknown_id_is_refused(api: Any) -> None:
    message = await send(api, "jobs/get", job_id="ghost")

    assert message["error"]["translation_key"] == "unknown_job"


async def test_jobs_cancel_stops_the_running_job(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry, slow_verify: None
) -> None:
    plan = await ok(api, "plan")
    await ok(api, "apply", plan_token=plan["token"])

    result = await ok(api, "jobs/cancel")
    await hass.async_block_till_done(wait_background_tasks=True)

    assert result["cancelled"] is True
    assert device_links_entry.runtime_data.coordinator.state.jobs[-1].status in {
        "cancelled",
        "completed",
    }


async def test_jobs_cancel_with_nothing_running_says_so(api: Any) -> None:
    result = await ok(api, "jobs/cancel")

    assert result["cancelled"] is False


# --------------------------------------------------------------------------------------
# jobs/subscribe
# --------------------------------------------------------------------------------------


async def test_jobs_subscribe_streams_progress_and_the_finished_job(
    hass: HomeAssistant,
    api: Any,
    hass_ws_client: WebSocketGenerator,
    device_links_entry: MockConfigEntry,
) -> None:
    """The work is driven from a second connection, so this one carries only the stream."""
    await api.send_json_auto_id({"type": "device_links/jobs/subscribe"})
    subscribed = await api.receive_json()
    assert subscribed["success"]
    first = await api.receive_json()
    assert first["event"]["type"] == "progress"
    assert first["event"]["job"] is None

    other = await hass_ws_client(hass)
    plan = await ok(other, "plan")
    await ok(other, "apply", plan_token=plan["token"])
    await hass.async_block_till_done(wait_background_tasks=True)

    events = []
    while True:
        message = await api.receive_json()
        events.append(message["event"])
        if message["event"]["type"] == "finished":
            break

    assert any(event["type"] == "progress" and event["job"] is not None for event in events)
    finished = events[-1]
    assert finished["job"]["status"] == "completed"
    assert finished["job"]["total"] > 0
    assert finished["job"]["id"]


async def test_a_subscription_stops_when_the_connection_closes(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    """A listener that outlives its connection survives a reload and is never found again."""
    coordinator = device_links_entry.runtime_data.coordinator
    before = coordinator.listener_count

    await api.send_json_auto_id({"type": "device_links/jobs/subscribe"})
    assert (await api.receive_json())["success"]
    await api.receive_json()
    assert coordinator.listener_count == before + 1

    await api.close()
    await hass.async_block_till_done()

    assert coordinator.listener_count == before
    # Nothing raises, because nothing is listening: the proof that it is really gone is the
    # count above, and this is the proof that firing at it is now harmless.
    coordinator.async_update_listeners()


async def test_unsubscribing_stops_the_stream_without_closing_the_connection(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    coordinator = device_links_entry.runtime_data.coordinator
    before = coordinator.listener_count
    await api.send_json_auto_id({"type": "device_links/jobs/subscribe"})
    subscription = await api.receive_json()
    await api.receive_json()

    await api.send_json_auto_id({"type": "unsubscribe_events", "subscription": subscription["id"]})
    assert (await api.receive_json())["success"]

    assert coordinator.listener_count == before
    coordinator.async_update_listeners()
    result = await ok(api, "jobs/list")
    assert result["jobs"] == []


# --------------------------------------------------------------------------------------
# Profiles and rules
# --------------------------------------------------------------------------------------


async def test_profiles_list_and_get(api: Any) -> None:
    listed = await ok(api, "profiles/list")
    got = await ok(api, "profiles/get", profile_id="away")

    assert [profile["id"] for profile in listed["profiles"]] == ["home", "away"]
    assert listed["active_profile_id"] == "home"
    assert listed["profiles"][0]["rules"] == 1
    assert got["profile"]["id"] == "away"
    assert got["rules"][0]["rule"]["id"] == "away-lobby"
    assert got["rules"][0]["state"] in {"pending", "in_sync", "drift", "unknown"}


async def test_profiles_create_update_and_delete(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    payload = profile_to_data(a_profile(a_rule("new-rule"), profile_id="new", name="New"))

    created = await ok(api, "profiles/create", profile=payload)
    updated = await ok(api, "profiles/update", profile={**payload, "name": "Renamed", "rules": []})
    listed = await ok(api, "profiles/list")

    assert created["profile"]["id"] == "new"
    assert updated["profile"]["name"] == "Renamed"
    assert {profile["id"] for profile in listed["profiles"]} == {"home", "away", "new"}

    await ok(api, "profiles/delete", profile_id="new")

    remaining = await ok(api, "profiles/list")
    assert {profile["id"] for profile in remaining["profiles"]} == {"home", "away"}


async def test_creating_a_profile_that_already_exists_is_refused(api: Any) -> None:
    message = await send(
        api, "profiles/create", profile={"id": "home", "name": "Home", "rules": []}
    )

    assert message["error"]["translation_key"] == "profile_exists"


async def test_a_profile_naming_a_device_this_network_does_not_have_is_refused(
    api: Any,
) -> None:
    """E38 again, through the panel's own door rather than through the YAML one."""
    payload = profile_to_data(HOME)
    payload["rules"][0]["source"]["device"] = "zwave:3538613642:222"

    message = await send(api, "profiles/update", profile=payload)

    assert message["error"]["translation_key"] == "profile_invalid"


async def test_deleting_the_active_profile_leaves_nothing_active(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    await ok(api, "profiles/delete", profile_id="home")

    listed = await ok(api, "profiles/list")
    assert listed["active_profile_id"] is None
    assert device_links_entry.runtime_data.coordinator.active_profile is None


async def test_profiles_activate_switches_without_writing(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    writes_before = zwave_driver.controller.write_count

    result = await ok(api, "profiles/activate", profile_id="away")

    assert zwave_driver.controller.write_count == writes_before
    assert result["plan"]["token"]
    assert device_links_entry.runtime_data.coordinator.active_profile.id == "away"


async def test_profiles_duplicate_copies_the_rules_under_a_new_id(api: Any) -> None:
    result = await ok(api, "profiles/duplicate", profile_id="home", name="Home copy")

    listed = await ok(api, "profiles/list")
    assert result["profile"]["name"] == "Home copy"
    assert result["profile"]["id"] != "home"
    assert result["profile"]["rules"] == 1
    assert len(listed["profiles"]) == 3


async def test_profiles_export_and_import_round_trip(
    hass: HomeAssistant, api: Any, zwave_driver: FakeDriver
) -> None:
    writes_before = zwave_driver.controller.write_count
    exported = await ok(api, "profiles/export", profile_id="away")

    await ok(api, "profiles/delete", profile_id="away")
    imported = await ok(api, "profiles/import", yaml=exported["yaml"])

    assert zwave_driver.controller.write_count == writes_before
    assert imported["profile"]["id"] == "away"
    assert imported["is_active"] is False


async def test_rules_validate_reports_the_compiler_without_saving_anything(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    rule = rule_to_data(a_rule("draft", emitter_id="g7", target_node=LOBBY))

    result = await ok(api, "rules/validate", rule=rule)

    assert result["links"], "a rule that compiles to nothing would not be worth validating"
    assert [warning["translation_key"] for warning in result["warnings"]] == [
        "feature_unavailable_level_set"
    ]
    assert result["errors"] == []
    stored = device_links_entry.runtime_data.coordinator.state.profiles
    assert {rule.id for profile in stored for rule in profile.rules} == {
        "bedroom-main",
        "away-lobby",
    }


async def test_rules_validate_reports_an_error_rather_than_raising(api: Any) -> None:
    """A rule the compiler refuses is an answer, not a failure: the panel shows the reason."""
    rule = rule_to_data(a_rule("draft", emitter_id="g99"))

    result = await ok(api, "rules/validate", rule=rule)

    assert result["links"] == []
    assert [error["translation_key"] for error in result["errors"]] == ["unknown_emitter"]


async def test_rules_upsert_adds_then_replaces_a_rule_in_the_active_profile(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    rule = rule_to_data(a_rule("extra", emitter_id="g5", target_node=LOBBY))

    await ok(api, "rules/upsert", rule=rule)
    await ok(api, "rules/upsert", rule={**rule, "name": "Renamed"})

    profile = device_links_entry.runtime_data.coordinator.active_profile
    assert [existing.id for existing in profile.rules] == ["bedroom-main", "extra"]
    assert profile.rules[1].name == "Renamed"


async def test_rules_delete_removes_it_from_the_profile(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    await ok(api, "rules/delete", rule_id="bedroom-main")

    profile = device_links_entry.runtime_data.coordinator.active_profile
    assert profile.rules == ()


async def test_rules_delete_with_an_unknown_id_is_refused(api: Any) -> None:
    message = await send(api, "rules/delete", rule_id="ghost")

    assert message["error"]["translation_key"] == "unknown_rule"


async def test_rules_set_enabled_goes_through_the_rate_limiter(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    """E35 again: the panel is a caller like any other, and NVM does not care who wrote."""
    await ok(api, "rules/set_enabled", rule_id="bedroom-main", enabled=False)
    await ok(api, "rules/set_enabled", rule_id="bedroom-main", enabled=True)
    await hass.async_block_till_done()

    toggles = device_links_entry.runtime_data.toggles
    assert toggles.is_rate_limited("bedroom-main") is True
    assert toggles.requested_state("bedroom-main") is True


# --------------------------------------------------------------------------------------
# Devices, templates, unmanaged links and snapshots
# --------------------------------------------------------------------------------------


async def test_devices_list_reports_what_each_backend_can_see(
    api: Any, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    result = await ok(api, "devices/list")

    device = next(
        entry for entry in result["devices"] if entry["identity"].endswith(f":{CONTROLLER}")
    )
    assert device["device_id"] == zwave_js_devices[CONTROLLER].id
    assert device["backend"] == "zwave"
    assert device["available"] is True
    assert device["links"] == 1
    assert device["emitters"] == 5


async def test_devices_get_reports_capabilities_observed_state_and_settings(
    api: Any, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    result = await ok(api, "devices/get", device_id=zwave_js_devices[CONTROLLER].id)

    assert result["device"]["name"] == "Bedroom Scene Controller"
    assert result["emitters"][0]["emitter_id"]
    assert result["emitters"][0]["capacity"] > 0
    assert result["links"][0]["is_system"] is True
    assert "settings" in result


async def test_devices_refresh_reads_the_device_again(
    api: Any, zwave_js_devices: dict[int, dr.DeviceEntry], zwave_driver: FakeDriver
) -> None:
    refreshes_before = zwave_driver.controller.refresh_count

    result = await ok(api, "devices/refresh", device_id=zwave_js_devices[LOBBY].id, deep=True)

    assert zwave_driver.controller.refresh_count > refreshes_before
    assert result["device"]["available"] is True


async def test_templates_list_names_every_template_a_rule_can_use(api: Any) -> None:
    result = await ok(api, "templates/list")

    assert {template["id"] for template in result["templates"]} == {
        "remote",
        "virtual_3way",
        "scene_button",
        "off_all",
        "status_feedback",
        "custom",
    }


async def test_unmanaged_ignore_is_remembered_and_reversible(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """FR-A5: a link the user said they did not care about is not re-flagged every restart."""
    controller = zwave_driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=CONTROLLER, endpoint=0),
        7,
        [AssociationAddress(controller, node_id=LOBBY, endpoint=None)],
    )
    await device_links_entry.runtime_data.coordinator.async_refresh()
    plan = await ok(api, "plan")
    device = next(
        entry for entry in plan["devices"] if entry["identity"].endswith(f":{CONTROLLER}")
    )
    fingerprint = device["unmanaged"][0]["fingerprint"]

    await ok(api, "unmanaged/ignore", fingerprints=[fingerprint], ignored=True)

    after = await ok(api, "plan")
    ignored = next(
        entry for entry in after["devices"] if entry["identity"].endswith(f":{CONTROLLER}")
    )["unmanaged"][0]
    assert ignored["ignored"] is True

    await ok(api, "unmanaged/ignore", fingerprints=[fingerprint], ignored=False)
    assert device_links_entry.runtime_data.coordinator.state.ignored_unmanaged == frozenset()


async def test_unmanaged_remove_takes_off_exactly_the_links_that_were_ticked(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    controller = zwave_driver.controller
    source = AssociationAddress(controller, node_id=CONTROLLER, endpoint=0)
    await controller.async_add_associations(
        source, 7, [AssociationAddress(controller, node_id=LOBBY, endpoint=None)]
    )
    await controller.async_add_associations(
        source, 9, [AssociationAddress(controller, node_id=MAIN_LIGHTS, endpoint=None)]
    )
    await device_links_entry.runtime_data.coordinator.async_refresh()
    plan = await ok(api, "plan")
    device = next(
        entry for entry in plan["devices"] if entry["identity"].endswith(f":{CONTROLLER}")
    )
    fingerprint = next(
        link["fingerprint"] for link in device["unmanaged"] if link["emitter_group"] == "7"
    )

    await ok(api, "unmanaged/remove", fingerprints=[fingerprint])
    await hass.async_block_till_done()

    held = controller.get_all_associations_sync(CONTROLLER)[CONTROLLER][0]
    assert held[7] == []
    assert [address.node_id for address in held[9]] == [MAIN_LIGHTS]


async def test_snapshots_list_reports_what_was_taken_before_each_apply(
    hass: HomeAssistant, api: Any
) -> None:
    plan = await ok(api, "plan")
    await ok(api, "apply", plan_token=plan["token"])
    await hass.async_block_till_done(wait_background_tasks=True)

    result = await ok(api, "snapshots/list")

    assert result["snapshots"][0]["reason"] == "pre_apply"
    assert result["snapshots"][0]["devices"]


# --------------------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------------------


async def test_a_command_with_no_entry_loaded_says_so(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """The panel can be open while the entry is retrying its setup, and has to be told."""
    assert await async_setup_component(hass, "device_links", {})
    client = await hass_ws_client(hass)

    message = await send(client, "profiles/list")

    assert message["error"]["translation_key"] == "not_loaded"


async def test_a_scope_naming_a_rule_that_does_not_exist_is_refused(api: Any) -> None:
    message = await send(api, "plan", rule_ids=["ghost"])

    assert message["error"]["translation_key"] == "unknown_rule"


async def test_a_rule_naming_a_device_this_network_does_not_have_is_refused(api: Any) -> None:
    rule = rule_to_data(a_rule("draft"))
    rule["targets"] = [{"device": "zwave:3538613642:222", "endpoint": None}]

    message = await send(api, "rules/validate", rule=rule)

    assert message["error"]["translation_key"] == "profile_invalid"


async def test_rules_set_enabled_with_an_unknown_rule_is_refused(api: Any) -> None:
    message = await send(api, "rules/set_enabled", rule_id="ghost", enabled=False)

    assert message["error"]["translation_key"] == "unknown_rule"


async def test_commands_that_need_an_active_profile_say_when_there_is_none(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    await ok(api, "profiles/delete", profile_id="home")

    message = await send(api, "profiles/export")

    assert message["error"]["translation_key"] == "no_active_profile"


async def test_importing_yaml_that_is_not_a_profile_is_refused(api: Any) -> None:
    message = await send(api, "profiles/import", yaml="version: 1\nprofile: []\n")

    assert message["error"]["translation_key"] == "profile_invalid"


async def test_importing_over_the_active_profile_answers_with_the_plan_it_implies(
    hass: HomeAssistant, api: Any, zwave_driver: FakeDriver
) -> None:
    writes_before = zwave_driver.controller.write_count
    changed = a_profile(a_rule(emitter_id="g5", target_node=LOBBY), profile_id="home", name="Home")

    result = await ok(api, "profiles/import", yaml=dump_profile(changed))

    assert zwave_driver.controller.write_count == writes_before
    assert result["is_active"] is True
    assert result["plan"]["counts"]["add"] > 0


async def test_apply_with_nothing_to_do_starts_no_job(hass: HomeAssistant, api: Any) -> None:
    plan = await ok(api, "plan")
    await ok(api, "apply", plan_token=plan["token"])
    await hass.async_block_till_done(wait_background_tasks=True)
    settled = await ok(api, "plan")

    result = await ok(api, "apply", plan_token=settled["token"])

    assert result["job_id"] is None
    assert result["status"] == "nothing_to_do"


async def test_unmanaged_remove_with_nothing_ticked_does_nothing(api: Any) -> None:
    result = await ok(api, "unmanaged/remove", fingerprints=["not-a-fingerprint"])

    assert result["job_id"] is None
    assert result["status"] == "nothing_to_do"


async def test_rules_validate_reports_the_device_settings_a_rule_would_write(
    api: Any,
) -> None:
    """A rule can ask for a device setting as well as for links (FR-R3).

    Nothing turns one into a plan item yet (open items T2 and T16), so this is where the
    panel sees it: the compiler resolves the capability to the parameter and bit that
    carries it, and says so before anybody presses apply.
    """
    rule = {**rule_to_data(a_rule("draft")), "mirror_source": "on"}

    result = await ok(api, "rules/validate", rule=rule)

    assert result["settings"] == [
        {
            "device_identity": "zwave:3538613642:36",
            "capability": "mirror_hub_commands",
            "parameter": 35,
            "bitmask": 4,
            "value": 1,
        }
    ]


async def test_importing_a_file_naming_devices_this_network_does_not_have_is_refused(
    hass: HomeAssistant, api: Any, device_links_entry: MockConfigEntry
) -> None:
    """E38, refused the same way and with the same message as the service (whole, not partly)."""
    text = dump_profile(AWAY).replace("3538613642:35", "3538613642:222")

    message = await send(api, "profiles/import", yaml=text)

    assert message["error"]["translation_key"] == "import_unknown_devices"
    stored = device_links_entry.runtime_data.coordinator.state.profiles
    assert {profile.id for profile in stored} == {"home", "away"}
