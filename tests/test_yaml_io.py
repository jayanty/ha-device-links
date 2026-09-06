"""Profile export and import: the file a user keeps in git, and reading it back.

The export exists so a design can live in version control (FR-P2), which only works if the
same profile always produces the same bytes. Half of these tests are about that, and the
other half are about an import saying which rule is wrong rather than "invalid profile".
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.device_links.models import (
    Backend,
    DeviceHandle,
    Direction,
    Feature,
    MatterFingerprint,
    MirrorChoice,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
    ZigbeeFingerprint,
)
from custom_components.device_links.yaml_io import (
    SCHEMA_VERSION,
    ProfileFormatError,
    dump_profile,
    observed_link_from_data,
    observed_link_to_data,
    parse_profile,
    profile_from_data,
    profile_to_data,
)
from tests.factories import handle, link, observed


def _handle(node_id: int) -> DeviceHandle:
    """Return a handle as an imported profile carries one: no local device registry id.

    `ha_device_id` is deliberately not exported, so a profile that has been through a file
    has none until the coordinator resolves it against this instance's registry. Building
    the fixtures that way is what lets the round trip be an equality rather than a
    field-by-field comparison that could quietly stop covering a field.
    """
    return replace(handle(node_id), ha_device_id="")


def _rule(
    rule_id: str = "rule-1",
    *,
    enabled: bool = True,
    mirror: MirrorChoice = MirrorChoice.LEAVE,
    targets: tuple[int, ...] = (38,),
) -> Rule:
    return Rule(
        id=rule_id,
        name=f"Rule {rule_id}",
        template=Template.REMOTE,
        backend=Backend.ZWAVE,
        source=RuleSource(device=_handle(36), endpoint=0, emitter_id="g2"),
        targets=tuple(RuleTarget(device=_handle(node), endpoint=None) for node in targets),
        features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD}),
        direction=Direction.TWO_WAY,
        mirror_source=mirror,
        enabled=enabled,
    )


def _profile() -> Profile:
    return Profile(
        id="profile-1",
        name="Bedroom",
        rules=(
            _rule("rule-1", mirror=MirrorChoice.ON, targets=(38, 35)),
            _rule("rule-2", enabled=False, mirror=MirrorChoice.OFF),
        ),
    )


def test_a_profile_round_trips() -> None:
    """Two rules, several targets, a disabled rule and mirror choices, back unchanged."""
    profile = _profile()

    assert parse_profile(dump_profile(profile)) == profile


def test_export_is_byte_identical_for_the_same_profile() -> None:
    """A diff that churns on every save makes the git-tracking use case worthless."""
    profile = _profile()

    assert dump_profile(profile) == dump_profile(_profile())
    assert dump_profile(profile) == dump_profile(profile)


def test_the_device_block_does_not_depend_on_the_order_devices_were_first_seen() -> None:
    """Mappings and sets have no stable iteration order, so both are sorted before dumping."""
    forwards = dump_profile(Profile(id="p", name="P", rules=(_rule(targets=(38, 35)),)))
    backwards = dump_profile(Profile(id="p", name="P", rules=(_rule(targets=(35, 38)),)))

    assert _section(forwards, "devices:") == _section(backwards, "devices:")


def _section(text: str, header: str) -> str:
    """Return one block of the dump, for comparing that block on its own."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next(
        (
            i
            for i, line in enumerate(lines[start + 1 :], start + 1)
            if len(line) - len(line.lstrip()) <= indent
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_export_omits_what_is_local_to_one_home_assistant() -> None:
    """A device registry id means nothing on the instance the file is imported into."""
    profile = Profile(id="p", name="P", rules=(_rule(),))
    local_id = handle(36).ha_device_id

    text = dump_profile(replace(profile, rules=(_local_rule(),)))

    assert "ha_device_id" not in text
    assert local_id not in text


def _local_rule() -> Rule:
    """Return a rule whose handles carry this instance's device registry ids."""
    rule = _rule()
    return replace(
        rule,
        source=replace(rule.source, device=handle(36)),
        targets=(RuleTarget(device=handle(38), endpoint=None),),
    )


def test_names_are_exported_for_the_reader_and_never_matched_on() -> None:
    """An export with no names is unreadable in a diff, which is half the point of it.

    So names are exported, and identity is `protocol_id`: renaming a device in the file
    changes what a human reads and nothing about which device a rule means.
    """
    text = dump_profile(Profile(id="p", name="P", rules=(_rule(),)))
    assert "Bedroom Scene Controller" in text

    renamed = parse_profile(text.replace("Bedroom Scene Controller", "Something Else"))

    assert renamed.rules[0].source.device.identity == _handle(36).identity
    assert renamed.rules[0].source.device.name_at_authoring == "Something Else"


def test_an_unknown_schema_version_is_refused_naming_both_versions() -> None:
    """E38. Guessing at a format a later version wrote is how an import loses rules."""
    text = dump_profile(_profile()).replace(f"version: {SCHEMA_VERSION}", "version: 99")

    with pytest.raises(ProfileFormatError) as error:
        parse_profile(text)

    assert "99" in str(error.value)
    assert str(SCHEMA_VERSION) in str(error.value)


def test_malformed_yaml_names_the_line() -> None:
    """ "Invalid YAML" in a forty-rule file is unactionable without a line number."""
    with pytest.raises(ProfileFormatError) as error:
        parse_profile("version: 1\nprofile:\n  id: x\n   name: bad indent\n")

    assert "line 4" in str(error.value)


def _mutated(**changes: object) -> str:
    """Return the export of a two-rule profile with rule-2's raw fields changed."""
    import yaml  # noqa: PLC0415

    payload = yaml.safe_load(dump_profile(_profile()))
    payload["profile"]["rules"][1].update(changes)
    return yaml.safe_dump(payload)


def test_a_rule_naming_an_unknown_template_is_rejected() -> None:
    with pytest.raises(ProfileFormatError, match="template"):
        parse_profile(_mutated(template="teleport"))


def test_a_rule_naming_a_feature_that_does_not_exist_is_rejected() -> None:
    with pytest.raises(ProfileFormatError, match="feature"):
        parse_profile(_mutated(features=["on_off", "smell"]))


def test_a_rule_with_no_targets_is_rejected() -> None:
    with pytest.raises(ProfileFormatError, match="target"):
        parse_profile(_mutated(targets=[]))


def test_a_rule_pointing_at_a_device_the_file_does_not_describe_is_rejected() -> None:
    """E38's "unknown devices": a target nothing else in the file says anything about."""
    with pytest.raises(ProfileFormatError, match="zwave:3538613642:404"):
        parse_profile(_mutated(targets=[{"device": "zwave:3538613642:404", "endpoint": None}]))


@pytest.mark.parametrize(
    "changes",
    [
        {"template": "teleport"},
        {"features": ["smell"]},
        {"targets": []},
        {"direction": "sideways"},
        {"mirror_source": "maybe"},
        {"backend": "zigbee"},
        {"source": {"device": "zwave:3538613642:404", "endpoint": 0, "emitter_id": "g2"}},
    ],
)
def test_every_rule_error_names_the_offending_rule(changes: dict[str, object]) -> None:
    """ "Invalid profile" is unactionable in a file with forty rules."""
    with pytest.raises(ProfileFormatError, match="rule-2"):
        parse_profile(_mutated(**changes))


def test_a_rule_with_no_usable_id_is_named_by_its_index() -> None:
    """A rule whose id is missing cannot be named by it, and must still be findable."""
    with pytest.raises(ProfileFormatError, match="index 1"):
        parse_profile(_mutated(id=None))


def test_every_broken_rule_is_reported_not_only_the_first() -> None:
    """E38 asks for the errors in the file, so one import fixes one round of editing."""
    import yaml  # noqa: PLC0415

    payload = yaml.safe_load(dump_profile(_profile()))
    payload["profile"]["rules"][0].update({"template": "teleport"})
    payload["profile"]["rules"][1].update({"targets": []})

    with pytest.raises(ProfileFormatError) as error:
        parse_profile(yaml.safe_dump(payload))

    assert "rule-1" in str(error.value)
    assert "rule-2" in str(error.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[]", "mapping"),
        ("version: 1\n", "profile"),
        ("profile:\n  id: x\n", "version"),
        ("version: 1\nprofile: []\n", "profile"),
        ("version: 1\nprofile:\n  id: x\n  name: y\n  rules: {}\n  devices: {}\n", "rules"),
    ],
)
def test_a_file_that_is_not_a_profile_at_all_is_refused(text: str, expected: str) -> None:
    with pytest.raises(ProfileFormatError, match=expected):
        parse_profile(text)


