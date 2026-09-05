# Stage 0 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove every protocol assumption in `docs/PRD.md` Section 3 against Jayant's live hardware, capture real fixtures for the test suite, and stand up the GitHub-to-Home-Assistant deploy loop, so Phase 1 is written against facts instead of assumptions.

**Architecture:** Stage 0 ships no product code. It ships three things: (1) `tools/probe_*.py` standalone probe scripts that import nothing from Home Assistant and run inside the HA Core container over SSH, (2) JSON fixtures under `tests/fixtures/` captured from the real network, and (3) `custom_components/device_links/backends/zwave_accessor.py`, the single version-guarded module that reaches the `zwave_js` driver, with an automated test that fails CI when Home Assistant refactors underneath us. A written report (`docs/stage0-report.md`) closes or amends every assumption A1-A4.

**Tech Stack:** Python 3.14, `zwave-js-server-python` 0.73.0, `pytest-homeassistant-custom-component`, MQTT via `aiomqtt`, `mypy --strict`, ruff.

---

## Ground rules for every task

Read `CLAUDE.md` first. The rules that bite hardest in Stage 0:

- **Never restart Home Assistant or any add-on.** Not over SSH, not over MCP.
- **Only two device writes are approved: Z3 and Z8, on node 36 only.** Z4 and G2 are NOT approved. Do not execute them. Where a task depends on them, write the code and its fixture-driven tests, then mark the path unproven in the report.
- Every probe is **read-before, act, read-after, restore**, and records all three in the fixture.
- SSH may need the source interface pinned: `ssh -b 10.10.1.157 root@10.10.1.11`.
- No em dash in any file you write.
- Run `scripts/lint && scripts/test` before every commit. Both must exit 0.

Probe invocation pattern used throughout (avoids writing anything into `/config`):

```bash
ssh -o BatchMode=yes root@10.10.1.11 'docker exec -i homeassistant python3 -' < tools/probe_x.py
```

## File Structure

| File | Responsibility |
|---|---|
| `tools/probe_common.py` | Shared probe helpers: JSON emit, redaction of home id and IEEE addresses, fixture envelope with captured-at timestamp and upstream versions. No HA imports. |
| `tools/probe_zwave.py` | Z1, Z2, Z6 read-only Z-Wave probes. Runs inside HA Core. |
| `tools/probe_zwave_write.py` | Z3 and Z8 only. Refuses to run against any node other than 36 and any group other than 8. |
| `tools/probe_zigbee.py` | G1: capture retained Zigbee2MQTT bridge topics. |
| `tools/probe_matter.py` | M1: Matter client reachability, Descriptor ClientList, Binding, ACL reads. |
| `tools/ha_deploy.py` | R2: the pull-based deploy tool. Stdlib only. Installed at `/config/tools/ha_deploy.py`. |
| `custom_components/device_links/backends/zwave_accessor.py` | The one place that knows how to reach the `zwave_js` driver and node objects. |
| `tests/test_zwave_accessor.py` | Fails when upstream `zwave_js` internals move. |
| `tests/test_ha_deploy.py` | Unit tests for the deploy tool's archive validation, swap, and rollback. |
| `tests/fixtures/*.json` | Captured real-network payloads. |
| `docs/stage0-report.md` | The deliverable: every assumption closed or amended. |
| `docs/dev-deploy.md` | How the deploy loop works and how to recover it. |

---

### Task 1: Probe harness

**Files:**
- Create: `tools/probe_common.py`
- Test: `tests/test_probe_common.py`

- [ ] **Step 1: Write the failing test**

```python
"""The probe harness must redact before anything is written to a fixture."""

from __future__ import annotations

import json

from tools.probe_common import envelope, redact


def test_redact_masks_home_id_and_ieee() -> None:
    payload = {
        "home_id": 3735928559,
        "nodes": [{"ieee_address": "0x00124b002e1dfd4a", "node_id": 36}],
    }
    cleaned = redact(payload)

    assert cleaned["home_id"] == "<redacted>"
    assert cleaned["nodes"][0]["ieee_address"] == "<redacted:...fd4a>"
    assert cleaned["nodes"][0]["node_id"] == 36, "node ids are not secret and must survive"


def test_envelope_records_provenance() -> None:
    out = envelope("z2_associations", {"a": 1}, versions={"homeassistant": "2026.8.3"})

    assert out["fixture"] == "z2_associations"
    assert out["data"] == {"a": 1}
    assert out["versions"]["homeassistant"] == "2026.8.3"
    assert out["captured_at"].endswith("Z"), "timestamps are UTC and comparable"
    json.dumps(out)  # must be serializable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_probe_common.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/__init__.py` as an empty file, then `tools/probe_common.py`:

```python
"""Shared helpers for Stage 0 probe scripts.

Imports nothing from Home Assistant so the same module runs inside the HA Core
container, inside an add-on container, and under pytest on the laptop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_SECRET_KEYS = frozenset({"home_id", "homeId", "dsk", "network_key", "s2_access_control"})
_TAIL_KEYS = frozenset({"ieee_address", "ieeeAddress", "ieee"})


def redact(value: Any) -> Any:
    """Recursively mask identifiers that must never reach a committed fixture.

    Node ids, endpoints, and group ids are deliberately preserved: the fixtures are
    useless without them and they identify nothing outside this network.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _SECRET_KEYS:
                out[key] = "<redacted>"
            elif key in _TAIL_KEYS and isinstance(item, str):
                out[key] = f"<redacted:...{item[-4:]}>"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def envelope(
    name: str, data: Any, *, versions: dict[str, str] | None = None
) -> dict[str, Any]:
    """Wrap probe output with provenance so a stale fixture is obvious."""
    return {
        "fixture": name,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "versions": versions or {},
        "data": redact(data),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_probe_common.py -v --no-cov`
