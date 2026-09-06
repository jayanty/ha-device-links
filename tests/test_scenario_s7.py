"""Scenario S7, end to end: a profile naming dead node 13, swapped onto live node 42.

PRD Section 15, S7: "import a profile referencing dead node 13 ('Ceiling Lights Old') and
swap it to node 42 ('Ceiling Lights')", passing when the wizard maps the emitters
automatically, rewrites the rules, plans links on 42, marks the old device's links as
unreachable, and applies and verifies.

Everything below goes through the real WebSocket commands, in the order a person presses
them, against the Stage 0 fakes: `profiles/import`, `swap/candidates`, `swap/preview`,
`swap/apply`, then `verify`. Nothing reaches past a handler, and the writes land in the
fake driver's own association tables, which is what the assertions read.

**Node 13 is a real artifact rather than an invented one, and that is why it is in no
fixture.** It was already dead and replaced before Stage 0 ran, so nothing on this network
can be asked about it any more. What the profile carries for it is what a profile carries
for any device: an address, a model and the name it had. That is exactly the case a swap
has to handle, because the ordinary reason for a swap is that the old device is gone.

Two divergences from S7 as written, both recorded in `docs/open-items.md` section 7:

- S7 says the emitters map automatically **because the model is the same**. On this network
  it is not: PRD Section 3.1 records node 13 as an Inovelli VZW31-SN and node 42 as a
  VZW32-SN. They map automatically anyway, because both devices call the paddle `paddle`,
  which is the mapping this flow does first. The criterion is met by the control rather
  than by the model.
- "Marks the old device's links as unreachable" is a preview field (`old_listed` and
  `old_reachable`) rather than a mark on a link. A device that is gone holds links nobody
  can read, let alone remove, and a per-link mark would be claiming to know what is on a
  device nothing can reach.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.device_links.const import DOMAIN
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    Feature,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from custom_components.device_links.yaml_io import dump_profile, rule_to_data
from tests.factories import CEILING_LIGHTS_OLD, handle
from tests.fakes.zwave import FakeDriver

# The devices S7 names. Node 42 is the replacement that is really on the network; node 37
# is the light the rule drives, so a rewrite that moved the wrong end of the rule shows up.
REPLACEMENT = 42
LIGHT = 37
CONTROLLER = 36
DIMMING = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})

# The paddle's three association groups on an Inovelli VZW32-SN: on/off, level set and
# level hold. Straight out of `tests/fixtures/z2_associations.json` for node 42.
PADDLE_GROUPS = (2, 3, 4)


def imported_profile(*, paddle: str = "paddle", features: frozenset[Feature] = DIMMING) -> Profile:
    """Return the profile S7 imports: two rules, both about the device that is gone.

    One drives from the dead switch and one drives it, because FR-S2 rewrites a device on
    both sides and a fixture with only the source side would prove half of it.

    `paddle` is the control the first rule drives from, and it is a parameter for one test
    only: a rule naming a control the replacement does not have is what the mapping step
    exists for, and it cannot be made by editing the profile afterwards, because
    `rules/upsert` resolves a rule's devices against the network and node 13 is not on it.
    """
    return Profile(
        id="ceiling",
        name="Ceiling",
        rules=(
            Rule(
                id="ceiling-paddle",
                name="Ceiling paddle controls Master Bedroom Lights",
                template=Template.REMOTE,
                backend=BackendId.ZWAVE,
                source=RuleSource(device=handle(CEILING_LIGHTS_OLD), endpoint=0, emitter_id=paddle),
                targets=(RuleTarget(device=handle(LIGHT), endpoint=None),),
                features=features,
            ),
            Rule(
                id="bedroom-drives-ceiling",
                name="Bedroom scene button 1 drives the ceiling",
                template=Template.SCENE_BUTTON,
                backend=BackendId.ZWAVE,
                source=RuleSource(device=handle(CONTROLLER), endpoint=0, emitter_id="g5"),
                targets=(RuleTarget(device=handle(CEILING_LIGHTS_OLD), endpoint=None),),
                features=frozenset({Feature.ON_OFF}),
            ),
        ),
    )


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


@pytest.fixture
async def client(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, device_links_entry: MockConfigEntry
) -> Any:
    """An admin connection to a set-up integration over the Stage 0 fake network."""
    return await hass_ws_client(hass)


async def import_profile(client: Any, profile: Profile, *, missing: list[str] | None = None) -> str:
    """Import one profile and make it active, as the panel's Profiles view does."""
    result = await call(
        client,
        "profiles/import",
        yaml=dump_profile(profile),
        # E38 refuses a file naming devices this network does not have, and node 13 is
        # exactly that. Saying so is how a swap begins: see `refuse_unknown_devices`.
        allow_missing_devices=True,
    )
    profile_id: str = result["profile"]["id"]
    assert result["missing_devices"] == ([old_identity()] if missing is None else missing)
    await call(client, "profiles/activate", profile_id=profile_id)
    return profile_id


