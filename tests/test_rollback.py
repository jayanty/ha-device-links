"""Rollback: putting a snapshot's devices back as they were, as a plan somebody confirms.

FR-P3, and PRD scenario S10's last clause. The executor already takes a snapshot before
every apply and caps them at 20; this is the other half, and the decision that shapes it is
what a rollback does about links that have appeared since the snapshot was taken.

**It really rolls back.** A snapshot is taken *before* an apply, so undoing that apply is
what somebody asking for one usually means, and a rollback that only ever added things back
would do nothing at all in exactly that case. So it removes as well as adds. What must never
happen is a removal nobody saw, and nothing here can produce one: every removal is in the
plan, on the device it is about, and the plan is confirmed by token like every other write
in this product.

**The removals a rule will undo are named separately.** A rollback restores devices and
leaves the rules alone, so a link an enabled rule still asks for is removed now, reads as
drift, and comes back the next time that rule is applied. `returns_on_next_apply` says which
those are, so a user who wants them gone for good disables the rule first rather than
finding out afterwards.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from zwave_js_server.model.association import AssociationAddress

from custom_components.device_links.yaml_io import rule_to_data
from tests.conftest import CONTROLLER, LOBBY, MAIN_LIGHTS, a_profile, a_rule, activate
from tests.fakes.zwave import FakeDriver

# The rule the fixtures start from drives node 37 off node 36's main button, which is
# association groups 2, 3 and 4 on a ZEN35.
PADDLE_GROUPS = (2, 3, 4)


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


async def refresh(entry: MockConfigEntry) -> None:
    """Re-read every device, as the debounced subscription does after somebody else writes.

    Explicit rather than waited for: a test that slept out the debounce window would be a
    test about timing.
    """
    await entry.runtime_data.coordinator.async_refresh()


async def unlink(driver: FakeDriver, node_id: int, group: int, target: int) -> None:
    """Take one association off a node behind Device Links's back, as a user would.

    Which is one of the two reasons a rollback exists: somebody edits a group in Z-Wave JS
    UI, or an apply half fails, and what the devices held before is the only record of it.
    """
    controller = driver.controller
    await controller.async_remove_associations(
        AssociationAddress(controller, node_id=node_id),
        group,
        [AssociationAddress(controller, node_id=target)],
    )


async def link(driver: FakeDriver, node_id: int, group: int, target: int) -> None:
    """Add one association behind Device Links's back, which makes it unmanaged."""
    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=node_id),
        group,
        [AssociationAddress(controller, node_id=target)],
    )


def group_of(driver: FakeDriver, node_id: int, group: int) -> list[int]:
    """Return what one association group of a node holds right now, as node ids."""
    associations = driver.controller.get_all_associations_sync(node_id)
    return [address.node_id for address in associations[node_id][0].get(group, [])]


@pytest.fixture
async def client(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, device_links_entry: MockConfigEntry
) -> Any:
    """An admin connection to a set-up integration over the Stage 0 fake network."""
    return await hass_ws_client(hass)


async def apply_everything(hass: HomeAssistant, client: Any) -> str:
    """Plan and apply the active profile, and return the snapshot that was taken first.

    A snapshot's id is its job's id (`executor._take_snapshot`), which is what lets the
    Activity view offer a rollback beside the job it belongs to.
    """
    plan = await call(client, "plan")
    started = await call(client, "apply", plan_token=plan["token"])
    await hass.async_block_till_done()
    return str(started["job_id"])