Expected: PASS, 2 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ tests/test_probe_common.py
git commit -m "feat(stage0): probe harness with fixture redaction and provenance"
```

---

### Task 2: Z-Wave driver accessor and its guard test

This is the module that pays for Decision D2 (a). Everything else in the Z-Wave backend
depends on it, and it is the single place that breaks when Home Assistant refactors.

**Files:**
- Create: `custom_components/device_links/backends/__init__.py`
- Create: `custom_components/device_links/backends/zwave_accessor.py`
- Test: `tests/test_zwave_accessor.py`

Facts established by the Z1 probe on 2026-09-05 (do not re-derive, but the test re-checks them):
`entry.runtime_data` is a `ZwaveJSData` with fields `client`, `driver_events`,
`old_server_log_level`; the driver is `entry.runtime_data.client.driver`;
`homeassistant.components.zwave_js.helpers.async_get_node_from_device_id(hass, device_id, dev_reg)`
resolves a HA device id to a `Node`.

- [ ] **Step 1: Write the failing test**

```python
"""Guards the one coupling to zwave_js internals (PRD Decision D2, Stage 0 Z1).

If Home Assistant moves runtime_data or renames the helper, this test fails in CI
rather than the integration failing on a user's system.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.device_links.backends.zwave_accessor import (
    ZWaveAccessorError,
    async_get_node,
    get_driver,
)


def test_upstream_runtime_data_shape_is_unchanged() -> None:
    """ZwaveJSData must still carry a client whose driver we can reach."""
    from homeassistant.components.zwave_js.models import ZwaveJSData

    assert "client" in ZwaveJSData.__dataclass_fields__, (
        "zwave_js.models.ZwaveJSData no longer exposes 'client'; "
        "update zwave_accessor.get_driver and docs/stage0-report.md"
    )


def test_upstream_helper_still_exists() -> None:
    """The device-id to Node helper must still exist with a compatible signature."""
    import inspect

    from homeassistant.components.zwave_js import helpers

    fn = getattr(helpers, "async_get_node_from_device_id", None)
    assert fn is not None, "zwave_js.helpers.async_get_node_from_device_id disappeared"

    params = list(inspect.signature(fn).parameters)
    assert params[:2] == ["hass", "device_id"], f"unexpected signature: {params}"


def test_get_driver_returns_the_entry_driver() -> None:
    entry = MagicMock()
    entry.runtime_data.client.driver = sentinel = object()

    assert get_driver(entry) is sentinel


def test_get_driver_raises_a_typed_error_when_the_client_has_no_driver() -> None:
    entry = MagicMock()
    entry.runtime_data.client.driver = None

    with pytest.raises(ZWaveAccessorError, match="not connected"):
        get_driver(entry)


async def test_async_get_node_wraps_upstream_failures(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing device must surface as our error type, not an upstream one."""

    def boom(*args: object, **kwargs: object) -> None:
        raise ValueError("Device ID not found")

    monkeypatch.setattr(
        "custom_components.device_links.backends.zwave_accessor."
        "zwave_js_helpers.async_get_node_from_device_id",
        boom,
    )

    with pytest.raises(ZWaveAccessorError, match="not a Z-Wave device"):
        async_get_node(hass, "missing-device-id")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_zwave_accessor.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'custom_components.device_links.backends'`

- [ ] **Step 3: Write minimal implementation**

`custom_components/device_links/backends/__init__.py`:

```python
"""Protocol adapters. Core code depends on backends/base.py, never on a concrete one."""
```

`custom_components/device_links/backends/zwave_accessor.py`:

```python
"""The single supported way to reach the Z-Wave JS driver from this integration.

PRD Decision D2 (a): reuse the zwave_js integration's existing connection rather than
opening a second, unauthenticated WebSocket to zwave-js-server. That couples us to
zwave_js internals, so every such access lives here and is covered by
tests/test_zwave_accessor.py, which fails in CI when upstream moves.

Verified against Home Assistant 2026.8.3 and zwave-js-server-python 0.73.0 on
2026-09-05 (Stage 0 item Z1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.zwave_js import helpers as zwave_js_helpers
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from zwave_js_server.model.driver import Driver
    from zwave_js_server.model.node import Node


class ZWaveAccessorError(HomeAssistantError):
    """Raised when the Z-Wave driver or a node cannot be reached."""


def get_driver(entry: ConfigEntry) -> Driver:
    """Return the live driver behind a loaded zwave_js config entry."""
    driver = getattr(getattr(entry.runtime_data, "client", None), "driver", None)
    if driver is None:
        raise ZWaveAccessorError("The Z-Wave JS client is not connected")
    return driver


def async_get_node(hass: HomeAssistant, device_id: str) -> Node:
    """Resolve a Home Assistant device id to a Z-Wave node."""
    try:
        return zwave_js_helpers.async_get_node_from_device_id(hass, device_id)
    except ValueError as err:
        raise ZWaveAccessorError(f"{device_id} is not a Z-Wave device: {err}") from err
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_zwave_accessor.py -v --no-cov`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add custom_components/device_links/backends tests/test_zwave_accessor.py
git commit -m "feat(zwave): version-guarded driver accessor with upstream-drift test"
```

---

### Task 3: Z2 association dump

Captures the real association topology. This fixture is what the Phase 1 compiler and
planner are tested against, so it must be complete before Phase 1 starts.

**Files:**
- Create: `tools/probe_zwave.py`
- Create: `tests/fixtures/z2_associations.json` (generated, committed)

- [ ] **Step 1: Write the probe**

`tools/probe_zwave.py` must, for nodes 35, 36, 37, 38, 39, 40, 29, 30, 42, 21, record:
`node.protocol` and its int value, `node.node_id`, `node.ready`, `node.status`,
`node.device_config` manufacturer and label, the fingerprint
(`manufacturer_id`, `product_type`, `product_id`, `firmware_version`),
`highest_security_class`, the supported command classes per endpoint filtered to
0x85 Association, 0x8E Multi Channel Association, 0x59 AGI, 0x87 Indicator,
0x5B Central Scene, 0x70 Configuration, and then for every endpoint the output of
`controller.async_get_association_groups(AssociationAddress(node_id=..., endpoint=...))`
and `controller.async_get_associations(...)`.

Because this needs the live driver, the probe cannot run as a bare `docker exec` script:
it must attach to the running Home Assistant. Use the zwave-js-server WebSocket directly
from inside the Z-Wave JS UI add-on container, which is read-only and does not touch
Home Assistant:

```bash
ssh root@10.10.1.11 'docker exec -i app_a0d7b954_zwavejs2mqtt node -e "$(cat)"' < tools/probe_zwave_ws.js
```

Write `tools/probe_zwave_ws.js` to open `ws://127.0.0.1:3000`, send
`{"command":"start_listening","messageId":"init"}`, and from the returned state dump
build the same structure. Then send `controller.get_all_association_groups` and
`controller.get_all_associations` per node id with incrementing `messageId`, collect
responses, and print one JSON document.

- [ ] **Step 2: Run the probe and confirm it is read-only**

Run the command above. Expected: a JSON document on stdout with ten node entries.
Confirm no `add_associations`, `remove_associations`, or `set_value` string appears in
the script: `grep -nE "add_assoc|remove_assoc|set_value" tools/probe_zwave_ws.js` must
print nothing.

- [ ] **Step 3: Save the fixture**

```bash
ssh root@10.10.1.11 'docker exec -i app_a0d7b954_zwavejs2mqtt node -e "$(cat)"' \
  < tools/probe_zwave_ws.js > /tmp/z2_raw.json
.venv/bin/python -c "
import json, sys
sys.path.insert(0, '.')
from tools.probe_common import envelope
raw = json.load(open('/tmp/z2_raw.json'))
out = envelope('z2_associations', raw, versions={'zwave_js_ui': '7.6.0'})
json.dump(out, open('tests/fixtures/z2_associations.json', 'w'), indent=1, sort_keys=True)
print('nodes captured:', len(raw))
"
```

Expected: `nodes captured: 10`

- [ ] **Step 4: Assert the fixture answers the questions the PRD asked**

Write `tests/test_fixture_z2.py`:

```python
"""The Z2 fixture must actually answer PRD Section 3.2's open questions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z2 fixture not captured yet")


