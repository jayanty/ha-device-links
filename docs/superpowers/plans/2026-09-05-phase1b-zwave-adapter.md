# Phase 1B: the Z-Wave adapter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the pure core built in Phase 1A to a real Z-Wave network, so that a plan becomes actual association entries on actual devices, and what the devices report becomes observed state the planner can diff against.

**Architecture:** One `Backend` protocol that core code depends on, and one Z-Wave implementation of it. The implementation is thin on purpose: every decision that can be made without I/O already lives in `zwave_protocol.py`, `compiler.py` and `planner.py`, and this layer only fetches, writes and translates. All coupling to `zwave_js` internals goes through the existing `zwave_accessor.py`.

**Tech Stack:** Python 3.14, `zwave-js-server-python` 0.73.0, `pytest-homeassistant-custom-component`, fake driver objects built from the Stage 0 fixtures.

---

## What changes about testing in this phase

Phase 1A was pure and could be tested exhaustively. This phase does I/O, so the discipline changes:

- The **adapter** is tested against fake `Node` and `Controller` objects built from
  `tests/fixtures/z2_associations.json`. Those fakes are the contract: if the real library
  changes shape, the fakes stop matching and `tests/test_zwave_accessor.py` fails first.
- Anything that *can* be decided without I/O belongs in Phase 1A's modules, not here. If you
  find yourself writing a branch in the adapter that does not touch the driver, it probably
  belongs in `zwave_protocol.py` where it can be property-tested.
- **No test in this phase may touch Jayant's real network.** The live suite is separate,
  opt-in, and is not part of this plan.

## Ground rules

Read `CLAUDE.md` first, then `docs/stage0-report.md` and `docs/open-items.md`.

- **Only `backends/zwave.py` may import `zwave_js` internals, and only through
  `zwave_accessor.py`.** Never import `homeassistant.components.zwave_js` directly anywhere
  else. Decision D2 confined this coupling to one place on purpose.
- **`zwave_protocol.py` stays pure.** It is in the enforced `PURE_MODULES` list. Add
  interpretation there, add I/O here.
- **No device write without a plan.** The adapter exposes add and remove for single links,
  and the executor (Phase 1C) drives them. The adapter itself never decides to write.
- **Lifelines are untouchable.** Phase 1A's planner will not plan a lifeline removal, but the
  adapter must refuse one too if asked directly. Defence in depth: a service call or a future
  caller could reach it without going through the planner.
- Never use the em dash. `mypy --strict` clean. 95% coverage gate overall.
- Conventional commits ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Ruff formats Python blocks inside Markdown; run `ruff format` on any `.md` you touch.

## Facts from Stage 0 this plan depends on

| Fact | Consequence |
|---|---|
| `entry.runtime_data.client.driver` reaches the driver | Use `zwave_accessor.async_get_driver` |
| `helpers.async_get_node_from_device_id(hass, device_id)` resolves a node | Use `zwave_accessor.async_get_node` |
| `AssociationCheckResult.OK == 1` | Compare explicitly. `zwave_protocol.is_ok` already does |
| `async_add_associations(source, group, [addr], wait_for_result=False)` | The sleeping-node handle |
| `AssociationAddress(controller, node_id=..., endpoint=...)` takes the controller first | Constructing it wrong raises `TypeError` |
| `async_refresh_cc_values` is **fire and forget** | Deep verify cannot be refresh-then-read. See Task 5 |
| The driver cache reflects our own writes immediately | Verifying our own apply is cheap |
| `get_all_association_groups` returns `{groups: {endpoint: {group: G}}}` | 2 levels |
| `get_all_associations` returns `{associations: {nodeId: {endpoint: {group: [addr]}}}}` | 3 levels, one deeper |
| Add took 67 ms, remove 253 ms on a listening node | Timeout and retry budgets in Phase 1C |
| `node.protocol` and `Protocols.ZWAVE_LONG_RANGE = 1` | The LR guard |