@pytest.fixture
async def applied(hass: HomeAssistant, client: Any, device_links_entry: MockConfigEntry) -> str:
    """One rule, applied, so there is a pre-apply snapshot of a device with nothing on it.

    The canonical case: the snapshot holds the paddle's groups as they were, which is
    empty, and rolling back to it takes the apply off again.
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    return await apply_everything(hass, client)


# --------------------------------------------------------------------------------------
# Nothing is written without a plan somebody looked at
# --------------------------------------------------------------------------------------


async def test_a_rollback_with_no_token_shows_the_plan_and_writes_nothing(
    client: Any, applied: str, zwave_driver: FakeDriver
) -> None:
    """The safe direction is the default: forgetting the token gets a preview."""
    result = await call(client, "snapshots/rollback", snapshot_id=applied)

    assert result["job_id"] is None
    assert result["status"] == "preview"
    assert result["plan"]["counts"]["remove"] == len(PADDLE_GROUPS)
    assert group_of(zwave_driver, CONTROLLER, 2) == [MAIN_LIGHTS], "a preview wrote to a device"


async def test_a_stale_token_is_refused_rather_than_applied(
    client: Any, applied: str, zwave_driver: FakeDriver
) -> None:
    """FR-A3 holds here too: applying a plan nobody saw is the thing it prevents."""
    error = await refused(
        client, "snapshots/rollback", snapshot_id=applied, plan_token="not-a-token"
    )

    assert error["translation_key"] == "plan_out_of_date"
    assert group_of(zwave_driver, CONTROLLER, 2) == [MAIN_LIGHTS], "a refusal wrote something"


async def test_a_rollback_is_refused_while_a_job_is_already_running(
    hass: HomeAssistant, client: Any, applied: str, zwave_driver: FakeDriver
) -> None:
    """Two applies driving one mesh at once is what E16 exists to prevent."""
    zwave_driver.controller.refresh_delay_seconds = 0.3
    preview = await call(client, "snapshots/rollback", snapshot_id=applied)
    await call(
        client, "snapshots/rollback", snapshot_id=applied, plan_token=preview["plan"]["token"]
    )

    error = await refused(
        client, "snapshots/rollback", snapshot_id=applied, plan_token=preview["plan"]["token"]
    )
    await hass.async_block_till_done()

    assert error["translation_key"] == "job_running"


async def test_a_snapshot_that_is_no_longer_kept_is_refused(client: Any, applied: str) -> None:
    """Only the last 20 are kept, so an id from an old Activity view can be gone."""
    error = await refused(client, "snapshots/rollback", snapshot_id="not-a-snapshot")

    assert error["translation_key"] == "unknown_snapshot"


# --------------------------------------------------------------------------------------
# What a rollback puts back, and what it takes off
# --------------------------------------------------------------------------------------


async def test_a_rollback_undoes_the_apply_the_snapshot_was_taken_before(
    hass: HomeAssistant, client: Any, applied: str, zwave_driver: FakeDriver
) -> None:
    """PRD scenario S10's last clause, and the case a rollback is usually asked for."""
    preview = await call(client, "snapshots/rollback", snapshot_id=applied)
    result = await call(
        client, "snapshots/rollback", snapshot_id=applied, plan_token=preview["plan"]["token"]
    )
    await hass.async_block_till_done()

    # Started in a background task, for the reason `apply` gives: a rollback can be a whole
    # house, and awaiting it in the command would tie writes that are already reaching a
    # mesh to the life of a browser tab.
    assert result["status"] == "running"
    assert result["job_id"] is not None
    for group in PADDLE_GROUPS:
        assert group_of(zwave_driver, CONTROLLER, group) == [], f"group {group}"
    # And the job is in the history, which is how the Activity view finds it afterwards.
    jobs = await call(client, "jobs/list")
    assert result["job_id"] in {job["id"] for job in jobs["jobs"]}


