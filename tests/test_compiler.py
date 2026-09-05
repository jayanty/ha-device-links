"""Compilation: intent in, links and settings out. Pure and deterministic."""

from __future__ import annotations

from dataclasses import replace

from custom_components.device_links.compiler import compile_rule
from custom_components.device_links.models import (
    Backend,
    Direction,
    Feature,
    MirrorChoice,
    Rule,
    RuleSource,
    RuleTarget,
    SettingsAdapter,
    Template,
)
from tests.factories import capabilities_for, handle


def _rule(**overrides: object) -> Rule:
    defaults = {
        "id": "rule-1",
        "name": "Button 3 controls Bedside Light L",
        "template": Template.SCENE_BUTTON,
        "backend": Backend.ZWAVE,
        "source": RuleSource(device=handle(36), endpoint=0, emitter_id="g9"),
        "targets": (RuleTarget(device=handle(38), endpoint=None),),
        "features": frozenset({Feature.ON_OFF}),
    }
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
    assert forward, "a two-way rule needs a link in each direction"
    assert reverse, "a two-way rule needs a link in each direction"


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


# The tests above are the plan's. The ones below cover the refusals and edge cases the
# implementation has to get right for the same reasons, which the plan left implicit.


def test_a_long_range_source_is_refused_before_anything_is_compiled() -> None:
    """D13: the protocol is fixed at inclusion, so an LR control can never drive a link."""
    result = compile_rule(
        _rule(source=RuleSource(device=handle(300, long_range=True), endpoint=0, emitter_id="g9")),
        capabilities_for(300, 38),
    )

    assert any("long_range" in error.translation_key for error in result.errors)
    assert not result.links


def test_a_device_the_capabilities_do_not_describe_is_an_error() -> None:
    """A rule can outlive a device being excluded, and must say so rather than guess."""
    source_missing = compile_rule(_rule(), capabilities_for(38))
    target_missing = compile_rule(_rule(), capabilities_for(36))

    assert any("unknown_device" in error.translation_key for error in source_missing.errors)
    assert any("unknown_device" in error.translation_key for error in target_missing.errors)
    assert not source_missing.links
    assert not target_missing.links


def test_an_emitter_the_device_does_not_offer_is_an_error() -> None:
    """A curated entry that regroups a model renames its controls, and a rule may predate it."""
    result = compile_rule(
        _rule(source=RuleSource(device=handle(36), endpoint=0, emitter_id="nonexistent")),
        capabilities_for(36, 38),
    )

    assert any("unknown_emitter" in error.translation_key for error in result.errors)
    assert not result.links


def test_a_target_that_cannot_act_on_the_command_is_refused() -> None:
    """E13: a link a device cannot act on is written, dead, and invisible. Refuse it instead."""
    caps = capabilities_for(36, 38)
    caps[handle(38).identity] = replace(caps[handle(38).identity], receivable=frozenset())

    result = compile_rule(_rule(), caps)

    assert any("cannot_receive" in error.translation_key for error in result.errors)
    assert not result.links


def test_one_refused_target_does_not_take_the_working_ones_with_it() -> None:
    """FR-R2 again: a rule reports what it cannot do and still does what it can."""
    result = compile_rule(
        _rule(
            targets=(
                RuleTarget(device=handle(38), endpoint=None),
                RuleTarget(device=handle(300, long_range=True), endpoint=None),
            )
        ),
        capabilities_for(36, 38, 300),
    )

    assert result.errors
    assert [link.target.handle.identity for link in result.links] == [handle(38).identity]


def test_holding_to_dim_a_light_you_cannot_turn_on_warns() -> None:
    """Legal, but rarely the intent, so it is said out loud rather than silently accepted."""
    result = compile_rule(_rule(features=frozenset({Feature.LEVEL_HOLD})), capabilities_for(36, 38))

    assert result.links
    assert any("level_hold_without_on_off" in w.translation_key for w in result.warnings)


