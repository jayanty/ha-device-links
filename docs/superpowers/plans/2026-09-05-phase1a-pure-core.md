# Phase 1A: the pure core (models, capabilities, compiler, planner)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the part of Device Links that decides *what should exist on the devices*, as pure Python that never imports Home Assistant, driven by the real fixtures Stage 0 captured.

**Architecture:** Four pure modules with one job each. `models.py` holds the value types. `backends/zwave_protocol.py` turns a raw Z-Wave association-group dump into a normalized capability model. `compiler.py` turns a user's rule into concrete links plus setting writes. `planner.py` diffs desired against observed and produces a plan. None of them do I/O, none import `homeassistant`, and all of them are tested against the JSON captured from Jayant's real network rather than against invented data.

**Tech Stack:** Python 3.14, dataclasses, `mypy --strict`, pytest, Hypothesis.

---

## Why this is Phase 1's foundation

Everything later in Phase 1 (the Z-Wave adapter, the executor, the entities, the panel) is
I/O and presentation around this core. If the core is right, the rest is plumbing. If it is
wrong, the bug reaches a user's lights.

Two properties make that safe, and both are why these modules must stay HA-free:

1. They can be tested exhaustively without the Home Assistant test harness, including with
   property-based tests that run thousands of generated cases.
2. They can be driven directly from `tests/fixtures/*.json`, which are byte-for-byte what
   Jayant's devices actually reported, so "works on my machine" means "works on the
   hardware this was built for".

`tests/test_manifest.py::test_pure_modules_never_import_home_assistant` already enforces the
no-HA-imports rule for exactly these file paths. It currently skips because the files do not
exist. Once you create them it starts asserting, so do not add an HA import expecting to
remove it later.

---

## Ground rules

Read `CLAUDE.md` first, then `docs/stage0-report.md`. The rules that bite in this phase:

- **No `homeassistant` import in any file this plan creates.** Not even under `TYPE_CHECKING`.
- **No I/O.** No file reads, no network, no clock reads that are not injected as a parameter.
  A pure function given the same inputs must return the same output forever.
- **No em dash** anywhere. A test enforces it.
- `mypy --strict` clean, no `Any` in public signatures.
- Coverage: these modules are inside `custom_components/device_links`, so every line counts
  toward the 95% gate. PRD Section 16 asks for **100% on pure modules**. Do not add
  `# pragma: no cover` to reach it; add the missing test.
- Run `./scripts/lint` and `./scripts/test` before every commit and check the exit codes.
- Conventional commits ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## Facts from Stage 0 that this plan is built on

Do not re-derive these. They come from `tests/fixtures/z2_associations.json`, captured live.

**Command class ids as they appear in `issued_commands`** (string keys, integer commands):

| CC | Name | Commands seen |
|---|---|---|
| `"32"` | Basic (0x20) | `1` = Basic Set |
| `"38"` | Multilevel Switch (0x26) | `1` = Set, `3` = Report, `4` = Start Level Change, `5` = Stop Level Change |
| `"43"` | Scene Activation (0x2B) | `1` = Scene Activation Set |
| `"37"` | Binary Switch (0x25) | `1` = Set |

**Real group layouts** (endpoint 0, group 1 is always the lifeline and always excluded):

Zooz ZEN35 (node 36), 12 groups, `max_nodes` 10, `multi_channel` true:

| Group | Profile | Issued | Label |
|---|---|---|---|
| 2 | 8193 | `{"32": [1]}` | Main Button - Pressed (Basic Set) |
| 3 | 8193 | `{"38": [1]}` | Main Button - Held (MultiLevel) |
| 4 | 8193 | `{"38": [4]}` | Main Button - Start / Stop (MultiLevel) |
| 5, 6 | 8194 | `{"32":[1]}`, `{"38":[4]}` | Button 1 - Pressed / Held |
| 7, 8 | 8195 | same | Button 2 - Pressed / Held |
| 9, 10 | 8196 | same | Button 3 - Pressed / Held |
| 11, 12 | 8197 | same | Button 4 - Pressed / Held |

Inovelli VZW32-SN (node 37), 7 groups, `max_nodes` 10:

| Group | Profile | Issued | Label |
|---|---|---|---|
| 2 | 8193 | `{"32": [1]}` | Basic Set |
| 3 | 8194 | `{"38": [1]}` | Multilevel Switch Set |
| 4 | 8195 | `{"38": [4, 5]}` | Multilevel Switch Start/Stop |
| 5 | 8196 | `{"32": [1]}` | Basic Set Double-tap |
| 6 | 8197 | `{"32": [1]}` | Basic Set Triple-tap |
| 7 | 8198 | `{"32": [1]}` | Multilevel Switch Set (Config Button) |

Zooz ZEN37 800LR (node 40), 9 groups, **`max_nodes` 5**:

| Group | Profile | Issued | Label |
|---|---|---|---|
| 2 | 8193 | `{"32": [1]}` | On/Off Control (Button 1 & 2) |
| 3 | 8194 | `{"32": [1]}` | On/Off Control (Button 3 & 4) |
| 4 | 8193 | `{"38": [4]}` | Dimmer Control (Button 1 & 2) |
| 5 | 8194 | `{"38": [4]}` | Dimmer Control (Button 3 & 4) |
| 6 | 8195 | `{"32": [1]}` | Toggle Control (Button 1) |
| 7 | **null** | `{"32": [1]}` | Toggle Control (Button 2) |
| 8 | 8197 | `{"32": [1]}` | Toggle Control (Button 3) |
| 9 | 8198 | `{"32": [1]}` | Toggle Control (Button 4) |

### The finding that shapes this whole phase

AGI `profile` is `0x2000 | keyN`, so it is meant to say which physical control a group
belongs to. **It is only trustworthy on one of the three models.**

- ZEN35: profile groups the button pairs perfectly. 8193 covers the main button's three
  groups, 8194 covers button 1's two groups, and so on.
- **Inovelli: every group has a distinct profile**, even though groups 2, 3 and 4 are all the
  same physical paddle. Grouping by profile would split one paddle into three emitters and
  make "paddle controls light with dimming" impossible to express as one rule.
- **ZEN37: group 7's profile is `null`**, and the sequence skips 8196. Grouping by profile
  would drop button 2 entirely or misfile it.

