"""Profile entries must match the hardware they claim to describe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.device_links import profile_db
from custom_components.device_links.backends import zigbee_protocol
from custom_components.device_links.backends.zwave_protocol import features_of_group
from custom_components.device_links.models import Feature, ZigbeeFingerprint, ZWaveFingerprint
from custom_components.device_links.profile_db import ProfileDatabase, load_profiles
from tests.factories import profiles, zigbee_devices

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
        ({"actions": {"on_off": "two"}}, "'two' is not a group id"),
        ({"actions": {"on_off": "07"}}, "'07' is not a group id"),
        ({"actions": {"on_off": "0"}}, "'0' is not a group id"),
        ({"actions": {"on_off": "\u0662"}}, "is not a group id"),
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


# --- Zigbee entries, validated against the Stage 0 G1 capture ------------------------------


def _zigbee_entries() -> tuple[Any, ...]:
    return profiles().zigbee_entries


def _matching_devices(entry: Any) -> list[Any]:
    """Return every device in the G1 capture this entry's fingerprints claim."""
    return [
        device
        for device in zigbee_devices().values()
        if zigbee_protocol.fingerprint_of(device)
        in [ZigbeeFingerprint(manufacturer=f.vendor, model=f.model) for f in entry.fingerprints]
    ]


def test_the_shipped_zigbee_entries_are_the_two_models_in_the_capture() -> None:
    """VZM35-SN is deliberately absent: nothing of that model is on this network.

    A curated entry writes a binding to the endpoint it names with complete confidence and
    no error, so an entry nobody could check against hardware is exactly the entry not to
    ship. Adding it is a job for whoever has one to capture.
    """
    models = {f.model for entry in _zigbee_entries() for f in entry.fingerprints}

    assert models == {"VZM31-SN", "VZM32-SN"}


def test_every_zigbee_entry_claims_a_device_that_is_really_on_this_network() -> None:
    for entry in _zigbee_entries():
        assert _matching_devices(entry), f"no device in the capture matches {entry.fingerprints}"


def test_every_endpoint_a_zigbee_entry_names_exists_on_a_real_device() -> None:
    """The check that stops a curated entry writing a binding to an endpoint that is not there.

    "On a real device" rather than "on every device of the model", because the capture shows
    the difference is real: two of the nine VZM31-SN switches are on software 2.00 and report
    no endpoint 3. What must be true is that nothing here was invented, so every emitter has
    to be demonstrable on at least one device the bridge actually reported.
    """
    for entry in _zigbee_entries():
        devices = _matching_devices(entry)
        for emitter in entry.emitters:
            supported = [
                device
                for device in devices
                if zigbee_protocol.endpoint_of(device, emitter.endpoint) is not None
            ]
            assert supported, (
                f"{entry.fingerprints[0].model} emitter {emitter.emitter_id!r} names endpoint "
                f"{emitter.endpoint}, which no device of that model reports"
            )


def test_every_cluster_a_zigbee_entry_claims_is_driven_by_that_endpoint() -> None:
    """A cluster an endpoint does not drive is a binding that is written and does nothing."""
    for entry in _zigbee_entries():
        for emitter in entry.emitters:
            for feature, cluster in emitter.actions.items():
                supported = [
                    device
                    for device in _matching_devices(entry)
                    if zigbee_protocol.emits(device, emitter.endpoint, cluster)
                ]
                assert supported, (
                    f"{entry.fingerprints[0].model} emitter {emitter.emitter_id!r} maps "
                    f"{feature} to {cluster} on endpoint {emitter.endpoint}, which no device "
                    "of that model drives from there"
                )
                assert feature in zigbee_protocol.features_of_cluster(cluster), (
                    f"{cluster} cannot carry {feature}"
                )


def test_a_curated_zigbee_entry_survives_resolution_on_the_devices_it_describes() -> None:
    """The end-to-end version: the entry and the hardware agree, device by device."""
    for entry in _zigbee_entries():
        for device in _matching_devices(entry):
            warnings: list[str] = []
            controls = zigbee_protocol.resolve_emitters(device, entry, warnings=warnings)

            assert controls, f"{device['friendly_name']} was left with no controls at all"
            for control in controls:
                assert zigbee_protocol.endpoint_of(device, control.endpoint) is not None
                for cluster in control.group_ids:
                    assert zigbee_protocol.emits(device, control.endpoint, cluster)


