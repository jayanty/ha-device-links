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
    defaults: dict[str, object] = {
        "id": "11111111-1111-4111-8111-111111111111",
        "name": "Scene controller button 3 controls Bedside Light L",
        "template": Template.SCENE_BUTTON,
        "backend": Backend.ZWAVE,
        "source": RuleSource(device=handle(36), endpoint=0, emitter_id="g9"),
        "targets": (RuleTarget(device=handle(38), endpoint=None),),
        "features": frozenset({Feature.ON_OFF, Feature.LEVEL_HOLD}),
    }
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


def test_a_profile_holds_the_rules_it_was_given() -> None:
    """Distinct ids are the ordinary case, and order is kept because a plan is compared."""
    first = _rule()
    second = _rule(id="22222222-2222-4222-8222-222222222222", name="Another rule")

    profile = Profile(id="p1", name="Home", rules=(first, second))

    assert profile.rules == (first, second)
