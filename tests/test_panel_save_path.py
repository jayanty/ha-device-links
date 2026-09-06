"""The payload the rule editor builds, pushed through the real `rules/upsert`.

Open item T50 is what this file exists for, and the shape of that bug is the reason it
had to be a new kind of test rather than one more case in an old one.

Everything here was already tested in layers, and each layer was right about itself.
`tests/test_panel_contract.py` proves the panel's TypeScript types are exactly the shapes
`serialize.py` produces, in both directions. `tests/test_websocket.py` exercises every
command against payloads written beside it. `frontend/test/rule-editor.test.ts` proves the
stepper sends `rules/upsert` when the user presses Save. Every one of those passed while
**every rule the panel could save was refused**: the editor built
`source: {device, endpoint: null, emitter_id}`, `yaml_io._require_int` wants a whole
number, and the two never met because a type check is not an acceptance check and no test
took a payload the editor would really build and gave it to the handler that really reads
it.

So that is what this file does, and the only thing it does: build the rule the way
`dialogs/rule-editor.ts` builds it, out of the same serialized payloads the panel is
handed (`devices/list` rows and `devices/get` details, over a real WebSocket connection),
send it through `rules/upsert`, and assert it is accepted and comes back the same. Four
shapes, because the endpoints differ in all four: a one-way Z-Wave rule, a two-way Z-Wave
rule (the reverse leg is where endpoints bite hardest), a one-way Zigbee rule, whose
binding is refused outright if the target endpoint is not named, and a two-way Zigbee rule,
which is the pair of Inovelli Blues the `virtual_3way` template defaults to.

`panel_rule` below is the mirror of the editor, and it is a mirror rather than the thing
itself because the editor is TypeScript. Two things keep the mirror honest:

- `frontend/test/rule-editor.test.ts::the payload it sends` drives the real component and
  asserts the payload it sends derives its endpoints from exactly these two fields, so an
  editor that stopped filling them in fails there.
- `RuleSourceData.endpoint` is `number` in `types.ts`, not `number | null`, so the
  original bug is now a TypeScript error rather than something a test has to notice.

The endpoints are read with `.get`, the way a JavaScript client reads a field that may not
be in the payload at all: a serializer that stopped carrying `Emitter.endpoint` or
`DeviceRow.receiving_endpoint` sends `null` from the panel and must fail here with the
refusal a user would see, not with a `KeyError` about a Python dictionary.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

import custom_components.device_links as integration
from custom_components.device_links.const import DOMAIN
from custom_components.device_links.models import Backend as BackendId
from tests.conftest import CONTROLLER, MAIN_LIGHTS
from tests.factories import AUX_IEEE, LIGHT_IEEE, zigbee_handle
from tests.fakes.zigbee import FakeBridge, build_bridge_from_fixture

# --------------------------------------------------------------------------------------
# The editor, mirrored
# --------------------------------------------------------------------------------------

# `TEMPLATE_DEFAULTS` in `dialogs/rule-editor.ts`: what choosing a template pre-fills.
TEMPLATE_DEFAULTS: Mapping[str, tuple[list[str], str, str]] = {
    "remote": (["on_off", "level_set", "level_hold"], "one_way", "leave"),
    "virtual_3way": (["on_off", "level_set", "level_hold"], "two_way", "leave"),
    "scene_button": (["on_off"], "one_way", "leave"),
    "off_all": (["on_off"], "one_way", "off"),
    "status_feedback": (["status_report"], "one_way", "leave"),
    "custom": (["on_off"], "one_way", "leave"),
}


def panel_rule(  # noqa: PLR0913
    *,
    rule_id: str,
    name: str,
    template: str,
    source: dict[str, Any],
    detail: dict[str, Any],
    emitter_id: str,
    targets: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Return the rule payload the editor would send for these choices.

    Step by step as `rule-editor.ts` does it: the template fills the defaults, choosing a
    device sets the backend, choosing a control sets the source endpoint and drops the
    features that control cannot carry, and ticking a target takes the endpoint the device
    says a link lands on when nobody was offered the choice.
    """
    defaults, direction, mirror = TEMPLATE_DEFAULTS[template]
    emitter = next(
        candidate for candidate in detail["emitters"] if candidate["emitter_id"] == emitter_id
    )
    # `_chooseEmitter`: a feature the control cannot carry is dropped rather than left to
    # compile into a warning the user did not cause, and an empty set falls back to one.
    kept = [feature for feature in defaults if feature in emitter["actions"]]
    return {
        "id": rule_id,
        "name": name,
        "template": template,
        "backend": source["backend"],
        "enabled": True,
        "direction": direction,
        "mirror_source": mirror,
        "features": kept or sorted(emitter["actions"])[:1],
        "source": {
            "device": source["identity"],
            "endpoint": emitter.get("endpoint"),
            "emitter_id": emitter_id,
        },
        "targets": [
            {"device": target["identity"], "endpoint": target.get("receiving_endpoint")}
            for target in targets
        ],
    }


