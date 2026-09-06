"""Device swap, as pure logic: what is proposed, what is refused, and what is lost.

The pure half of FR-S2 and FR-S3. Everything here runs without Home Assistant, against the
real Stage 0 capture, so the decision that rewrites somebody's whole configuration can be
checked exhaustively before it reaches a house. `tests/test_scenario_s7.py` is the other
half: the same swap driven end to end through the real WebSocket commands.

The device pair is the real one. Node 13, "Ceiling Lights Old", was replaced by node 42,
"Ceiling Lights", before Stage 0 ran, which is why node 13 is in no fixture: a swap fixture
whose old device can still be read would be testing the easy half.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.device_links.models import (
    Backend as BackendId,
)
from custom_components.device_links.models import (
    DeviceCapabilities,
    Emitter,
    Feature,
    MatterFingerprint,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
    ZigbeeFingerprint,
    ZWaveFingerprint,
)
from custom_components.device_links.swap import (
    MappingBasis,
    find_replacements,
    propose,
)
from tests.factories import CEILING_LIGHTS_OLD, capabilities_for, handle

# Node 42 is the replacement, and node 37 is a light both the old rule and the new one
# drive, so a rewrite that moved the wrong end of a rule is visible.
REPLACEMENT = 42
LIGHT = 37
DIMMING = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})


def old_handle() -> object:
    """Return the handle the imported profile carries for the dead node 13."""
    return handle(CEILING_LIGHTS_OLD)


def a_rule(  # noqa: PLR0913
    *,
    rule_id: str = "ceiling",
    name: str = "Ceiling paddle controls Master Bedroom Lights",
    source_node: int = CEILING_LIGHTS_OLD,
    emitter_id: str = "paddle",
    targets: tuple[int, ...] = (LIGHT,),
    features: frozenset[Feature] = DIMMING,
    enabled: bool = True,
) -> Rule:
    """Return one rule of the imported profile, sourced on the dead device by default."""
    return Rule(
        id=rule_id,
        name=name,
        template=Template.REMOTE,
        backend=BackendId.ZWAVE,
        source=RuleSource(device=handle(source_node), endpoint=0, emitter_id=emitter_id),
        targets=tuple(RuleTarget(device=handle(node), endpoint=None) for node in targets),
        features=features,
        enabled=enabled,
    )


def network(*node_ids: int) -> dict[str, DeviceCapabilities]:
    """Return the capabilities of the nodes that are really on the network."""
    return capabilities_for(*node_ids)


def a_proposal(*rules: Rule, chosen: dict[str, str] | None = None) -> object:
    """Return the proposal for the real node 13 to node 42 swap over these rules."""
    return propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=rules or (a_rule(),),
        capabilities=network(REPLACEMENT, LIGHT),
        chosen=chosen,
    )


# --------------------------------------------------------------------------------------
# Mapping the controls across
# --------------------------------------------------------------------------------------


def test_a_control_with_the_same_id_on_the_replacement_maps_without_being_asked() -> None:
    """The same-model case of FR-S2, and the one a user should never have to answer.

    Node 13 is an Inovelli VZW31-SN and node 42 is a VZW32-SN, so this is a different
    fingerprint. It still maps with no question asked, because both call the paddle
    `paddle`, and that is the point of matching on the control rather than on the model:
    PRD scenario S7 asks for an automatic mapping and gets one by the id rather than by
    the fingerprint the PRD assumed.
    """
    proposal = a_proposal()

    assert proposal.same_model is False
    assert [(m.old_emitter_id, m.new_emitter_id, m.basis) for m in proposal.mappings] == [
        ("paddle", "paddle", MappingBasis.SAME_EMITTER_ID)
    ]
    assert proposal.unmapped == ()
    assert proposal.is_applicable


def test_the_one_control_that_can_do_what_the_rules_asked_is_pre_filled() -> None:
    """When the ids disagree, the features decide, and only when one control can do it."""
    proposal = a_proposal(a_rule(emitter_id="main", features=frozenset({Feature.LEVEL_SET})))

    mapping = proposal.mappings[0]

    assert mapping.old_emitter_id == "main"
    assert mapping.basis is MappingBasis.SAME_FEATURES
    assert mapping.new_emitter_id == "paddle", "only the paddle carries level_set on a VZW32"


def test_a_control_with_the_same_id_wins_even_when_it_carries_less() -> None:
    """The id says which physical control it is, and that beats a guess from the features.

    `g5` is the double tap on both devices, so a rule written on it stays on it even though
    the paddle could carry more of what the rule asked for. What the double tap cannot do
    is reported as a loss rather than quietly re-pointed at a button the user did not name.
    """
    proposal = a_proposal(a_rule(emitter_id="g5", features=frozenset({Feature.LEVEL_SET})))

    assert proposal.mappings[0].new_emitter_id == "g5"
    assert proposal.mappings[0].basis is MappingBasis.SAME_EMITTER_ID
    assert proposal.mappings[0].features_carried == ()
    assert proposal.is_lossy


def test_several_controls_that_could_do_it_are_not_guessed_between() -> None:
    """Two paddles that both fit is where a guess puts a rule on the wrong half of a device."""
    proposal = a_proposal(a_rule(emitter_id="g99", features=frozenset({Feature.ON_OFF})))

    assert proposal.mappings[0].basis is MappingBasis.UNMAPPED
    assert proposal.unmapped == ("g99",)
    assert not proposal.is_applicable, "a swap with an unanswered control cannot be applied"


def test_what_the_user_picked_wins_over_both_pre_fills() -> None:
    """A pre-fill is a suggestion; the person looking at the wall knows which paddle it is."""
    proposal = a_proposal(a_rule(features=frozenset({Feature.ON_OFF})), chosen={"paddle": "g5"})

    assert proposal.mappings[0].new_emitter_id == "g5"
    assert proposal.mappings[0].basis is MappingBasis.CHOSEN


def test_a_choice_naming_a_control_the_replacement_does_not_have_falls_back() -> None:
    """A stale wizard is not a reason to write a rule onto a control that is not there."""
    proposal = a_proposal(chosen={"paddle": "not_a_control"})

    assert proposal.mappings[0].new_emitter_id == "paddle"
    assert proposal.mappings[0].basis is MappingBasis.SAME_EMITTER_ID


def test_a_device_that_is_only_ever_a_target_needs_no_mapping() -> None:
    """Nothing drives from it, so there is no control to map: it swaps on its address."""
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(a_rule(source_node=36, targets=(CEILING_LIGHTS_OLD,)),),
        capabilities=network(36, REPLACEMENT),
    )

    assert proposal.mappings == ()
    assert proposal.is_applicable
    assert proposal.rewrites[0].after.targets[0].device.identity == handle(REPLACEMENT).identity


# --------------------------------------------------------------------------------------
# Rewriting the rules
# --------------------------------------------------------------------------------------


def test_every_rule_that_named_the_old_device_is_rewritten_as_source_and_as_target() -> None:
    """FR-S2 says both ends, because a swapped switch is usually driven as well as driving."""
    drives = a_rule(rule_id="drives")
    is_driven = a_rule(rule_id="driven", source_node=36, targets=(CEILING_LIGHTS_OLD,))
    unrelated = a_rule(rule_id="unrelated", source_node=36, targets=(LIGHT,))
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(drives, is_driven, unrelated),
        capabilities=network(36, REPLACEMENT, LIGHT),
    )

    rewritten = {rewrite.rule_id: rewrite.after for rewrite in proposal.rewrites}

    assert set(rewritten) == {"drives", "driven"}, "an unrelated rule was rewritten"
    assert rewritten["drives"].source.device.identity == handle(REPLACEMENT).identity
    assert rewritten["driven"].targets[0].device.identity == handle(REPLACEMENT).identity
    assert proposal.rules_after((drives, is_driven, unrelated))[2] is unrelated


def test_the_profiles_rule_order_survives_a_rewrite() -> None:
    """Rule order is the user's, and a swap is not a reason to disturb it."""
    rules = (
        a_rule(rule_id="one", source_node=36, targets=(LIGHT,)),
        a_rule(rule_id="two"),
        a_rule(rule_id="three", source_node=36, targets=(LIGHT,), emitter_id="g5"),
    )
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=rules,
        capabilities=network(36, REPLACEMENT, LIGHT),
    )

    assert [rule.id for rule in proposal.rules_after(rules)] == ["one", "two", "three"]