def test_a_two_way_target_with_no_suitable_control_warns_and_compiles_one_way() -> None:
    """A remote is a fine target and a hopeless reverse source. Say so and keep the forward leg."""
    caps = capabilities_for(36, 38)
    caps[handle(38).identity] = replace(caps[handle(38).identity], emitters=())

    result = compile_rule(_rule(direction=Direction.TWO_WAY), caps)

    assert [link.source.identity for link in result.links] == [handle(36).identity]
    assert any("two_way" in w.translation_key for w in result.warnings)


def test_the_reverse_leg_uses_the_targets_own_primary_control() -> None:
    """The reverse link must come off one control, not be scattered over several."""
    rule = _rule(
        template=Template.VIRTUAL_3WAY,
        source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
        targets=(RuleTarget(device=handle(35), endpoint=None),),
        features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD}),
        direction=Direction.TWO_WAY,
    )
    result = compile_rule(rule, capabilities_for(37, 35))

    reverse = [link for link in result.links if link.source.identity == handle(35).identity]
    assert {link.emitter_id for link in reverse} == {"paddle"}
    assert {link.emitter_group for link in reverse} == {"2", "4"}


def test_an_adapter_that_cannot_express_the_choice_warns_like_a_missing_one() -> None:
    """A setting whose values do not include the one asked for is not available either."""
    caps = capabilities_for(37, 38)
    identity = handle(37).identity
    caps[identity] = replace(
        caps[identity],
        settings={"mirror_hub_commands": SettingsAdapter(parameter=59, bitmask=2, values={"x": 1})},
    )

    result = compile_rule(
        _rule(
            source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
            mirror_source=MirrorChoice.ON,
        ),
        caps,
    )

    assert not result.settings
    assert any("settings_not_available" in w.translation_key for w in result.warnings)


def test_the_same_warning_is_reported_once_however_many_links_provoke_it() -> None:
    """A dialog that says the same thing twice teaches the user to stop reading it.

    On/off and hold-to-dim are two links to one device through one control, so the endpoint
    they cannot have is one fact about that pair, not one fact per link.
    """
    result = compile_rule(
        _rule(
            targets=(RuleTarget(device=handle(38), endpoint=2),),
            features=frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD}),
        ),
        capabilities_for(36, 38, multi_channel=False),
    )

    downgrades = [w for w in result.warnings if "multi_channel_downgrade" in w.translation_key]
    assert len(result.links) == 2
    assert len(downgrades) == 1


def test_links_are_ordered_by_target_and_feature() -> None:
    """The plan token and the dialog both read the compiler's output in order."""
    rule = _rule(
        source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
        targets=(
            RuleTarget(device=handle(38), endpoint=None),
            RuleTarget(device=handle(35), endpoint=None),
        ),
        features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET}),
    )
    result = compile_rule(rule, capabilities_for(37, 35, 38))

    assert [(link.target.handle.identity, str(link.feature)) for link in result.links] == sorted(
        (link.target.handle.identity, str(link.feature)) for link in result.links
    )


def test_nothing_is_compiled_for_a_rule_whose_hybrid_legs_phase_has_not_arrived() -> None:
    """Decision D3 puts hybrid legs in Phase 2. Until then the field is honestly empty."""
    assert compile_rule(_rule(), capabilities_for(36, 38)).hybrid_legs == ()


def test_the_reverse_leg_skips_a_control_that_cannot_carry_every_feature() -> None:
    """One control has to do the whole job, so a partial one is passed over rather than used.

    The Inovelli's gesture and config controls carry on/off and nothing else. A two-way rule
    that also syncs level has to land on the paddle, however the device happens to order its
    controls.
    """
    caps = capabilities_for(37, 38)
    identity = handle(38).identity
    caps[identity] = replace(caps[identity], emitters=tuple(reversed(caps[identity].emitters)))

    result = compile_rule(
        _rule(
            template=Template.VIRTUAL_3WAY,
            source=RuleSource(device=handle(37), endpoint=0, emitter_id="paddle"),
            features=frozenset({Feature.ON_OFF, Feature.LEVEL_SET}),
            direction=Direction.TWO_WAY,
        ),
        caps,
    )

    reverse = [link for link in result.links if link.source.identity == identity]
    assert {link.emitter_id for link in reverse} == {"paddle"}