async def test_a_rollback_puts_back_a_link_somebody_took_off_by_hand(
    hass: HomeAssistant,
    client: Any,
    device_links_entry: MockConfigEntry,
    zwave_driver: FakeDriver,
) -> None:
    """The other direction, from a snapshot taken while the links were already there."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    await apply_everything(hass, client)
    # A second apply with nothing to do takes no snapshot, so one more rule is added and
    # applied: that job's snapshot holds the first rule's links, in place and managed.
    await call(
        client,
        "rules/upsert",
        rule=rule_to_data(a_rule("lobby", emitter_id="g5", target_node=LOBBY)),
    )
    await hass.async_block_till_done()
    snapshot_id = await apply_everything(hass, client)

    await unlink(zwave_driver, CONTROLLER, 2, MAIN_LIGHTS)
    await refresh(device_links_entry)
    assert group_of(zwave_driver, CONTROLLER, 2) == []

    preview = await call(client, "snapshots/rollback", snapshot_id=snapshot_id)
    await call(
        client,
        "snapshots/rollback",
        snapshot_id=snapshot_id,
        plan_token=preview["plan"]["token"],
    )
    await hass.async_block_till_done()

    assert preview["plan"]["counts"]["add"] == 1
    assert group_of(zwave_driver, CONTROLLER, 2) == [MAIN_LIGHTS]


async def test_a_rollback_onto_the_state_it_already_describes_does_nothing(
    hass: HomeAssistant, client: Any, applied: str
) -> None:
    """Idempotence: a rollback applied twice is a rollback applied once."""
    preview = await call(client, "snapshots/rollback", snapshot_id=applied)
    await call(
        client, "snapshots/rollback", snapshot_id=applied, plan_token=preview["plan"]["token"]
    )
    await hass.async_block_till_done()

    again = await call(client, "snapshots/rollback", snapshot_id=applied)
    confirmed = await call(
        client, "snapshots/rollback", snapshot_id=applied, plan_token=again["plan"]["token"]
    )

    assert again["plan"]["is_empty"]
    # Confirmed anyway, which has to be answerable rather than a job that writes nothing:
    # a caller cannot know it is empty until it has asked, and the answer says so.
    assert confirmed["status"] == "nothing_to_do"
    assert confirmed["job_id"] is None


# --------------------------------------------------------------------------------------
# What was added since, which is the decision this file is about
# --------------------------------------------------------------------------------------


async def test_a_removal_an_enabled_rule_will_undo_is_named_before_it_is_made(
    hass: HomeAssistant,
    client: Any,
    device_links_entry: MockConfigEntry,
    zwave_driver: FakeDriver,
) -> None:
    """The judgment this file is about: the rollback removes it, and says it will be back.

    The rule that wants the link still exists, so the rollback takes it off, the rule reads
    as drifted, and the next apply writes it again. Everything about that is fine and none
    of it is something to discover afterwards, so it is named per link with the rule that
    owns it, beside the plan, before anything is written.
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    snapshot_id = await apply_everything(hass, client)
    await call(
        client,
        "rules/upsert",
        rule=rule_to_data(a_rule("lobby", emitter_id="g5", target_node=LOBBY)),
    )
    await hass.async_block_till_done()
    await apply_everything(hass, client)
    assert group_of(zwave_driver, CONTROLLER, 5) == [LOBBY]

    result = await call(client, "snapshots/rollback", snapshot_id=snapshot_id)

    returning = result["returns_on_next_apply"]
    assert {entry["rule_id"] for entry in returning} == {"bedroom-main", "lobby"}
    assert {entry["emitter_group"] for entry in returning} == {"2", "3", "4", "5", "6"}
    # Every one of them is a removal in the plan as well, on the device it is about, so
    # nothing here lives only in a side channel.
    removals = {
        item["link"]["fingerprint"]
        for device in result["plan"]["devices"]
        for item in device["remove"]
    }
    assert {entry["fingerprint"] for entry in returning} <= removals


async def test_a_disabled_rules_links_are_removed_for_good_and_not_listed_as_returning(
    hass: HomeAssistant, client: Any, device_links_entry: MockConfigEntry
) -> None:
    """Nothing will re-add them, so the plan's own removal list is the whole story."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    snapshot_id = await apply_everything(hass, client)
    await call(client, "rules/upsert", rule={**rule_to_data(a_rule()), "enabled": False})
    await hass.async_block_till_done()

    result = await call(client, "snapshots/rollback", snapshot_id=snapshot_id)

    assert result["plan"]["counts"]["remove"] == len(PADDLE_GROUPS)
    assert result["returns_on_next_apply"] == []


# --------------------------------------------------------------------------------------
# What a rollback never touches
# --------------------------------------------------------------------------------------


async def test_an_unmanaged_link_is_reported_and_neither_put_back_nor_taken_off(
    client: Any,
    device_links_entry: MockConfigEntry,
    applied: str,
    zwave_driver: FakeDriver,
) -> None:
    """Decision D9 holds here like everywhere: somebody's own association is theirs."""
    await link(zwave_driver, CONTROLLER, 9, LOBBY)
    await refresh(device_links_entry)

    result = await call(client, "snapshots/rollback", snapshot_id=applied)

    unmanaged = [entry for device in result["plan"]["devices"] for entry in device["unmanaged"]]
    assert [entry["emitter_group"] for entry in unmanaged] == ["9"]
    assert not any(
        item["link"]["emitter_group"] == "9"
        for device in result["plan"]["devices"]
        for item in device["remove"]
    )