# --------------------------------------------------------------------------------------
# A house with both radios in it, and an admin connection to it
# --------------------------------------------------------------------------------------


@pytest.fixture
def zigbee2mqtt(monkeypatch: pytest.MonkeyPatch) -> FakeBridge:
    """Make setup believe MQTT is loaded, and hand the adapter the G1 capture."""
    bridge = build_bridge_from_fixture()
    monkeypatch.setattr(integration, "async_mqtt_is_available", lambda hass: True)
    monkeypatch.setattr(integration, "HomeAssistantMqttClient", lambda hass: bridge)
    return bridge


@pytest.fixture
async def both_radios(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zigbee2mqtt: FakeBridge,
) -> AsyncGenerator[MockConfigEntry]:
    """Device Links over the fake Z-Wave network and the fake Zigbee bridge at once."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
async def client(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, both_radios: MockConfigEntry
) -> Any:
    """An admin WebSocket client, which is the only kind the panel can be."""
    return await hass_ws_client(hass)


async def call(client: Any, command: str, **data: Any) -> Any:
    """Send one command and return its result, failing loudly if it was refused."""
    await client.send_json_auto_id({"type": f"device_links/{command}", **data})
    message = await client.receive_json()
    assert message["success"], message["error"]
    return message["result"]


async def refused(client: Any, command: str, **data: Any) -> dict[str, Any]:
    """Send one command that is expected to be refused, and return the refusal."""
    await client.send_json_auto_id({"type": f"device_links/{command}", **data})
    message = await client.receive_json()
    assert not message["success"], f"{command} was accepted: {message.get('result')}"
    error: dict[str, Any] = message["error"]
    return error


async def rows(client: Any) -> dict[str, dict[str, Any]]:
    """Return the device list the panel holds, keyed by identity."""
    listed = await call(client, "devices/list")
    return {device["identity"]: device for device in listed["devices"]}


async def zwave_detail(client: Any, device: dict[str, Any]) -> dict[str, Any]:
    """Return what the editor loads when a Z-Wave device is chosen as the source."""
    return await call(client, "devices/get", device_id=device["device_id"])


def zigbee_detail(hass: HomeAssistant, entry: MockConfigEntry, ieee: str) -> dict[str, Any]:
    """Return the `devices/get` payload for a Zigbee device.

    The same function the command answers with, reached without the device-registry
    lookup in front of it: a Zigbee handle resolves to no Home Assistant device id yet
    (`rule_entity._upstream_identifier` is Z-Wave only), so `devices/get` cannot be asked
    for one by id and neither can the panel. That gap is open item T57; it is about which
    devices the panel can reach, and this file is about what it sends when it reaches one.
    """
    from custom_components.device_links.websocket import _device_detail  # noqa: PLC0415

    return _device_detail(hass, entry, zigbee_handle(ieee))  # type: ignore[arg-type]


def stored(profile: dict[str, Any], rule_id: str) -> dict[str, Any]:
    """Return one rule as it came back from the backend, by id."""
    return next(row["rule"] for row in profile["rules"] if row["rule"]["id"] == rule_id)


@pytest.fixture
async def profile(client: Any) -> str:
    """An empty profile of the user's own, made active, as pressing New profile does."""
    created = await call(
        client, "profiles/create", profile={"id": "panel", "name": "Panel", "rules": []}
    )
    profile_id: str = created["profile"]["id"]
    await call(client, "profiles/activate", profile_id=profile_id)
    return profile_id


# --------------------------------------------------------------------------------------
# The rules the panel builds, through the handler that reads them
# --------------------------------------------------------------------------------------


async def test_issue_50_a_one_way_zwave_rule_the_panel_builds_is_accepted(
    client: Any, profile: str
) -> None:
    """The plainest rule the panel can produce: one button, one light, on/off and dim."""
    devices = await rows(client)
    source = devices[f"zwave:{_home()}:{CONTROLLER}"]
    detail = await zwave_detail(client, source)
    target = devices[f"zwave:{_home()}:{MAIN_LIGHTS}"]
    rule = panel_rule(
        rule_id="panel-remote",
        name="Main button controls Master Bedroom Lights",
        template="remote",
        source=source,
        detail=detail,
        emitter_id=_first_control(detail),
        targets=[target],
    )

    compiled = await call(client, "rules/validate", rule=rule)
    saved = await call(client, "rules/upsert", rule=rule, profile_id=profile)

    assert compiled["errors"] == []
    assert compiled["links"], "the rule the panel built compiles to no links"
    assert saved["rule"] == {**rule, "features": sorted(rule["features"])}
    # And it is really stored, rather than merely echoed back.
    assert stored(await call(client, "profiles/get", profile_id=profile), "panel-remote")


