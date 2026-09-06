"""Profile diff: the two questions it answers, and why one answer is not enough.

FR-P4. "What did I change" and "what will be written" are different questions with
different answers, and a comparison that offered only one of them would be misleading in
opposite directions: a rename would read as a change to somebody's house, or a device swap
underneath an untouched rule would read as no change at all.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.device_links.diff import (
    ChangeKind,
    diff_against_links,
    diff_profiles,
)
from custom_components.device_links.models import Feature, Profile
from tests.conftest import CONTROLLER, LOBBY, MAIN_LIGHTS, a_profile, a_rule, activate
from tests.factories import capabilities_for, handle, link, observed

CAPABILITIES = capabilities_for(CONTROLLER, MAIN_LIGHTS, LOBBY)


def compiled_links(profile: Profile) -> list[Any]:
    """Return every link a profile's enabled rules would write."""
    from custom_components.device_links.compiler import compile_rule  # noqa: PLC0415

    return [link for rule in profile.rules for link in compile_rule(rule, CAPABILITIES).links]


# --------------------------------------------------------------------------------------
# Profile against profile
# --------------------------------------------------------------------------------------


def test_two_copies_of_one_profile_differ_in_nothing() -> None:
    """The answer a user needs most often, and the one an over-eager diff gets wrong."""
    profile = a_profile()

    diff = diff_profiles(profile, profile, CAPABILITIES)

    assert diff.is_empty
    assert {rule.kind for rule in diff.rules} == {ChangeKind.UNCHANGED}


def test_a_rule_only_the_right_side_has_is_added_and_carries_its_links() -> None:
    """What a user is moving towards, said as what it would put on their devices."""
    before = a_profile()
    after = a_profile(*before.rules, a_rule("lobby", emitter_id="g5", target_node=LOBBY))

    diff = diff_profiles(before, after, CAPABILITIES)

    added = [rule for rule in diff.rules if rule.kind is ChangeKind.ADDED]
    assert [rule.rule_id for rule in added] == ["lobby"]
    assert added[0].links_added
    assert not added[0].links_removed
    assert not diff.is_empty


def test_a_rule_only_the_left_side_has_is_removed_with_the_links_that_would_go() -> None:
    """The other direction, which is the one somebody restoring an old file is reading."""
    before = a_profile(a_rule(), a_rule("lobby", emitter_id="g5", target_node=LOBBY))
    after = a_profile(a_rule())

    diff = diff_profiles(before, after, CAPABILITIES)

    removed = [rule for rule in diff.rules if rule.kind is ChangeKind.REMOVED]
    assert [rule.rule_id for rule in removed] == ["lobby"]
    assert removed[0].links_removed
    assert [change.kind for change in diff.links].count(ChangeKind.REMOVED) == len(
        removed[0].links_removed
    )


def test_a_renamed_rule_is_changed_and_writes_nothing_new() -> None:
    """The case that makes both levels necessary: a change to a profile and not to a house."""
    before = a_profile()
    after = a_profile(replace(before.rules[0], name="A better name"))

    diff = diff_profiles(before, after, CAPABILITIES)

    (changed,) = [rule for rule in diff.rules if rule.kind is ChangeKind.CHANGED]
    assert changed.fields == ("name",)
    assert changed.writes_nothing_new
    assert changed.links_unchanged == len(compiled_links(after))
    # And the link level agrees: nothing at all would be written.
    assert all(change.kind is ChangeKind.UNCHANGED for change in diff.links)
    assert not diff.is_empty


def test_a_rule_whose_features_changed_names_the_field_and_the_links() -> None:
    """What a user changed, and what that costs, in one row."""
    before = a_profile()
    after = a_profile(replace(before.rules[0], features=frozenset({Feature.ON_OFF})))

    diff = diff_profiles(before, after, CAPABILITIES)

    (changed,) = [rule for rule in diff.rules if rule.kind is ChangeKind.CHANGED]
    assert changed.fields == ("features",)
    assert not changed.writes_nothing_new
    assert changed.links_removed
    assert not changed.links_added


def test_a_disabled_rule_writes_nothing_on_either_side() -> None:
    """A diff is about what would be written, and a rule that is off writes nothing."""
    before = a_profile(a_rule().with_enabled(False))
    after = a_profile(a_rule(name="Renamed").with_enabled(False))

    diff = diff_profiles(before, after, CAPABILITIES)

    (changed,) = diff.rules
    assert changed.kind is ChangeKind.CHANGED
    assert changed.writes_nothing_new
    assert diff.links == ()


def test_the_rules_are_listed_in_the_right_hand_side_order_then_the_leftovers() -> None:
    """The right-hand side is what the user is reading; what would go comes after."""
    before = a_profile(a_rule("gone"), a_rule("kept"))
    after = a_profile(a_rule("kept"), a_rule("new"))

    diff = diff_profiles(before, after, CAPABILITIES)

    assert [rule.rule_id for rule in diff.rules] == ["kept", "new", "gone"]


def test_the_counts_add_up_to_what_is_in_the_lists() -> None:
    """The summary a user reads before opening anything, derived once rather than twice."""
    before = a_profile(a_rule("gone"))
    after = a_profile(a_rule("new", emitter_id="g5", target_node=LOBBY))

    counts = diff_profiles(before, after, CAPABILITIES).counts()

    assert counts["rules_added"] == counts["rules_removed"] == 1
    assert counts["rules_changed"] == counts["rules_unchanged"] == 0
    assert counts["links_added"] > 0
    assert counts["links_removed"] > 0