def test_the_two_older_switches_lose_the_config_button_and_keep_the_paddle() -> None:
    """The one place in the capture where a shipped entry and a real device disagree."""
    entry = next(e for e in _zigbee_entries() if e.fingerprints[0].model == "VZM31-SN")
    older = [
        device
        for device in _matching_devices(entry)
        if zigbee_protocol.endpoint_of(device, 3) is None
    ]

    assert [device["friendly_name"] for device in older] == [
        "Hallway Side Lights",
        "House Front Lights",
    ]
    for device in older:
        controls = zigbee_protocol.resolve_emitters(device, entry)
        assert [control.endpoint for control in controls] == [2]
        assert controls[0].label == "Paddle"


def test_the_config_button_is_marked_as_not_established() -> None:
    """Same treatment as the Zooz small button (A3): the pessimistic case, carried forward.

    Nobody has observed what an Inovelli config button sends on a press, so Off-all must not
    compile silently onto it. The compiler warns instead.
    """
    for entry in _zigbee_entries():
        button = next(e for e in entry.emitters if e.emitter_id == "config_button")
        assert button.semantics == profile_db.SEMANTICS_UNKNOWN


def test_the_zigbee_settings_adapters_name_the_same_choices_on_both_sides() -> None:
    """`values` is what the compiler asks for and `payloads` is what the bridge is sent.

    The property names and the payload labels are the one thing in these entries the G1
    capture could not confirm: it trimmed `definition.exposes`, which is where Zigbee2MQTT
    describes them. Nothing writes them today and the adapter says so, so what this can
    check is that they are internally complete. See docs/open-items.md T45.
    """
    for entry in _zigbee_entries():
        assert set(entry.settings) == {
            "smart_bulb_mode",
            "local_protection",
            "remote_protection",
            "binding_off_to_on_sync_level",
        }
        for adapter in entry.settings.values():
            assert set(adapter.values) == set(adapter.payloads)
            assert adapter.property_name


def test_the_load_endpoint_is_receivable_without_being_curated() -> None:
    """Endpoint 1 is what a rule targets, and the device already says what it can act on."""
    for entry in _zigbee_entries():
        for device in _matching_devices(entry):
            assert Feature.ON_OFF in zigbee_protocol.receivable_features(device)
            assert zigbee_protocol.accepts(device, 1, zigbee_protocol.GEN_ON_OFF)


# --- the Zigbee half of the schema, and the validator it documents -------------------------


def test_the_shipped_schema_documents_the_zigbee_shapes_too() -> None:
    """Same reasoning as the Z-Wave half: the schema documents, profile_db.py enforces."""
    defs = _schema()["$defs"]

    def keys(node: dict[str, Any]) -> tuple[set[str], set[str]]:
        return set(node["properties"]), set(node.get("required", []))

    assert keys(defs["zigbee_device"]) == (
        profile_db.ZIGBEE_DEVICE_REQUIRED_KEYS | profile_db.ZIGBEE_DEVICE_OPTIONAL_KEYS,
        set(profile_db.ZIGBEE_DEVICE_REQUIRED_KEYS),
    )
    assert keys(defs["zigbee_fingerprint"]) == (
        set(profile_db.ZIGBEE_FINGERPRINT_REQUIRED_KEYS),
        set(profile_db.ZIGBEE_FINGERPRINT_REQUIRED_KEYS),
    )
    assert keys(defs["zigbee_emitter"]) == (
        profile_db.ZIGBEE_EMITTER_REQUIRED_KEYS | profile_db.ZIGBEE_EMITTER_OPTIONAL_KEYS,
        set(profile_db.ZIGBEE_EMITTER_REQUIRED_KEYS),
    )
    assert keys(defs["zigbee_settings_adapter"]) == (
        set(profile_db.ZIGBEE_ADAPTER_REQUIRED_KEYS),
        set(profile_db.ZIGBEE_ADAPTER_REQUIRED_KEYS),
    )
    assert set(defs["zigbee_actions"]["propertyNames"]["enum"]) == {str(f) for f in Feature}
    assert {
        defs["device"]["properties"]["backend"]["const"],
        defs["zigbee_device"]["properties"]["backend"]["const"],
    } == profile_db.PROFILE_BACKENDS


# --- validation: what a contributor's Zigbee mistake must do -------------------------------


