"""Value types, and the link identity everything else depends on."""

from __future__ import annotations

import pytest

from custom_components.device_links.models import (
    Backend,
    DeviceCapabilities,
    DeviceHandle,
    Emitter,
    Feature,
    Link,
    LinkTarget,
    MatterFingerprint,
    ObservedLink,
    SettingsAdapter,
    ZigbeeFingerprint,
    ZWaveFingerprint,
)
from tests.factories import handle


def test_a_handle_is_identified_by_protocol_id_not_by_name() -> None:
    """Renames and area moves must never break a rule (FR-S1)."""
    original = handle(name="Bedroom Scene Controller")
    renamed = handle(name="Master Bedroom Scene Controller")

    assert original.identity == renamed.identity
    assert original.identity == "zwave:3538613642:36"


def test_handles_for_different_nodes_are_different() -> None:
    assert handle(36).identity != handle(37).identity


def test_link_fingerprint_is_stable_across_equal_links() -> None:
    """Two links describing the same device state must share a fingerprint."""
    first = Link(
        backend=Backend.ZWAVE,
        source=handle(36),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=handle(38), endpoint=None),
        feature=Feature.ON_OFF,
    )
    second = Link(
        backend=Backend.ZWAVE,
        source=handle(36, name="renamed since"),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=handle(38), endpoint=None),
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
        source=handle(36),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=handle(38), endpoint=None),
        feature=Feature.ON_OFF,
    )
    variants = {
        "emitter": Link(**{**base.as_kwargs(), "emitter_id": "g9"}),
        "target": Link(**{**base.as_kwargs(), "target": LinkTarget(handle(37), None)}),
        "endpoint": Link(**{**base.as_kwargs(), "target": LinkTarget(handle(38), 2)}),
        "feature": Link(**{**base.as_kwargs(), "feature": Feature.LEVEL_HOLD}),
        "source": Link(**{**base.as_kwargs(), "source": handle(39)}),
    }

    assert variants[change].fingerprint != base.fingerprint


def test_a_link_cannot_target_its_own_source() -> None:
    """E7: a node cannot be a member of its own association group."""
    device = handle(36)
    with pytest.raises(ValueError, match="cannot control itself"):
        Link(
            backend=Backend.ZWAVE,
            source=device,
            source_endpoint=0,
            emitter_id="g7",
            target=LinkTarget(handle=device, endpoint=None),
            feature=Feature.ON_OFF,
        )


def test_value_types_are_immutable() -> None:
    """Plans are compared and hashed; mutable value types would corrupt that."""
    link = Link(
        backend=Backend.ZWAVE,
        source=handle(36),
        source_endpoint=0,
        emitter_id="g7",
        target=LinkTarget(handle=handle(38), endpoint=None),
        feature=Feature.ON_OFF,
    )
    with pytest.raises(AttributeError):
        link.emitter_id = "g9"  # type: ignore[misc]


# --- identity is the group that gets written, not the emitter the user picked -------------


def _link(**overrides: object) -> Link:
    kwargs: dict[str, object] = {
        "backend": Backend.ZWAVE,
        "source": handle(36),
        "source_endpoint": 0,
        "emitter_id": "g7",
        "target": LinkTarget(handle=handle(38), endpoint=None),
        "feature": Feature.ON_OFF,
    }
    kwargs.update(overrides)
    return Link(**kwargs)


def test_links_are_hashable_so_a_plan_can_index_them() -> None:
    """A field that is not hashable would break set membership silently, not loudly."""
    assert len({_link(), _link(rule_id="rule-1")}) == 2
    assert len({_link(), _link()}) == 1


def test_a_per_group_emitter_id_names_its_own_group() -> None:
    """The convenience default, and the only shape it is allowed for."""
    assert _link(emitter_id="g7").emitter_group == "7"
    assert _link(emitter_id="7").emitter_group == "7"


def test_an_emitter_that_is_not_a_single_group_must_name_its_group() -> None:
    """The Inovelli paddle spans groups 2, 3 and 4, so guessing one would be wrong."""
    with pytest.raises(ValueError, match="emitter_group"):
        _link(emitter_id="paddle")

    assert _link(emitter_id="paddle", emitter_group="3").emitter_group == "3"


def test_the_fingerprint_follows_the_group_not_the_emitter_id() -> None:
    """The same physical write is one identity, whichever emitter the rule named it by."""
    by_group = _link(emitter_id="g3")
    by_paddle = _link(emitter_id="paddle", emitter_group="3")

    assert by_paddle.fingerprint == by_group.fingerprint


def test_reassigning_a_link_to_another_rule_does_not_change_its_identity() -> None:
    """Rule ownership is bookkeeping; the device write is unchanged."""
    assert _link(rule_id="rule-1").fingerprint == _link(rule_id="rule-2").fingerprint
    assert _link(rule_id=None).fingerprint == _link(rule_id="rule-1").fingerprint