async def test_a_ticked_unmanaged_link_is_removed_by_a_rollback_like_any_other_plan(
    hass: HomeAssistant,
    client: Any,
    device_links_entry: MockConfigEntry,
    applied: str,
    zwave_driver: FakeDriver,
) -> None:
    """The per-link opt-in is the same one every other plan takes, and it works here too."""
    await link(zwave_driver, CONTROLLER, 9, LOBBY)
    await refresh(device_links_entry)
    listed = await call(client, "snapshots/rollback", snapshot_id=applied)
    fingerprint = next(
        entry["fingerprint"]
        for device in listed["plan"]["devices"]
        for entry in device["unmanaged"]
    )

    preview = await call(
        client, "snapshots/rollback", snapshot_id=applied, remove_unmanaged=[fingerprint]
    )
    await call(
        client,
        "snapshots/rollback",
        snapshot_id=applied,
        remove_unmanaged=[fingerprint],
        plan_token=preview["plan"]["token"],
    )
    await hass.async_block_till_done()

    assert preview["plan"]["counts"]["remove"] == len(PADDLE_GROUPS) + 1
    assert group_of(zwave_driver, CONTROLLER, 9) == []


async def test_a_lifeline_in_a_snapshot_is_never_planned_for_anything(
    client: Any, device_links_entry: MockConfigEntry, applied: str
) -> None:
    """A snapshot holds the whole observed set, lifelines included, and that is deliberate.

    `Snapshot.links` keeps `is_system` for exactly this reason: a rollback that had lost it
    could plan against the entry that is how a device reports to Home Assistant at all
    (CLAUDE.md Section 3 rule 4). It is in the snapshot, it is not in the desired set
    because it is nobody's to manage, and it is in no bucket of the plan.
    """
    stored = next(
        snapshot
        for snapshot in device_links_entry.runtime_data.coordinator.state.snapshots
        if snapshot.id == applied
    )
    lifelines = [entry for entry in stored.links if entry.is_system]

    result = await call(client, "snapshots/rollback", snapshot_id=applied)
    mentioned = {
        item["link"]["fingerprint"]
        for device in result["plan"]["devices"]
        for bucket in ("add", "remove", "blocked", "pending", "set_param")
        for item in device[bucket]
        if item["link"] is not None
    } | {
        entry["fingerprint"]
        for device in result["plan"]["devices"]
        for entry in device["unmanaged"]
    }

    assert lifelines, "the snapshot kept no system link, so this proves nothing"
    assert all(entry.managed_by is None for entry in lifelines)
    assert not {entry.fingerprint for entry in lifelines} & mentioned


async def test_a_device_the_snapshot_covers_that_cannot_be_read_is_named(
    client: Any,
    device_links_entry: MockConfigEntry,
    applied: str,
    zwave_driver: FakeDriver,
) -> None:
    """A rollback onto a device nobody can reach is not one, and must not read as one.

    Nothing is planned for it, which on its own looks exactly like a device with nothing to
    do. Naming the devices the snapshot covers that nobody could read is what tells the two
    apart, and it is the same distinction `Snapshot.devices` exists to make.
    """
    zwave_driver.controller.nodes.pop(CONTROLLER)
    await refresh(device_links_entry)

    result = await call(client, "snapshots/rollback", snapshot_id=applied)

    assert result["plan"]["is_empty"]
    assert result["unreadable_devices"] == [f"zwave:{zwave_driver.controller.home_id}:{CONTROLLER}"]
