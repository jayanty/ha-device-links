"""Merging a curated profile entry with what a device reports about itself.

The entry decides the grouping, because reassembling the Inovelli paddle is the reason it
exists. The device decides capacity and endpoint support, because those are facts about the
hardware in front of us and not something an entry restates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from custom_components.device_links.backends.zwave_protocol import (
    GROUPING_PROFILE_DB,
    derive_emitters,
    resolve_emitters,
)
from custom_components.device_links.models import Feature
from custom_components.device_links.profile_db import (
    ProfileDatabase,
    ProfileEmitter,
    ProfileEntry,
    load_profiles,
)

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"
PROFILES_DIR = Path("custom_components/device_links/profiles_db")


def _database() -> ProfileDatabase:
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


def _groups(node_id: int) -> dict[str, Any]:
    return _node(node_id)["association_groups"]["0"]


def _entry(node_id: int) -> ProfileEntry:
    fingerprint = _node(node_id)["fingerprint"]
    return next(
        e
        for e in _database().entries
        if any(
            f.manufacturer_id == fingerprint["manufacturer_id"]
            and f.product_type == fingerprint["product_type"]
            and f.product_id == fingerprint["product_id"]
            for f in e.fingerprints
        )
    )


def _emitter(**overrides: Any) -> ProfileEmitter:
    defaults: dict[str, Any] = {
        "emitter_id": "paddle",
        "label": "Paddle",
        "kind": "paddle",
        "actions": {Feature.ON_OFF: "2"},
    }
    return ProfileEmitter(**{**defaults, **overrides})


def _custom_entry(*emitters: ProfileEmitter) -> ProfileEntry:
    return ProfileEntry(
        fingerprints=(), emitters=emitters, settings={}, wake_instruction=None, notes=""
    )


def test_no_entry_leaves_the_generic_derivation_alone() -> None:
    assert resolve_emitters(_groups(37)) == derive_emitters(_groups(37))


def test_the_curated_entry_reassembles_the_inovelli_paddle() -> None:
    """The case the profile database exists for: three AGI profiles, one physical paddle."""
    emitters = {e.emitter_id: e for e in resolve_emitters(_groups(37), _entry(37))}

    paddle = emitters["paddle"]
    assert paddle.group_ids == ("2", "3", "4")
    assert paddle.actions[Feature.ON_OFF] == "2"
    assert paddle.actions[Feature.LEVEL_SET] == "3"
    assert paddle.actions[Feature.LEVEL_HOLD] == "4"
    assert paddle.grouping == GROUPING_PROFILE_DB


def test_a_curated_emitter_inherits_capacity_from_the_groups_it_names() -> None:
    """The ZEN37 reports 5 nodes per group where every other model reports 10.

    A curated entry never restates capacity, so getting it from the entry would silently
    give this device twice the room it has.
    """
    emitters = {e.emitter_id: e for e in resolve_emitters(_groups(40), _entry(40))}

    assert emitters["buttons_1_2"].capacity == 5
    assert all(emitter.capacity == 5 for emitter in emitters.values())


def test_a_curated_emitter_inherits_endpoint_support_from_the_groups_it_names() -> None:
    groups = {
        group_id: {**group, "multi_channel": False} for group_id, group in _groups(37).items()
    }

    emitters = resolve_emitters(groups, _entry(37))

    assert all(not emitter.supports_endpoint_targets for emitter in emitters)
    assert all(
        emitter.supports_endpoint_targets for emitter in resolve_emitters(_groups(37), _entry(37))
    )


def test_a_curated_emitter_that_regroups_is_named_by_the_entry() -> None:
    """The paddle spans groups the derivation never put together, so it is a new control."""
    assert "paddle" in {e.emitter_id for e in resolve_emitters(_groups(37), _entry(37))}


def test_a_curated_emitter_that_agrees_with_the_device_keeps_the_derived_id() -> None:
    """Adding a curated entry must not rename controls the derivation already got right.

    Every ZEN35 emitter covers exactly the groups AGI profile already grouped, so the entry
    only adds a label and the Stage 0 Z7 marker. A rule written against `g9` before the entry
    shipped still means button 3 after it ships.
    """
    derived_ids = {e.emitter_id for e in derive_emitters(_groups(36))}
    resolved = {e.emitter_id: e for e in resolve_emitters(_groups(36), _entry(36))}

    assert set(resolved) == derived_ids
    assert resolved["g9"].actions[Feature.ON_OFF] == "9"
    assert resolved["g9"].actions[Feature.LEVEL_HOLD] == "10"
    assert resolved["g9"].label == "Button 3"


def test_the_stage_0_z7_marker_survives_the_merge() -> None:
    """The unresolved finding has to reach the compiler, which is the only thing that can act."""
    resolved = {e.emitter_id: e for e in resolve_emitters(_groups(36), _entry(36))}

    assert resolved["g9"].semantics == "unknown"
    assert resolved["g2"].semantics is None, "the main paddle has a real off press"


def test_a_capacity_override_wins_over_the_reported_capacity() -> None:
    """Some firmware reports a capacity it does not honour, which is what the override is for."""
    entry = _custom_entry(_emitter(capacity_override=3))

    assert resolve_emitters(_groups(37), entry)[0].capacity == 3


def test_an_entry_naming_a_group_the_device_does_not_report_is_set_aside() -> None:
    """A wrong group number reaches the radio, so an entry that has one is not half believed."""
    entry = _custom_entry(_emitter(actions={Feature.ON_OFF: "99"}))
    warnings: list[str] = []

    emitters = resolve_emitters(_groups(37), entry, warnings=warnings)

    assert emitters == derive_emitters(_groups(37))
    assert any("does not report" in warning for warning in warnings)


def test_an_entry_naming_the_lifeline_is_set_aside() -> None:
    """The lifeline is never a control, whatever a contributor typed."""
    entry = _custom_entry(_emitter(actions={Feature.ON_OFF: "1"}))
    warnings: list[str] = []

    emitters = resolve_emitters(_groups(37), entry, warnings=warnings)

    assert emitters == derive_emitters(_groups(37))
    assert any("lifeline" in warning for warning in warnings)


def test_an_entry_claiming_a_feature_the_group_cannot_issue_is_set_aside() -> None:
    """Group 2 issues Basic Set, so an entry calling it a dimming group describes another device."""
    entry = _custom_entry(_emitter(actions={Feature.LEVEL_SET: "2"}))
    warnings: list[str] = []

    emitters = resolve_emitters(_groups(37), entry, warnings=warnings)

    assert emitters == derive_emitters(_groups(37))
    assert any("cannot carry" in warning for warning in warnings)


def test_a_contradicted_entry_is_set_aside_even_with_nobody_collecting_warnings() -> None:
    """The caller may not want the warnings, but the fallback is not optional."""
    entry = _custom_entry(_emitter(actions={Feature.ON_OFF: "99"}))

    assert resolve_emitters(_groups(37), entry) == derive_emitters(_groups(37))