def _zigbee_emitter(**overrides: Any) -> dict[str, Any]:
    return {
        "emitter_id": "paddle",
        "label": "Paddle",
        "kind": "paddle",
        "endpoint": 2,
        "actions": {"on_off": "genOnOff"},
        **overrides,
    }


def _zigbee_device(**overrides: Any) -> dict[str, Any]:
    return {
        "backend": "zigbee2mqtt",
        "model": "Test model",
        "manufacturer": "Test",
        "fingerprints": [{"vendor": "Test", "model": "Test model"}],
        "emitters": [_zigbee_emitter()],
        **overrides,
    }


def test_a_minimal_zigbee_entry_loads() -> None:
    database = load_profiles(_files(_zigbee_device()))

    assert database.entries == ()
    assert len(database.zigbee_entries) == 1
    assert database.zigbee_entries[0].emitters[0].endpoint == 2
    assert database.zigbee_entries[0].settings == {}


def test_an_entry_with_no_backend_is_still_a_zwave_entry() -> None:
    """Every entry written before Phase 2 is one, and a default that rewrote history
    would be worse than one that matches it.
    """
    database = load_profiles(_files(_device()))

    assert len(database.entries) == 1
    assert database.zigbee_entries == ()


def test_a_zigbee_device_is_looked_up_by_its_converter_definition() -> None:
    database = load_profiles(_files(_zigbee_device()))

    assert database.lookup_zigbee(ZigbeeFingerprint(manufacturer="Test", model="Test model"))
    assert database.lookup_zigbee(ZigbeeFingerprint(manufacturer="Test", model="Other")) is None


def test_two_zigbee_entries_claiming_one_model_are_refused() -> None:
    """At most one entry may match a device, or the lookup depends on iteration order."""
    with pytest.raises(ValueError, match="already claimed"):
        load_profiles(_files(_zigbee_device(), _zigbee_device()))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"backend": "matter"}, "'backend': 'matter' is not one of"),
        ({"backend": 5}, "'backend': expected a string"),
        ({"capacity_override": 3}, "unknown key"),
        ({"fingerprints": [{"vendor": "Test"}]}, "missing required key"),
        ({"fingerprints": [{"vendor": "Test", "model": ""}]}, "'model': must not be empty"),
        (
            {"emitters": [_zigbee_emitter(endpoint=0)]},
            "'endpoint': expected an integer of at least 1",
        ),
        ({"emitters": [_zigbee_emitter(endpoint="2")]}, "'endpoint': expected an integer"),
        ({"emitters": [_zigbee_emitter(actions={})]}, "must name at least one feature"),
        ({"emitters": [_zigbee_emitter(actions={"nope": "genOnOff"})]}, "is not a feature"),
        (
            {"emitters": [_zigbee_emitter(actions={"on_off": "gen OnOff"})]},
            "is not a cluster name",
        ),
        ({"emitters": [_zigbee_emitter(actions={"on_off": 6})]}, "expected a cluster name"),
        ({"emitters": [_zigbee_emitter(capacity_override=3)]}, "unknown key"),
        ({"emitters": [_zigbee_emitter(semantics="maybe")]}, "'semantics': 'maybe' is not"),
        (
            {"settings": {"a": {"property": "p", "values": {"on": 1}}}},
            "missing required key\\(s\\) 'payloads'",
        ),
        (
            {"settings": {"a": {"property": "p", "values": {"on": 1}, "payloads": {"off": "No"}}}},
            "every choice needs both",
        ),
        (
            {"settings": {"a": {"property": "", "values": {"on": 1}, "payloads": {"on": "Yes"}}}},
            "'property': must not be empty",
        ),
        (
            {"settings": {"a": {"property": "p", "values": {"on": 1}, "payloads": {"on": 3}}}},
            "'on': expected a string",
        ),
        (
            {"settings": {"a": {"property": "p", "values": {"on": 1}, "payloads": {}}}},
            "must name at least one value",
        ),
    ],
)
def test_a_malformed_zigbee_entry_is_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_profiles(_files(_zigbee_device(**overrides)))


def test_two_zigbee_emitters_with_one_id_are_refused() -> None:
    with pytest.raises(ValueError, match="appears twice"):
        load_profiles(
            _files(_zigbee_device(emitters=[_zigbee_emitter(), _zigbee_emitter(endpoint=3)]))
        )