@pytest.fixture
async def imported(client: Any) -> str:
    """The S7 profile, imported and active."""
    return await import_profile(client, imported_profile())


def old_identity() -> str:
    """Return the address the imported profile knows the dead device by."""
    return handle(CEILING_LIGHTS_OLD).identity


def group_of(driver: FakeDriver, node_id: int, group: int) -> list[int]:
    """Return what one association group of a node holds right now, as node ids."""
    associations = driver.controller.get_all_associations_sync(node_id)
    return [address.node_id for address in associations[node_id][0].get(group, [])]


async def preview(client: Any, devices: dict[int, dr.DeviceEntry], **extra: Any) -> Any:
    """Return the swap preview for node 13 to node 42."""
    return await call(
        client,
        "swap/preview",
        old_identity=old_identity(),
        new_device_id=devices[REPLACEMENT].id,
        **extra,
    )


# --------------------------------------------------------------------------------------
# S7, in the order a person does it
# --------------------------------------------------------------------------------------


async def test_s7_the_panel_offers_the_device_that_is_gone_even_with_no_lookalike(
    hass: HomeAssistant, client: Any, imported: str
) -> None:
    """The swap screen lists node 13, and nothing volunteers it, and both are right.

    This is where S7 diverges from FR-S3 as written, on this network's own facts. FR-S3
    offers a swap when a device disappears **and a device with the same fingerprint
    appears**. Node 13 was an Inovelli VZW31-SN and node 42 is a VZW32-SN, so no same-model
    device is waiting and the unprompted offer correctly stays quiet: volunteering a swap
    because some unused switch happens to be on the network is how a Repairs panel becomes
    something people dismiss.

    What the user gets instead is E19's report that rules name a device that is not there,
    and a swap screen that lists it as soon as they open one. The candidate list is empty,
    so they pick the replacement themselves, which is what the wizard asks for whenever
    there is more than one anyway.
    """
    candidates = await call(client, "swap/candidates")
    issues = {
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith(("swap_", "rules_missing"))
    }

    assert [found["old"]["identity"] for found in candidates["replacements"]] == [old_identity()]
    assert candidates["replacements"][0]["candidates"] == []
    assert candidates["replacements"][0]["changed_in_place"] is False
    assert sorted(candidates["replacements"][0]["rule_ids"]) == [
        "bedroom-drives-ceiling",
        "ceiling-paddle",
    ]
    assert issues == {"rules_missing_devices"}, "a swap with no candidate was volunteered"