def test_a_rule_that_already_named_the_replacement_does_not_end_up_naming_it_twice() -> None:
    """A `Rule` refuses a duplicate target, so the merge has to happen and has to be said.

    Real rather than theoretical: a rule that turned on the old ceiling light and the new
    one during the changeover is exactly what somebody would have written.
    """
    both = a_rule(targets=(LIGHT, CEILING_LIGHTS_OLD, REPLACEMENT), source_node=36)
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(both,),
        capabilities=network(36, REPLACEMENT, LIGHT),
    )

    rewrite = proposal.rewrites[0]

    assert [target.device.identity for target in rewrite.after.targets] == [
        handle(LIGHT).identity,
        handle(REPLACEMENT).identity,
    ]
    assert [note.translation_key for note in rewrite.notes] == ["swap_duplicate_target_merged"]


def test_a_disabled_rule_is_carried_across_too() -> None:
    """Disabling is not deleting (FR-R5), so its intent moves with everything else."""
    proposal = a_proposal(a_rule(enabled=False))

    assert proposal.rewrites[0].after.enabled is False
    assert proposal.rewrites[0].after.source.device.identity == handle(REPLACEMENT).identity


def test_the_source_endpoint_comes_from_the_control_that_took_over() -> None:
    """The same rule the editor follows: a control drives from its own endpoint."""
    proposal = a_proposal()

    assert proposal.rewrites[0].after.source.endpoint == 0