def test_a_zigbee_and_a_matter_rule_round_trip_too() -> None:
    """The codec is not Z-Wave's: each backend's model identity has its own shape."""
    zigbee = DeviceHandle(
        backend=Backend.ZIGBEE2MQTT,
        protocol_id="0x00124b002e1dfd4a",
        ha_device_id="",
        fingerprint=ZigbeeFingerprint(manufacturer="IKEA", model="LED2201G8"),
        name_at_authoring="Entrance Inside Lights",
    )
    matter = DeviceHandle(
        backend=Backend.MATTER,
        protocol_id="1:8",
        ha_device_id="",
        fingerprint=MatterFingerprint(vendor="Inovelli", product="VTM31-SN"),
        name_at_authoring="Office Fan Switch",
    )
    profile = Profile(
        id="mixed",
        name="Mixed",
        rules=(
            Rule(
                id="zigbee-rule",
                name="Aux controls the load",
                template=Template.VIRTUAL_3WAY,
                backend=Backend.ZIGBEE2MQTT,
                source=RuleSource(device=zigbee, endpoint=2, emitter_id="ep2"),
                targets=(RuleTarget(device=matter, endpoint=1),),
                features=frozenset({Feature.ON_OFF}),
            ),
        ),
    )

    assert parse_profile(dump_profile(profile)) == profile