So emitter identity cannot be derived from profile alone, and it cannot be derived from
labels alone either (Inovelli's labels share no common prefix). The design that follows
uses three tiers, most specific first: a curated profile-database entry keyed by fingerprint,
then AGI profile but only when it partitions cleanly, then one emitter per group as a
conservative fallback for unknown hardware.

---

## File structure

| File | Responsibility |
|---|---|
| `custom_components/device_links/models.py` | Value types shared by every layer: fingerprints, handles, features, emitters, capabilities, links, rules, profiles, plans. No behavior beyond validation and identity. |
| `custom_components/device_links/backends/zwave_protocol.py` | Pure Z-Wave interpretation: classify issued commands into features, derive emitters from a raw group dump, map check-result codes to blocked reasons. |
| `custom_components/device_links/profiles_db/` | JSON device profiles plus `schema.json`. Data, not code. |
| `custom_components/device_links/profile_db.py` | Loads and validates profile JSON into typed models. Pure: takes already-read text, does no file I/O of its own. |
| `custom_components/device_links/compiler.py` | `compile_rule(rule, capabilities) -> CompiledRule`. Turns intent into links, settings and warnings. |
| `custom_components/device_links/planner.py` | `build_plan(desired, observed, options) -> Plan`. Diff, capacity, safety, unmanaged classification. |

---

### Task 1: Core value types and link identity

**Files:**
- Create: `custom_components/device_links/models.py`
- Test: `tests/test_models.py`

The single most important thing here is `Link.fingerprint`. A link's identity is what lets
the planner say "this desired link already exists" and "this observed link is unmanaged".
Get it wrong and the integration either re-writes links that are already present or fails to
recognise its own work after a restart.

- [ ] **Step 1: Write the failing tests**

```python
"""Value types, and the link identity everything else depends on."""

from __future__ import annotations

import pytest

from custom_components.device_links.models import (
    Backend,
    DeviceHandle,
    Feature,
    Link,
    LinkTarget,
    ZWaveFingerprint,
)


def _handle(node_id: int = 36, name: str = "Bedroom Scene Controller") -> DeviceHandle:
    return DeviceHandle(
        backend=Backend.ZWAVE,
        protocol_id=f"3538613642:{node_id}",
        ha_device_id="1f50c99924ffdc3f767cdcdb9f6b6294",
        fingerprint=ZWaveFingerprint(
            manufacturer_id=634, product_type=28672, product_id=40984, firmware="1.40.0"
        ),
        name_at_authoring=name,
    )


def test_a_handle_is_identified_by_protocol_id_not_by_name() -> None:
    """Renames and area moves must never break a rule (FR-S1)."""
    original = _handle(name="Bedroom Scene Controller")
    renamed = _handle(name="Master Bedroom Scene Controller")

    assert original.identity == renamed.identity
    assert original.identity == "zwave:3538613642:36"


def test_handles_for_different_nodes_are_different() -> None:
    assert _handle(36).identity != _handle(37).identity


def test_link_fingerprint_is_stable_across_equal_links() -> None:
    """Two links describing the same device state must share a fingerprint."""
    first = Link(
        backend=Backend.ZWAVE,
        source=_handle(36),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=_handle(38), endpoint=None),
        feature=Feature.ON_OFF,
    )
    second = Link(
        backend=Backend.ZWAVE,
        source=_handle(36, name="renamed since"),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=_handle(38), endpoint=None),
        feature=Feature.ON_OFF,
    )

    assert first.fingerprint == second.fingerprint


@pytest.mark.parametrize(
    "change",
    ["emitter", "target", "endpoint", "feature", "source"],
)
def test_link_fingerprint_changes_when_the_link_does(change: str) -> None:
    """Anything that changes what is written to the device must change identity."""
    base = Link(
        backend=Backend.ZWAVE,
        source=_handle(36),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=_handle(38), endpoint=None),
        feature=Feature.ON_OFF,
    )
    variants = {
        "emitter": Link(**{**base.as_kwargs(), "emitter_id": "g9"}),
        "target": Link(**{**base.as_kwargs(), "target": LinkTarget(_handle(37), None)}),
        "endpoint": Link(**{**base.as_kwargs(), "target": LinkTarget(_handle(38), 2)}),
        "feature": Link(**{**base.as_kwargs(), "feature": Feature.LEVEL_HOLD}),
        "source": Link(**{**base.as_kwargs(), "source": _handle(39)}),
    }

    assert variants[change].fingerprint != base.fingerprint


def test_a_link_cannot_target_its_own_source() -> None:
    """E7: a node cannot be a member of its own association group."""
    handle = _handle(36)
    with pytest.raises(ValueError, match="cannot control itself"):
        Link(
            backend=Backend.ZWAVE,
            source=handle,
            source_endpoint=0,
            emitter_id="g7",
            target=LinkTarget(handle=handle, endpoint=None),
            feature=Feature.ON_OFF,
        )


def test_value_types_are_immutable() -> None:
    """Plans are compared and hashed; mutable value types would corrupt that."""
    link = Link(
        backend=Backend.ZWAVE,
        source=_handle(36),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=_handle(38), endpoint=None),
        feature=Feature.ON_OFF,
    )
    with pytest.raises(AttributeError):
        link.emitter_id = "g9"  # type: ignore[misc]
```

- [ ] **Step 2: Run and confirm failure**

`.venv/bin/python -m pytest tests/test_models.py -v --no-cov`
Expected: `ModuleNotFoundError` for `custom_components.device_links.models`.

- [ ] **Step 3: Implement**

Create `models.py` with frozen dataclasses and `StrEnum`s. Required names and semantics:

- `Backend(StrEnum)`: `ZWAVE = "zwave"`, `ZIGBEE2MQTT = "zigbee2mqtt"`, `MATTER = "matter"`.
- `Feature(StrEnum)`: `ON_OFF`, `LEVEL_SET`, `LEVEL_HOLD`, `SCENE`, `COLOR`, `STATUS_REPORT`.
- `ZWaveFingerprint`, `ZigbeeFingerprint`, `MatterFingerprint`: frozen dataclasses.
- `DeviceHandle`: `backend`, `protocol_id`, `ha_device_id`, `fingerprint`, `name_at_authoring`.
  Property `identity` returns `f"{backend}:{protocol_id}"` and is what equality-by-device
  means everywhere. `ha_device_id` and `name_at_authoring` are explicitly NOT part of it.
- `LinkTarget`: `handle`, `endpoint: int | None`.
- `Link`: the fields in the test, plus `emitter_group: str` and `rule_id: str | None = None`.
  `__post_init__` raises `ValueError` containing "cannot control itself" when source and
  target identities match. `fingerprint` is a stable string derived from backend, source
  identity, source endpoint, **emitter group**, target identity, target endpoint and feature
  - and from nothing else, so a rename or a rule reassignment does not change it.

  **Why both `emitter_id` and `emitter_group`:** an emitter is one physical control and can
  span several groups. The Inovelli paddle is emitter `paddle` but writes into groups 2, 3
  and 4 depending on the feature. `emitter_id` is what the user picked; `emitter_group` is
  what actually gets written to the device, and it is therefore the one that belongs in the
  fingerprint, because two links differing only in group are two different device writes.
  In the Task 1 tests `emitter_id` and `emitter_group` are both `"g7"`, since a per-group
  emitter uses its own group; give `emitter_group` a default of `None` meaning "same as
  `emitter_id`" only if you also normalise it in `__post_init__`, otherwise pass it
  explicitly everywhere.

- `ObservedLink`: the same shape as `Link` plus `is_system: bool` and a resolved
  `managed_by: str | None`. It carries the same `fingerprint` derivation, so a desired
  `Link` and an observed one describing the same device state compare equal by fingerprint.
  This is what makes the planner's diff work at all.

- `DeviceCapabilities`: frozen, with `handle: DeviceHandle`, `emitters: tuple[Emitter, ...]`,
  `receivable: frozenset[Feature]` (what the device can act on, used to reject a link that
  could do nothing), `is_long_range: bool`, and `settings: Mapping[str, SettingsAdapter]`
  populated from the profile database. `Emitter` itself is defined in Task 3, so add a
  forward-compatible placeholder here and fill it in then, or define `Emitter` in Task 1
  and leave `derive_emitters` to Task 3. Either is fine; be consistent.
- `as_kwargs()` on `Link` returning a dict suitable for `Link(**kwargs)`, used by the tests.

Use `@dataclass(frozen=True, slots=True)`.

- [ ] **Step 4: Confirm the tests pass, and coverage of `models.py` is 100%**

`.venv/bin/python -m pytest tests/test_models.py -v --no-cov`
then `./scripts/test` and read the `models.py` row.

- [ ] **Step 5: Commit**

```bash
git add custom_components/device_links/models.py tests/test_models.py
git commit -m "feat(core): value types and stable link identity"
```

---

### Task 2: Classifying what an association group can do

**Files:**
- Create: `custom_components/device_links/backends/zwave_protocol.py`
- Test: `tests/test_zwave_protocol.py`

This is the function that avoids per-device hardcoding. Given a group's `issued_commands`,
it says which features that group can carry. Everything the compiler does rests on it.

- [ ] **Step 1: Write the failing tests, driven by the real fixture**

```python
"""Feature classification, checked against every group Stage 0 actually captured."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.device_links.models import Feature
from custom_components.device_links.backends.zwave_protocol import features_of_group

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"


def _groups(node_id: int) -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text())["data"]
    node = next(n for n in data["nodes"] if n["node_id"] == node_id)
    return node["association_groups"]["0"]


def test_basic_set_is_on_off() -> None:
    assert features_of_group({"32": [1]}) == frozenset({Feature.ON_OFF})


def test_binary_switch_set_is_also_on_off() -> None:
    """Not every device uses Basic Set; the classifier must not assume it does."""
    assert features_of_group({"37": [1]}) == frozenset({Feature.ON_OFF})


def test_multilevel_set_is_level_set() -> None:
    assert features_of_group({"38": [1]}) == frozenset({Feature.LEVEL_SET})


def test_start_level_change_is_level_hold() -> None:
    assert features_of_group({"38": [4]}) == frozenset({Feature.LEVEL_HOLD})


def test_start_and_stop_together_are_still_just_level_hold() -> None:
    """Inovelli group 4 issues both. Hold-to-dim is one feature, not two."""
    assert features_of_group({"38": [4, 5]}) == frozenset({Feature.LEVEL_HOLD})


def test_multilevel_report_is_a_status_report_not_a_control() -> None:
    """Lifeline issues 38 command 3. Treating a report as control would be a real bug."""
    assert features_of_group({"38": [3]}) == frozenset({Feature.STATUS_REPORT})


def test_scene_activation_is_scene() -> None:
    assert features_of_group({"43": [1]}) == frozenset({Feature.SCENE})


def test_an_unknown_command_class_yields_no_features() -> None:
    """Better to offer nothing than to offer something that does not work."""
    assert features_of_group({"113": [5]}) == frozenset()


def test_an_empty_or_absent_issued_map_yields_no_features() -> None:
    assert features_of_group({}) == frozenset()
    assert features_of_group(None) == frozenset()


@pytest.mark.parametrize("node_id", [36, 37, 40])
def test_every_non_lifeline_group_on_real_hardware_classifies(node_id: int) -> None:
    """A real group that produces no features is an emitter the user cannot use."""
    unclassified = []
    for group_id, group in _groups(node_id).items():
        if group["is_lifeline"]:
            continue
        if not features_of_group(group["issued_commands"]):
            unclassified.append(f"g{group_id} {group['label']!r} {group['issued_commands']}")

    assert not unclassified, f"node {node_id} has groups the classifier cannot use: {unclassified}"


def test_the_lifeline_classifies_as_report_only() -> None:
    """Safety: the lifeline must never look like something a user can control with."""
    lifeline = _groups(36)["1"]
    features = features_of_group(lifeline["issued_commands"])

    assert Feature.ON_OFF not in features
    assert Feature.LEVEL_SET not in features
    assert Feature.LEVEL_HOLD not in features
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement `features_of_group`**

Signature: `def features_of_group(issued: Mapping[str, Sequence[int]] | None) -> frozenset[Feature]`.

Map, using named constants rather than bare numbers:
`(BASIC_CC, SET)` and `(BINARY_SWITCH_CC, SET)` to `ON_OFF`; `(MULTILEVEL_CC, SET)` to
`LEVEL_SET`; `(MULTILEVEL_CC, START_LEVEL_CHANGE)` or `STOP_LEVEL_CHANGE` to `LEVEL_HOLD`;
`(MULTILEVEL_CC, REPORT)` to `STATUS_REPORT`; `(SCENE_ACTIVATION_CC, SET)` to `SCENE`.
Accept both string and integer keys, because JSON gives strings and the driver gives ints.
Unknown pairs contribute nothing.

- [ ] **Step 4: Confirm tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(zwave): classify association groups into features from issued commands"
```

---

### Task 3: Deriving emitters, including where AGI profile lies

**Files:**
- Modify: `custom_components/device_links/backends/zwave_protocol.py`
- Test: `tests/test_zwave_emitters.py`

An **emitter** is one physical control (a paddle, a small button) presented to the user, with
a map from feature to the group that carries it. This task builds the generic derivation.
Task 5 adds the curated overrides that fix Inovelli and the ZEN37.

- [ ] **Step 1: Write the failing tests**

```python
"""Emitter derivation, including the models where AGI profile cannot be trusted.

Stage 0 found that profile groups correctly on the ZEN35, gives every Inovelli group a
distinct profile even though three of them are one paddle, and is null for ZEN37 group 7.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from custom_components.device_links.models import Feature
from custom_components.device_links.backends.zwave_protocol import derive_emitters

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"


def _groups(node_id: int) -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text())["data"]
    node = next(n for n in data["nodes"] if n["node_id"] == node_id)
    return node["association_groups"]["0"]


def test_the_lifeline_never_becomes_an_emitter() -> None:
    """Hard safety rule: the lifeline is not a control the user can pick."""
    emitters = derive_emitters(_groups(36))

    assert all("1" not in e.group_ids for e in emitters)
    assert all(not e.is_lifeline for e in emitters)


def test_zen35_profile_grouping_produces_one_emitter_per_physical_button() -> None:
    """The ZEN35 is the model where AGI profile does the right thing."""
    emitters = {e.emitter_id: e for e in derive_emitters(_groups(36))}

    assert len(emitters) == 5, f"expected main button plus 4 buttons, got {sorted(emitters)}"

    main = next(e for e in emitters.values() if "Main" in e.label)
    assert main.actions[Feature.ON_OFF] == "2"
    assert main.actions[Feature.LEVEL_SET] == "3"
    assert main.actions[Feature.LEVEL_HOLD] == "4"

    button_two = next(e for e in emitters.values() if "Button 2" in e.label)
    assert button_two.actions[Feature.ON_OFF] == "7"
    assert button_two.actions[Feature.LEVEL_HOLD] == "8"
    assert Feature.LEVEL_SET not in button_two.actions


def test_inovelli_profile_grouping_is_rejected_and_falls_back() -> None:
    """Every Inovelli group has its own profile, so profile grouping is meaningless here.

    Grouping by it would split one paddle into three emitters and make the Remote template
    impossible. Without a curated override the derivation must fall back to one emitter per
    group and say so, rather than producing a confidently wrong grouping.
    """
    emitters = derive_emitters(_groups(37))

    assert len(emitters) == 6, "expected one emitter per non-lifeline group in fallback mode"
    assert all(e.grouping == "per_group" for e in emitters)
    assert all(len(e.group_ids) == 1 for e in emitters)


def test_zen37_null_profile_does_not_lose_a_button() -> None:
    """ZEN37 group 7 has a null profile. No button may be silently dropped."""
    groups = _groups(40)
    emitters = derive_emitters(groups)

    covered = {group_id for emitter in emitters for group_id in emitter.group_ids}
    expected = {gid for gid, g in groups.items() if not g["is_lifeline"]}

    assert covered == expected, f"groups lost during derivation: {expected - covered}"


def test_capacity_is_the_smallest_capacity_of_the_groups_it_uses() -> None:
    """A rule using two groups is limited by the tighter one (FR-R6)."""
    zen35 = next(e for e in derive_emitters(_groups(36)) if "Main" in e.label)
    zen37 = derive_emitters(_groups(40))[0]

    assert zen35.capacity == 10
    assert zen37.capacity == 5, "the ZEN37 holds 5 targets per group, not 10"


def test_every_emitter_reports_whether_it_can_target_an_endpoint() -> None:
    """E11: a group without multi-channel support cannot address a target endpoint."""
    for emitter in derive_emitters(_groups(36)):
        assert emitter.supports_endpoint_targets is True


def test_emitter_ids_are_stable_and_derived_from_groups() -> None:
    """Rules store emitter ids, so they must not move when a device is re-read."""
    first = derive_emitters(_groups(36))
    second = derive_emitters(_groups(36))

    assert [e.emitter_id for e in first] == [e.emitter_id for e in second]
    for emitter in first:
        assert emitter.emitter_id.startswith("g"), emitter.emitter_id
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

Add to `models.py` (if you did not already define it in Task 1): a frozen `Emitter`
dataclass with `emitter_id`, `label`, `group_ids: tuple[str, ...]`,
`actions: Mapping[Feature, str]` mapping a feature to the **group id** that carries it,
`capacity: int`, `supports_endpoint_targets: bool`, `is_lifeline: bool`, `grouping: str`.

`actions` is the bridge to `Link.emitter_group`: the compiler looks up
`emitter.actions[feature]` and puts that group id on the link it produces.

Add `derive_emitters(groups) -> list[Emitter]` to `zwave_protocol.py`:

1. Drop any group where `is_lifeline` is true. Never emit one.
2. Classify each remaining group with `features_of_group`. Drop groups with no features,
   but never silently: they belong in a returned warning or a debug log, not nowhere.
3. Decide grouping:
   - **profile grouping** is used only when every non-lifeline group has a non-null profile
     AND at least one profile covers more than one group AND no profile covers two groups
     that carry the same feature (two groups both offering `ON_OFF` under one profile means
     the profile is not identifying a single control). The ZEN35 satisfies this; Inovelli
     fails the "covers more than one group" test; the ZEN37 fails the null test.
   - otherwise **per_group**: one emitter per group, `emitter_id` = `f"g{group_id}"`,
     label from the group label.
4. For profile grouping, `emitter_id` is the lowest group id in the profile prefixed with
   `g`, so ids stay stable and sortable. Label is the longest common prefix of the member
   labels, trimmed of trailing punctuation and whitespace, falling back to the lowest
   group's label when there is no useful common prefix.
5. `capacity` is `min(max_nodes)` across the emitter's groups.
6. `supports_endpoint_targets` is `all(multi_channel)` across its groups.
7. Sort the result by lowest group id so output order is deterministic.

- [ ] **Step 4: Confirm tests pass and coverage is 100% for the module.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(zwave): derive emitters, rejecting AGI profile where it does not partition"
```

---

### Task 4: Mapping refusal reasons to something a user can act on

**Files:**
- Modify: `custom_components/device_links/backends/zwave_protocol.py`
- Test: `tests/test_zwave_check_results.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Check-result mapping. The values come from Stage 0, not from the documentation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.device_links.backends.zwave_protocol import (
    CheckResult,
    blocked_reason_for,
    is_ok,
)

Z3 = Path(__file__).parent / "fixtures" / "z3_write_roundtrip.json"


def test_ok_is_one_not_zero() -> None:
    """Pinned by Stage 0 Z3 against the live driver. A falsy check would invert this."""
    assert CheckResult.OK == 1
    assert is_ok(1) is True
    assert is_ok(0) is False, "0 is not a valid result and must never read as success"


def test_the_live_check_result_matches_the_enum() -> None:
    observed = json.loads(Z3.read_text())["data"]["check_result"]

    assert CheckResult(observed["value"]).name == observed["name"]


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        (2, "long_range"),
        (3, "long_range"),
        (4, "self_association"),
        (5, "security_class"),
        (6, "security_class"),
        (7, "no_supported_commands"),
    ],
)
def test_every_refusal_maps_to_a_translation_key(value: int, fragment: str) -> None:
    """E7 to E10: each refusal needs a reason the user can act on, not a number."""
    reason = blocked_reason_for(value)

    assert reason is not None
    assert fragment in reason.translation_key


def test_ok_has_no_blocked_reason() -> None:
    assert blocked_reason_for(CheckResult.OK) is None


def test_an_unknown_result_is_blocked_rather_than_allowed() -> None:
    """A future driver value must fail closed. Never write on an unrecognised answer."""
    reason = blocked_reason_for(99)

    assert reason is not None
    assert "unknown" in reason.translation_key
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`CheckResult(IntEnum)` with `OK = 1` through `FORBIDDEN_NO_SUPPORTED_CCS = 7`, matching the
names Stage 0 recorded. `is_ok(value) -> bool` compares to `CheckResult.OK` explicitly and
never uses truthiness. `blocked_reason_for(value) -> BlockedReason | None` returns a frozen
`BlockedReason(translation_key, placeholders)` for everything except `OK`, and returns an
`unknown_check_result` reason for any value outside the enum, so the system fails closed.

- [ ] **Step 4: Confirm tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(zwave): map association check results to actionable blocked reasons"
```

---

### Task 5: The device profile database

**Files:**
- Create: `custom_components/device_links/profile_db.py`
- Create: `custom_components/device_links/profiles_db/schema.json`
- Create: `custom_components/device_links/profiles_db/zooz.json`
- Create: `custom_components/device_links/profiles_db/inovelli.json`
- Test: `tests/test_profile_db.py`

This is where the Inovelli paddle gets put back together, and where settings adapters get
their parameter numbers. A profile entry is data, so a contributor can add a device without
touching Python (PRD persona: Contributor).

**The entries must be validated against the fixtures.** A profile database that drifts from
the hardware is worse than none, because it is confidently wrong.

- [ ] **Step 1: Write the failing tests**

```python
"""Profile entries must match the hardware they claim to describe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.device_links.models import Feature, ZWaveFingerprint
from custom_components.device_links.profile_db import ProfileDatabase, load_profiles

PROFILES_DIR = Path("custom_components/device_links/profiles_db")
FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"


@pytest.fixture
def database() -> ProfileDatabase:
    return load_profiles(
        {
            path.name: path.read_text()
            for path in PROFILES_DIR.glob("*.json")
            if path.name != "schema.json"
        }
    )


def _node(node_id: int) -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text())["data"]
    return next(n for n in data["nodes"] if n["node_id"] == node_id)


def _fingerprint(node_id: int) -> ZWaveFingerprint:
    fp = _node(node_id)["fingerprint"]
    return ZWaveFingerprint(
        manufacturer_id=fp["manufacturer_id"],
        product_type=fp["product_type"],
        product_id=fp["product_id"],
        firmware=fp["firmware_version"],
    )


def test_the_inovelli_entry_reassembles_the_paddle(database: ProfileDatabase) -> None:
    """The whole reason the profile DB exists for this model.

    AGI gives groups 2, 3 and 4 distinct profiles even though they are one paddle. The
    curated entry puts them back together so "paddle controls light with dimming" is one
    rule rather than three.
    """
    entry = database.lookup(_fingerprint(37))
    assert entry is not None, "no profile entry matched the VZW32-SN fingerprint"

    paddle = next(e for e in entry.emitters if e.emitter_id == "paddle")
    assert paddle.actions[Feature.ON_OFF] == "2"
    assert paddle.actions[Feature.LEVEL_SET] == "3"
    assert paddle.actions[Feature.LEVEL_HOLD] == "4"


def test_every_group_a_profile_entry_names_exists_on_the_real_device(
    database: ProfileDatabase,
) -> None:
    """Guards against a profile entry drifting from the hardware.

    A curated entry overrides the generic derivation, so a wrong group number here writes
    an association to the wrong place with full confidence.
    """
    for node_id in (36, 37, 40):
        entry = database.lookup(_fingerprint(node_id))
        if entry is None:
            continue
        real_groups = set(_node(node_id)["association_groups"]["0"])
        for emitter in entry.emitters:
            for feature, group_id in emitter.actions.items():
                assert group_id in real_groups, (
                    f"node {node_id} profile entry maps {emitter.emitter_id}.{feature} to "
                    f"group {group_id}, which does not exist on the device"
                )


def test_a_profile_entry_never_maps_a_feature_onto_the_lifeline(
    database: ProfileDatabase,
) -> None:
    """The hardest safety rule, checked at the data layer too, not only in code."""
    for node_id in (36, 37, 40):
        entry = database.lookup(_fingerprint(node_id))
        if entry is None:
            continue
        for emitter in entry.emitters:
            assert "1" not in emitter.actions.values(), (
                f"node {node_id} profile entry maps a feature onto the lifeline"
            )


def test_declared_features_match_what_the_group_can_actually_issue(
    database: ProfileDatabase,
) -> None:
    """A curated entry claiming a group does something it cannot is a silent failure."""
    from custom_components.device_links.backends.zwave_protocol import features_of_group

    for node_id in (36, 37, 40):
        entry = database.lookup(_fingerprint(node_id))
        if entry is None:
            continue
        groups = _node(node_id)["association_groups"]["0"]
        for emitter in entry.emitters:
            for feature, group_id in emitter.actions.items():
                available = features_of_group(groups[group_id]["issued_commands"])
                assert feature in available, (
                    f"node {node_id} {emitter.emitter_id} claims {feature} on group "
                    f"{group_id}, which issues {groups[group_id]['issued_commands']}"
                )


def test_settings_adapters_point_at_parameters_that_exist(database: ProfileDatabase) -> None:
    """Z6 captured the real value ids; the adapters must agree with them."""
    for node_id in (37, 39):
        entry = database.lookup(_fingerprint(node_id))
        if entry is None:
            continue
        real = {(v["property"], v["property_key"]) for v in _node(node_id).get("config_values", [])}
        for name, adapter in entry.settings.items():
            assert (adapter.parameter, adapter.bitmask) in real, (
                f"node {node_id} adapter {name!r} points at parameter "
                f"{adapter.parameter}/{adapter.bitmask}, which the device does not expose"
            )


def test_mirror_hub_commands_is_defined_for_both_families(database: ProfileDatabase) -> None:
    """FR-R4 needs this adapter on Zooz and Inovelli, with the values Stage 0 recorded."""
    zooz = database.lookup(_fingerprint(39))
    inovelli = database.lookup(_fingerprint(37))

    assert zooz is not None and inovelli is not None
    assert (
        zooz.settings["mirror_hub_commands"].parameter,
        zooz.settings["mirror_hub_commands"].bitmask,
    ) == (35, 4)
    assert (
        inovelli.settings["mirror_hub_commands"].parameter,
        inovelli.settings["mirror_hub_commands"].bitmask,
    ) == (59, 2)


def test_an_unknown_fingerprint_returns_none_rather_than_guessing(
    database: ProfileDatabase,
) -> None:
    unknown = ZWaveFingerprint(manufacturer_id=1, product_type=1, product_id=1, firmware="0.0.0")
    assert database.lookup(unknown) is None


def test_every_shipped_profile_file_validates_against_the_schema() -> None:
    """A contributor's malformed entry must fail loudly at load, not at apply time."""
    files = {
        path.name: path.read_text()
        for path in PROFILES_DIR.glob("*.json")
        if path.name != "schema.json"
    }
    assert files, "no profile files shipped"
    load_profiles(files)  # must not raise


def test_a_malformed_profile_file_is_rejected_with_a_useful_message() -> None:
    with pytest.raises(ValueError, match="emitters"):
        load_profiles({"broken.json": json.dumps({"devices": [{"fingerprint": {}}]})})
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`profile_db.py` exposes `load_profiles(files: Mapping[str, str]) -> ProfileDatabase`. It
takes already-read text, so the module stays pure and the caller owns file I/O. Validate
against a hand-written check (no new dependency; `voluptuous` is available through HA but
this module must not import it, so validate with plain Python and raise `ValueError` with a
message naming the file and the offending field).

Frozen models: `SettingsAdapter(parameter: int, bitmask: int | None, values: Mapping[str, int])`,
`ProfileEmitter(emitter_id, label, kind, actions: Mapping[Feature, str], capacity_override)`,
`ProfileEntry(fingerprints, emitters, settings, wake_instruction, notes)`,
`ProfileDatabase` with `lookup(fingerprint) -> ProfileEntry | None` matching on
manufacturer/product ids and ignoring firmware.

Write `zooz.json` covering ZEN35 (`manufacturer_id` 634) with the main button and four
small buttons, and the ZEN37 with its real layout from the table above; and
`inovelli.json` covering VZW32-SN with `paddle` (groups 2, 3, 4), `double_tap` (5),
`triple_tap` (6) and `config_button` (7). Take every group number and parameter from the
tables in this plan, which came from the fixture. Settings adapters: Zooz
`mirror_hub_commands` 35 bit 4, `send_local_to_associations` 35 bit 1, `report_command_class`
33, `local_control` 19; Inovelli `send_local_to_associations` 59 bit 1,
`mirror_hub_commands` 59 bit 2, `smart_bulb_mode` 52, `group_7_enable` 130.

Get the fingerprints from the fixture rather than from memory: node 36 and 39 are ZEN35,
node 40 is ZEN37, node 37 is VZW32-SN.

- [ ] **Step 4: Confirm tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(core): device profile database with fixture-validated entries"
```

---

### Task 6: Rules and profiles

**Files:**
- Modify: `custom_components/device_links/models.py`
- Test: `tests/test_rules.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Rules are the unit of intent, and of enable/disable."""

from __future__ import annotations

import pytest

from custom_components.device_links.models import (
    Backend,
    Direction,
    Feature,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from tests.factories import handle  # small helper you add alongside this test


def _rule(**overrides: object) -> Rule:
    defaults = dict(
        id="11111111-1111-4111-8111-111111111111",
        name="Scene controller button 3 controls Bedside Light L",
        template=Template.SCENE_BUTTON,
        backend=Backend.ZWAVE,
        source=RuleSource(device=handle(36), endpoint=0, emitter_id="g9"),
        targets=(RuleTarget(device=handle(38), endpoint=None),),
        features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD}),
    )
    return Rule(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_a_rule_is_enabled_by_default() -> None:
    assert _rule().enabled is True


def test_a_rule_requires_at_least_one_target() -> None:
    with pytest.raises(ValueError, match="at least one target"):
        _rule(targets=())


def test_a_rule_requires_at_least_one_feature() -> None:
    with pytest.raises(ValueError, match="at least one feature"):
        _rule(features=frozenset())


def test_a_rule_rejects_duplicate_targets() -> None:
    """Two identical targets would plan the same write twice."""
    target = RuleTarget(device=handle(38), endpoint=None)
    with pytest.raises(ValueError, match="duplicate target"):
        _rule(targets=(target, target))


def test_a_rule_defaults_to_one_way() -> None:
    """UC6: direction is explicit, and one-way is the safe default."""
    assert _rule().direction is Direction.ONE_WAY


def test_a_profile_has_exactly_one_rule_per_id() -> None:
    rule = _rule()
    with pytest.raises(ValueError, match="duplicate rule id"):
        Profile(id="p1", name="Home", rules=(rule, rule))


def test_disabling_a_rule_does_not_delete_it() -> None:
    """FR-R5: a disabled rule's links are planned for removal, but intent is kept."""
    rule = _rule()
    disabled = rule.with_enabled(False)

    assert disabled.enabled is False
    assert disabled.id == rule.id
    assert rule.enabled is True, "rules are immutable; with_enabled returns a copy"
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

Add `Template(StrEnum)` with `REMOTE`, `VIRTUAL_3WAY`, `SCENE_BUTTON`, `OFF_ALL`,
`STATUS_FEEDBACK`, `CUSTOM`; `Direction(StrEnum)` with `ONE_WAY`, `TWO_WAY`;
`MirrorChoice(StrEnum)` with `ON`, `OFF`, `LEAVE`; `RuleSource`, `RuleTarget`, `Rule`,
`Profile`, all frozen, with the validation the tests require and a `with_enabled` copier.
Also create `tests/factories.py` with the `handle()` helper so test files stop repeating it,
and refactor `tests/test_models.py` to use it.

- [ ] **Step 4: Confirm tests pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(core): rule and profile models with intent-level validation"
```

---

### Task 7: The compiler

**Files:**
- Create: `custom_components/device_links/compiler.py`
- Test: `tests/test_compiler.py`

`compile_rule` is the heart of the product: it turns "this button should control that light,
with dimming" into the exact groups that must contain the exact node ids. It is pure, so it
is also the cheapest place in the system to be certain.

- [ ] **Step 1: Write the failing tests**

```python
"""Compilation: intent in, links and settings out. Pure and deterministic."""

from __future__ import annotations

import pytest

from custom_components.device_links.compiler import compile_rule
from custom_components.device_links.models import (
    Backend,
    Direction,
    Feature,
    MirrorChoice,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from tests.factories import capabilities_for, handle


def _rule(**overrides: object) -> Rule:
    defaults = dict(
        id="rule-1",
        name="Button 3 controls Bedside Light L",
        template=Template.SCENE_BUTTON,
        backend=Backend.ZWAVE,
        source=RuleSource(device=handle(36), endpoint=0, emitter_id="g9"),
        targets=(RuleTarget(device=handle(38), endpoint=None),),
        features=frozenset({Feature.ON_OFF}),
    )
    return Rule(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_one_feature_one_target_compiles_to_one_link() -> None:
    result = compile_rule(_rule(), capabilities_for(36, 38))

    assert not result.errors
    assert len(result.links) == 1
    link = result.links[0]
    assert link.emitter_id == "g9"
    assert link.target.handle.identity == handle(38).identity
    assert link.feature is Feature.ON_OFF
    assert link.rule_id == "rule-1"


def test_adding_dimming_adds_the_held_group_not_a_second_on_off() -> None:
    """S3: selecting on_off + level_hold on ZEN35 button 3 compiles groups 9 and 10."""
    result = compile_rule(
        _rule(features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD})),
        capabilities_for(36, 38),
    )

    groups = {link.emitter_group for link in result.links}
    assert groups == {"9", "10"}


def test_the_inovelli_paddle_compiles_all_three_groups() -> None:
    """S2 and UC1: on/off, level sync and hold-to-dim from one paddle."""
    rule = _rule(
        template=Template.REMOTE,
        source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
        features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD}),
    )
    result = compile_rule(rule, capabilities_for(37, 38))

    assert {link.emitter_group for link in result.links} == {"2", "3", "4"}


def test_many_targets_produce_one_link_each() -> None:
    """UC8: one button controls several lights."""
    rule = _rule(
        targets=(
            RuleTarget(device=handle(35), endpoint=None),
            RuleTarget(device=handle(37), endpoint=None),
            RuleTarget(device=handle(38), endpoint=None),
        )
    )
    result = compile_rule(rule, capabilities_for(36, 35, 37, 38))

    assert len(result.links) == 3
    assert len({link.fingerprint for link in result.links}) == 3


def test_compilation_is_deterministic() -> None:
    """The plan token depends on this: the same rule must always compile identically."""
    rule = _rule(features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD}))
    caps = capabilities_for(36, 38)

    first = compile_rule(rule, caps)
    second = compile_rule(rule, caps)

    assert [link.fingerprint for link in first.links] == [link.fingerprint for link in second.links]


def test_a_feature_the_emitter_cannot_carry_is_an_error_not_a_silent_drop() -> None:
    """ZEN35 button 3 has no Multilevel Set group, so level_set cannot be honoured."""
    result = compile_rule(_rule(features=frozenset({Feature.LEVEL_SET})), capabilities_for(36, 38))

    assert result.errors, "a rule that can produce no link must error"
    assert any("level_set" in error.translation_key for error in result.errors)
    assert not result.links


def test_a_partially_unsupported_feature_set_warns_and_compiles_the_rest() -> None:
    """FR-R2: errors block only when the rule can produce no link at all."""
    result = compile_rule(
        _rule(features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET})),
        capabilities_for(36, 38),
    )

    assert not result.errors
    assert len(result.links) == 1
    assert any("level_set" in warning.translation_key for warning in result.warnings)


def test_a_disabled_rule_compiles_to_nothing() -> None:
    """FR-R5: desired state excludes disabled rules, so their links get removed."""
    result = compile_rule(_rule().with_enabled(False), capabilities_for(36, 38))

    assert result.links == ()
    assert not result.errors


def test_self_targeting_is_blocked_with_the_hybrid_suggestion() -> None:
    """E7 and UC4: a node cannot be in its own group. Say so, and say what to do."""
    result = compile_rule(
        _rule(targets=(RuleTarget(device=handle(36), endpoint=None),)),
        capabilities_for(36),
    )

    assert result.errors
    assert any("self_association" in error.translation_key for error in result.errors)
    assert any("hybrid" in error.translation_key for error in result.errors)


def test_a_long_range_device_is_refused_as_a_target() -> None:
    """D13 and E8: LR nodes cannot participate in associations at all."""
    result = compile_rule(
        _rule(targets=(RuleTarget(device=handle(300, long_range=True), endpoint=None),)),
        capabilities_for(36, 300),
    )

    assert result.errors
    assert any("long_range" in error.translation_key for error in result.errors)


def test_a_two_way_rule_compiles_the_reverse_links() -> None:
    """UC2: both switches control the same light from both places."""
    rule = _rule(
        template=Template.VIRTUAL_3WAY,
        source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
        targets=(RuleTarget(device=handle(35), endpoint=None),),
        features=frozenset({Feature.ON_OFF}),
        direction=Direction.TWO_WAY,
    )
    result = compile_rule(rule, capabilities_for(37, 35))

    forward = [link for link in result.links if link.source.identity == handle(37).identity]
    reverse = [link for link in result.links if link.source.identity == handle(35).identity]
    assert forward and reverse, "a two-way rule needs a link in each direction"


def test_mirroring_plans_a_parameter_write_naming_the_parameter() -> None:
    """FR-R4: the UI shows the exact parameter, so the compiler must produce it."""
    rule = _rule(
        template=Template.VIRTUAL_3WAY,
        source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
        targets=(RuleTarget(device=handle(35), endpoint=None),),
        direction=Direction.TWO_WAY,
        mirror_source=MirrorChoice.ON,
    )
    result = compile_rule(rule, capabilities_for(37, 35))

    settings = [s for s in result.settings if s.capability == "mirror_hub_commands"]
    assert len(settings) == 1
    assert settings[0].parameter == 59
    assert settings[0].bitmask == 2
    assert settings[0].value == 1


def test_mirror_leave_never_writes_a_parameter() -> None:
    """FR-R4: `leave` must be a genuine no-op, not a write of the current value."""
    rule = _rule(
        source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
        mirror_source=MirrorChoice.LEAVE,
    )
    result = compile_rule(rule, capabilities_for(37, 38))

    assert not [s for s in result.settings if s.capability == "mirror_hub_commands"]


def test_mirroring_on_a_model_without_an_adapter_warns_rather_than_failing() -> None:
    """E31: links still work; only the setting is unavailable."""
    rule = _rule(
        source=RuleSource(device=handle(99, unknown_model=True), endpoint=0, emitter_id="g2"),
        mirror_source=MirrorChoice.ON,
    )
    result = compile_rule(rule, capabilities_for(99, 38))

    assert not result.errors
    assert any("settings_not_available" in w.translation_key for w in result.warnings)


def test_off_all_on_a_zooz_small_button_warns_about_unknown_semantics() -> None:
    """Stage 0 Z7 is unresolved, and this is the consequence it must not outlive.

    Nobody has observed whether a Zooz small button sends a fixed OFF or toggles. Until
    Z7 is closed, an Off-all rule on one of these buttons must carry an explicit warning,
    because if it toggles the button turns the lights back on every second press.
    """
    result = compile_rule(
        _rule(template=Template.OFF_ALL, features=frozenset({Feature.ON_OFF})),
        capabilities_for(36, 38),
    )

    assert any("button_semantics_unknown" in w.translation_key for w in result.warnings), (
        "Off-all on a Zooz scene button must warn until Stage 0 Z7 is closed"
    )


def test_a_target_endpoint_on_a_group_without_multi_channel_is_downgraded() -> None:
    """E11: downgrade to a node association and warn, rather than writing nonsense."""
    result = compile_rule(
        _rule(targets=(RuleTarget(device=handle(38), endpoint=2),)),
        capabilities_for(36, 38, multi_channel=False),
    )

    assert result.links[0].target.endpoint is None
    assert any("multi_channel_downgrade" in w.translation_key for w in result.warnings)
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`compile_rule(rule: Rule, capabilities: Mapping[str, DeviceCapabilities]) -> CompiledRule`,
where the mapping is keyed by `DeviceHandle.identity`. `CompiledRule` is a frozen dataclass
with `links: tuple[Link, ...]`, `settings: tuple[SettingWrite, ...]`,
`hybrid_legs: tuple[HybridLeg, ...]`, `warnings: tuple[Diagnostic, ...]`,
`errors: tuple[Diagnostic, ...]`. `Diagnostic` carries `translation_key` and
`placeholders: Mapping[str, str]`, never an English sentence: user-facing text is a
translation key (CLAUDE.md Section 7).

Rules the implementation must follow:

- A disabled rule compiles to no links and no errors.
- For each requested feature, look it up in the source emitter's `actions`. Present means a
  link per target. Absent means a warning, unless no feature resolved at all, which is an
  error.
- Refuse and error, never warn, on: self-association, a Long Range source or target, and a
  target whose capabilities show it cannot receive the command.
- `Feature.LEVEL_HOLD` without `Feature.ON_OFF` is legal but warns, because holding to dim a
  light you cannot turn on is rarely the intent.
- Two-way compiles the reverse links by swapping source and target and using the target's
  own emitter for the same feature; if the target has no suitable emitter, warn and compile
  one-way.
- Mirroring resolves through the profile DB settings adapter. `LEAVE` writes nothing.
  A missing adapter warns with `settings_not_available`.
- Off-all onto an emitter whose profile entry marks `semantics: unknown` adds the
  `button_semantics_unknown` warning. Mark the Zooz small buttons that way in `zooz.json`,
  and add a note in the file pointing at Stage 0 Z7.
- Endpoint downgrade when the emitter does not support endpoint targets.
- Output ordering is deterministic: sort links by (target identity, feature).

- [ ] **Step 4: Confirm tests pass, and that `compiler.py` is at 100%.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(core): compile rules into links, settings and diagnostics"
```

---

### Task 8: The planner

**Files:**
- Create: `custom_components/device_links/planner.py`
- Test: `tests/test_planner.py`

The planner is where the safety rules become code. Everything it refuses to do is something
that could otherwise damage a working home.

- [ ] **Step 1: Write the failing tests**

```python
"""Planning: desired versus observed, with the safety rules that must never bend."""

from __future__ import annotations

import pytest

from custom_components.device_links.models import Feature, ObservedLink, PlanOp
from custom_components.device_links.planner import build_plan
from tests.factories import capabilities_for, handle, link, observed


def test_a_missing_link_is_planned_as_an_add() -> None:
    desired = (link(36, "g9", 38, Feature.ON_OFF),)
    plan = build_plan(desired=desired, observed=(), capabilities=capabilities_for(36, 38))

    assert [item.op for item in plan.items] == [PlanOp.ADD]


def test_a_link_that_already_exists_is_not_rewritten() -> None:
    """E12: writing a link that is already present wastes a radio round trip."""
    wanted = link(36, "g9", 38, Feature.ON_OFF)
    plan = build_plan(
        desired=(wanted,),
        observed=(observed(wanted, rule_id="rule-1"),),
        capabilities=capabilities_for(36, 38),
    )

    assert not [item for item in plan.items if item.op is PlanOp.ADD]
    assert plan.unchanged_count == 1


def test_a_managed_link_no_longer_desired_is_planned_for_removal() -> None:
    """A disabled or deleted rule's links must actually come off the device."""
    stale = link(36, "g9", 38, Feature.ON_OFF)
    plan = build_plan(
        desired=(),
        observed=(observed(stale, rule_id="rule-1"),),
        capabilities=capabilities_for(36, 38),
    )

    assert [item.op for item in plan.items] == [PlanOp.REMOVE]


def test_an_unmanaged_link_is_reported_but_never_removed_by_default() -> None:
    """D9 and FR-U1. This is the difference between a tool and a hazard."""
    foreign = link(36, "g9", 35, Feature.ON_OFF)
    plan = build_plan(
        desired=(),
        observed=(observed(foreign, rule_id=None),),
        capabilities=capabilities_for(36, 35),
    )

    assert not [item for item in plan.items if item.op is PlanOp.REMOVE]
    assert len(plan.unmanaged) == 1


def test_an_unmanaged_link_is_removed_only_when_explicitly_selected() -> None:
    foreign = link(36, "g9", 35, Feature.ON_OFF)
    observed_foreign = observed(foreign, rule_id=None)
    plan = build_plan(
        desired=(),
        observed=(observed_foreign,),
        capabilities=capabilities_for(36, 35),
        remove_unmanaged=frozenset({observed_foreign.fingerprint}),
    )

    assert [item.op for item in plan.items] == [PlanOp.REMOVE]


def test_a_lifeline_entry_is_never_planned_for_removal() -> None:
    """The single most dangerous write in the system. Refuse it in code, not in the UI."""
    lifeline = observed(link(36, "g1", 1, Feature.STATUS_REPORT), rule_id=None, system=True)
    plan = build_plan(
        desired=(),
        observed=(lifeline,),
        capabilities=capabilities_for(36),
        remove_unmanaged=frozenset({lifeline.fingerprint}),
    )

    assert not [item for item in plan.items if item.op is PlanOp.REMOVE], (
        "a lifeline was planned for removal even though it was explicitly selected"
    )
    assert lifeline not in plan.unmanaged, "a lifeline is a system link, not an unmanaged one"


def test_a_full_group_blocks_the_add_and_says_how_full_it_is() -> None:
    """E6 and FR-R6: the message must be actionable, with counts."""
    existing = tuple(
        observed(link(40, "g2", target, Feature.ON_OFF), rule_id=None)
        for target in (30, 31, 32, 33, 34)
    )
    plan = build_plan(
        desired=(link(40, "g2", 35, Feature.ON_OFF),),
        observed=existing,
        capabilities=capabilities_for(40, 35, 30, 31, 32, 33, 34),
    )

    blocked = [item for item in plan.items if item.op is PlanOp.BLOCKED]
    assert len(blocked) == 1
    assert "group_full" in blocked[0].reason.translation_key
    assert blocked[0].reason.placeholders["used"] == "5"
    assert blocked[0].reason.placeholders["capacity"] == "5"


def test_capacity_counts_unmanaged_entries_too() -> None:
    """A group full of links we did not create is still full."""
    existing = tuple(
        observed(link(40, "g2", target, Feature.ON_OFF), rule_id=None)
        for target in (30, 31, 32, 33)
    )
    plan = build_plan(
        desired=(link(40, "g2", 35, Feature.ON_OFF), link(40, "g2", 36, Feature.ON_OFF)),
        observed=existing,
        capabilities=capabilities_for(40, 35, 36, 30, 31, 32, 33),
    )

    assert len([i for i in plan.items if i.op is PlanOp.ADD]) == 1
    assert len([i for i in plan.items if i.op is PlanOp.BLOCKED]) == 1


def test_the_plan_token_changes_when_observed_state_changes() -> None:
    """FR-A3: applying a stale plan must be detectable."""
    desired = (link(36, "g9", 38, Feature.ON_OFF),)
    caps = capabilities_for(36, 38, 35)

    empty = build_plan(desired=desired, observed=(), capabilities=caps)
    changed = build_plan(
        desired=desired,
        observed=(observed(link(36, "g9", 35, Feature.ON_OFF), rule_id=None),),
        capabilities=caps,
    )

    assert empty.token != changed.token


def test_the_plan_token_is_stable_for_identical_inputs() -> None:
    desired = (link(36, "g9", 38, Feature.ON_OFF),)
    caps = capabilities_for(36, 38)

    assert build_plan(desired=desired, observed=(), capabilities=caps).token == (
        build_plan(desired=desired, observed=(), capabilities=caps).token
    )


def test_a_plan_groups_its_items_by_device() -> None:
    """The apply dialog and the executor both work per device."""
    plan = build_plan(
        desired=(link(36, "g9", 38, Feature.ON_OFF), link(37, "paddle", 35, Feature.ON_OFF)),
        observed=(),
        capabilities=capabilities_for(36, 37, 38, 35),
    )

    assert set(plan.by_device()) == {handle(36).identity, handle(37).identity}


def test_an_empty_plan_is_reported_as_empty() -> None:
    """Idempotence: applying twice must produce nothing the second time."""
    wanted = link(36, "g9", 38, Feature.ON_OFF)
    plan = build_plan(
        desired=(wanted,),
        observed=(observed(wanted, rule_id="rule-1"),),
        capabilities=capabilities_for(36, 38),
    )

    assert plan.is_empty
```

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**

`build_plan(*, desired, observed, capabilities, remove_unmanaged=frozenset()) -> Plan`.

`PlanOp(StrEnum)`: `ADD`, `REMOVE`, `SET_PARAM`, `BLOCKED`, `PENDING`.
`PlanItem`: `op`, `device_identity`, `link: Link | ObservedLink | None`,
`setting: SettingWrite | None`, `reason: Diagnostic | None`.
`Plan`: `token`, `items`, `unmanaged`, `unchanged_count`, `is_empty`, `by_device()`.

`ObservedLink` and its `is_system` flag come from Task 1. The property test in Task 9
asserts `item.link.is_system` on every planned removal, so `PlanItem.link` must carry the
observed link (not a rebuilt desired one) whenever the op is `REMOVE`.

Order of operations matters and must be implemented in this order:

1. Index observed by fingerprint.
2. Classify every observed link: `system` (lifeline or coordinator) is neither managed nor
   unmanaged and is never touched; `managed` when it carries a rule id; otherwise unmanaged.
3. Desired minus observed becomes adds; managed observed minus desired becomes removes;
   the intersection is unchanged.
4. Unmanaged links appear in `plan.unmanaged` and become removes only when their fingerprint
   is in `remove_unmanaged`. **A system link is never removable, even when explicitly
   selected**, and never appears in `unmanaged`.
5. Capacity: for each target group, count observed entries that will survive, add the
   planned adds, and block the overflow with a `group_full` diagnostic carrying `used` and
   `capacity` placeholders. Process adds in a deterministic order so which one is blocked is
   reproducible.
6. `token` is a stable hash over the sorted fingerprints of desired and observed plus the
   capability capacities. It must not depend on dict ordering or on wall-clock time.

- [ ] **Step 4: Confirm tests pass at 100% coverage.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(core): plan desired against observed with capacity and safety rules"
```

---

### Task 9: Property-based tests

**Files:**
- Create: `tests/test_properties.py`

Nine hand-written planner tests cannot cover the space of profiles and observed states a
real house produces. These properties are what let us claim the core is correct rather than
merely tested.

- [ ] **Step 1: Write the properties**

```python
"""Invariants that must hold for every profile and every starting state.

These use Hypothesis to generate rules, capabilities and observed states, then assert the
properties PRD Section 16 requires. A failure here is a real defect, not a flaky test:
Hypothesis will shrink it to a minimal reproduction.
"""

from __future__ import annotations

from hypothesis import given, settings

from custom_components.device_links.models import PlanOp
from custom_components.device_links.planner import build_plan
from tests.strategies import networks


@given(networks())
@settings(max_examples=200, deadline=None)
def test_applying_a_plan_reaches_the_desired_state(network: object) -> None:
    """Plan then apply on a fake backend converges to desired state."""
    result = network.apply(build_plan(**network.plan_inputs()))

    remaining = build_plan(**network.plan_inputs(observed=result))
    assert not [i for i in remaining.items if i.op is PlanOp.ADD]


@given(networks())
@settings(max_examples=200, deadline=None)
def test_a_second_plan_is_empty(network: object) -> None:
    """Idempotence. Applying twice must not write anything the second time."""
    first = build_plan(**network.plan_inputs())
    state = network.apply(first)
    second = build_plan(**network.plan_inputs(observed=state))

    assert second.is_empty or all(i.op is PlanOp.BLOCKED for i in second.items)


@given(networks())
@settings(max_examples=200, deadline=None)
def test_a_lifeline_is_never_removed(network: object) -> None:
    """The invariant that matters most. No generated input may violate it."""
    plan = build_plan(**network.plan_inputs(remove_everything=True))

    for item in plan.items:
        if item.op is PlanOp.REMOVE:
            assert not item.link.is_system, f"planned removal of a system link: {item.link}"


@given(networks())
@settings(max_examples=200, deadline=None)
def test_group_capacity_is_never_exceeded(network: object) -> None:
    plan = build_plan(**network.plan_inputs())
    state = network.apply(plan)

    for group_id, entries in network.entries_by_group(state).items():
        assert len(entries) <= network.capacity_of(group_id), (
            f"group {group_id} exceeded its capacity"
        )


@given(networks())
@settings(max_examples=200, deadline=None)
def test_unmanaged_links_survive_unless_selected(network: object) -> None:
    """D9: the integration never destroys what it did not create."""
    before = network.unmanaged_fingerprints()
    state = network.apply(build_plan(**network.plan_inputs()))
    after = {entry.fingerprint for entry in state}

    assert before <= after, f"unmanaged links disappeared: {before - after}"
```

- [ ] **Step 2: Build `tests/strategies.py`**

A `networks()` Hypothesis strategy producing a small in-memory model: 2 to 5 devices drawn
from the real fingerprints in the fixtures, each with its real capabilities; a random set of
rules over them; and a random observed state that always includes a lifeline entry per
device and sometimes includes unmanaged entries. It exposes `plan_inputs()`, `apply(plan)`
returning the resulting observed tuple, `entries_by_group`, `capacity_of` and
`unmanaged_fingerprints`. `apply` is a faithful in-memory simulation: it performs adds and
removes and nothing else, and it refuses to exceed capacity.

Keep the strategy small and shrinkable. Prefer `sampled_from` over free-form text so a
failure reproduces as something a human can read.

- [ ] **Step 3: Run them**

`.venv/bin/python -m pytest tests/test_properties.py -v --no-cov`

If a property fails, **do not weaken the property**. Hypothesis has found a real defect in
the planner or the compiler. Fix the code, then add the shrunk counterexample as a named
regression test in the appropriate test file.

- [ ] **Step 4: Confirm the full suite and both gates pass.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "test(core): property-based invariants for the planner"
```

---

## Phase 1A exit criteria

- [ ] `models.py`, `zwave_protocol.py`, `profile_db.py`, `compiler.py` and `planner.py` exist
      and import no Home Assistant module, enforced by the existing manifest test
- [ ] Coverage is 100% on every one of those modules, with no added `pragma: no cover`
- [ ] The profile DB entries are validated against `tests/fixtures/z2_associations.json`,
      so a wrong group number fails CI rather than reaching a device
- [ ] The five Hypothesis properties pass at 200 examples each
- [ ] Off-all on a Zooz small button warns, carrying the unresolved Stage 0 Z7 finding
      forward into the product rather than losing it
- [ ] `./scripts/lint` and `./scripts/test` exit 0, and CI is green on `dev`

## What Phase 1A deliberately does not do

No Home Assistant integration, no I/O, no entities, no panel, no writes to any device. The
Z-Wave adapter that turns these plans into real association writes is Phase 1B, the executor
and storage are Phase 1C, the HA surface is Phase 1D, and the panel is Phase 1E. Keeping
this phase pure is what makes the property tests possible.