# --------------------------------------------------------------------------------------
# Loss, which must never be silent
# --------------------------------------------------------------------------------------


def test_a_feature_the_replacement_cannot_carry_is_reported_as_a_loss() -> None:
    """The judgment this module exists for: a partial swap is never a silent one.

    The config button on a VZW32-SN carries on/off and nothing else, so a rule that asked
    for dimming through it loses two thirds of what it was written to do. It is still
    rewritten, because leaving the rule pointing at a device that is not there helps
    nobody, and every feature it can no longer carry is named.
    """
    proposal = a_proposal(a_rule(emitter_id="g7"), chosen={"g7": "g7"})

    rewrite = proposal.rewrites[0]

    assert proposal.is_lossy
    assert rewrite.is_lossy
    assert {loss.placeholders["feature"] for loss in rewrite.losses} == {
        "level_set",
        "level_hold",
    }
    assert all(loss.translation_key == "swap_feature_lost" for loss in rewrite.losses)
    assert rewrite.after.source.emitter_id == "g7", "the rule was still rewritten"


def test_a_swap_that_loses_nothing_says_so() -> None:
    """The ordinary case has to be distinguishable from the lossy one, or nothing is."""
    proposal = a_proposal()

    assert not proposal.is_lossy
    assert proposal.rewrites[0].losses == ()
    assert proposal.rewrites[0].errors == ()


def test_a_rewritten_rule_that_cannot_compile_at_all_carries_the_compilers_own_refusal() -> None:
    """A rule the swap turns into a device controlling itself is an error, not a loss.

    It compiles to nothing, so every feature is lost as well, and the compiler's own
    message is what says why rather than a second sentence invented here.
    """
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(a_rule(source_node=REPLACEMENT, targets=(CEILING_LIGHTS_OLD,)),),
        capabilities=network(REPLACEMENT, LIGHT),
    )

    rewrite = proposal.rewrites[0]

    assert [error.translation_key for error in rewrite.errors] == [
        "self_association_use_hybrid_leg"
    ]
    assert rewrite.is_lossy


# --------------------------------------------------------------------------------------
# What stops a swap before any rule is looked at
# --------------------------------------------------------------------------------------


