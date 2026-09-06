"""The hub device and the entities that describe the integration to itself.

The Health sensor is the reason this file is longer than the others. PRD Section 17.1
makes it the single entity read first when something is wrong on a system nobody can put
a debugger on, so what it says has to be true on a system where everything has gone
wrong: no backend answering, no `.deployed` file, no profile. Two of the tests below are
about exactly that, and one of them is about a file that does not exist, because a HACS
install has none and reporting `error` for its absence would send every future
investigation down the wrong path on its first read.
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.model.association import AssociationAddress

from custom_components.device_links import PLATFORMS
from custom_components.device_links.backends.base import BackendDevice
from custom_components.device_links.const import DOMAIN
from custom_components.device_links.coordinator import RuleState
from custom_components.device_links.deployment import read_deployment
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.storage import JobLinkResult, JobSummary
from tests.conftest import CONTROLLER, LOBBY, a_profile, a_rule, activate
from tests.fakes.zwave import FakeDriver

HEALTH = "sensor.device_links_health"
DRIFT = "binary_sensor.device_links_drift"
PROFILE_STATUS = "sensor.device_links_active_profile_status"
PENDING = "sensor.device_links_pending_links"

MANIFEST = Path(__file__).parent.parent / "custom_components" / "device_links" / "manifest.json"


def attributes(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} has no state"
    return dict(state.attributes)


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} has no state"
    return state.state


# --------------------------------------------------------------------------------------
# The hub device
# --------------------------------------------------------------------------------------


async def test_a_hub_device_named_device_links_is_created(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """The hub holds everything that is about the integration rather than about a device."""
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, device_links_entry.entry_id)}
    )

    assert device is not None, "no hub device was created for the config entry"
    assert device.name == "Device Links"
    assert device.entry_type is dr.DeviceEntryType.SERVICE


# --------------------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------------------


async def test_the_health_sensor_exists_and_is_enabled_by_default(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    entry = er.async_get(hass).async_get(HEALTH)

    assert entry is not None, f"{HEALTH} was not created"
    assert entry.disabled_by is None, "the health sensor must be enabled by default"
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert state_of(hass, HEALTH) in {"ok", "degraded", "error"}


async def test_the_health_sensor_reports_the_manifest_version_and_the_backends(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Version, backend state and upstream version are the first three things looked at."""
    data = attributes(hass, HEALTH)

    assert data["version"] == json.loads(MANIFEST.read_text())["version"]
    assert data["backends"] == {
        "zwave": {"available": True, "upstream": "zwave_js", "upstream_version": "1.44.0"}
    }


