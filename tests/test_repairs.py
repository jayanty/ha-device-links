"""Repairs, and the property that matters more than raising one: withdrawing it.

An issue that outlives its cause teaches a user to ignore the Repairs panel, and a panel
nobody reads is worse than one nothing was ever written to. So every test here raises the
condition, sees the issue, clears the condition, and sees the issue go.

Four conditions: a backend that stopped answering (E1), a write queued at a sleeping
device for more than a day (E5), a rule whose device is no longer on the network (E19),
and stored data that could not be read at all (E18).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.device_links.const import DOMAIN
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.repairs import (
    ISSUE_BACKEND_UNAVAILABLE,
    ISSUE_PENDING_WAKEUP,
    ISSUE_PENDING_WAKEUP_INSTRUCTED,
    ISSUE_RULES_MISSING_DEVICES,
    ISSUE_STORAGE_UNREADABLE,
    PENDING_WAKEUP_AFTER,
    RECHECK_INTERVAL,
)
from custom_components.device_links.storage import JobLinkResult, JobSummary
from tests.conftest import a_profile, a_rule, activate
from tests.factories import handle

MISSING_NODE = 222


def issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    """Return the Repairs issue with this id, or None when there is none."""
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def break_the_backend(
    hass: HomeAssistant, entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make the Z-Wave adapter stop answering, as a restarting add-on does."""

    async def _no_answer() -> Any:
        raise TimeoutError("the driver did not answer")

    monkeypatch.setattr(entry.runtime_data.backends[BackendId.ZWAVE], "async_devices", _no_answer)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# E1: a backend that is not answering
# --------------------------------------------------------------------------------------