---

## File structure

| File | Responsibility |
|---|---|
| `custom_components/device_links/backends/base.py` | The `Backend` Protocol, plus the shared result and error types every backend returns. No Z-Wave in it. |
| `custom_components/device_links/backends/zwave.py` | The Z-Wave implementation. Fetches capabilities and observed state, performs single link writes, reads and writes settings, subscribes to change events. |
| `tests/fakes/zwave.py` | Fake `Driver`, `Controller` and `Node` built from the Stage 0 fixture, mimicking the real library's shapes including the two different nesting depths. |
| `tests/test_backend_base.py` | That the protocol is satisfiable and that a non-conforming backend fails type checking. |
| `tests/test_zwave_backend.py` | The adapter against the fakes. |

---

### Task 1: The Backend protocol

**Files:**
- Create: `custom_components/device_links/backends/base.py`
- Test: `tests/test_backend_base.py`

Core code must never branch on which backend it is talking to. This protocol is what makes
that possible, and what lets Zigbee and Matter arrive later without touching the core.

- [ ] **Step 1: Write the failing tests**

```python
"""The Backend protocol is the seam that keeps core code backend-neutral."""

from __future__ import annotations

from typing import Protocol, get_type_hints

from custom_components.device_links.backends.base import (
    Backend,
    LinkResult,
    LinkResultStatus,
    SettingResult,
)


def test_the_protocol_is_runtime_checkable_and_names_the_expected_surface() -> None:
    """A backend that is missing a method must be detectable, not merely wrong later."""
    expected = {
        "async_devices",
        "async_capabilities",
        "async_observed",
        "async_check_link",
        "async_add_link",
        "async_remove_link",
        "async_read_setting",
        "async_write_setting",
        "subscribe",
        "wake_instructions",
    }
    actual = {name for name in dir(Backend) if not name.startswith("_")}

    assert expected <= actual, f"Backend protocol lost: {expected - actual}"


def test_link_result_statuses_cover_every_outcome_the_executor_must_handle() -> None:
    """FR-A2 lists these by name. A missing one becomes an unhandled case in a job."""
    assert {status.value for status in LinkResultStatus} == {
        "applied",
        "already_present",
        "pending_wakeup",
        "failed",
        "blocked",
    }


def test_a_result_carrying_failed_must_carry_a_reason() -> None:
    """A failure with no reason is untriageable from a job log."""
    import pytest

    with pytest.raises(ValueError, match="reason"):
        LinkResult(status=LinkResultStatus.FAILED, reason=None)


def test_a_successful_result_needs_no_reason() -> None:
    assert LinkResult(status=LinkResultStatus.APPLIED).reason is None
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`base.py` defines `LinkResultStatus(StrEnum)` with the five values above, a frozen
`LinkResult(status, reason: Diagnostic | None = None, raw_error: str | None = None)` that
validates in `__post_init__`, a frozen `SettingResult`, and the `Backend` Protocol with the
ten members from PRD Section 8.3. Use `typing.Protocol` and mark it `@runtime_checkable`.

`raw_error` exists because PRD Section 9 wants the untranslated backend error visible under
an expander for issue reports. It is never shown as the primary message.

This module may import `homeassistant` (it is not in `PURE_MODULES`), but it should not need
to beyond typing. Keep it minimal.

- [ ] **Step 4: Confirm the tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(backends): the Backend protocol every adapter implements"
```

---

### Task 2: Fake Z-Wave objects built from the real capture

**Files:**
- Create: `tests/fakes/__init__.py`, `tests/fakes/zwave.py`
- Test: `tests/test_fakes_zwave.py`

The fakes are the contract with `zwave-js-server-python`. They must mimic the real shapes
closely enough that a test passing against them means something. Where Stage 0 found a
surprising shape, the fake reproduces the surprise.

- [ ] **Step 1: Write the failing tests**