def test_a_profile_with_two_rules_sharing_an_id_is_refused() -> None:
    """The rule id is how everything downstream refers to a rule, ambiguity included."""
    with pytest.raises(ProfileFormatError, match="duplicate"):
        parse_profile(_mutated(id="rule-1"))


def test_a_rule_naming_the_same_target_twice_is_refused() -> None:
    """Two identical targets would compile the same link twice and plan it once."""
    duplicate = {"device": "zwave:3538613642:38", "endpoint": None}
    with pytest.raises(ProfileFormatError, match="duplicate target"):
        parse_profile(_mutated(targets=[duplicate, dict(duplicate)]))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"enabled": "yes"}, "true or false"),
        ({"name": 7}, "must be text"),
        (
            {"source": {"device": "zwave:3538613642:36", "endpoint": "0", "emitter_id": "g2"}},
            "whole number",
        ),
        ({"features": "on_off"}, "must be a list"),
    ],
)
def test_a_field_of_the_wrong_kind_says_what_was_found(
    changes: dict[str, object], expected: str
) -> None:
    with pytest.raises(ProfileFormatError, match=expected):
        parse_profile(_mutated(**changes))


def test_a_rule_that_is_not_a_mapping_is_named_by_its_index() -> None:
    import yaml  # noqa: PLC0415

    payload = yaml.safe_load(dump_profile(_profile()))
    payload["profile"]["rules"][1] = "not a rule"

    with pytest.raises(ProfileFormatError, match="index 1"):
        parse_profile(yaml.safe_dump(payload))


def test_a_device_filed_under_an_address_it_disagrees_with_is_refused() -> None:
    """The key is the identity everything else in the file refers to, so it has to be true."""
    text = dump_profile(_profile()).replace(
        "protocol_id: '3538613642:38'", "protocol_id: '3538613642:99'"
    )

    with pytest.raises(ProfileFormatError, match="disagrees"):
        parse_profile(text)


def test_a_rule_with_no_features_is_rejected() -> None:
    with pytest.raises(ProfileFormatError, match="features"):
        parse_profile(_mutated(features=[]))


def test_the_data_form_keeps_the_local_device_id_when_storage_asks_for_it() -> None:
    """Storage is this instance's own file, so there the registry id is worth keeping."""
    profile = Profile(id="p", name="P", rules=(_local_rule(),))

    data = profile_to_data(profile, keep_local_ids=True)
    devices = data["devices"]
    assert isinstance(devices, dict)

    assert devices[handle(36).identity]["ha_device_id"] == handle(36).ha_device_id
    assert profile_from_data(data) == profile


def test_an_observed_link_round_trips_with_its_ownership_intact() -> None:
    """Snapshots are rebuilt from these, so what may be done to an entry must survive."""
    entry = observed(link(36, "g2", 38, Feature.ON_OFF), rule_id="rule-1")

    assert observed_link_from_data(observed_link_to_data(entry)) == entry


def test_a_stored_link_that_could_never_exist_is_refused() -> None:
    """A file saying a device controls itself is corrupt, not something to reconstruct."""
    data = observed_link_to_data(observed(link(36, "g2", 38, Feature.ON_OFF), rule_id=None))
    data["target"] = {"device": data["source"], "endpoint": None}

    with pytest.raises(ProfileFormatError, match="cannot control itself"):
        observed_link_from_data(data)


def test_a_stored_link_missing_a_field_says_which_one() -> None:
    data = observed_link_to_data(observed(link(36, "g2", 38, Feature.ON_OFF), rule_id=None))
    del data["feature"]

    with pytest.raises(ProfileFormatError, match="feature"):
        observed_link_from_data(data)


def test_a_rules_features_are_written_in_a_fixed_order() -> None:
    """A frozenset has no order of its own, so one is imposed before it is written.

    Without the sort this is a file that can differ from itself between two processes with
    nothing changed, which is exactly the churn that makes tracking an export in git
    pointless. The literal below is the file, not an implementation detail: it is what a
    diff shows.
    """
    text = dump_profile(Profile(id="p", name="P", rules=(_rule(),)))

    assert "    features:\n    - level_hold\n    - on_off\n" in text
