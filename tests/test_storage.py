"""Storage: where the user's work lives, and the migration mechanism that protects it.

A migration that loses a profile loses hours of somebody's configuration with no undo, so
the two tests that matter most here are the ones about versions: that a store written by a
newer Home Assistant is refused rather than guessed at, and that the migration chain runs
its steps in order over real data. `STORAGE_VERSION` is 1 and there is nothing to migrate
yet, so the chain is exercised with a synthetic step registered into the real registry: the
mechanism under test is the production one, and only the step is invented.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import storage as ha_storage
import pytest

from custom_components.device_links.const import STORAGE_KEY, STORAGE_VERSION
from custom_components.device_links.models import Backend, Feature, Profile, Rule
from custom_components.device_links.storage import (
    MAX_JOBS,
    MAX_SNAPSHOTS,
    SAVE_DELAY_SECONDS,
    DeviceLinksStore,
    JobLinkResult,
    JobSummary,
    Snapshot,
    StorageSchemaError,
    StoredState,
)
from custom_components.device_links.yaml_io import profile_to_data
from tests.factories import handle, link, observed
from tests.test_yaml_io import _rule


@pytest.fixture(autouse=True)
def _use_storage(hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Every test here reads or writes the store, so mock it for all of them."""
    return hass_storage


@pytest.fixture
def write_count(hass_storage: dict[str, Any]) -> Generator[Callable[[], int]]:
    """Count how many times a store really wrote, on top of the mocked storage.

    Patched and unpatched here rather than through `monkeypatch`, and depending on
    `hass_storage` so this wrapper is installed over that fixture's mock and taken off
    again before it: undoing these two in the wrong order leaves the mock installed on the
    real class and breaks every test that runs afterwards.
    """
    writes = 0
    original = ha_storage.Store._async_write_data

    async def _counted(store: ha_storage.Store[Any], data: dict[str, Any]) -> None:
        nonlocal writes
        writes += 1
        await original(store, data)

    ha_storage.Store._async_write_data = _counted
    yield lambda: writes
    ha_storage.Store._async_write_data = original


def _profile(profile_id: str = "profile-1") -> Profile:
    return Profile(id=profile_id, name="Bedroom", rules=(_rule("rule-1"),))


def _snapshot(index: int) -> Snapshot:
    return Snapshot(
        id=f"snapshot-{index}",
        created_at=f"2026-09-05T12:{index:02d}:00+00:00",
        reason="before_apply",
        links=(observed(link(36, "g2", 38, Feature.ON_OFF), rule_id="rule-1"),),
    )


def _job(index: int) -> JobSummary:
    return JobSummary(
        id=f"job-{index}",
        created_at=f"2026-09-05T12:{index:02d}:00+00:00",
        scope="profile",
        status="completed",
        results=(
            JobLinkResult(
                fingerprint=link(36, "g2", 38, Feature.ON_OFF).fingerprint,
                status="applied",
            ),
        ),
    )