```python
"""The fakes must reproduce the real library's shapes, including its inconsistencies."""

from __future__ import annotations

import pytest

from tests.fakes.zwave import FakeDriver, build_driver_from_fixture


@pytest.fixture
def driver() -> FakeDriver:
    return build_driver_from_fixture()


def test_the_fixture_nodes_are_all_present(driver: FakeDriver) -> None:
    assert set(driver.controller.nodes) >= {21, 29, 30, 35, 36, 37, 38, 39, 40, 42}


def test_association_groups_are_keyed_by_endpoint_then_group(driver: FakeDriver) -> None:
    """Two levels, as get_all_association_groups really returns."""
    groups = driver.controller.get_all_association_groups_sync(36)

    assert set(groups) == {0}, "outer key must be the endpoint"
    assert 1 in groups[0], "inner key must be the group id"
    assert groups[0][1].is_lifeline is True


def test_associations_are_keyed_by_node_then_endpoint_then_group(driver: FakeDriver) -> None:
    """Three levels. Stage 0 found this differs from the groups call by one level.

    Reading it at the groups depth returns plausible empty groups rather than an error,
    which is a bug that hides. The fake reproduces the real depth so the adapter is
    written against the shape it will actually meet.
    """
    associations = driver.controller.get_all_associations_sync(36)

    assert set(associations) == {36}, "outer key must be the node id"
    assert set(associations[36]) == {0}, "then the endpoint"
    assert 1 in associations[36][0], "then the group id"


def test_the_lifeline_contains_the_controller(driver: FakeDriver) -> None:
    lifeline = driver.controller.get_all_associations_sync(36)[36][0][1]

    assert [address.node_id for address in lifeline] == [1]


def test_a_sleeping_node_is_marked_asleep(driver: FakeDriver) -> None:
    """Node 40 was asleep during capture and is the pending_wakeup test subject."""
    assert driver.controller.nodes[40].status == 1
    assert driver.controller.nodes[36].status == 4


def test_node_protocol_is_available_for_the_long_range_guard(driver: FakeDriver) -> None:
    assert driver.controller.nodes[36].protocol == 0


def test_config_values_are_exposed_for_the_settings_adapters(driver: FakeDriver) -> None:
    node = driver.controller.nodes[37]
    keys = {(value.property_, value.property_key) for value in node.values.values()}

    assert (59, 1) in keys
    assert (59, 2) in keys


async def test_adding_an_association_is_visible_on_the_next_read(driver: FakeDriver) -> None:
    """The fake radio must behave like the real one: our own writes are visible at once."""
    from zwave_js_server.model.association import AssociationAddress

    controller = driver.controller
    source = AssociationAddress(controller, node_id=36)
    target = AssociationAddress(controller, node_id=38)

    await controller.async_add_associations(source, 7, [target])
    associations = await controller.async_get_associations(source)

    assert [address.node_id for address in associations[7]] == [38]


async def test_the_fake_refuses_to_exceed_group_capacity(driver: FakeDriver) -> None:
    """A fake more permissive than the hardware proves less than it appears to."""
    from zwave_js_server.model.association import AssociationAddress

    controller = driver.controller
    source = AssociationAddress(controller, node_id=40)  # ZEN37, capacity 5

    for node_id in (21, 29, 30, 35, 36):
        await controller.async_add_associations(
            source, 2, [AssociationAddress(controller, node_id=node_id)]
        )

    with pytest.raises(Exception, match="capacity"):
        await controller.async_add_associations(
            source, 2, [AssociationAddress(controller, node_id=37)]
        )
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`build_driver_from_fixture()` reads `tests/fixtures/z2_associations.json` and constructs
fake objects. Use the real `AssociationAddress` and `AssociationGroup` classes from
`zwave_js_server` where practical, so the shapes cannot drift; fake only `Driver`,
`Controller`, `Node` and the value objects.

The fake controller implements the async methods the adapter calls
(`async_get_association_groups`, `async_get_associations`, `async_check_association`,
`async_add_associations`, `async_remove_associations`) plus the `_sync` accessors the tests
above use for inspection. It maintains real state, so an add is visible on the next read, and
it enforces capacity.

`async_check_association` returns `CheckResult.OK` unless the target is the source
(`FORBIDDEN_SELF_ASSOCIATION`) or either end is Long Range.

- [ ] **Step 4: Confirm the tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "test(zwave): fake driver built from the Stage 0 capture"
```