def _nodes() -> dict[str, dict]:
    return {str(n["node_id"]): n for n in json.loads(FIXTURE.read_text())["data"]}


def test_every_expected_node_was_captured() -> None:
    captured = _nodes()
    for node_id in ("21", "29", "30", "35", "36", "37", "38", "39", "40", "42"):
        assert node_id in captured, f"node {node_id} missing from the Z2 fixture"


def test_group_one_is_the_lifeline_everywhere() -> None:
    """Safety invariant: we must be able to recognise a lifeline on every model."""
    for node_id, node in _nodes().items():
        groups = node.get("association_groups", {}).get("0", {})
        if not groups:
            continue
        assert groups["1"]["is_lifeline"] is True, f"node {node_id} group 1 is not a lifeline"


def test_zen35_button_group_layout_matches_the_prd() -> None:
    """PRD Appendix A: small button N uses groups (3+2N) and (4+2N)."""
    node = _nodes()["36"]
    groups = node["association_groups"]["0"]
    for button, (pressed, held) in {1: (5, 6), 2: (7, 8), 3: (9, 10), 4: (11, 12)}.items():
        assert str(pressed) in groups, f"ZEN35 button {button} pressed group missing"
        assert str(held) in groups, f"ZEN35 button {button} held group missing"


def test_no_node_is_long_range() -> None:
    """PRD 3.4: this network is all classic. An LR node would change the plan."""
    for node_id, node in _nodes().items():
        assert node["node_id"] < 256, f"node {node_id} looks like a Long Range node"