async def test_the_health_sensor_reports_job_counters_and_the_last_error(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    data = attributes(hass, HEALTH)

    assert data["jobs"] == {"total": 0, "last_status": None, "last_at": None}
    assert data["last_error"] is None


async def test_the_health_sensor_reports_the_deployed_commit_when_there_is_one(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """The dev deploy loop ends by comparing this attribute with the SHA that was pushed."""
    from custom_components.device_links import deployment  # noqa: PLC0415

    (tmp_path / ".deployed").write_text(
        json.dumps(
            {
                "commit": "0123456789abcdef",
                "branch": "dev",
                "deployed_at": "2026-09-05T22:00:00+00:00",
                "previous_commit": "fedcba9876543210",
                "changed_files": ["custom_components/device_links/sensor.py"],
            }
        )
    )
    monkeypatch.setattr(deployment, "COMPONENT_DIR", tmp_path)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    data = attributes(hass, HEALTH)

    assert data["commit"] == "0123456789abcdef"
    assert data["branch"] == "dev"
    assert data["deployed_at"] == "2026-09-05T22:00:00+00:00"
    assert state_of(hass, HEALTH) == "ok"


async def test_a_missing_deployed_file_is_not_an_error(
    hass: HomeAssistant, no_deployed_file: None, device_links_entry: MockConfigEntry
) -> None:
    """A HACS install has no `.deployed` file, and reporting `error` would mislead.

    The file only ever exists on a dev deployment. Every remote investigation starts by
    reading this sensor, so an install that is perfectly well must not read as broken
    because a file only the deploy tool writes was never written.
    """
    data = attributes(hass, HEALTH)

    assert state_of(hass, HEALTH) == "ok"
    assert data["commit"] is None
    assert data["deployed_at"] is None


def test_a_deployed_file_that_is_not_json_reads_as_no_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-written file must not stop the integration from setting up."""
    from custom_components.device_links import deployment  # noqa: PLC0415

    (tmp_path / ".deployed").write_text("{ this is not json")
    monkeypatch.setattr(deployment, "COMPONENT_DIR", tmp_path)

    assert read_deployment() is None


def test_a_deployed_file_that_is_not_an_object_reads_as_no_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid JSON of the wrong shape is still not a deployment record."""
    from custom_components.device_links import deployment  # noqa: PLC0415

    (tmp_path / ".deployed").write_text('["dev", "0123456789abcdef"]')
    monkeypatch.setattr(deployment, "COMPONENT_DIR", tmp_path)

    assert read_deployment() is None


async def test_health_is_degraded_when_the_last_apply_did_not_finish_cleanly(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """An apply that half worked is not `ok`, and is not `error` either.

    `error` is reserved for "nothing can be read", because that is the state in which no
    other entity here is saying anything true. A partial job is the integration working
    and something in the house not, which is exactly what `degraded` is for.
    """
    coordinator = device_links_entry.runtime_data.coordinator
    coordinator.async_update_state(
        coordinator.state.with_job(
            JobSummary(
                id="j1",
                created_at="2026-09-05T00:00:00+00:00",
                scope="rules:bedroom-main",
                status="partial",
                results=(
                    JobLinkResult(fingerprint="a", status="failed", reason="link_write_failed"),
                ),
            )
        )
    )
    await hass.async_block_till_done()

    assert state_of(hass, HEALTH) == "degraded"
    assert attributes(hass, HEALTH)["jobs"] == {
        "total": 1,
        "last_status": "partial",
        "last_at": "2026-09-05T00:00:00+00:00",
    }


async def test_the_health_sensor_stays_available_and_says_error_when_nothing_answers(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one entity that must never go unavailable, because it is the one read first.

    Every other entity is unavailable when nothing can be read, which is honest. This one
    would then have no state to report the outage in, and PRD Section 17.1 makes it the
    first thing looked at, so it deliberately stays available and says `error` instead.
    """
    await stop_the_backend_answering(hass, device_links_entry, monkeypatch)

    data = attributes(hass, HEALTH)
    assert state_of(hass, HEALTH) == "error"
    assert data["backends"]["zwave"]["available"] is False
    assert data["last_error"] is not None


# --------------------------------------------------------------------------------------
# Drift, profile status and pending links
# --------------------------------------------------------------------------------------


async def test_the_drift_binary_sensor_is_a_problem_sensor_enabled_by_default(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    entry = er.async_get(hass).async_get(DRIFT)

    assert entry is not None, f"{DRIFT} was not created"
    assert entry.disabled_by is None
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert attributes(hass, DRIFT)["device_class"] == BinarySensorDeviceClass.PROBLEM


async def test_drift_turns_on_when_an_applied_link_goes_missing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Drift is a link that was applied and is no longer there (FR-A5)."""
    activate(device_links_entry, a_profile(a_rule()))
    await apply_the_active_profile(device_links_entry)
    await hass.async_block_till_done()

    assert state_of(hass, DRIFT) == STATE_OFF
    assert state_of(hass, PROFILE_STATUS) == RuleState.IN_SYNC

    await remove_by_hand(zwave_driver, source=CONTROLLER, group=2, target=37)
    await device_links_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert state_of(hass, DRIFT) == STATE_ON
    assert state_of(hass, PROFILE_STATUS) == RuleState.DRIFT


async def test_the_active_profile_status_aggregates_the_rules(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Two rules that were never applied aggregate to pending, not to in sync."""
    activate(
        device_links_entry,
        a_profile(a_rule(), a_rule("second", emitter_id="g5", target_node=LOBBY)),
    )
    await hass.async_block_till_done()

    assert state_of(hass, PROFILE_STATUS) == RuleState.PENDING
    assert attributes(hass, PROFILE_STATUS)["rules"] == 2


async def test_pending_links_is_disabled_by_default(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A count almost every install reads zero is not worth a state row per restart."""
    entry = er.async_get(hass).async_get(PENDING)

    assert entry is not None, f"{PENDING} was not created"
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(PENDING) is None, "a disabled entity must have no state"


async def test_pending_links_counts_the_links_a_job_left_waiting(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Enabled by hand, it counts the fingerprints whose last job said pending_wakeup (E5)."""
    er.async_get(hass).async_update_entity(PENDING, disabled_by=None)
    await hass.config_entries.async_reload(device_links_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = device_links_entry.runtime_data.coordinator
    coordinator.async_update_state(
        coordinator.state.with_job(
            JobSummary(
                id="j1",
                created_at="2026-09-05T00:00:00+00:00",
                scope="all",
                status="completed",
                results=(
                    JobLinkResult(fingerprint="a", status="pending_wakeup"),
                    JobLinkResult(fingerprint="b", status="applied"),
                ),
            )
        )
    )
    await hass.async_block_till_done()

    assert state_of(hass, PENDING) == "1"


# --------------------------------------------------------------------------------------
# Availability, and saying so once
# --------------------------------------------------------------------------------------


async def test_entities_go_unavailable_when_every_backend_is(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert state_of(hass, DRIFT) != STATE_UNAVAILABLE

    await stop_the_backend_answering(hass, device_links_entry, monkeypatch)

    assert state_of(hass, DRIFT) == STATE_UNAVAILABLE
    assert state_of(hass, PROFILE_STATUS) == STATE_UNAVAILABLE


async def test_losing_and_regaining_a_backend_is_logged_once_each(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A warning that repeats every refresh is one users filter out (log-when-unavailable)."""
    coordinator = device_links_entry.runtime_data.coordinator
    backend = device_links_entry.runtime_data.backends[BackendId.ZWAVE]
    working = backend.async_devices

    async def refuse() -> list[BackendDevice]:
        raise ConnectionError("the Z-Wave JS add-on is not answering")

    with caplog.at_level(logging.INFO, logger="custom_components.device_links.coordinator"):
        monkeypatch.setattr(backend, "async_devices", refuse)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        lost = caplog.text.count("stopped answering")

        monkeypatch.setattr(backend, "async_devices", working)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        recovered = caplog.text.count("is answering again")

    assert lost == 1, f"the loss was logged {lost} times, not once"
    assert recovered == 1, f"the recovery was logged {recovered} times, not once"


# --------------------------------------------------------------------------------------
# Quality-scale rules that apply to every platform
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("platform", [str(platform) for platform in PLATFORMS])
def test_every_platform_declares_parallel_updates_zero(platform: str) -> None:
    """Entities here are push-updated, so serializing their updates buys nothing."""
    module = importlib.import_module(f"custom_components.device_links.{platform}")

    assert getattr(module, "PARALLEL_UPDATES", None) == 0, (
        f"{platform}.py must declare PARALLEL_UPDATES = 0"
    )


async def test_every_entity_has_a_unique_id_derived_from_the_entry(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    entries = er.async_entries_for_config_entry(er.async_get(hass), device_links_entry.entry_id)

    assert entries, "the integration created no entities at all"
    for entry in entries:
        assert entry.unique_id.startswith(device_links_entry.entry_id), (
            f"{entry.entity_id} has unique id {entry.unique_id!r}, which is not derived "
            "from the config entry id, so two entries would collide"
        )
        assert entry.has_entity_name, f"{entry.entity_id} is not has_entity_name"
        assert entry.translation_key, f"{entry.entity_id} has no translation key"


async def test_an_entity_stops_listening_when_it_is_removed(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """entity-event-setup: a listener that outlives its entity survives a reload.

    Asserted on the coordinator's listener count rather than on a state, because the
    failure this guards against is invisible from the outside until the second reload.
    """
    coordinator = device_links_entry.runtime_data.coordinator

    assert coordinator.listener_count > 0, "no entity subscribed to the coordinator at all"

    await hass.config_entries.async_unload(device_links_entry.entry_id)
    await hass.async_block_till_done()

    assert coordinator.listener_count == 0, (
        "entities left listeners behind on unload; each one fires at a dead entity after a reload"
    )


# --------------------------------------------------------------------------------------
# Helpers shared with the other entity test modules
# --------------------------------------------------------------------------------------


async def stop_the_backend_answering(
    hass: HomeAssistant, entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drop the Z-Wave JS connection the way a restarted add-on does."""

    async def refuse() -> list[BackendDevice]:
        raise ConnectionError("the Z-Wave JS add-on is not answering")

    monkeypatch.setattr(entry.runtime_data.backends[BackendId.ZWAVE], "async_devices", refuse)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def apply_the_active_profile(entry: MockConfigEntry) -> None:
    """Plan and apply the whole active profile, as pressing Apply does."""
    runtime = entry.runtime_data
    plan = await runtime.coordinator.async_plan()
    await runtime.runner.async_apply(plan)


async def remove_by_hand(driver: FakeDriver, *, source: int, group: int, target: int) -> None:
    """Take one association off the way somebody using Z-Wave JS UI would."""
    controller = driver.controller
    await controller.async_remove_associations(
        AssociationAddress(controller, node_id=source),
        group,
        [AssociationAddress(controller, node_id=target)],
    )