def test_a_node_replaced_in_place_is_a_swap_rather_than_nothing_to_do() -> None:
    """E20 and FR-S3's second case: the address stayed and the model under it changed.

    Z-Wave's "replace failed node" keeps the node id, so every rule still names the right
    device and every rule is still wrong: the controls belong to a model that is gone, and
    the handle each rule stores carries that model's fingerprint. Refusing this as "the
    same device" would have the Repairs issue offer a flow that then declined to run.
    """
    # The rules were written against node 42's VZW32-SN; a ZEN35 answers at that address now.
    replaced = replace(handle(REPLACEMENT), fingerprint=handle(36).fingerprint)
    rules = (a_rule(source_node=REPLACEMENT, targets=(LIGHT,)),)
    proposal = propose(
        old=handle(REPLACEMENT),
        new=replaced,
        rules=rules,
        capabilities={**network(LIGHT), replaced.identity: network(36)[handle(36).identity]},
    )

    assert proposal.errors == ()
    assert proposal.same_model is False
    # The paddle is `paddle` on a VZW32-SN and `g2` on a ZEN35, and only one control on a
    # ZEN35 carries all three of on/off, level set and level hold, so it maps without being
    # asked even though nothing about the two ids agrees.
    assert [(m.old_emitter_id, m.new_emitter_id, m.basis) for m in proposal.mappings] == [
        ("paddle", "g2", MappingBasis.SAME_FEATURES)
    ]
    after = proposal.rewrites[0].after
    assert after.source.device.identity == handle(REPLACEMENT).identity, "the address stayed"
    assert after.source.device.fingerprint == handle(36).fingerprint, "the model was refreshed"
    assert after.source.emitter_id == "g2"


def test_swapping_a_device_for_the_same_model_at_the_same_address_is_still_nothing_to_do() -> None:
    """The address and the model both unchanged is the case there is genuinely nothing in."""
    proposal = propose(
        old=handle(REPLACEMENT),
        new=handle(REPLACEMENT),
        rules=(a_rule(source_node=REPLACEMENT, targets=(LIGHT,)),),
        capabilities=network(REPLACEMENT, LIGHT),
    )

    assert [error.translation_key for error in proposal.errors] == ["swap_same_device"]


def test_a_replacement_on_another_protocol_is_refused_rather_than_attempted() -> None:
    """Every link a rule makes lives in one protocol; a cross-protocol swap is a new rule."""
    zigbee = replace(
        handle(REPLACEMENT),
        backend=BackendId.ZIGBEE2MQTT,
        protocol_id="0x00124b002e1dfd4a",
        fingerprint=ZigbeeFingerprint(manufacturer="Inovelli", model="VZM31-SN"),
    )
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=zigbee,
        rules=(a_rule(),),
        capabilities={**network(REPLACEMENT, LIGHT), zigbee.identity: _empty(zigbee)},
    )

    assert [error.translation_key for error in proposal.errors] == ["swap_across_backends"]


def test_a_replacement_nobody_has_read_is_refused() -> None:
    """Swapping onto a device whose capabilities are unknown is swapping onto a claim."""
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(a_rule(),),
        capabilities=network(LIGHT),
    )

    assert [error.translation_key for error in proposal.errors] == ["swap_replacement_unreadable"]


def test_swapping_a_device_no_rule_names_changes_nothing_and_says_so() -> None:
    proposal = propose(
        old=handle(38),
        new=handle(REPLACEMENT),
        rules=(a_rule(source_node=36, targets=(LIGHT,)),),
        capabilities=network(36, REPLACEMENT, LIGHT),
    )

    assert [error.translation_key for error in proposal.errors] == ["swap_device_not_referenced"]


# --------------------------------------------------------------------------------------
# FR-S3: when a swap should be offered, and when it must stay quiet
# --------------------------------------------------------------------------------------


def listed(*node_ids: int) -> dict[str, object]:
    """Return the devices a backend lists, keyed by identity, as the coordinator holds them."""
    return {handle(node).identity: handle(node) for node in node_ids}


def test_a_device_that_left_the_network_with_a_lookalike_waiting_is_offered() -> None:
    """FR-S3's whole case: node 13 is gone and something with its model is unclaimed."""
    twin = replace(handle(38), fingerprint=handle(CEILING_LIGHTS_OLD).fingerprint)
    found = find_replacements(
        rules=(a_rule(),),
        listed={**listed(LIGHT), twin.identity: twin},
        answering=[BackendId.ZWAVE],
    )

    assert [replacement.old.identity for replacement in found] == [
        handle(CEILING_LIGHTS_OLD).identity
    ]
    assert found[0].candidates == (twin,)
    assert found[0].changed_in_place is False
    assert found[0].rule_ids == ("ceiling",)