```

Run: `.venv/bin/python -m pytest tests/test_fixture_z2.py -v --no-cov`
Expected: PASS. If `test_zen35_button_group_layout_matches_the_prd` fails, the PRD's
Appendix A is wrong; record the real layout in `docs/stage0-report.md` and amend the test
to the observed truth rather than forcing the device to match the document.

- [ ] **Step 5: Commit**

```bash
git add tools/probe_zwave_ws.js tests/fixtures/z2_associations.json tests/test_fixture_z2.py
git commit -m "feat(stage0): capture live Z-Wave association topology (Z2)"
```

---

### Task 4: Z6 configuration parameter value ids

**Files:**
- Create: `tests/fixtures/z6_config_values.json`
- Test: `tests/test_fixture_z6.py`

- [ ] **Step 1: Capture the values**

Extend `tools/probe_zwave_ws.js` (or add `tools/probe_zwave_params.js`) to read, from the
`start_listening` state dump, every value whose `commandClass` is 112 (0x70) for nodes 36,
37, 39, and emit `{node_id, property, property_key, endpoint, value, metadata: {label, min,
max, states, writeable}}`. Save through `envelope("z6_config_values", ...)`.

- [ ] **Step 2: Assert the settings adapters have somewhere to write**

```python
"""Z6: the parameters the settings adapters need must exist and be writeable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z6_config_values.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z6 fixture not captured yet")


def _values(node_id: int) -> dict[tuple[int, int | None], dict]:
    data = json.loads(FIXTURE.read_text())["data"]
    return {
        (v["property"], v.get("property_key")): v
        for v in data
        if v["node_id"] == node_id
    }


def test_zen35_mirror_bit_exists() -> None:
    """mirror_hub_commands maps to Zooz param 35 bit 4 (PRD Appendix A)."""
    values = _values(39)
    assert (35, 4) in values, "ZEN35 param 35 bit 4 not exposed as a value id"
    assert values[(35, 4)]["metadata"]["writeable"] is True


def test_inovelli_mirror_bit_exists() -> None:
    """mirror_hub_commands maps to Inovelli param 59 bit 2."""
    values = _values(37)
    assert (59, 2) in values, "VZW32-SN param 59 bit 2 not exposed as a value id"
    assert values[(59, 2)]["metadata"]["writeable"] is True


def test_zen35_report_command_class_parameter_exists() -> None:
    """report_cc maps to Zooz param 33 (FR-F2)."""
    assert (33, None) in _values(39), "ZEN35 param 33 missing"
```

Run: `.venv/bin/python -m pytest tests/test_fixture_z6.py -v --no-cov`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tools/ tests/fixtures/z6_config_values.json tests/test_fixture_z6.py
git commit -m "feat(stage0): capture config parameter value ids for settings adapters (Z6)"
```

---

### Task 5: Z3 approved write test (node 36, group 8, add then remove node 1)

**This is one of the two approved device writes. Read `CLAUDE.md` Section 3 before starting.**
Node 36 group 8 only. If the read-before step shows group 8 is NOT empty, **stop, do not
write**, and record the finding in the report: the PRD assumed it was unused.

**Files:**
- Create: `tools/probe_zwave_write.py`
- Create: `tests/fixtures/z3_write_roundtrip.json`

- [ ] **Step 1: Write the guard rails first**

`tools/probe_zwave_write.py` must refuse anything outside the sandbox before it connects:

```python
"""Stage 0 Z3: prove the Z-Wave association write path on the one approved sandbox.

Approved sandbox, and nothing else: node 36 (Bedroom Scene Controller, Zooz ZEN35),
association group 8 ("Button 2 - Held"), adding and then removing node 1 (the controller).
Any other target is refused before a connection is opened.
"""

from __future__ import annotations

import sys

APPROVED_SOURCE_NODE = 36
APPROVED_GROUP = 8
APPROVED_TARGET_NODE = 1


def assert_in_sandbox(source_node: int, group: int, target_node: int) -> None:
    """Refuse any write Jayant has not approved. Called before anything connects."""
    if (source_node, group, target_node) != (
        APPROVED_SOURCE_NODE,
        APPROVED_GROUP,
        APPROVED_TARGET_NODE,
    ):
        raise SystemExit(
            f"REFUSED: node {source_node} group {group} target {target_node} is outside "
            f"the approved Stage 0 sandbox (node {APPROVED_SOURCE_NODE} group "
            f"{APPROVED_GROUP} target {APPROVED_TARGET_NODE}). "
            "Get explicit approval from Jayant for this specific write first."
        )


if __name__ == "__main__":
    assert_in_sandbox(*(int(a) for a in sys.argv[1:4]))
```

- [ ] **Step 2: Test the guard rails before touching hardware**

`tests/test_probe_write_guard.py`:

```python
"""The write sandbox guard must refuse everything it was not explicitly approved for."""

from __future__ import annotations

import pytest

from tools.probe_zwave_write import assert_in_sandbox


def test_the_approved_write_is_allowed() -> None:
    assert_in_sandbox(36, 8, 1)  # must not raise


@pytest.mark.parametrize(
    ("node", "group", "target"),
    [
        (36, 1, 1),   # lifeline: never
        (36, 2, 1),   # a group the bedroom design uses
        (37, 8, 1),   # a different node
        (36, 8, 37),  # a different target
        (39, 8, 1),   # Bedside Light R, not approved
    ],
)
def test_everything_else_is_refused(node: int, group: int, target: int) -> None:
    with pytest.raises(SystemExit, match="REFUSED"):
        assert_in_sandbox(node, group, target)
```

Run: `.venv/bin/python -m pytest tests/test_probe_write_guard.py -v --no-cov`
Expected: PASS, 6 passed

- [ ] **Step 3: Read before write**

Read node 36 group 8 through the same read path as Task 3 and save it as
`before` in the fixture. **If it is non-empty, stop here** and write the finding into
`docs/stage0-report.md` under Z3 as "not executed: group 8 was not empty".

- [ ] **Step 4: Execute the round trip**

Add node 1 to node 36 group 8, wait for the result, re-read, remove it, re-read.
Record wall-clock timing for each operation. Record whether the driver's cached
`get_associations` reflected the change immediately or needed
`node.async_refresh_cc_values(CommandClass.ASSOCIATION)`. That answer determines whether
FR-B4 deep verify is required after every write or only on demand.

- [ ] **Step 5: Prove restoration**

The fixture must contain `before`, `after_add`, `after_remove`, and a computed
`restored: true`. Assert it in `tests/test_fixture_z3.py`:

```python
"""Z3: the write path works and left the device exactly as it was found."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z3_write_roundtrip.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z3 not executed yet")