async def test_issue_50_a_two_way_zwave_rule_the_panel_builds_is_accepted(
    client: Any, profile: str
) -> None:
    """Two-way is where the endpoints bite: the reverse leg lands back on the source."""
    devices = await rows(client)
    source = devices[f"zwave:{_home()}:{CONTROLLER}"]
    detail = await zwave_detail(client, source)
    rule = panel_rule(
        rule_id="panel-3way",
        name="Virtual 3-way",
        template="virtual_3way",
        source=source,
        detail=detail,
        emitter_id=_first_control(detail),
        targets=[devices[f"zwave:{_home()}:{MAIN_LIGHTS}"]],
    )

    compiled = await call(client, "rules/validate", rule=rule)
    await call(client, "rules/upsert", rule=rule, profile_id=profile)
    plan = await call(client, "plan", rule_ids=["panel-3way"])

    assert rule["direction"] == "two_way"
    assert compiled["errors"] == []
    # Both directions compiled, and each leg drives from the endpoint its own control uses.
    assert {link["source"]["identity"] for link in compiled["links"]} == {
        source["identity"],
        devices[f"zwave:{_home()}:{MAIN_LIGHTS}"]["identity"],
    }
    assert plan["counts"]["add"], "a two-way rule the panel saved planned no work"
    assert not plan["counts"]["blocked"]


async def test_issue_50_a_zigbee_rule_the_panel_builds_is_accepted(
    hass: HomeAssistant, client: Any, both_radios: MockConfigEntry, profile: str
) -> None:
    """Zigbee refuses a binding that does not name both endpoints, so this is the sharp one.

    The aux paddle drives from endpoint 2 and the light's load receives on endpoint 1.
    Neither is a number the panel can guess: one comes from the emitter the user picked and
    the other from the target device's own capabilities.
    """
    devices = await rows(client)
    source = devices[zigbee_handle(AUX_IEEE).identity]
    detail = zigbee_detail(hass, both_radios, AUX_IEEE)
    target = devices[zigbee_handle(LIGHT_IEEE).identity]
    rule = panel_rule(
        rule_id="panel-zigbee",
        name="Aux paddle controls Entrance Inside Lights",
        template="remote",
        source=source,
        detail=detail,
        emitter_id=_first_control(detail),
        targets=[target],
    )

    compiled = await call(client, "rules/validate", rule=rule)
    await call(client, "rules/upsert", rule=rule, profile_id=profile)
    plan = await call(client, "plan", rule_ids=["panel-zigbee"])

    assert rule["backend"] == str(BackendId.ZIGBEE2MQTT)
    assert compiled["errors"] == []
    assert compiled["warnings"] == []
    # The endpoints the hardware really has, on both ends of every link.
    assert {
        (link["source"]["endpoint"], link["target"]["endpoint"]) for link in compiled["links"]
    } == {(2, 1)}
    assert plan["counts"]["add"], "a Zigbee rule the panel saved planned no work"
    assert not plan["counts"]["blocked"]


async def test_issue_50_a_two_way_zigbee_rule_the_panel_builds_converges(
    hass: HomeAssistant, client: Any, both_radios: MockConfigEntry, profile: str
) -> None:
    """The canonical two-Inovelli-Blue 3-way, authored the way the panel authors it."""
    devices = await rows(client)
    source = devices[zigbee_handle(AUX_IEEE).identity]
    detail = zigbee_detail(hass, both_radios, AUX_IEEE)
    rule = panel_rule(
        rule_id="panel-zigbee-3way",
        name="Entrance 3-way",
        template="virtual_3way",
        source=source,
        detail=detail,
        emitter_id=_first_control(detail),
        targets=[devices[zigbee_handle(LIGHT_IEEE).identity]],
    )

    compiled = await call(client, "rules/validate", rule=rule)
    await call(client, "rules/upsert", rule=rule, profile_id=profile)
    plan = await call(client, "plan", rule_ids=["panel-zigbee-3way"])

    assert compiled["errors"] == []
    assert compiled["warnings"] == []
    # Forward off the aux paddle onto the light's load, reverse off the light's paddle onto
    # the aux's load. Nothing here is endpoint 0, which is the Z-Wave root and nothing here.
    assert {
        (link["source"]["endpoint"], link["target"]["endpoint"]) for link in compiled["links"]
    } == {(2, 1)}
    assert plan["counts"]["add"]
    assert not plan["counts"]["blocked"]