async def test_a_fresh_install_loads_empty_and_writes_nothing(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A first start must not create a file: an empty store is a state, not a save."""
    state = await DeviceLinksStore(hass).async_load()

    assert state == StoredState()
    assert state.active_profile is None
    assert STORAGE_KEY not in hass_storage


async def test_saving_and_loading_round_trips_everything_the_store_holds(
    hass: HomeAssistant,
) -> None:
    """Profiles, the active id, dismissed links, snapshots and job history, all of it."""
    state = StoredState(
        profiles=(_profile(), _profile("profile-2")),
        active_profile_id="profile-2",
        ignored_unmanaged=frozenset({"zwave|a|0|2|zwave|b||on_off"}),
        snapshots=(_snapshot(1),),
        jobs=(_job(1),),
    )
    store = DeviceLinksStore(hass)
    await store.async_save(state)

    assert await DeviceLinksStore(hass).async_load() == state


async def test_the_active_profile_is_the_one_the_id_names(hass: HomeAssistant) -> None:
    state = StoredState(profiles=(_profile(), _profile("profile-2")), active_profile_id="profile-2")

    assert state.active_profile == _profile("profile-2")


async def test_an_active_profile_id_naming_nothing_resolves_to_no_profile(
    hass: HomeAssistant,
) -> None:
    """A dangling id must read as "no active profile", not raise on every access."""
    state = StoredState(profiles=(_profile(),), active_profile_id="deleted")

    assert state.active_profile is None


async def test_an_ignored_unmanaged_link_survives_a_restart(hass: HomeAssistant) -> None:
    """FR-A5: a user who dismissed a link must not see it re-flagged after a restart."""
    dismissed = observed(link(36, "g2", 35, Feature.ON_OFF), rule_id=None).fingerprint
    await DeviceLinksStore(hass).async_save(StoredState(ignored_unmanaged=frozenset({dismissed})))

    assert (await DeviceLinksStore(hass).async_load()).ignored_unmanaged == frozenset({dismissed})


async def test_snapshots_are_capped_and_the_oldest_goes_first(hass: HomeAssistant) -> None:
    """FR-P3 keeps the last 20. Unbounded, this file would grow forever."""
    state = StoredState()
    for index in range(MAX_SNAPSHOTS + 5):
        state = state.with_snapshot(_snapshot(index))

    assert len(state.snapshots) == MAX_SNAPSHOTS
    assert state.snapshots[0].id == "snapshot-5"
    assert state.snapshots[-1].id == f"snapshot-{MAX_SNAPSHOTS + 4}"


async def test_job_summaries_are_capped_at_fifty(hass: HomeAssistant) -> None:
    """PRD Section 8.2. Activity history is useful, not archival."""
    state = StoredState()
    for index in range(MAX_JOBS + 3):
        state = state.with_job(_job(index))

    assert len(state.jobs) == MAX_JOBS
    assert state.jobs[0].id == "job-3"


async def test_saving_is_debounced(hass: HomeAssistant, write_count: Callable[[], int]) -> None:
    """Ten edits in a row are one file write, not ten. A save is not free.

    The delay is shortened rather than mocked, because the mechanism being tested is Home
    Assistant's own delayed save: a fake timer would prove the test's timer works.
    """
    store = DeviceLinksStore(hass, save_delay_seconds=0.05)
    for index in range(10):
        store.async_schedule_save(StoredState(profiles=(_profile(f"profile-{index}"),)))

    assert write_count() == 0

    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    assert write_count() == 1
    assert (await DeviceLinksStore(hass).async_load()).profiles[0].id == "profile-9"


async def test_the_save_delay_is_long_enough_to_coalesce_an_editing_session() -> None:
    """A one second delay would write on every keystroke; a minute would lose real work."""
    assert SAVE_DELAY_SECONDS == 10


async def test_loading_a_current_version_store_does_not_migrate(
    hass: HomeAssistant, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to migrate must mean nothing is touched, not a no-op migration that runs."""
    migrated = False

    def _tripwire(version: int, data: dict[str, Any]) -> dict[str, Any]:
        nonlocal migrated
        migrated = True
        return data

    monkeypatch.setattr("custom_components.device_links.storage._MIGRATIONS", {0: _tripwire})
    hass_storage[STORAGE_KEY] = {
        "version": STORAGE_VERSION,
        "data": {"active_profile_id": "profile-1", "profiles": [profile_to_data(_profile())]},
    }

    state = await DeviceLinksStore(hass).async_load()

    assert not migrated
    assert state.active_profile == _profile()


async def test_a_future_schema_version_is_refused_naming_both_versions(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """E18. A newer file is not guessed at: the integration comes up read-only instead."""
    hass_storage[STORAGE_KEY] = {"version": STORAGE_VERSION + 1, "data": {}}

    with pytest.raises(StorageSchemaError) as error:
        await DeviceLinksStore(hass).async_load()

    assert str(STORAGE_VERSION + 1) in str(error.value)
    assert str(STORAGE_VERSION) in str(error.value)


async def test_the_migration_chain_runs_its_steps_over_real_data(
    hass: HomeAssistant, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first real migration must be an edit to tested code, not a new invention.

    So the chain runner is production code and this test registers one synthetic step into
    it: a version 0 that called the active profile `active`, renamed by its step. What is
    proved is what the first real migration will rely on: the step is handed the stored
    payload, its result is what gets decoded, and the store is written back at the new
    version so the migration happens once rather than on every start.
    """
    seen: list[str] = []

    def _rename_active(version: int, data: dict[str, Any]) -> dict[str, Any]:
        seen.append(f"step from version {version}")
        return {**data, "active_profile_id": data.pop("active")}

    monkeypatch.setattr("custom_components.device_links.storage._MIGRATIONS", {0: _rename_active})
    hass_storage[STORAGE_KEY] = {
        "version": 0,
        "data": {"active": "profile-1", "profiles": [profile_to_data(_profile())]},
    }

    state = await DeviceLinksStore(hass).async_load()

    assert seen == ["step from version 0"]
    assert state.active_profile == _profile()
    assert hass_storage[STORAGE_KEY]["version"] == STORAGE_VERSION
    assert hass_storage[STORAGE_KEY]["data"]["active_profile_id"] == "profile-1"


async def test_a_version_with_no_migration_step_is_refused_rather_than_guessed_at(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """An old version nobody wrote a step for is a bug, and losing the file is not the fix."""
    hass_storage[STORAGE_KEY] = {"version": 0, "data": {"profiles": []}}

    with pytest.raises(StorageSchemaError, match="0"):
        await DeviceLinksStore(hass).async_load()


async def test_stored_data_that_is_not_a_profile_is_refused_with_its_reason(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A hand-edited or truncated .storage file must not come back as half a profile."""
    hass_storage[STORAGE_KEY] = {
        "version": STORAGE_VERSION,
        "data": {"profiles": [{"id": "p", "name": "P", "devices": {}, "rules": [{"id": "r"}]}]},
    }

    with pytest.raises(StorageSchemaError, match="'r'"):
        await DeviceLinksStore(hass).async_load()


async def test_a_snapshot_keeps_what_the_device_held_before_the_apply(
    hass: HomeAssistant,
) -> None:
    """Rollback re-applies a snapshot's links, so ownership and system flags must survive."""
    system = observed(link(36, "g1", 1, Feature.STATUS_REPORT), rule_id=None, system=True)
    mine = observed(link(36, "g2", 38, Feature.ON_OFF), rule_id="rule-1")
    snapshot = Snapshot(
        id="s1",
        created_at="2026-09-05T12:00:00+00:00",
        reason="before_apply",
        links=(system, mine),
    )
    await DeviceLinksStore(hass).async_save(StoredState(snapshots=(snapshot,)))

    loaded = (await DeviceLinksStore(hass).async_load()).snapshots[0]

    assert loaded == snapshot
    assert loaded.links[0].is_system
    assert loaded.links[1].managed_by == "rule-1"
    assert loaded.links[0].source == handle(36)


async def test_a_rule_a_backend_no_longer_knows_still_loads(hass: HomeAssistant) -> None:
    """A rule for an integration the user removed must not stop the store from loading.

    The profile is the user's intent and outlives any backend being present, so decoding
    depends on nothing but the file itself.
    """
    zigbee_rule = Rule(
        id="rule-z",
        name="Zigbee rule",
        template=_rule().template,
        backend=Backend.ZIGBEE2MQTT,
        source=_rule().source,
        targets=_rule().targets,
        features=frozenset({Feature.ON_OFF}),
    )
    state = StoredState(profiles=(Profile(id="p", name="P", rules=(zigbee_rule,)),))
    await DeviceLinksStore(hass).async_save(state)

    assert (await DeviceLinksStore(hass).async_load()) == state