---

### Task 3: Reading capabilities and observed state

**Files:**
- Create: `custom_components/device_links/backends/zwave.py`
- Test: `tests/test_zwave_backend.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Reading: devices, capabilities and observed state, against the fake driver."""

from __future__ import annotations

import pytest

from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import Feature
from custom_components.device_links.backends.zwave import ZWaveBackend
from tests.fakes.zwave import build_driver_from_fixture


@pytest.fixture
def backend() -> ZWaveBackend:
    return ZWaveBackend(driver=build_driver_from_fixture(), profiles=None)


async def test_devices_are_discovered_with_stable_handles(backend: ZWaveBackend) -> None:
    devices = await backend.async_devices()
    identities = {device.handle.identity for device in devices}

    assert any(identity.endswith(":36") for identity in identities)
    assert all(identity.startswith("zwave:") for identity in identities)


async def test_capabilities_use_the_curated_profile_when_one_matches() -> None:
    """The Inovelli paddle must come back as one control, not three groups."""
    from custom_components.device_links.profile_db import load_profiles
    from pathlib import Path

    directory = Path("custom_components/device_links/profiles_db")
    profiles = load_profiles(
        {
            path.name: path.read_text()
            for path in directory.glob("*.json")
            if path.name != "schema.json"
        }
    )
    backend = ZWaveBackend(driver=build_driver_from_fixture(), profiles=profiles)

    capabilities = await backend.async_capabilities(await _handle_for(backend, 37))
    paddle = next(e for e in capabilities.emitters if e.emitter_id == "paddle")

    assert paddle.actions[Feature.ON_OFF] == "2"
    assert paddle.actions[Feature.LEVEL_HOLD] == "4"


async def test_capabilities_fall_back_when_no_profile_matches(backend: ZWaveBackend) -> None:
    """An unknown model still gets usable links, just per-group emitters."""
    capabilities = await backend.async_capabilities(await _handle_for(backend, 37))

    assert all(emitter.grouping == "per_group" for emitter in capabilities.emitters)


async def test_the_lifeline_never_appears_as_an_emitter(backend: ZWaveBackend) -> None:
    capabilities = await backend.async_capabilities(await _handle_for(backend, 36))

    assert all(not emitter.is_lifeline for emitter in capabilities.emitters)


async def test_a_long_range_node_is_reported_as_such(backend: ZWaveBackend) -> None:
    """D13: LR nodes cannot participate in associations, and the UI must say so."""
    capabilities = await backend.async_capabilities(await _handle_for(backend, 36))

    assert capabilities.is_long_range is False


async def test_observed_state_reads_the_three_level_association_shape(
    backend: ZWaveBackend,
) -> None:
    """The bug Stage 0 hit: reading at the wrong depth returns plausible empties."""
    observed = await backend.async_observed(await _handle_for(backend, 36))

    lifelines = [link for link in observed.links if link.is_system]
    assert lifelines, "the lifeline was not read; check the nesting depth"
    assert lifelines[0].target.handle.protocol_id.endswith(":1")


async def test_the_lifeline_is_classified_as_a_system_link(backend: ZWaveBackend) -> None:
    """This is what stops it ever being offered for removal."""
    observed = await backend.async_observed(await _handle_for(backend, 36))

    for link in observed.links:
        if link.emitter_group == "1":
            assert link.is_system is True


async def test_non_lifeline_links_are_not_system_links(backend: ZWaveBackend) -> None:
    from zwave_js_server.model.association import AssociationAddress

    driver = build_driver_from_fixture()
    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=36),
        7,
        [AssociationAddress(controller, node_id=38)],
    )
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle_for(backend, 36))
    added = next(link for link in observed.links if link.emitter_group == "7")

    assert added.is_system is False
    assert added.managed_by is None, "ownership is resolved by the coordinator, not here"


async def _handle_for(backend: ZWaveBackend, node_id: int):
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement the read half of `ZWaveBackend`**

Constructor takes the driver and an optional `ProfileDatabase`. Do not fetch anything in
`__init__`.

- `async_devices` walks `driver.controller.nodes`, building a `DeviceHandle` per node with
  `protocol_id` of `f"{home_id}:{node_id}"` and the fingerprint from the node.
- `async_capabilities` fetches the group dump, then calls `zwave_protocol.resolve_emitters`
  with the matching profile entry (or `None`). Sets `is_long_range` from `node.protocol` with
  a node-id fallback, as Stage 0 recorded.
- `async_observed` fetches associations **at the correct three-level depth**, and asserts the
  node key is the one requested rather than trusting position. Builds `ObservedLink`s with
  `is_system=True` exactly when the group is a lifeline. Leaves `managed_by` as `None`: the
  coordinator resolves ownership, because only it knows the active profile.

Reuse `zwave_protocol` for every interpretation. This module should read as fetch, delegate,
translate.

- [ ] **Step 4: Confirm the tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(zwave): read devices, capabilities and observed state"
```