async def test_issue_50_a_rule_the_panel_saved_survives_export_and_import(
    client: Any, profile: str
) -> None:
    """A rule the panel built is a rule the YAML codec can write and read back.

    `rules/upsert` and `profiles/import` narrow the same data through the same module, so
    a payload one accepts and the other refuses would be a rule that could be saved and
    never restored.
    """
    devices = await rows(client)
    source = devices[f"zwave:{_home()}:{CONTROLLER}"]
    detail = await zwave_detail(client, source)
    rule = panel_rule(
        rule_id="panel-export",
        name="Goodnight",
        template="off_all",
        source=source,
        detail=detail,
        emitter_id=_first_control(detail),
        targets=[devices[f"zwave:{_home()}:{MAIN_LIGHTS}"]],
    )
    await call(client, "rules/upsert", rule=rule, profile_id=profile)

    exported = await call(client, "profiles/export", profile_id=profile)
    imported = await call(client, "profiles/import", yaml=exported["yaml"])

    assert imported["profile"]["rules"] == 1


async def test_a_target_that_can_receive_nothing_is_refused_before_the_save(
    hass: HomeAssistant, client: Any, both_radios: MockConfigEntry, profile: str
) -> None:
    """A device with no endpoint for a link to land on, chosen as a target.

    The other half of the endpoint decision, and the one that has to end somewhere a user
    can act. `DeviceCapabilities.receiving_endpoint` is None for the Aqara sensors on this
    network, because they serve no cluster a binding could send to, and that is the same
    devices whose `receivable` set is empty. So the editor sends a null endpoint, and the
    answer the user gets is the compiler's, at the review step, before anything is stored:
    "cannot act on on_off", per feature, with the target named. Not a save that fails.
    """
    devices = await rows(client)
    source = devices[zigbee_handle(AUX_IEEE).identity]
    detail = zigbee_detail(hass, both_radios, AUX_IEEE)
    sensor = next(
        device
        for device in devices.values()
        if device["backend"] == str(BackendId.ZIGBEE2MQTT) and device["receiving_endpoint"] is None
    )
    rule = panel_rule(
        rule_id="panel-sensor",
        name="Paddle drives a thermometer",
        template="remote",
        source=source,
        detail=detail,
        emitter_id=_first_control(detail),
        targets=[sensor],
    )

    compiled = await call(client, "rules/validate", rule=rule)

    assert compiled["links"] == []
    assert {error["translation_key"] for error in compiled["errors"]} == {"target_cannot_receive"}
    assert all(error["placeholders"]["device"] == sensor["name"] for error in compiled["errors"])


# --------------------------------------------------------------------------------------
# What the backend still refuses, and why that is the right layer for it
# --------------------------------------------------------------------------------------


async def test_a_null_source_endpoint_is_still_refused_rather_than_guessed(
    client: Any, profile: str
) -> None:
    """T50's decision, pinned: the editor fills the endpoints in, and nothing else does.

    A null arriving here would have to mean both "the user did not choose" and "there is
    genuinely no endpoint", and those need different answers. So the refusal stays, and
    this is the message that was reaching every save from the panel until T50 was closed.
    """
    devices = await rows(client)
    source = devices[f"zwave:{_home()}:{CONTROLLER}"]
    detail = await zwave_detail(client, source)
    rule = panel_rule(
        rule_id="panel-null",
        name="No endpoint",
        template="remote",
        source=source,
        detail=detail,
        emitter_id=_first_control(detail),
        targets=[devices[f"zwave:{_home()}:{MAIN_LIGHTS}"]],
    )
    rule["source"]["endpoint"] = None

    error = await refused(client, "rules/upsert", rule=rule, profile_id=profile)

    assert error["translation_key"] == "profile_invalid"
    assert "source endpoint must be a whole number, not nothing" in error["message"]


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _home() -> str:
    """Return the fake network's home id, which every Z-Wave identity starts with."""
    from tests.factories import HOME_ID  # noqa: PLC0415

    return str(HOME_ID)


def _first_control(detail: dict[str, Any]) -> str:
    """Return the first control the editor would offer, which is what a user clicks.

    A lifeline is shown and is not selectable, exactly as `_renderEmitter` renders it.
    """
    return next(
        emitter["emitter_id"] for emitter in detail["emitters"] if not emitter["is_lifeline"]
    )