async def test_a_verify_of_the_whole_network_is_what_notices_a_device_has_left(
    hass: HomeAssistant,
    client: Any,
    device_links_entry: MockConfigEntry,
    zwave_driver: FakeDriver,
) -> None:
    """The path a person actually walks when a node has been excluded.

    A per-device read cannot tell "gone" from "did not answer": it asks about a device we
    already know of. Asking the backend for its listing again is the only thing that can,
    and an unscoped Verify is where that belongs, because it is what somebody presses when
    they think the picture is out of date. A scoped one names devices it already knows, so
    it asks a narrower question and does not re-list.
    """
    from tests.factories import HOME_ID  # noqa: PLC0415

    retired = f"zwave:{HOME_ID}:39"
    await import_profile(
        client,
        Profile(
            id="bedroom",
            name="Bedroom",
            rules=(
                Rule(
                    id="gone",
                    name="A retired ZEN35 drives the lights",
                    template=Template.REMOTE,
                    backend=BackendId.ZWAVE,
                    source=RuleSource(device=handle(39), endpoint=0, emitter_id="g2"),
                    targets=(RuleTarget(device=handle(LIGHT), endpoint=None),),
                    features=DIMMING,
                ),
            ),
        ),
        missing=[],
    )
    zwave_driver.controller.nodes.pop(39)

    # A scoped verify reads one device deeply and leaves the listing alone.
    await call(client, "verify", rule_ids=["gone"])
    assert await call(client, "swap/candidates") == {"replacements": []}

    await call(client, "verify")

    candidates = await call(client, "swap/candidates")
    assert [found["old"]["identity"] for found in candidates["replacements"]] == [retired]
    assert device_links_entry.runtime_data.coordinator.handle_for(retired) is None


async def test_a_device_with_a_lookalike_waiting_is_offered_unprompted(
    hass: HomeAssistant,
    client: Any,
    device_links_entry: MockConfigEntry,
    zwave_driver: FakeDriver,
) -> None:
    """FR-S3's own case, which this network does not supply and a house with two does.

    Node 30 is a second ZEN35, unused by any rule and the same model as node 39. Retire
    node 39 from the network and node 30 is exactly the "device with the same fingerprint
    appears" FR-S3 is written about, so the swap is offered without being asked for.
    """
    from tests.factories import HOME_ID  # noqa: PLC0415

    retired = f"zwave:{HOME_ID}:39"
    # Node 39 leaves the network, and the driver stops listing it, which is what a device
    # that has been excluded really looks like. Not merely unreachable: that is the case
    # this must stay silent about, and `tests/test_swap.py` pins it.
    zwave_driver.controller.nodes.pop(39)
    await device_links_entry.runtime_data.coordinator.async_refresh()

    profile = Profile(
        id="bedroom",
        name="Bedroom",
        rules=(
            Rule(
                id="gone",
                name="A retired ZEN35 drives the lights",
                template=Template.REMOTE,
                backend=BackendId.ZWAVE,
                source=RuleSource(device=handle(39), endpoint=0, emitter_id="g2"),
                targets=(RuleTarget(device=handle(LIGHT), endpoint=None),),
                features=DIMMING,
            ),
        ),
    )
    await import_profile(client, profile, missing=[retired])

    candidates = await call(client, "swap/candidates")
    issues = {
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith(("swap_", "rules_missing"))
    }

    assert [found["old"]["identity"] for found in candidates["replacements"]] == [retired]
    # Both ZEN35s that nothing else claims, in address order, because a wizard picking
    # between two identical switches for the user is picking the wrong one half the time.
    assert [candidate["identity"] for candidate in candidates["replacements"][0]["candidates"]] == [
        handle(30).identity,
        handle(36).identity,
    ]
    assert issues == {f"swap_candidate_{retired}"}, "one device, told about twice"