---

### Task 4: Writing links, with the refusals in the right order

**Files:**
- Modify: `custom_components/device_links/backends/zwave.py`
- Test: `tests/test_zwave_writes.py`

Order matters here. The check runs before the write, and the lifeline guard runs before
everything.

- [ ] **Step 1: Write the failing tests**

```python
"""Writing. Every refusal is tested, because each one protects a working home."""

from __future__ import annotations

import pytest

from custom_components.device_links.backends.base import LinkResultStatus
from custom_components.device_links.backends.zwave import ZWaveBackend
from tests.fakes.zwave import build_driver_from_fixture


async def test_adding_a_link_writes_it_and_reports_applied() -> None:
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.APPLIED
    observed = await backend.async_observed(await _handle(backend, 36))
    assert any(link.emitter_group == "7" for link in observed.links)


async def test_adding_a_link_that_is_already_present_is_not_a_write() -> None:
    """E12. Re-writing an existing entry wastes a radio round trip on a busy mesh."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    await backend.async_add_link(_link(36, "7", 38))

    before = driver.controller.write_count
    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert driver.controller.write_count == before, "a redundant write reached the radio"


async def test_removing_a_lifeline_is_refused_even_when_asked_directly() -> None:
    """Defence in depth. The planner will not ask, but a service call could.

    Removing a lifeline stops the device reporting to Home Assistant entirely, and the
    user has no easy way to notice or to undo it.
    """
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_remove_link(_link(36, "1", 1))

    assert result.status is LinkResultStatus.BLOCKED
    assert "lifeline" in result.reason.translation_key
    assert driver.controller.write_count == before, "a lifeline removal reached the radio"


async def test_a_self_association_is_blocked_before_any_write() -> None:
    """E7. The driver would refuse it too, but we must not spend a round trip finding out."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_add_link(_link(36, "7", 36))

    assert result.status is LinkResultStatus.BLOCKED
    assert "self_association" in result.reason.translation_key
    assert driver.controller.write_count == before


async def test_a_check_refusal_blocks_and_translates_the_reason() -> None:
    """FR-B2: any non-OK check result blocks with the enum reason as a message."""
    driver = build_driver_from_fixture()
    driver.controller.force_check_result = 6  # destination security class not granted
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.BLOCKED
    assert "security_class" in result.reason.translation_key


async def test_an_unknown_check_result_fails_closed() -> None:
    """A future driver value must never be read as permission to write."""
    driver = build_driver_from_fixture()
    driver.controller.force_check_result = 99
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.BLOCKED
    assert driver.controller.write_count == before


async def test_a_sleeping_node_reports_pending_wakeup_rather_than_failing() -> None:
    """E5. Node 40 is a battery remote. A queued write is not an error.

    NOTE: this behaviour is modelled from the library signature, not observed. Stage 0
    item Z4 was not approved, so the real behaviour of a queued write is unproven. See
    docs/open-items.md J1 and issue #5.
    """
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(40, "6", 38))

    assert result.status is LinkResultStatus.PENDING_WAKEUP


async def test_a_driver_exception_becomes_a_failed_result_with_the_raw_error() -> None:
    """E13. The raw text goes under an expander for issue reports, never as the message."""
    driver = build_driver_from_fixture()
    driver.controller.raise_on_write = RuntimeError("ZW0201: transmit failed")
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.FAILED
    assert result.raw_error is not None
    assert "ZW0201" in result.raw_error
    assert "ZW0201" not in result.reason.translation_key


async def test_force_is_never_passed_to_the_driver() -> None:
    """CLAUDE.md Section 3 rule 6. force skips the driver's own safety checks."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    await backend.async_add_link(_link(36, "7", 38))

    assert driver.controller.last_add_options.get("force") in (None, False)


def _link(source: int, group: str, target: int):
    from tests.factories import link

    return link(source, f"g{group}", target)


async def _handle(backend: ZWaveBackend, node_id: int):
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement the write half**

`async_add_link` in this order, and no other:

1. **Lifeline guard.** If the target group is a lifeline, return `BLOCKED` immediately.
   Never reach the driver.
2. **Self-association guard.** Source identity equals target identity, return `BLOCKED`.
3. **Already present.** Read current associations; if the target is there, return
   `ALREADY_PRESENT` with no write.
4. **Check.** Call `async_check_association`, map with `zwave_protocol.blocked_reason_for`.
   Anything not `OK`, including unknown values, returns `BLOCKED`.
5. **Write.** Call `async_add_associations` with `wait_for_result=True` for a listening node
   and `False` for a sleeping one, returning `PENDING_WAKEUP` in the latter case.
   **Never pass `force`.**
6. **Translate exceptions** into `FAILED` with `raw_error` carrying the original text and a
   translated `reason` that does not.

`async_remove_link` follows the same shape minus the check: lifeline guard, then not-present
becomes `ALREADY_PRESENT` (nothing to do), then the write.

- [ ] **Step 4: Confirm the tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(zwave): write links with lifeline, self and check refusals in order"
```

