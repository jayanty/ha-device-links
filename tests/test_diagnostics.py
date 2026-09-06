"""Diagnostics, and the one assertion that makes redaction real.

A diagnostics file is the artifact a user pastes into a public issue tracker. So the tests
here do not check that `async_redact_data` was called: they serialize the dump and search
the text for the raw values. A test that only checks the call passes while the data leaks,
which is the failure that matters, because by the time anybody notices, the file is on the
internet under somebody's real name.

What is scrubbed is what identifies a network rather than what describes a fault: the
Z-Wave home id, a Zigbee IEEE address, a Matter node id and anything shaped like a DSK. Node
numbers, group numbers, rule ids and device names stay, because a dump nobody can read is a
dump nobody will send.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
    get_diagnostics_for_device,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.device_links.diagnostics import REDACTED
from custom_components.device_links.models import (
    Backend as BackendId,
)
from custom_components.device_links.models import (
    DeviceHandle,
    Feature,
    MatterFingerprint,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
    ZigbeeFingerprint,
)
from tests.conftest import CONTROLLER, a_profile, a_rule, activate
from tests.factories import HOME_ID
from tests.fakes.zwave import FakeDriver

# A DSK is five-digit groups; the pattern is what a user pastes when they are asked for one.
A_DSK = "12345-01234-56789-01234-56789-01234-56789-01234"

IEEE = "0x00124b002e1dfd4a"
MATTER_NODE_ID = "8021771453412961111"


def a_zigbee_handle(name: str = "Entrance Inside Lights Aux") -> DeviceHandle:
    """Return a Zigbee handle, whose protocol address is an IEEE address."""
    return DeviceHandle(
        backend=BackendId.ZIGBEE2MQTT,
        protocol_id=IEEE,
        ha_device_id="",
        fingerprint=ZigbeeFingerprint(manufacturer="Inovelli", model="VZM31-SN"),
        name_at_authoring=name,
    )


def a_matter_handle() -> DeviceHandle:
    """Return a Matter handle, whose protocol address is a node id."""
    return DeviceHandle(
        backend=BackendId.MATTER,
        protocol_id=MATTER_NODE_ID,
        ha_device_id="",
        fingerprint=MatterFingerprint(vendor="Eve", product="Energy"),
        name_at_authoring=f"Eve Energy {A_DSK}",
    )


def a_foreign_profile() -> Profile:
    """Return a profile naming devices from the two protocols with no adapter yet.

    Stored profiles reach diagnostics whether or not their backend is loaded, so this is
    how an IEEE address and a Matter node id get into a dump on a Z-Wave-only system, and
    therefore how the redaction of both can be proved rather than assumed.
    """
    return Profile(
        id="foreign",
        name="Foreign",
        rules=(
            Rule(
                id="zigbee-rule",
                name="Aux switch drives the lights",
                template=Template.REMOTE,
                backend=BackendId.ZIGBEE2MQTT,
                source=RuleSource(device=a_zigbee_handle(), endpoint=2, emitter_id="g1"),
                targets=(RuleTarget(device=a_matter_handle(), endpoint=1),),
                features=frozenset({Feature.ON_OFF}),
            ),
        ),
    )


@pytest.fixture
async def applied(hass: HomeAssistant, device_links_entry: MockConfigEntry) -> MockConfigEntry:
    """Return an entry with a profile, a job in its history and a snapshot behind it."""
    activate(device_links_entry, a_profile(a_rule()), a_foreign_profile())
    await hass.async_block_till_done()
    runtime = device_links_entry.runtime_data
    plan = await runtime.coordinator.async_plan()
    await runtime.runner.async_apply(plan)
    await hass.async_block_till_done()
    return device_links_entry


# --------------------------------------------------------------------------------------
# What the dump says
# --------------------------------------------------------------------------------------


async def test_the_config_entry_dump_carries_what_a_report_needs(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, applied: MockConfigEntry
) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, applied)

    assert result["integration"]["version"]
    assert result["integration"]["options"] == {}
    assert result["backends"][0]["backend"] == "zwave"
    assert result["backends"][0]["available"] is True
    assert result["backends"][0]["upstream"] == "zwave_js"
    assert result["coordinator"]["devices"] > 0
    assert result["coordinator"]["unavailable"] == []
    assert result["jobs"][0]["status"] == "completed"
    assert result["snapshots"][0]["reason"] == "pre_apply"


async def test_the_dump_says_what_each_rule_wants_and_what_is_really_there(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, applied: MockConfigEntry
) -> None:
    """Desired against observed, per link. The first question of any report is which."""
    result = await get_diagnostics_for_config_entry(hass, hass_client, applied)

    profile = result["active_profile"]
    assert profile["id"] == "bedroom"
    rule = profile["rules"][0]
    assert rule["id"] == "bedroom-main"
    assert rule["state"] == "in_sync"
    assert len(rule["links"]) == 3
    assert all(link["desired"] and link["observed"] for link in rule["links"])


async def test_the_dump_carries_the_observed_cache_device_by_device(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, applied: MockConfigEntry
) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, applied)

    devices = {device["name"]: device for device in result["observed"]}
    controller = devices["Bedroom Scene Controller"]
    assert controller["available"] is True
    assert controller["backend"] == "zwave"
    assert any(link["is_system"] for link in controller["links"]), "no lifeline is reported"
    assert len(controller["links"]) == 4


async def test_a_device_dump_is_about_that_device(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    applied: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    result = await get_diagnostics_for_device(
        hass, hass_client, applied, zwave_js_devices[CONTROLLER]
    )

    assert result["device"]["name"] == "Bedroom Scene Controller"
    assert result["emitters"][0]["emitter_id"] == "g2"
    assert [rule["id"] for rule in result["rules"]] == ["bedroom-main"]
    assert result["job_results"][0]["status"] == "applied"


# --------------------------------------------------------------------------------------
# Redaction, proved by searching the output
# --------------------------------------------------------------------------------------


async def test_the_z_wave_home_id_is_nowhere_in_the_dump(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, applied: MockConfigEntry
) -> None:
    """It is in every device address and inside every fingerprint, which is the point.

    `async_redact_data` redacts by key and the home id is never a value of its own: it is a
    substring of `zwave:3538613642:36` and of every link fingerprint built from that. A
    redaction that only looked at keys would leave every one of them in place.
    """
    result = await get_diagnostics_for_config_entry(hass, hass_client, applied)

    serialized = json.dumps(result)
    assert HOME_ID not in serialized
    assert REDACTED in serialized
    assert ":36" in serialized, "the node number is not a secret and is what makes a dump useful"


async def test_a_device_dump_hides_the_home_id_too(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    applied: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    result = await get_diagnostics_for_device(
        hass, hass_client, applied, zwave_js_devices[CONTROLLER]
    )

    assert HOME_ID not in json.dumps(result)


async def test_a_zigbee_address_and_a_matter_node_id_are_hidden(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, device_links_entry: MockConfigEntry
) -> None:
    """The two protocols with no adapter yet still reach a dump through a stored profile.

    Their whole address is the secret, unlike Z-Wave: an IEEE address and a Matter node id
    identify a device globally rather than within one network, so there is no node number
    worth keeping out of them.
    """
    activate(device_links_entry, a_foreign_profile())
    await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(hass, hass_client, device_links_entry)

    serialized = json.dumps(result)
    assert IEEE not in serialized
    assert MATTER_NODE_ID not in serialized
    # The addresses really were in this dump, which is what makes the two lines above mean
    # something rather than merely be true.
    assert f"zigbee2mqtt:{REDACTED}" in serialized
    assert f"matter:{REDACTED}" in serialized


async def test_anything_dsk_shaped_is_scrubbed_wherever_it_turns_up(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """Defence in depth, by shape rather than by where a DSK was expected.

    Nothing stores a DSK today. The config entry's options are the part of this dump that
    grows without this module being touched, so an option nobody has listed as a secret is
    exactly where one would first appear, and it is caught by what it looks like.
    """
    entry = MockConfigEntry(
        domain="device_links",
        unique_id="device_links",
        title="Device Links",
        options={"support_note": f"the device joined with {A_DSK}"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert A_DSK not in json.dumps(result)
    assert REDACTED in result["integration"]["options"]["support_note"]


async def test_the_home_id_is_hidden_even_when_the_devices_cannot_be_read(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    applied: MockConfigEntry,
    zwave_driver: FakeDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The addresses a dump has to redact are the ones it can no longer look up.

    A dump taken while the backend is down is exactly the dump somebody sends, and the
    device list it derives its secrets from is empty at that point, so the secrets have to
    come from everything the dump actually contains rather than from what answers now.
    """
    runtime = applied.runtime_data
    monkeypatch.setattr(runtime.coordinator, "_handles", {})

    result = await get_diagnostics_for_config_entry(hass, hass_client, applied)

    assert HOME_ID not in json.dumps(result)