async def test_a_backend_that_stops_answering_raises_an_issue_naming_it(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E1. The integration is up and can see nothing, which is not the same as being down."""
    assert issue(hass, f"{ISSUE_BACKEND_UNAVAILABLE}_zwave") is None

    await break_the_backend(hass, device_links_entry, monkeypatch)

    raised = issue(hass, f"{ISSUE_BACKEND_UNAVAILABLE}_zwave")
    assert raised is not None
    assert raised.translation_key == ISSUE_BACKEND_UNAVAILABLE
    assert raised.translation_placeholders == {"backend": "zwave", "integration": "zwave_js"}
    assert raised.severity is ir.IssueSeverity.ERROR
    assert raised.is_fixable is False


async def test_the_backend_issue_goes_when_the_backend_answers_again(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    await break_the_backend(hass, device_links_entry, monkeypatch)
    assert issue(hass, f"{ISSUE_BACKEND_UNAVAILABLE}_zwave") is not None

    monkeypatch.undo()
    await device_links_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert issue(hass, f"{ISSUE_BACKEND_UNAVAILABLE}_zwave") is None


# --------------------------------------------------------------------------------------
# E5: a write queued at a sleeping device for more than a day
# --------------------------------------------------------------------------------------


def with_a_pending_write(entry: MockConfigEntry, *, hours_ago: float, fingerprint: str) -> None:
    """Record a job that queued one write at a sleeping node, that long ago."""
    coordinator = entry.runtime_data.coordinator
    created = dt_util.utcnow() - timedelta(hours=hours_ago)
    coordinator.async_update_state(
        replace(
            coordinator.state,
            jobs=(
                JobSummary(
                    id="job-1",
                    created_at=created.isoformat(),
                    scope="all",
                    status="completed",
                    results=(JobLinkResult(fingerprint=fingerprint, status="pending_wakeup"),),
                ),
            ),
        )
    )


def a_pending_fingerprint(entry: MockConfigEntry) -> str:
    """Return a fingerprint of the active rule, as a real queued write would carry."""
    compiled = entry.runtime_data.coordinator.compiled_for("bedroom-main")
    assert compiled is not None
    return compiled.links[0].fingerprint


async def test_a_write_queued_for_a_day_raises_an_issue(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """E5. Below a day this is normal: a battery device wakes when it wakes."""
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    fingerprint = a_pending_fingerprint(device_links_entry)

    with_a_pending_write(device_links_entry, hours_ago=2, fingerprint=fingerprint)
    await hass.async_block_till_done()
    assert issue(hass, f"{ISSUE_PENDING_WAKEUP}_zwave:3538613642:36") is None

    with_a_pending_write(device_links_entry, hours_ago=30, fingerprint=fingerprint)
    await hass.async_block_till_done()

    raised = issue(hass, f"{ISSUE_PENDING_WAKEUP}_zwave:3538613642:36")
    assert raised is not None
    assert raised.translation_key == ISSUE_PENDING_WAKEUP
    assert raised.translation_placeholders["device"] == "Bedroom Scene Controller"
    assert raised.translation_placeholders["links"] == "1"
    assert raised.severity is ir.IssueSeverity.WARNING


async def test_the_issue_carries_the_wake_instruction_when_the_database_has_one(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The profile database records how a model is woken, so the issue can say it.

    No shipped model carries one yet (open item T4 and Stage 0 item Z4), which is why the
    issue has two forms: this one, and the one above that says nothing it cannot support.
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    backend = device_links_entry.runtime_data.backends[BackendId.ZWAVE]
    monkeypatch.setattr(backend, "wake_instructions", lambda handle: "Press the button three times")

    with_a_pending_write(
        device_links_entry, hours_ago=30, fingerprint=a_pending_fingerprint(device_links_entry)
    )
    await hass.async_block_till_done()

    raised = issue(hass, f"{ISSUE_PENDING_WAKEUP}_zwave:3538613642:36")
    assert raised is not None
    assert raised.translation_key == ISSUE_PENDING_WAKEUP_INSTRUCTED
    assert raised.translation_placeholders["instruction"] == "Press the button three times"


async def test_the_pending_issue_goes_when_the_write_lands(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    fingerprint = a_pending_fingerprint(device_links_entry)
    with_a_pending_write(device_links_entry, hours_ago=30, fingerprint=fingerprint)
    await hass.async_block_till_done()
    assert issue(hass, f"{ISSUE_PENDING_WAKEUP}_zwave:3538613642:36") is not None

    coordinator = device_links_entry.runtime_data.coordinator
    coordinator.async_update_state(
        replace(
            coordinator.state,
            jobs=(
                JobSummary(
                    id="job-2",
                    created_at=dt_util.utcnow().isoformat(),
                    scope="all",
                    status="completed",
                    results=(JobLinkResult(fingerprint=fingerprint, status="applied"),),
                ),
            ),
        )
    )
    await hass.async_block_till_done()

    assert issue(hass, f"{ISSUE_PENDING_WAKEUP}_zwave:3538613642:36") is None


async def test_a_write_that_passes_a_day_while_nothing_happens_is_still_noticed(
    hass: HomeAssistant,
    device_links_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Nothing changes when a link stays queued, so nothing would fire the check.

    A queued write ages without any event: no device answers, no state moves, and the
    listener the rest of this module hangs on never fires. The timer is what makes the
    threshold a real one rather than one that only triggers if something else happens.
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()
    with_a_pending_write(
        device_links_entry,
        hours_ago=PENDING_WAKEUP_AFTER.total_seconds() / 3600 - 0.5,
        fingerprint=a_pending_fingerprint(device_links_entry),
    )
    await hass.async_block_till_done()
    assert issue(hass, f"{ISSUE_PENDING_WAKEUP}_zwave:3538613642:36") is None

    freezer.tick(RECHECK_INTERVAL + timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert issue(hass, f"{ISSUE_PENDING_WAKEUP}_zwave:3538613642:36") is not None


# --------------------------------------------------------------------------------------
# E19: a rule whose device is gone
# --------------------------------------------------------------------------------------


async def test_a_rule_naming_a_device_that_is_not_on_the_network_raises_an_issue(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """E19. The swap flow is Phase 2; saying which rules are stranded is not."""
    activate(
        device_links_entry,
        a_profile(a_rule(), a_rule("stranded", target_node=MISSING_NODE)),
    )
    await hass.async_block_till_done()

    raised = issue(hass, ISSUE_RULES_MISSING_DEVICES)
    assert raised is not None
    assert raised.translation_placeholders["rules"] == "stranded"
    assert raised.translation_placeholders["count"] == "1"
    assert handle(MISSING_NODE).name_at_authoring in raised.translation_placeholders["devices"]


async def test_the_missing_device_issue_goes_when_the_rule_does(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    activate(
        device_links_entry,
        a_profile(a_rule(), a_rule("stranded", target_node=MISSING_NODE)),
    )
    await hass.async_block_till_done()
    assert issue(hass, ISSUE_RULES_MISSING_DEVICES) is not None

    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    assert issue(hass, ISSUE_RULES_MISSING_DEVICES) is None


async def test_a_rule_whose_device_is_merely_unreachable_raises_nothing(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E4 and E19 are different faults, and only one of them is about a missing device.

    A device that has stopped answering is still on the network and its rules are
    `unknown`, not stranded. Raising the swap-flow issue for a node that is asleep or for
    an add-on that is restarting is how a user learns to dismiss it.
    """
    activate(device_links_entry, a_profile(a_rule()))
    await hass.async_block_till_done()

    await break_the_backend(hass, device_links_entry, monkeypatch)

    assert issue(hass, ISSUE_RULES_MISSING_DEVICES) is None


# --------------------------------------------------------------------------------------
# E18: stored data that cannot be read
# --------------------------------------------------------------------------------------


async def test_storage_that_cannot_be_read_raises_an_issue_saying_where_it_is(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    """E18. The entry does not load, so the issue is the only thing that can explain it."""
    hass_storage["device_links.profiles"] = {
        "version": 1,
        "minor_version": 1,
        "key": "device_links.profiles",
        "data": {"profiles": [{"this": "is not a profile"}]},
    }
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    raised = issue(hass, ISSUE_STORAGE_UNREADABLE)
    assert raised is not None
    assert raised.severity is ir.IssueSeverity.ERROR
    assert ".storage/device_links.profiles" in raised.translation_placeholders["path"]
    assert raised.translation_placeholders["error"]


async def test_the_storage_issue_goes_when_the_file_can_be_read_again(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zwave_js_devices: dict[int, dr.DeviceEntry],
) -> None:
    hass_storage["device_links.profiles"] = {
        "version": 1,
        "minor_version": 1,
        "key": "device_links.profiles",
        "data": {"profiles": [{"this": "is not a profile"}]},
    }
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert issue(hass, ISSUE_STORAGE_UNREADABLE) is not None

    hass_storage["device_links.profiles"]["data"] = {"profiles": []}
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert issue(hass, ISSUE_STORAGE_UNREADABLE) is None


async def test_the_issues_of_an_entry_that_unloads_do_not_linger(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unloaded integration is not reporting on anything, so it says nothing.

    Its issues were about a live system, and none of them can be re-evaluated while it is
    down: leaving them would leave a user reading about a backend that stopped answering
    for an integration that is no longer running.
    """
    await break_the_backend(hass, device_links_entry, monkeypatch)
    assert issue(hass, f"{ISSUE_BACKEND_UNAVAILABLE}_zwave") is not None

    await hass.config_entries.async_unload(device_links_entry.entry_id)
    await hass.async_block_till_done()

    assert issue(hass, f"{ISSUE_BACKEND_UNAVAILABLE}_zwave") is None