def test_nothing_is_offered_when_no_device_could_take_over() -> None:
    """Without a candidate there is nothing to propose, and E19 is the honest report."""
    found = find_replacements(rules=(a_rule(),), listed=listed(LIGHT), answering=[BackendId.ZWAVE])

    assert found == ()


def test_a_device_that_is_merely_unreachable_is_never_offered() -> None:
    """The whole reason this does not cry wolf: a sleeping remote is still on the list.

    Availability is not consulted at all here, and that is deliberate. A battery device
    that has not answered for an hour, and a node whose mesh route is down, are both still
    in their driver's own device list, so neither reaches this function's question.
    """
    twin = replace(handle(38), fingerprint=handle(CEILING_LIGHTS_OLD).fingerprint)
    found = find_replacements(
        rules=(a_rule(),),
        listed={**listed(CEILING_LIGHTS_OLD, LIGHT), twin.identity: twin},
        answering=[BackendId.ZWAVE],
    )

    assert found == ()


def test_a_backend_that_is_not_answering_is_not_asked() -> None:
    """A restarting Z-Wave JS lists nothing, and would otherwise look like 36 swaps at once."""
    twin = replace(handle(38), fingerprint=handle(CEILING_LIGHTS_OLD).fingerprint)
    found = find_replacements(
        rules=(a_rule(),), listed={twin.identity: twin}, answering=[BackendId.ZIGBEE2MQTT]
    )

    assert found == ()


def test_a_device_another_rule_already_names_is_not_offered_as_a_replacement() -> None:
    """A switch that is doing a job of its own is not a spare."""
    twin = replace(handle(38), fingerprint=handle(CEILING_LIGHTS_OLD).fingerprint)
    claimed = a_rule(rule_id="claimed", source_node=36, targets=(38,))
    found = find_replacements(
        rules=(a_rule(), replace(claimed, targets=(RuleTarget(device=twin, endpoint=None),))),
        listed={**listed(LIGHT), twin.identity: twin},
        answering=[BackendId.ZWAVE],
    )

    assert found == ()


def test_a_node_that_answers_as_a_different_model_is_offered_in_place() -> None:
    """E20: replace-failed-node keeps the address and changes the model underneath it."""
    changed = replace(
        handle(CEILING_LIGHTS_OLD),
        fingerprint=ZWaveFingerprint(
            manufacturer_id=634, product_type=28672, product_id=40984, firmware="1.40.0"
        ),
    )
    found = find_replacements(
        rules=(a_rule(),),
        listed={changed.identity: changed, **listed(LIGHT)},
        answering=[BackendId.ZWAVE],
    )

    assert found[0].changed_in_place is True
    assert found[0].candidates == (changed,)


def test_a_firmware_update_is_not_a_replaced_device() -> None:
    """The false positive that would fire on every user, on the day they update a switch."""
    updated = replace(
        handle(CEILING_LIGHTS_OLD),
        fingerprint=replace(handle(CEILING_LIGHTS_OLD).fingerprint, firmware="1.9.9"),
    )
    found = find_replacements(
        rules=(a_rule(),),
        listed={updated.identity: updated, **listed(LIGHT)},
        answering=[BackendId.ZWAVE],
    )

    assert found == ()


def test_one_device_is_reported_once_however_many_rules_name_it() -> None:
    twin = replace(handle(38), fingerprint=handle(CEILING_LIGHTS_OLD).fingerprint)
    found = find_replacements(
        rules=(a_rule(rule_id="one"), a_rule(rule_id="two", emitter_id="g5")),
        listed={**listed(LIGHT), twin.identity: twin},
        answering=[BackendId.ZWAVE],
    )

    assert len(found) == 1
    assert found[0].rule_ids == ("one", "two")