async def test_a_backend_that_is_down_is_reported_rather_than_hidden(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    applied: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = applied.runtime_data
    coordinator = runtime.coordinator

    async def _no_answer() -> Any:
        raise TimeoutError("the driver did not answer")

    monkeypatch.setattr(runtime.backends[BackendId.ZWAVE], "async_devices", _no_answer)
    await coordinator.async_refresh()

    result = await get_diagnostics_for_config_entry(hass, hass_client, applied)

    assert result["backends"][0]["available"] is False
    assert result["coordinator"]["last_error"] == {
        "backend": "zwave",
        "error": "TimeoutError",
    }
    assert len(result["coordinator"]["unavailable"]) > 0
    assert HOME_ID not in json.dumps(result)


async def test_the_dump_is_the_same_whether_or_not_a_profile_is_active(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, device_links_entry: MockConfigEntry
) -> None:
    """A system with nothing set up yet is one somebody asks for help with too."""
    result = await get_diagnostics_for_config_entry(hass, hass_client, device_links_entry)

    assert result["active_profile"] is None
    assert result["jobs"] == []
    assert result["observed"]


async def test_a_device_dump_for_a_device_that_is_not_ours_says_so(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    applied: MockConfigEntry,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """The hub is our own device and no rule is about it, so there is nothing to report."""
    hub = dr.async_get(hass).async_get_device(identifiers={("device_links", applied.entry_id)})
    assert hub is not None

    result = await get_diagnostics_for_device(hass, hass_client, applied, hub)

    assert result["device"] is None
    assert result["rules"] == []


async def test_the_dump_says_which_commit_is_running_on_a_dev_deployment(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, applied: MockConfigEntry
) -> None:
    """PRD 17.5: the deploy loop ends by comparing this with the SHA that was pushed.

    A HACS install has no such record and reports none, which is why the whole block is
    optional rather than a set of empty strings.
    """
    from custom_components.device_links.deployment import Deployment  # noqa: PLC0415

    applied.runtime_data.deployment = Deployment(
        commit="a1b2c3d",
        branch="dev",
        deployed_at="2026-09-05T12:00:00+00:00",
        previous_commit="0f0f0f0",
        changed_files=4,
    )

    result = await get_diagnostics_for_config_entry(hass, hass_client, applied)

    assert result["integration"]["deployment"] == {
        "commit": "a1b2c3d",
        "branch": "dev",
        "deployed_at": "2026-09-05T12:00:00+00:00",
        "previous_commit": "0f0f0f0",
        "changed_files": 4,
    }