---

### Task 5: Deep verify, given that refresh is fire and forget

**Files:**
- Modify: `custom_components/device_links/backends/zwave.py`
- Test: `tests/test_zwave_verify.py`

This is the task where Stage 0's most consequential finding lands.

FR-B4 describes deep verify as: refresh the Association CC values from the device, then read.
Stage 0 measured `async_refresh_cc_values` at 0 ms and found it sends
`wait_for_result=False`. It is **fire and forget**: it returns before the device has
answered, so a read issued immediately afterwards returns the same cache it would have
returned anyway. Implemented literally, FR-B4 produces a verify that always agrees with
itself, which is worse than no verify because it looks like assurance.

- [ ] **Step 1: Write the failing tests**

```python
"""Deep verify must actually wait for the device, not just ask nicely.

Stage 0 Z3 found refresh_cc_values is fire and forget. See docs/stage0-report.md.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.device_links.backends.zwave import ZWaveBackend
from tests.fakes.zwave import build_driver_from_fixture


async def test_deep_verify_waits_for_the_refresh_to_land() -> None:
    """The fake delays its cache update, exactly as a real device does."""
    driver = build_driver_from_fixture()
    driver.controller.refresh_delay_seconds = 0.05
    driver.controller.stale_group = (36, 7, 38)  # cache lags reality
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle(backend, 36), deep=True)

    assert any(link.emitter_group == "7" for link in observed.links), (
        "deep verify returned the stale cache; it did not wait for the refresh"
    )


async def test_a_shallow_read_does_not_refresh_at_all() -> None:
    """Refreshing on every read would flood the mesh on a large network (E36)."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    await backend.async_observed(await _handle(backend, 36), deep=False)

    assert driver.controller.refresh_count == 0


async def test_deep_verify_gives_up_after_a_bounded_wait() -> None:
    """A device that never answers must not hang a job forever."""
    driver = build_driver_from_fixture()
    driver.controller.refresh_never_lands = True
    backend = ZWaveBackend(driver=driver, profiles=None, deep_verify_timeout=0.1)

    observed = await backend.async_observed(await _handle(backend, 36), deep=True)

    assert observed.deep_verify_timed_out is True, (
        "a timed-out deep verify must say so, so the caller does not read it as confirmation"
    )


async def test_deep_verify_is_skipped_for_a_sleeping_node() -> None:
    """Refreshing a sleeping node cannot succeed and would burn the whole timeout."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle(backend, 40), deep=True)

    assert driver.controller.refresh_count == 0
    assert observed.deep_verify_skipped_reason == "asleep"


async def _handle(backend: ZWaveBackend, node_id: int):
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`async_observed(handle, deep=False)`. When `deep` is true and the node is listening:

1. Subscribe to the node's value-updated events for CC 0x85 and 0x8E **before** calling
   refresh, so a fast device cannot answer before you are listening.
2. Call `async_refresh_cc_values` for both command classes.
3. Wait for the value-updated events, or for `deep_verify_timeout` (default 5 seconds).
4. Read the associations and return them, setting `deep_verify_timed_out` when the wait
   expired.

Sleeping nodes skip the refresh entirely and set `deep_verify_skipped_reason`.

Add `deep_verify_timed_out` and `deep_verify_skipped_reason` to `ObservedDevice`. The caller
must be able to tell "verified" from "we tried and could not", because reporting the second
as the first is exactly the false assurance this task exists to avoid.

- [ ] **Step 4: Confirm the tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "fix(zwave): deep verify waits for the refresh rather than reading the cache back"
```