def test_the_write_landed_and_was_then_undone() -> None:
    data = json.loads(FIXTURE.read_text())["data"]

    assert data["before"] == [], "group 8 was expected to be unused"
    assert data["after_add"] == [{"node_id": 1, "endpoint": None}], "the add did not land"
    assert data["after_remove"] == data["before"], "the device was not restored"
    assert data["restored"] is True


def test_timing_was_recorded_for_the_executor_budget() -> None:
    """FR-A2 needs real numbers to set timeouts and retry backoff."""
    data = json.loads(FIXTURE.read_text())["data"]
    assert data["timing_ms"]["add"] > 0
    assert data["timing_ms"]["remove"] > 0
```

Run: `.venv/bin/python -m pytest tests/test_fixture_z3.py -v --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/probe_zwave_write.py tests/test_probe_write_guard.py \
        tests/fixtures/z3_write_roundtrip.json tests/test_fixture_z3.py
git commit -m "feat(stage0): prove the Z-Wave association write path (Z3, approved sandbox)"
```

---

### Task 6: Z8 approved LED parameter write and Indicator CC verdict

**The second and last approved device write.** Node 36, the LED-mode parameter for small
button 2 (param 3). Record the current value first and restore it.

**Files:**
- Create: `tests/fixtures/z8_led_path.json`
- Test: `tests/test_fixture_z8.py`

- [ ] **Step 1: Record the current value, write, read back, restore**

Same read-before/restore discipline as Task 5. Record latency. Then, without writing,
inspect whether node 36 supports Indicator CC (0x87) and whether it exposes per-button
indicator ids in its value list. This decides hybrid leg kind (c) per Decision D6.

- [ ] **Step 2: Assert the verdict is recorded**

```python
"""Z8: decides how hybrid leg kind (c) drives scene-controller button LEDs (D6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z8_led_path.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z8 not executed yet")


def test_the_parameter_was_restored() -> None:
    data = json.loads(FIXTURE.read_text())["data"]
    assert data["param_before"] == data["param_after_restore"], "LED mode was not restored"


def test_the_indicator_cc_verdict_is_explicit() -> None:
    """Decision D6 needs a yes or no, not a maybe."""
    data = json.loads(FIXTURE.read_text())["data"]
    assert isinstance(data["indicator_cc_supported"], bool)
    if data["indicator_cc_supported"]:
        assert data["indicator_ids"], "Indicator CC is supported but no ids were recorded"
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/z8_led_path.json tests/test_fixture_z8.py
git commit -m "feat(stage0): LED parameter path and Indicator CC verdict (Z8, approved)"
```

---

### Task 7: G1 Zigbee2MQTT bridge capture (read-only)

**Files:**
- Create: `tools/probe_zigbee.py`
- Create: `tests/fixtures/g1_bridge_devices.json`, `tests/fixtures/g1_bridge_groups.json`, `tests/fixtures/g1_bridge_info.json`
- Test: `tests/test_fixture_g1.py`

- [ ] **Step 1: Capture the retained topics**

Subscribe to `zigbee2mqtt/bridge/devices`, `bridge/groups`, `bridge/info` on the Mosquitto
broker and write the first retained message from each. Run it from the SSH add-on with
`mosquitto_sub -h core-mosquitto`, or from HA Core using `aiomqtt`. Read-only: never
publish to a `bridge/request/...` topic in this task.

- [ ] **Step 2: Assert assumption A3 is closed**

```python
"""G1 closes PRD assumption A3 about the bridge/devices schema on Z2M 2.14.1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "g1_bridge_devices.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="G1 fixture not captured yet")


def _devices() -> list[dict]:
    return json.loads(FIXTURE.read_text())["data"]


def test_endpoints_expose_bindings_and_clusters() -> None:
    """A3: per-endpoint bindings, clusters.input/output, configured_reportings."""
    with_endpoints = [d for d in _devices() if d.get("endpoints")]
    assert with_endpoints, "no device reported endpoints"

    sample = with_endpoints[0]["endpoints"]
    first = next(iter(sample.values()))
    assert "bindings" in first, "A3 is wrong: no per-endpoint bindings key"
    assert "clusters" in first and "output" in first["clusters"], "no output clusters"
    assert "configured_reportings" in first


def test_inovelli_blue_paddle_endpoint_is_bindable() -> None:
    """PRD 3.2: VZM31-SN endpoint 2 is the paddle client endpoint."""
    blues = [d for d in _devices() if d.get("definition", {}).get("model") == "VZM31-SN"]
    assert blues, "no Inovelli Blue VZM31-SN found"

    ep2 = blues[0]["endpoints"]["2"]
    outputs = ep2["clusters"]["output"]
    assert "genOnOff" in outputs, "EP2 does not emit genOnOff; the PRD binding plan is wrong"
    assert "genLevelCtrl" in outputs, "EP2 does not emit genLevelCtrl"


def test_the_coordinator_is_identifiable() -> None:
    """FR-B5 classifies coordinator bindings as system links, so we must spot it."""
    coordinators = [d for d in _devices() if d.get("type") == "Coordinator"]
    assert len(coordinators) == 1, f"expected exactly one coordinator, got {len(coordinators)}"