# --------------------------------------------------------------------------------------
# The fingerprints themselves
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fingerprint", "expected"),
    [
        (ZWaveFingerprint(1, 2, 3, "4.5.6"), ("1", "2", "3")),
        (ZigbeeFingerprint("Inovelli", "VZM31-SN"), ("Inovelli", "VZM31-SN")),
        (MatterFingerprint("Eve", "Energy"), ("Eve", "Energy")),
    ],
)
def test_every_fingerprint_answers_what_identifies_its_model(
    fingerprint: object, expected: tuple[str, ...]
) -> None:
    """Every protocol's swap matching asks the same question, so every one has to answer."""
    assert fingerprint.model_key == expected  # type: ignore[attr-defined]


def _empty(device: object) -> DeviceCapabilities:
    """Return capabilities for a device that offers nothing, for the refusal tests."""
    return DeviceCapabilities(
        handle=device,  # type: ignore[arg-type]
        emitters=(),
        receivable=frozenset(),
        is_long_range=False,
    )


def test_a_profile_is_only_ever_read_and_never_changed_by_a_proposal() -> None:
    """Nothing here writes or stores: a proposal is a description (FR-S2)."""
    rule = a_rule()
    profile = Profile(id="imported", name="Imported", rules=(rule,))
    proposal = a_proposal(rule)

    assert profile.rules[0] is rule
    assert proposal.rewrites[0].before is rule
    assert proposal.rewrites[0].after is not rule


def test_an_emitter_that_carries_nothing_the_rules_need_is_not_pre_filled() -> None:
    """A control offering no overlap is not a candidate, however few others there are."""
    only_scene = DeviceCapabilities(
        handle=handle(REPLACEMENT),
        emitters=(
            Emitter(
                emitter_id="scene_only",
                label="Scene",
                endpoint=0,
                group_ids=("2",),
                actions={Feature.SCENE: "2"},
                capacity=5,
                supports_endpoint_targets=True,
                is_lifeline=False,
                grouping="per_group",
            ),
        ),
        receivable=frozenset({Feature.ON_OFF}),
        is_long_range=False,
    )
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(a_rule(features=frozenset({Feature.ON_OFF})),),
        capabilities={**network(LIGHT), handle(REPLACEMENT).identity: only_scene},
    )

    assert proposal.unmapped == ("paddle",)


def _receiving_on(endpoint: int | None) -> DeviceCapabilities:
    """Return the replacement's capabilities with one receiving endpoint named."""
    return replace(network(REPLACEMENT)[handle(REPLACEMENT).identity], receiving_endpoint=endpoint)


def test_a_target_endpoint_that_has_to_move_is_said_rather_than_moved_quietly() -> None:
    """A link lands where the replacement receives, which may not be where the old one did.

    Z-Wave answers None (the whole node) and Zigbee answers its load endpoint, so a swap
    between two devices that answer differently moves the target endpoint under a rule the
    user did not edit. It is the same default the rule editor's targets step already takes
    (open items T53 and T56); what this adds is saying so.
    """
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(a_rule(source_node=36, targets=(CEILING_LIGHTS_OLD,)),),
        capabilities={
            **network(36),
            handle(REPLACEMENT).identity: _receiving_on(1),
        },
    )

    rewrite = proposal.rewrites[0]

    assert rewrite.after.targets[0].endpoint == 1
    assert [note.translation_key for note in rewrite.notes] == ["swap_target_endpoint_moved"]
    assert rewrite.notes[0].placeholders["endpoint"] == "1"


def test_a_target_that_becomes_the_whole_device_says_so_without_a_hole_in_the_sentence() -> None:
    """None is the Z-Wave answer, and an empty placeholder would read as a missing word."""
    rule = replace(
        a_rule(source_node=36, targets=(CEILING_LIGHTS_OLD,)),
        targets=(RuleTarget(device=handle(CEILING_LIGHTS_OLD), endpoint=2),),
    )
    proposal = propose(
        old=handle(CEILING_LIGHTS_OLD),
        new=handle(REPLACEMENT),
        rules=(rule,),
        capabilities={**network(36), handle(REPLACEMENT).identity: _receiving_on(None)},
    )

    assert proposal.rewrites[0].notes[0].placeholders["endpoint"] == "-"
