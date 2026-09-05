"""Profile entries must match the hardware they claim to describe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.device_links import profile_db
from custom_components.device_links.backends.zwave_protocol import features_of_group
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

    assert zooz is not None
    assert inovelli is not None
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


# --- checks the plan's tests imply but do not spell out -----------------------------------


ALL_NODE_IDS = tuple(n["node_id"] for n in json.loads(FIXTURE.read_text())["data"]["nodes"])


def _entries_matching_the_fixture(
    database: ProfileDatabase,
) -> list[tuple[int, Any]]:
    """Return every fixture node a curated entry claims, with the entry that claims it."""
    matched = []
    for node_id in ALL_NODE_IDS:
        entry = database.lookup(_fingerprint(node_id))
        if entry is not None:
            matched.append((node_id, entry))
    assert matched, "no shipped entry matched any node in the fixture"
    return matched


def test_the_cross_checks_hold_for_every_node_of_a_curated_model(
    database: ProfileDatabase,
) -> None:
    """The same three checks the plan runs on nodes 36, 37 and 40, on every node captured.

    Four of Jayant's nodes share the VZW32-SN fingerprint and three share the ZEN35 one, so
    an entry that is right for one of them must be right for all of them.
    """
    for node_id, entry in _entries_matching_the_fixture(database):
        groups = _node(node_id)["association_groups"]["0"]
        for emitter in entry.emitters:
            for feature, group_id in emitter.actions.items():
                assert group_id in groups, (
                    f"node {node_id} {emitter.emitter_id}.{feature} names group {group_id}, "
                    "which does not exist on the device"
                )
                assert not groups[group_id]["is_lifeline"], (
                    f"node {node_id} {emitter.emitter_id}.{feature} names the lifeline"
                )
                assert feature in features_of_group(groups[group_id]["issued_commands"]), (
                    f"node {node_id} {emitter.emitter_id} claims {feature} on group "
                    f"{group_id}, which issues {groups[group_id]['issued_commands']}"
                )


def test_settings_adapters_hold_for_every_node_whose_config_was_captured(
    database: ProfileDatabase,
) -> None:
    """Only nodes with captured config values can be checked; the rest prove nothing."""
    checked = 0
    for node_id, entry in _entries_matching_the_fixture(database):
        config_values = _node(node_id).get("config_values", [])
        if not config_values:
            continue
        real = {(v["property"], v["property_key"]) for v in config_values}
        for name, adapter in entry.settings.items():
            checked += 1
            assert (adapter.parameter, adapter.bitmask) in real, (
                f"node {node_id} adapter {name!r} points at parameter "
                f"{adapter.parameter}/{adapter.bitmask}, which the device does not expose"
            )
    assert checked, "no adapter was cross-checked against a real device"


def test_the_inovelli_config_button_follows_its_commands_and_not_its_label(
    database: ProfileDatabase,
) -> None:
    """Group 7 is labelled Multilevel Switch Set but issues Basic Set. The label lies."""
    entry = database.lookup(_fingerprint(37))
    assert entry is not None

    group_7 = _node(37)["association_groups"]["0"]["7"]
    assert group_7["label"] == "Multilevel Switch Set (Config Button)"
    assert group_7["issued_commands"] == {"32": [1]}

    config_button = next(e for e in entry.emitters if e.emitter_id == "config_button")
    assert config_button.actions == {Feature.ON_OFF: "7"}
    assert "Multilevel" not in config_button.label, "the honest label must not repeat the lie"


def test_the_zooz_small_buttons_stay_marked_until_stage_0_z7_is_closed(
    database: ProfileDatabase,
) -> None:
    """Task 7 refuses Off-all on these emitters, and this marker is the only thing saying so."""
    entry = database.lookup(_fingerprint(36))
    assert entry is not None

    marked = {e.emitter_id for e in entry.emitters if e.semantics == "unknown"}
    assert marked == {"button_1", "button_2", "button_3", "button_4"}

    main = next(e for e in entry.emitters if e.emitter_id == "main_button")
    assert main.semantics is None, "the main paddle has a real off press, so it is not in doubt"


def test_lookup_ignores_firmware(database: ProfileDatabase) -> None:
    """One entry covers every firmware of a model, so an update never loses the profile."""
    current = _fingerprint(37)
    upgraded = ZWaveFingerprint(
        manufacturer_id=current.manufacturer_id,
        product_type=current.product_type,
        product_id=current.product_id,
        firmware="99.0.0",
    )

    assert database.lookup(upgraded) is database.lookup(current)


# --- the shipped schema, and the hand rolled validator it documents ------------------------


def _schema() -> dict[str, Any]:
    return json.loads((PROFILES_DIR / "schema.json").read_text())


def test_every_profile_file_points_at_the_shipped_schema() -> None:
    """The schema is only useful to a contributor if their editor finds it."""
    for path in PROFILES_DIR.glob("*.json"):
        if path.name == "schema.json":
            continue
        assert json.loads(path.read_text())["$schema"] == "./schema.json", path.name


def test_the_shipped_schema_matches_the_hand_rolled_validator() -> None:
    """The schema documents; profile_db.py enforces. This is what stops them drifting.

    No JSON Schema validator ships with the integration (that would be a new dependency), so
    the schema cannot be executed. Comparing the two descriptions of the same rules is the
    next best thing, and it fails the build rather than misleading a contributor.
    """
    schema = _schema()
    defs = schema["$defs"]

    def keys(node: dict[str, Any]) -> tuple[set[str], set[str]]:
        return set(node["properties"]), set(node.get("required", []))

    assert keys(schema) == (
        profile_db.TOP_REQUIRED_KEYS | profile_db.TOP_OPTIONAL_KEYS,
        set(profile_db.TOP_REQUIRED_KEYS),
    )
    assert keys(defs["device"]) == (
        profile_db.DEVICE_REQUIRED_KEYS | profile_db.DEVICE_OPTIONAL_KEYS,
        set(profile_db.DEVICE_REQUIRED_KEYS),
    )
    assert keys(defs["fingerprint"]) == (
        set(profile_db.FINGERPRINT_REQUIRED_KEYS),
        set(profile_db.FINGERPRINT_REQUIRED_KEYS),
    )
    assert keys(defs["emitter"]) == (
        profile_db.EMITTER_REQUIRED_KEYS | profile_db.EMITTER_OPTIONAL_KEYS,
        set(profile_db.EMITTER_REQUIRED_KEYS),
    )
    assert keys(defs["settings_adapter"]) == (
        set(profile_db.ADAPTER_REQUIRED_KEYS),
        set(profile_db.ADAPTER_REQUIRED_KEYS),
    )
    assert set(defs["emitter"]["properties"]["kind"]["enum"]) == profile_db.EMITTER_KINDS
    assert set(defs["emitter"]["properties"]["semantics"]["enum"]) == (
        profile_db.SEMANTICS_MARKERS | {None}
    )
    assert set(defs["actions"]["propertyNames"]["enum"]) == {str(f) for f in Feature}


# --- validation: what a contributor's mistake must do -------------------------------------


def _emitter(**overrides: Any) -> dict[str, Any]:
    return {
        "emitter_id": "paddle",
        "label": "Paddle",
        "kind": "paddle",
        "actions": {"on_off": "2"},
        **overrides,
    }


def _device(**overrides: Any) -> dict[str, Any]:
    return {
        "model": "Test model",
        "manufacturer": "Test",
        "fingerprints": [{"manufacturer_id": 1, "product_type": 2, "product_id": 3}],
        "emitters": [_emitter()],
        **overrides,
    }


def _files(*devices: dict[str, Any], name: str = "test.json") -> dict[str, str]:
    return {name: json.dumps({"devices": list(devices)})}


def test_a_minimal_entry_loads() -> None:
    """The baseline the rejection cases are variations on."""
    database = load_profiles(_files(_device()))

    assert len(database.entries) == 1
    assert database.entries[0].settings == {}
    assert database.entries[0].wake_instruction is None
    assert database.entries[0].notes == ""
    assert database.entries[0].emitters[0].capacity_override is None
    assert database.entries[0].emitters[0].semantics is None


def test_the_optional_entry_fields_are_carried_through() -> None:
    device = _device(
        wake_instruction="Press the button on the back",
        notes="captured from node 40",
        emitters=[_emitter(capacity_override=5, semantics="unknown")],
        settings={"local_control": {"parameter": 19, "bitmask": None, "values": {"off": 0}}},
    )
    entry = load_profiles(_files(device)).entries[0]

    assert entry.wake_instruction == "Press the button on the back"
    assert entry.notes == "captured from node 40"
    assert entry.emitters[0].capacity_override == 5
    assert entry.emitters[0].semantics == "unknown"
    assert entry.settings["local_control"].bitmask is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "expected an object, got a list"),
        ('{"devices": []}', "must not be empty"),
        ('{"devices": {}}', "expected a list, got an object"),
        ('{"devices": [], "extra": 1}', "unknown key\\(s\\) 'extra'"),
        ('{"devices": [1]}', "expected an object, got a number"),
        ('{"devices": [true]}', "expected an object, got a boolean"),
        ('{"devices": [null]}', "expected an object, got null"),
    ],
)
def test_a_malformed_document_is_rejected(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_profiles({"broken.json": text})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"model": ""}, "'model': must not be empty"),
        ({"model": 5}, "'model': expected a string, got a number"),
        ({"manufacturer": None}, "'manufacturer': expected a string, got null"),
        ({"extra": 1}, "unknown key\\(s\\) 'extra'"),
        ({"fingerprints": []}, "'fingerprints': must not be empty"),
        (
            {
                "fingerprints": [{"manufacturer_id": 1}],
            },
            "missing required key",
        ),
        (
            {"fingerprints": [{"manufacturer_id": "1", "product_type": 2, "product_id": 3}]},
            "'manufacturer_id': expected an integer",
        ),
        (
            {"fingerprints": [{"manufacturer_id": -1, "product_type": 2, "product_id": 3}]},
            "at least 0",
        ),
        ({"emitters": []}, "'emitters': must not be empty"),
        ({"emitters": [_emitter(), _emitter()]}, "emitter id 'paddle' appears twice"),
        ({"notes": ""}, "'notes': must not be empty"),
        ({"wake_instruction": 3}, "'wake_instruction': expected a string"),
        ({"settings": []}, "'settings': expected an object, got a list"),
    ],
)
def test_a_malformed_device_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_profiles(_files(_device(**overrides)))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"emitter_id": 2}, "'emitter_id': expected a string"),
        ({"label": ""}, "'label': must not be empty"),
        ({"kind": "knob"}, "'knob' is not one of"),
        ({"semantics": "unkown"}, "'unkown' is not one of"),
        ({"capacity_override": 0}, "at least 1"),
        ({"actions": {}}, "must name at least one feature"),
        ({"actions": {"dimming": "2"}}, "'dimming' is not a feature"),
        ({"actions": {"on_off": 2}}, "expected a group id to be a string"),
        ({"actions": {"on_off": "two"}}, "'two' is not a decimal group id"),
        ({"actions": {"on_off": "1"}}, "group 1 is the lifeline"),
        ({"scene": "3"}, "unknown key\\(s\\) 'scene'"),
    ],
)
def test_a_malformed_emitter_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_profiles(_files(_device(emitters=[_emitter(**overrides)])))


@pytest.mark.parametrize(
    ("adapter", "message"),
    [
        ({"parameter": 35, "values": {"on": 1}}, "missing required key\\(s\\) 'bitmask'"),
        ({"parameter": 0, "bitmask": None, "values": {"on": 1}}, "at least 1"),
        ({"parameter": 35, "bitmask": 0, "values": {"on": 1}}, "at least 1"),
        ({"parameter": 35, "bitmask": None, "values": {}}, "must name at least one value"),
        ({"parameter": 35, "bitmask": None, "values": {"on": "1"}}, "expected an integer"),
        ({"parameter": 35, "bitmask": None, "values": {"on": True}}, "got a boolean"),
    ],
)
def test_a_malformed_settings_adapter_is_rejected(adapter: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_profiles(_files(_device(settings={"mirror_hub_commands": adapter})))


def test_two_entries_cannot_claim_the_same_device() -> None:
    """Otherwise which profile a device got would depend on dict ordering."""
    with pytest.raises(ValueError, match="already claimed by"):
        load_profiles(_files(_device(), _device(model="Rebadge")))


def test_a_duplicate_fingerprint_across_files_is_rejected_in_a_stable_order() -> None:
    """Files load in name order, so the same clash names the same file every run."""
    files = {
        "b.json": json.dumps({"devices": [_device(model="Second")]}),
        "a.json": json.dumps({"devices": [_device(model="First")]}),
    }
    with pytest.raises(ValueError, match=r"b\.json Second.*already claimed by a\.json First"):
        load_profiles(files)


def test_a_device_with_no_model_still_names_its_file_in_the_error() -> None:
    """The label an error uses is best effort, so a broken entry still points somewhere."""
    with pytest.raises(ValueError, match=r"^broken\.json: missing required key"):
        load_profiles({"broken.json": json.dumps({"devices": [{}]})})