```

- [ ] **Step 3: Commit**

```bash
git add tools/probe_zigbee.py tests/fixtures/g1_*.json tests/test_fixture_g1.py
git commit -m "feat(stage0): capture Zigbee2MQTT bridge state, closing assumption A3 (G1)"
```

---

### Task 8: M1 Matter feasibility (read-only)

**Files:**
- Create: `tools/probe_matter.py`
- Create: `tests/fixtures/m1_matter.json`
- Test: `tests/test_fixture_m1.py`

- [ ] **Step 1: Probe the client and read the attributes**

From inside HA Core, confirm how a custom integration reaches the `matter` client on
2026.8.3 (assumption A4) and read, for the two Inovelli White switches, the Aqara H2 and the
BILRESA button: `Descriptor.ClientList` (endpoint/29/2) and `Binding.Binding` (endpoint/30/0).
For one Eve Energy read `AccessControl.ACL` (0/31/0) plus
`SubjectsPerAccessControlEntry`, `TargetsPerAccessControlEntry`,
`AccessControlEntriesPerFabric`. Write nothing.

- [ ] **Step 2: Assert a Phase 3 verdict exists**

```python
"""M1: closes assumption A4 and gives Phase 3 a go or no-go."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "m1_matter.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="M1 fixture not captured yet")


def test_the_client_api_verdict_is_explicit() -> None:
    data = json.loads(FIXTURE.read_text())["data"]
    assert isinstance(data["read_attribute_available"], bool)
    assert isinstance(data["write_attribute_available"], bool)
    assert data["accessor_notes"], "record how the client was reached, for Phase 3"


def test_at_least_one_real_binding_source_exists() -> None:
    """Phase 3 is only worth building if this network has a source to bind from."""
    data = json.loads(FIXTURE.read_text())["data"]
    sources = [d for d in data["devices"] if d.get("client_clusters")]
    assert sources, "no Matter device exposes client clusters; revisit Decision D11"


def test_acl_capacity_was_recorded() -> None:
    """E27 and E28 need real capacity numbers to produce useful errors."""
    data = json.loads(FIXTURE.read_text())["data"]
    assert data["acl_capacity"]["entries_per_fabric"] > 0
```

- [ ] **Step 3: Commit**

```bash
git add tools/probe_matter.py tests/fixtures/m1_matter.json tests/test_fixture_m1.py
git commit -m "feat(stage0): Matter binding and ACL feasibility, closing A4 (M1)"
```

---

### Task 9: The deploy tool

**Files:**
- Create: `tools/ha_deploy.py`
- Test: `tests/test_ha_deploy.py`
- Create: `docs/dev-deploy.md`

Stdlib only (`urllib`, `zipfile`, `json`, `shutil`, `hashlib`, `compileall`, `argparse`).
It runs on the HA host, where nothing but the standard library is guaranteed.

- [ ] **Step 1: Write the failing tests**

```python
"""The deploy tool must fail safe: a bad archive never reaches custom_components."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from tools.ha_deploy import DeployError, extract_component, verify_archive


def _archive(files: dict[str, str], root: str = "ha-device-links-abc123") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(f"{root}/{name}", body)
    return buf.getvalue()


def test_a_valid_archive_passes() -> None:
    data = _archive(
        {
            "custom_components/device_links/manifest.json": json.dumps({"domain": "device_links"}),
            "custom_components/device_links/__init__.py": "",
        }
    )
    assert verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links") == (
        "ha-device-links-abc123"
    )