# --------------------------------------------------------------------------------------
# Profile against a snapshot
# --------------------------------------------------------------------------------------


def test_a_snapshot_is_compared_only_over_the_devices_it_covers() -> None:
    """A device the snapshot never recorded is not a device it says was empty."""
    profile = a_profile(a_rule(), a_rule("lobby", emitter_id="g5", target_node=LOBBY))
    covered = handle(CONTROLLER).identity

    diff = diff_against_links(profile, [], CAPABILITIES, devices=[covered])

    assert diff.devices == (covered,)
    assert diff.rules == ()
    assert {change.kind for change in diff.links} == {ChangeKind.ADDED}
    assert all(change.link.source.identity == covered for change in diff.links)


def test_a_snapshot_that_holds_what_the_profile_wants_differs_in_nothing() -> None:
    """The ordinary answer after an apply: the devices hold what the profile asked for."""
    profile = a_profile()
    recorded = compiled_links(profile)

    diff = diff_against_links(
        profile, recorded, CAPABILITIES, devices=[handle(CONTROLLER).identity]
    )

    assert diff.is_empty


def test_a_link_the_snapshot_holds_and_the_profile_does_not_reads_as_removed() -> None:
    """Restoring the snapshot would put this back, which is the whole question being asked."""
    profile = a_profile()
    stray = observed(link(CONTROLLER, "g7", LOBBY, Feature.ON_OFF), rule_id=None)

    diff = diff_against_links(
        profile,
        [*compiled_links(profile), stray],
        CAPABILITIES,
        devices=[handle(CONTROLLER).identity],
    )

    removed = [change for change in diff.links if change.kind is ChangeKind.REMOVED]
    assert [change.link.fingerprint for change in removed] == [stray.fingerprint]


# --------------------------------------------------------------------------------------
# Through the API, where a user meets it
# --------------------------------------------------------------------------------------


@pytest.fixture
async def client(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, device_links_entry: MockConfigEntry
) -> Any:
    """An admin connection to an integration holding two profiles."""
    activate(
        device_links_entry,
        a_profile(a_rule()),
        a_profile(a_rule(), a_rule("lobby", emitter_id="g5", target_node=LOBBY), profile_id="big"),
    )
    await hass.async_block_till_done()
    return await hass_ws_client(hass)


async def call(client: Any, command: str, **data: Any) -> Any:
    """Send one command and return its result, failing loudly if it was refused."""
    await client.send_json_auto_id({"type": f"device_links/{command}", **data})
    message = await client.receive_json()
    assert message["success"], message
    return message["result"]


async def refused(client: Any, command: str, **data: Any) -> Any:
    """Send one command and return the error it was refused with."""
    await client.send_json_auto_id({"type": f"device_links/{command}", **data})
    message = await client.receive_json()
    assert not message["success"], message
    return message["error"]


async def test_the_command_compares_two_profiles(client: Any) -> None:
    """FR-P4's first half, over the wire the panel really uses."""
    result = await call(client, "profiles/diff", profile_id="bedroom", other_profile_id="big")

    assert not result["is_empty"]
    assert result["counts"]["rules_added"] == 1
    assert [rule["rule_id"] for rule in result["rules"] if rule["kind"] == "added"] == ["lobby"]


async def test_the_command_compares_a_profile_with_a_snapshot(
    hass: HomeAssistant, client: Any
) -> None:
    """FR-P4's second half. The snapshot comes from a real apply, as it always would."""
    plan = await call(client, "plan")
    await call(client, "apply", plan_token=plan["token"])
    await hass.async_block_till_done()
    snapshots = (await call(client, "snapshots/list"))["snapshots"]
    assert snapshots, "the apply recorded no snapshot, so nothing was compared"

    result = await call(
        client, "profiles/diff", profile_id="bedroom", snapshot_id=snapshots[-1]["id"]
    )

    assert result["rules"] == []
    assert result["devices"], "a snapshot comparison has to say which devices it speaks for"


async def test_naming_neither_side_or_both_is_refused_rather_than_guessed(client: Any) -> None:
    """The two comparisons answer different questions, so one of them has to be chosen."""
    neither = await refused(client, "profiles/diff", profile_id="bedroom")
    both = await refused(
        client,
        "profiles/diff",
        profile_id="bedroom",
        other_profile_id="big",
        snapshot_id="whatever",
    )

    assert neither["translation_key"] == both["translation_key"] == "diff_needs_one_other_side"


async def test_a_profile_that_does_not_exist_is_refused_by_name(client: Any) -> None:
    """The same refusal every other command that names a profile gives."""
    error = await refused(client, "profiles/diff", profile_id="bedroom", other_profile_id="nothing")

    assert error["translation_key"] == "unknown_profile"


async def test_a_snapshot_that_does_not_exist_is_refused_by_name(client: Any) -> None:
    """A stale id from a listing somebody left open is a refusal, not an empty diff."""
    error = await refused(client, "profiles/diff", profile_id="bedroom", snapshot_id="never-taken")

    assert error["translation_key"] == "unknown_snapshot"