async def test_s7_the_preview_shows_the_whole_swap_and_writes_nothing(
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """The safety property: everything a swap would do, before any of it is done.

    Both rules, before and after, the control mapping with the reason it was pre-filled,
    what would be lost (nothing here) and the full plan. And the devices are untouched
    afterwards, which is what makes this a preview rather than a description of the past.
    """
    before = {group: group_of(zwave_driver, REPLACEMENT, group) for group in PADDLE_GROUPS}

    result = await preview(client, zwave_js_devices)

    proposal = result["proposal"]
    assert proposal["old"]["identity"] == old_identity()
    assert proposal["new"]["identity"] == handle(REPLACEMENT).identity
    # S7's "maps emitters automatically", by the control's id rather than by the model.
    assert proposal["same_model"] is False
    assert [
        (m["old_emitter_id"], m["new_emitter_id"], m["basis"]) for m in proposal["mappings"]
    ] == [("paddle", "paddle", "same_emitter_id")]
    assert proposal["unmapped"] == []
    assert proposal["is_applicable"] is True
    assert proposal["is_lossy"] is False
    # Both rules, source side and target side, each carried in full rather than summarised.
    assert {rewrite["rule_id"] for rewrite in proposal["rewrites"]} == {
        "ceiling-paddle",
        "bedroom-drives-ceiling",
    }
    rewrites = {rewrite["rule_id"]: rewrite for rewrite in proposal["rewrites"]}
    assert rewrites["ceiling-paddle"]["after"]["source"]["device"] == handle(REPLACEMENT).identity
    assert rewrites["bedroom-drives-ceiling"]["after"]["targets"] == [
        {"device": handle(REPLACEMENT).identity, "endpoint": None}
    ]
    # S7's "marks the old device's links as unreachable".
    assert result["old_listed"] is False
    assert result["old_reachable"] is False
    # And nothing was written.
    assert {group: group_of(zwave_driver, REPLACEMENT, group) for group in PADDLE_GROUPS} == before


async def test_s7_the_preview_plans_the_links_on_the_replacement(
    client: Any, imported: str, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """S7's "plans links on 42": the paddle's three groups, plus the button that drives it."""
    result = await preview(client, zwave_js_devices)

    adds = {
        (item["link"]["source"]["identity"], item["link"]["emitter_group"])
        for device in result["plan"]["devices"]
        for item in device["add"]
    }

    assert (handle(REPLACEMENT).identity, "2") in adds
    assert (handle(REPLACEMENT).identity, "3") in adds
    assert (handle(REPLACEMENT).identity, "4") in adds
    assert (handle(CONTROLLER).identity, "5") in adds, "the rule that drives it moved too"
    assert not result["plan"]["counts"]["blocked"]
    # Nothing is planned against the device that is gone: it cannot be reached, so its
    # entries cannot be removed and the plan does not pretend otherwise.
    assert old_identity() not in {device["identity"] for device in result["plan"]["devices"]}


async def test_s7_applying_rewrites_the_rules_and_writes_the_links(
    hass: HomeAssistant,
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """The whole of S7: apply, then verify, then read the devices themselves."""
    result = await preview(client, zwave_js_devices)

    applied = await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )
    await hass.async_block_till_done()

    assert sorted(applied["rules_rewritten"]) == ["bedroom-drives-ceiling", "ceiling-paddle"]
    # The rules now name the replacement, and are stored that way.
    stored = await call(client, "profiles/get", profile_id=imported)
    rules = {row["rule"]["id"]: row["rule"] for row in stored["rules"]}
    assert rules["ceiling-paddle"]["source"]["device"] == handle(REPLACEMENT).identity
    assert rules["bedroom-drives-ceiling"]["targets"][0]["device"] == handle(REPLACEMENT).identity
    # The device really holds the links, read out of the fake driver's own tables.
    for group in PADDLE_GROUPS:
        assert group_of(zwave_driver, REPLACEMENT, group) == [LIGHT], f"group {group}"
    assert REPLACEMENT in group_of(zwave_driver, CONTROLLER, 5)
    # And a verify agrees, which is S7's last word.
    verified = await call(client, "verify")
    assert verified["rules"] == {
        "bedroom-drives-ceiling": "in_sync",
        "ceiling-paddle": "in_sync",
    }


async def test_s7_the_swap_stops_being_offered_once_it_is_done(
    hass: HomeAssistant,
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """An issue that outlives its cause teaches people to ignore the Repairs panel."""
    result = await preview(client, zwave_js_devices)
    await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )
    await hass.async_block_till_done()

    candidates = await call(client, "swap/candidates")
    issues = {
        issue_id
        for (domain, issue_id) in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith("swap_")
    }

    assert candidates["replacements"] == []
    assert issues == set()


async def test_s7_a_second_plan_after_the_swap_is_empty(
    hass: HomeAssistant,
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """Convergence, which is the property that says the swap really finished."""
    result = await preview(client, zwave_js_devices)
    await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )
    await hass.async_block_till_done()

    plan = await call(client, "plan")

    assert plan["is_empty"], plan["devices"]


async def test_a_swap_plans_nothing_for_a_rule_it_is_not_about(
    hass: HomeAssistant,
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """ "Swap this switch" must not also do an unrelated rule's outstanding work.

    A third rule, on devices the swap does not touch, has never been applied and so has
    work waiting. The swap's plan is scoped to the devices it writes to, so that work is
    not in it, and pressing Apply on a swap does exactly the swap. The devices themselves
    are the assertion, because a plan that merely did not list it would still write it.
    """
    await call(
        client,
        "rules/upsert",
        profile_id=imported,
        rule=rule_to_data(
            Rule(
                id="elsewhere",
                name="Hallway scene drives the lobby",
                template=Template.SCENE_BUTTON,
                backend=BackendId.ZWAVE,
                source=RuleSource(device=handle(30), endpoint=0, emitter_id="g5"),
                targets=(RuleTarget(device=handle(35), endpoint=None),),
                features=frozenset({Feature.ON_OFF}),
            )
        ),
    )
    await hass.async_block_till_done()

    result = await preview(client, zwave_js_devices)
    await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )
    await hass.async_block_till_done()

    assert handle(30).identity not in {device["identity"] for device in result["plan"]["devices"]}
    assert group_of(zwave_driver, 30, 5) == [], "the swap applied a rule it was not about"
    # And the swap itself still happened.
    assert group_of(zwave_driver, REPLACEMENT, 2) == [LIGHT]


# --------------------------------------------------------------------------------------
# What the swap refuses to do
# --------------------------------------------------------------------------------------


async def test_a_swap_of_a_disabled_rule_rewrites_it_and_writes_nothing(
    hass: HomeAssistant, client: Any, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """Disabling is not deleting (FR-R5), so the intent moves even when no link does.

    A disabled rule contributes nothing to the desired state, and the device it named is
    gone, so there is nothing on any radio for this swap to change. The rule still has to
    follow the hardware: re-enabling it later should write links to the switch that is in
    the wall, not to the one that was taken out of it.
    """
    profile = imported_profile()
    await import_profile(
        client,
        replace(profile, rules=tuple(rule.with_enabled(False) for rule in profile.rules)),
    )

    result = await preview(client, zwave_js_devices)
    applied = await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )
    await hass.async_block_till_done()

    assert result["plan"]["is_empty"]
    assert applied["status"] == "nothing_to_do"
    assert applied["job_id"] is None
    assert sorted(applied["rules_rewritten"]) == ["bedroom-drives-ceiling", "ceiling-paddle"]
    stored = await call(client, "profiles/get", profile_id="ceiling")
    rules = {row["rule"]["id"]: row["rule"] for row in stored["rules"]}
    assert rules["ceiling-paddle"]["source"]["device"] == handle(REPLACEMENT).identity
    assert rules["ceiling-paddle"]["enabled"] is False


async def test_a_swap_cannot_be_applied_without_a_plan_somebody_looked_at(
    client: Any, imported: str, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """There is no "just do it" path: a token can only come from a preview (FR-A3)."""
    error = await refused(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token="not-a-token",
    )

    assert error["translation_key"] == "plan_out_of_date"


async def test_a_swap_that_would_lose_work_is_refused_until_it_is_acknowledged(
    hass: HomeAssistant,
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """A partial swap must never be a silent one.

    The config button on a VZW32-SN carries on/off and nothing else, so mapping the old
    paddle onto it loses dimming. The preview says so, and the apply refuses until the
    caller says it has seen that: `accept_lossy` is not a formality, it is the difference
    between a user choosing to lose dimming and a user discovering it a week later.
    """
    result = await preview(client, zwave_js_devices, mapping={"paddle": "g7"})

    assert result["proposal"]["is_lossy"] is True
    lost = {
        loss["placeholders"]["feature"]
        for rewrite in result["proposal"]["rewrites"]
        for loss in rewrite["losses"]
    }
    assert lost == {"level_set", "level_hold"}

    error = await refused(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        mapping={"paddle": "g7"},
        plan_token=result["plan"]["token"],
    )

    assert error["translation_key"] == "swap_would_lose_work"
    assert group_of(zwave_driver, REPLACEMENT, 7) == [], "a refused swap wrote something"

    accepted = await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        mapping={"paddle": "g7"},
        plan_token=result["plan"]["token"],
        accept_lossy=True,
    )
    await hass.async_block_till_done()

    assert accepted["status"] == "running"
    assert group_of(zwave_driver, REPLACEMENT, 7) == [LIGHT]


async def test_a_swap_whose_controls_are_not_all_answered_is_refused(
    client: Any, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """FR-S2's mapping step is a question, and an unanswered question is not a default."""
    # On/off only, because the features are the second pre-fill: a rule asking for dimming
    # names the paddle uniquely and would be mapped for the user. Four controls on a
    # VZW32-SN can do on/off, and picking between them is the user's job (FR-S2).
    await import_profile(
        client,
        imported_profile(paddle="unknown_button", features=frozenset({Feature.ON_OFF})),
    )

    result = await preview(client, zwave_js_devices)
    error = await refused(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )

    assert result["proposal"]["unmapped"] == ["unknown_button"]
    assert result["proposal"]["is_applicable"] is False
    assert error["translation_key"] == "swap_mapping_incomplete"


async def test_a_device_no_rule_names_cannot_be_swapped(
    client: Any, imported: str, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """The old device is named by address, so what keeps it honest is that a rule names it."""
    error = await refused(
        client,
        "swap/preview",
        old_identity="zwave:9999:1",
        new_device_id=zwave_js_devices[REPLACEMENT].id,
    )

    assert error["translation_key"] == "swap_unknown_old_device"


async def test_a_swap_onto_a_device_that_is_already_the_one_named_is_refused(
    client: Any, imported: str, zwave_js_devices: dict[int, dr.DeviceEntry]
) -> None:
    """Nothing to do, and a plan of nothing would read as a swap that worked."""
    result = await call(
        client,
        "swap/preview",
        old_identity=handle(LIGHT).identity,
        new_device_id=zwave_js_devices[LIGHT].id,
    )
    error = await refused(
        client,
        "swap/apply",
        old_identity=handle(LIGHT).identity,
        new_device_id=zwave_js_devices[LIGHT].id,
        plan_token=result["plan"]["token"],
    )

    assert [error["translation_key"] for error in result["proposal"]["errors"]] == [
        "swap_same_device"
    ]
    assert error["translation_key"] == "swap_not_possible"


async def test_a_swap_is_refused_while_a_job_is_already_running(
    hass: HomeAssistant,
    client: Any,
    imported: str,
    zwave_js_devices: dict[int, dr.DeviceEntry],
    zwave_driver: FakeDriver,
) -> None:
    """Two applies driving one mesh at once is the thing E16 exists to prevent."""
    zwave_driver.controller.refresh_delay_seconds = 0.3
    result = await preview(client, zwave_js_devices)
    await call(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )

    error = await refused(
        client,
        "swap/apply",
        old_identity=old_identity(),
        new_device_id=zwave_js_devices[REPLACEMENT].id,
        plan_token=result["plan"]["token"],
    )
    await hass.async_block_till_done()

    assert error["translation_key"] == "job_running"


async def test_a_swap_with_no_profile_active_is_refused(
    client: Any, device_links_entry: MockConfigEntry
) -> None:
    """Nothing is active, so there are no rules to rewrite and nothing to name a device."""
    assert device_links_entry.state is ConfigEntryState.LOADED

    error = await refused(
        client, "swap/preview", old_identity=old_identity(), new_device_id="anything"
    )

    assert error["translation_key"] == "no_active_profile"
    assert await call(client, "swap/candidates") == {"replacements": []}