def test_an_archive_without_the_component_is_refused() -> None:
    data = _archive({"README.md": "nothing here"})
    with pytest.raises(DeployError, match="manifest.json"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_a_domain_mismatch_is_refused() -> None:
    data = _archive(
        {"custom_components/device_links/manifest.json": json.dumps({"domain": "something_else"})}
    )
    with pytest.raises(DeployError, match="domain"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_path_traversal_in_the_archive_is_refused(tmp_path: Path) -> None:
    """A zip entry escaping the target directory must never be written."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/custom_components/device_links/manifest.json", '{"domain":"device_links"}')
        zf.writestr("root/custom_components/device_links/../../../etc/evil", "pwned")

    with pytest.raises(DeployError, match="escapes"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", tmp_path
        )
    assert not (tmp_path.parent / "etc" / "evil").exists()


def test_extract_writes_only_the_component_subtree(tmp_path: Path) -> None:
    data = _archive(
        {
            "custom_components/device_links/manifest.json": '{"domain":"device_links"}',
            "custom_components/device_links/const.py": "X = 1",
            "docs/PRD.md": "should not be deployed",
            "tests/test_x.py": "should not be deployed",
        }
    )
    extract_component(
        zipfile.ZipFile(io.BytesIO(data)), "ha-device-links-abc123", "device_links", tmp_path
    )

    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "const.py").read_text() == "X = 1"
    assert not (tmp_path / "docs").exists(), "only custom_components/<domain> is deployed"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_ha_deploy.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'DeployError'`

- [ ] **Step 3: Implement `tools/ha_deploy.py`**

Implement `verify_archive`, `extract_component`, and the `deploy`, `rollback`, `status`
subcommands exactly as PRD Section 17.5 step 2 specifies: resolve the branch head through
`https://api.github.com/repos/<owner>/<repo>/commits/<branch>`, download
`https://codeload.github.com/<owner>/<repo>/zip/<sha>`, verify, extract to
`/config/custom_components/.<domain>.new`, run `compileall`, hash-diff against the current
directory, back up to `/config/<domain>/backups/<timestamp>-<oldsha>/` keeping the last 5,
swap atomically, write `.deployed`, and print one JSON object with `ok`, `commit`,
`previous_commit`, `changed_files`, `restart_required`, `browser_reload`.

`restart_required` is true when any changed path is outside `frontend/`.
It must never restart Home Assistant, never reload a config entry, and never touch `.storage`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ha_deploy.py -v --no-cov`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ha_deploy.py tests/test_ha_deploy.py
git commit -m "feat(stage0): pull-based GitHub to Home Assistant deploy tool"
```

---

### Task 10: R2 deploy bootstrap and round trip

- [ ] **Step 1: Install the tool on the HA host**

```bash
ssh root@10.10.1.11 'mkdir -p /config/tools'
scp tools/ha_deploy.py root@10.10.1.11:/config/tools/ha_deploy.py
```

This is the one and only file we place in `/config` (CLAUDE.md Section 3 rule 9).

- [ ] **Step 2: Run a real deploy and confirm it is inert until restart**

```bash
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py deploy \
  --repo jayanty/ha-device-links --branch dev --domain device_links'
```

Expected: a single JSON object with `"ok": true`, a `commit` equal to
`git rev-parse origin/dev`, and `"restart_required": true`.
Then confirm the component landed and nothing else changed:

```bash
ssh root@10.10.1.11 'ls /config/custom_components/device_links && \
  cat /config/custom_components/device_links/.deployed'
```

- [ ] **Step 3: Prove rollback**

```bash
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py rollback --domain device_links'
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py status --domain device_links'
```

Expected: rollback prints `"ok": true` and status reports the previous commit.
Re-deploy afterwards so the host is left on the newest `dev` commit.

- [ ] **Step 4: Add the shell_command block for the MCP path**

Append to `/config/configuration.yaml` (the only edit we make to Jayant's configuration),
after confirming no `shell_command:` key already exists:

```yaml
shell_command:
  deploy_device_links: "python3 /config/tools/ha_deploy.py deploy --repo jayanty/ha-device-links --branch dev --domain device_links"
  rollback_device_links: "python3 /config/tools/ha_deploy.py rollback --domain device_links"
  device_links_deploy_status: "python3 /config/tools/ha_deploy.py status --domain device_links"
```

**Do not restart Home Assistant to load it.** Create a persistent notification telling
Jayant that a restart will activate both `shell_command` and the newly deployed component,
and continue using the SSH invocation until then.

- [ ] **Step 5: Document and commit**

Write `docs/dev-deploy.md` covering the loop, the JSON contract, rollback, and what to do
when the tool itself is broken (SSH fallback). Commit.

```bash
git add docs/dev-deploy.md
git commit -m "docs(stage0): document the dev deploy loop"
```

---

### Task 11: Z7 Zooz small-button Basic Set semantics

The "Off all" template (UC4) compiles differently depending on whether a Zooz small button
sends a fixed ON, a fixed OFF, or alternates. Getting this wrong produces a button that
toggles lights instead of turning them off. Answer it before Phase 1 compiles anything.

**Files:**
- Create: `tests/fixtures/z7_button_semantics.json`
- Test: `tests/test_fixture_z7.py`

- [ ] **Step 1: Read the manuals first**

For the ZEN35 (node 36/39) and ZEN32 (node 29), record from Zooz's published manuals what
the "Pressed" group emits: Basic Set with a fixed value, an alternating value, or a value
governed by a parameter. Record the manual URL and the exact wording in the fixture under
`documented`.

- [ ] **Step 2: Confirm against the wire, reusing the Z3 window**

While node 1 is temporarily in node 36 group 8 (Task 5, between the add and the remove),
have the Z-Wave JS UI debug log running and record what arrives at the controller when
button 2 is held. The controller only sees association traffic when it is itself a member
of the group, which is exactly the Z3 state.

If the Z3 window has already been closed, do **not** reopen it: mark `observed` as
`"not captured"` and rely on the documented behaviour, noting the reduced confidence in the
report. Do not open a new write window for this.

- [ ] **Step 3: Assert the compiler has an unambiguous answer**

```python
"""Z7: how a Zooz small button's Pressed group behaves decides the Off-all compilation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "z7_button_semantics.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="Z7 fixture not captured yet")


def test_every_model_has_a_definite_semantic() -> None:
    data = json.loads(FIXTURE.read_text())["data"]

    for model in ("ZEN35", "ZEN32"):
        assert model in data, f"no Z7 finding recorded for {model}"
        semantic = data[model]["semantic"]
        assert semantic in {"always_on", "always_off", "alternating", "parameter_governed"}, (
            f"{model} semantic {semantic!r} is not one the compiler can act on"
        )


def test_the_source_of_each_finding_is_recorded() -> None:
    """A documented-only finding is acceptable, but it must be labelled as such."""
    data = json.loads(FIXTURE.read_text())["data"]

    for model, finding in data.items():
        assert finding["documented"], f"{model} has no manual reference"
        assert "observed" in finding, f"{model} does not say whether it was seen on the wire"
```

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/z7_button_semantics.json tests/test_fixture_z7.py
git commit -m "feat(stage0): Zooz small-button Basic Set semantics for Off-all (Z7)"
```

---

### Task 12: P1 panel spike

Proves the custom panel can be registered and that the Home Assistant web components the
UI spec depends on are actually loadable on 2026.8.3. If a component is missing, the UI
spec in PRD Section 7 needs amending before Phase 1 builds against it.

**Files:**
- Create: `tools/spike_panel/` (a throwaway custom component, not shipped)
- Create: `docs/stage0-panel-spike.md`

- [ ] **Step 1: Build the throwaway integration**

A minimal component that in `async_setup_entry` calls
`hass.http.async_register_static_paths([StaticPathConfig(url, path, False)])` and
`panel_custom.async_register_panel(hass, webcomponent_name=..., frontend_url_path=...,
sidebar_title=..., sidebar_icon="mdi:link-variant", module_url=..., embed_iframe=False,
require_admin=True)`, serving one ES module that force-loads components via
`window.loadCardHelpers()` and reports which ones resolved.

- [ ] **Step 2: Deploy it and check it without restarting**

Deploy with the Task 9 tool to a `spike/panel` branch, then tell Jayant a restart is needed
and **stop**. This spike is the one place where waiting for a restart is unavoidable. Do
other tasks meanwhile; return to it once the restart has happened.

- [ ] **Step 3: Record which components resolved**

The module must list, for each of `ha-top-app-bar-fixed`, `ha-menu-button`, `ha-tabs`,
`ha-tab-group`, `ha-card`, `ha-data-table`, `ha-dialog`, `ha-form`, `ha-alert`, `ha-button`,
`ha-icon-button`, `ha-switch`, `ha-select`, `ha-list-item`, `ha-expansion-panel`,
`ha-chip-set`, `ha-assist-chip`, `ha-spinner`, `ha-markdown`, `ha-svg-icon`, whether
`customElements.whenDefined` resolved within 5 s. Write the results to
`docs/stage0-panel-spike.md` with a screenshot from desktop and from the companion app.

Any component that does not resolve gets a documented fallback in the report, because
PRD Section 7.1 requires the panel to degrade gracefully rather than break.

- [ ] **Step 4: Commit**

```bash
git add tools/spike_panel docs/stage0-panel-spike.md
git commit -m "feat(stage0): panel registration spike and HA component availability (P1)"
```

---

### Task 13: P2 entity attachment spike

FR-E1 attaches rule entities to the existing `zwave_js`, `mqtt`, and `matter` device
entries. That only works if we know each integration's exact identifier format, and it must
not damage the upstream device when we unload.

**Files:**
- Create: `tests/fixtures/p2_device_identifiers.json`
- Test: `tests/test_fixture_p2.py`

- [ ] **Step 1: Record the identifier format for each integration**

Read the device registry over MCP or SSH and record, for one real device per backend, the
`identifiers` set and `config_entries`: a `zwave_js` device (node 36), a Zigbee2MQTT device
under `mqtt` ("Entrance Inside Lights"), and a `matter` device (an Inovelli White switch).

- [ ] **Step 2: Assert the formats are what the entity code will rely on**

```python
"""P2: rule entities attach to existing devices, so identifier formats must be exact."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "p2_device_identifiers.json"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="P2 fixture not captured yet")


def _by_backend() -> dict[str, dict]:
    return json.loads(FIXTURE.read_text())["data"]


def test_every_backend_has_a_recorded_identifier_format() -> None:
    captured = _by_backend()
    for backend in ("zwave_js", "mqtt", "matter"):
        assert backend in captured, f"no identifier sample captured for {backend}"
        assert captured[backend]["identifiers"], f"{backend} sample has no identifiers"


def test_zwave_identifier_is_domain_and_home_node() -> None:
    """zwave_js uses (DOMAIN, f"{home_id}-{node_id}"), which our handles must mirror."""
    sample = _by_backend()["zwave_js"]
    domain, value = sample["identifiers"][0]

    assert domain == "zwave_js"
    assert "-" in value, f"unexpected zwave_js identifier shape: {value!r}"


def test_unload_leaves_the_upstream_device_intact() -> None:
    """Attaching must never make us an owner of someone else's device entry."""
    sample = _by_backend()["zwave_js"]
    assert sample["upstream_config_entries_after_unload"] == sample["upstream_config_entries"], (
        "unloading the spike changed the upstream device's config entries"
    )
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/p2_device_identifiers.json tests/test_fixture_p2.py
git commit -m "feat(stage0): device identifier formats for entity attachment (P2)"
```

---

### Task 14: The Stage 0 report

**Files:**
- Create: `docs/stage0-report.md`

- [ ] **Step 1: Write the report**

One section per Stage 0 item (Z1-Z8, G1, G2, M1, P1, P2, R1, R2, D1). Each states:
what was run, the verdict, the fixture path, and whether it was executed or deferred.
A table at the top closes or amends assumptions A1, A2, A3, A4 with the evidence.
A second table records every decision-register default that was applied without an answer
from Jayant, per PRD Section 0 rule 4.

State plainly and without softening: Z4 and G2 were **not executed** because they were not
approved, so sleeping-node writes and the Zigbee write path remain unproven against
hardware. Z5 needs Jayant to make a manual edit in Z-Wave JS UI and is deferred; the report
must say what drift detection falls back to if the event does not materialise (periodic
verify per FR-B3).

- [ ] **Step 2: Verify every assumption is addressed**

Run: `grep -c "^| A[1-4]" docs/stage0-report.md`
Expected: `4`

- [ ] **Step 3: Commit and open the PR to main**

```bash
git add docs/stage0-report.md
git commit -m "docs(stage0): validation report closing assumptions A1-A4"
git push origin dev
gh pr create --base main --head dev --title "Stage 0: validation, fixtures, and the deploy loop" \
  --body "Closes Stage 0. See docs/stage0-report.md."
```

Expected: CI green on the PR before merge. `main` is protected and will refuse otherwise.

---

## Stage 0 exit criteria

Do not start Phase 1 until all of these hold:

- [ ] All read-only items complete: Z1, Z2, Z6, Z7, G1, M1, P1, P2
- [ ] R1 and D1 complete (done: repository created, CI green)
- [ ] Z3 executed and restored, or explicitly recorded as not executed
- [ ] Z8 executed and restored, giving Decision D6 a definite answer
- [ ] Z4 and G2 recorded as deferred and unapproved, with the affected paths flagged
- [ ] Assumptions A1-A4 closed or amended in `docs/stage0-report.md`
- [ ] Fixtures committed under `tests/fixtures/` and asserted by tests
- [ ] `scripts/lint` and `scripts/test` exit 0, and CI is green on `main`