def test_a_separator_inside_a_field_cannot_forge_another_links_fingerprint() -> None:
    """Two genuinely different links must never collide through delimiter injection."""
    forged_target = DeviceHandle(
        backend=Backend.ZWAVE,
        protocol_id="a|zwave:b",
        ha_device_id="d",
        fingerprint=ZWaveFingerprint(
            manufacturer_id=634, product_type=28672, product_id=40984, firmware="1.40.0"
        ),
        name_at_authoring="forged",
    )
    plain_target = DeviceHandle(
        backend=Backend.ZWAVE,
        protocol_id="b",
        ha_device_id="d",
        fingerprint=ZWaveFingerprint(
            manufacturer_id=634, product_type=28672, product_id=40984, firmware="1.40.0"
        ),
        name_at_authoring="plain",
    )

    forged = _link(emitter_group="7", target=LinkTarget(forged_target, None))
    plain = _link(emitter_group="7|zwave:a", target=LinkTarget(plain_target, None))

    assert forged.fingerprint != plain.fingerprint


@pytest.mark.parametrize(
    "link",
    [
        _link(),
        _link(emitter_id="paddle", emitter_group="3", rule_id="rule-1"),
        _link(target=LinkTarget(handle(38), 2)),
    ],
)
def test_as_kwargs_reconstructs_the_same_link(link: Link) -> None:
    """It is a copy helper, so a copy with no overrides must change nothing."""
    assert Link(**link.as_kwargs()) == link


# --- observed links, capabilities ---------------------------------------------------------


def _observed(**overrides: object) -> ObservedLink:
    kwargs: dict[str, object] = {
        "backend": Backend.ZWAVE,
        "source": handle(36),
        "source_endpoint": 0,
        "emitter_id": "g7",
        "target": LinkTarget(handle=handle(38), endpoint=None),
        "feature": Feature.ON_OFF,
        "is_system": False,
    }
    kwargs.update(overrides)
    return ObservedLink(**kwargs)


def test_an_observed_link_matches_the_desired_link_it_describes() -> None:
    """This is the whole basis of the planner's diff."""
    desired = _link(rule_id="rule-1")
    observed = _observed(rule_id=None, managed_by="rule-1")

    assert observed.fingerprint == desired.fingerprint
    assert observed.is_system is False
    assert observed.managed_by == "rule-1"


def test_an_observed_link_must_say_whether_it_is_a_system_link() -> None:
    """Defaulting this would let a lifeline pass as an ordinary removable link."""
    with pytest.raises(TypeError, match="is_system"):
        ObservedLink(  # type: ignore[call-arg]
            backend=Backend.ZWAVE,
            source=handle(36),
            source_endpoint=0,
            emitter_id="g1",
            target=LinkTarget(handle=handle(1), endpoint=None),
            feature=Feature.STATUS_REPORT,
        )


def test_an_observed_link_round_trips_through_as_kwargs() -> None:
    observed = _observed(is_system=True, managed_by="rule-1")

    assert ObservedLink(**observed.as_kwargs()) == observed


def test_capabilities_carry_the_emitters_a_link_can_be_built_from() -> None:
    """The Inovelli paddle: one emitter, three groups, a group per feature."""
    paddle = Emitter(
        emitter_id="paddle",
        label="Paddle",
        endpoint=0,
        group_ids=("2", "3", "4"),
        actions={Feature.ON_OFF: "2", Feature.LEVEL_SET: "3", Feature.LEVEL_HOLD: "4"},
        capacity=10,
        supports_endpoint_targets=True,
        is_lifeline=False,
        grouping="profile_db",
    )
    capabilities = DeviceCapabilities(
        handle=handle(37),
        emitters=(paddle,),
        receivable=frozenset({Feature.ON_OFF, Feature.LEVEL_SET}),
        is_long_range=False,
        settings={"send_local_to_associations": SettingsAdapter(59, 1, {"on": 1, "off": 0})},
    )

    held = _link(
        source=capabilities.handle,
        emitter_id=paddle.emitter_id,
        emitter_group=paddle.actions[Feature.LEVEL_HOLD],
        feature=Feature.LEVEL_HOLD,
    )
    pressed = _link(
        source=capabilities.handle,
        emitter_id=paddle.emitter_id,
        emitter_group=paddle.actions[Feature.ON_OFF],
        feature=Feature.ON_OFF,
    )

    assert held.fingerprint != pressed.fingerprint
    assert capabilities.settings["send_local_to_associations"].parameter == 59
    assert capabilities.emitters[0].capacity == 10


def test_capabilities_default_to_no_settings_adapters() -> None:
    """Most devices have none, and the compiler must not have to care."""
    capabilities = DeviceCapabilities(
        handle=handle(38),
        emitters=(),
        receivable=frozenset({Feature.ON_OFF}),
        is_long_range=False,
    )

    assert capabilities.settings == {}


def test_every_backend_has_a_fingerprint_type() -> None:
    """Phase 2 and 3 handles carry their own identity, not a Z-Wave shaped one."""
    zigbee = DeviceHandle(
        backend=Backend.ZIGBEE2MQTT,
        protocol_id="0x00124b002e1dfd4a",
        ha_device_id="d",
        fingerprint=ZigbeeFingerprint(manufacturer="Inovelli", model="VZM31-SN"),
        name_at_authoring="Upper Stairway Lights",
    )
    matter = DeviceHandle(
        backend=Backend.MATTER,
        protocol_id="5",
        ha_device_id="d",
        fingerprint=MatterFingerprint(vendor="Google LLC", product="Nest Learning Thermostat"),
        name_at_authoring="Thermostat",
    )

    assert zigbee.identity == "zigbee2mqtt:0x00124b002e1dfd4a"
    assert matter.identity == "matter:5"