---

### Task 6: Settings, and change subscriptions

**Files:**
- Modify: `custom_components/device_links/backends/zwave.py`
- Test: `tests/test_zwave_settings.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Settings adapters and the subscription that keeps observed state fresh."""

from __future__ import annotations

import pytest

from custom_components.device_links.backends.zwave import ZWaveBackend
from tests.fakes.zwave import build_driver_from_fixture


@pytest.fixture
def backend() -> ZWaveBackend:
    from pathlib import Path

    from custom_components.device_links.profile_db import load_profiles

    directory = Path("custom_components/device_links/profiles_db")
    profiles = load_profiles(
        {
            path.name: path.read_text()
            for path in directory.glob("*.json")
            if path.name != "schema.json"
        }
    )
    return ZWaveBackend(driver=build_driver_from_fixture(), profiles=profiles)


async def test_reading_a_bitmask_setting_returns_just_that_bit(backend: ZWaveBackend) -> None:
    """Inovelli parameter 59 bit 2 is mirror_hub_commands, and it was 0 at capture."""
    value = await backend.async_read_setting(await _handle(backend, 37), "mirror_hub_commands")

    assert value.value == 0
    assert value.parameter == 59
    assert value.bitmask == 2


async def test_writing_a_setting_reads_it_back(backend: ZWaveBackend) -> None:
    """PRD Section 8.4: parameter writes are read back after writing."""
    handle = await _handle(backend, 37)
    result = await backend.async_write_setting(handle, "mirror_hub_commands", 1)

    assert result.ok is True
    assert result.read_back == 1


async def test_writing_a_setting_a_model_does_not_have_fails_cleanly(
    backend: ZWaveBackend,
) -> None:
    """E31: an unknown adapter is a clear message, not a traceback."""
    result = await backend.async_write_setting(await _handle(backend, 40), "mirror_hub_commands", 1)

    assert result.ok is False
    assert "settings_not_available" in result.reason.translation_key


async def test_a_setting_write_never_touches_local_control_unasked(
    backend: ZWaveBackend,
) -> None:
    """Decision D4: parameter 19 is Jayant's deliberate state. Never write it implicitly."""
    driver = build_driver_from_fixture()
    from custom_components.device_links.profile_db import load_profiles
    from pathlib import Path

    directory = Path("custom_components/device_links/profiles_db")
    profiles = load_profiles(
        {
            path.name: path.read_text()
            for path in directory.glob("*.json")
            if path.name != "schema.json"
        }
    )
    backend = ZWaveBackend(driver=driver, profiles=profiles)

    await backend.async_write_setting(await _handle(backend, 39), "mirror_hub_commands", 1)

    assert 19 not in driver.controller.written_parameters


async def test_subscribing_delivers_a_callback_when_an_association_changes(
    backend: ZWaveBackend,
) -> None:
    """FR-B3 and goal G3: drift is noticed without polling.

    NOTE: whether a real driver emits this for an externally-made change is Stage 0 item
    Z5, which was never run. See docs/open-items.md J4 and issue #8.
    """
    seen: list[str] = []
    unsubscribe = backend.subscribe(lambda identity: seen.append(identity))

    backend._driver.controller.emit_association_changed(36)

    assert seen == ["zwave:3538613642:36"] or seen[0].endswith(":36")
    unsubscribe()


async def test_unsubscribing_stops_callbacks(backend: ZWaveBackend) -> None:
    """A listener that outlives an unload leaks and fires against a dead entry."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(lambda identity: seen.append(identity))
    unsubscribe()

    backend._driver.controller.emit_association_changed(36)

    assert seen == []


async def _handle(backend: ZWaveBackend, node_id: int):
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`async_read_setting` and `async_write_setting` resolve a named capability through the profile
entry's settings adapters into a concrete value id, read or write it, and read back after a
write. A bitmask adapter reads and writes only that bit.

`subscribe(callback)` registers for value-updated events on CC 0x85, 0x8E and 0x70, debounces
by 2 seconds as FR-B3 requires, and returns an unsubscribe callable. Removing every listener
on unsubscribe matters: a listener that outlives a config entry unload fires against a dead
entry and is exactly the kind of leak that survives a reload and confuses everyone.

- [ ] **Step 4: Confirm the tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(zwave): settings adapters and debounced change subscriptions"
```

---

## Phase 1B exit criteria

- [ ] `ZWaveBackend` satisfies the `Backend` protocol, checked by a test
- [ ] Every read and write path is covered against the fakes, and the fakes reproduce the
      real library's shapes including the two different nesting depths
- [ ] A lifeline removal is refused by the adapter itself, not only by the planner
- [ ] `force` is never passed to the driver, asserted by a test
- [ ] Deep verify waits for the refresh and reports honestly when it could not confirm
- [ ] Overall coverage stays at or above 95%, and `./scripts/lint` and `./scripts/test`
      exit 0 with CI green on `dev`
- [ ] The two paths that Stage 0 could not prove, sleeping-node writes and external-change
      events, carry a comment naming the open item and the issue, so nobody later mistakes
      modelled behaviour for observed behaviour

## What Phase 1B deliberately does not do

No job runner, no retries, no storage, no entities, no panel, and **no writes to Jayant's
real network**. The executor that drives these single-link operations into a sequenced,
retrying, cancellable job is Phase 1C.
