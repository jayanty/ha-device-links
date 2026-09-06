"""Compilation: one rule's intent in, the links and settings that express it out.

This is where "this button should control that light, with dimming" becomes the exact
association groups that must contain the exact node ids. It is the last place a mistake is
still cheap: everything downstream writes what this module decided.

It is pure. No Home Assistant import, no I/O, no clock, no randomness and no dependence on
dict ordering, so the same rule and the same capabilities compile to the same links forever,
which is what lets the planner hash them into a token and the tests assert on them.

Three rules of the design are worth stating where they cannot be missed:

- A refusal is an error and never a warning. Self-association, Long Range, and a target that
  cannot act on the command all produce no link at all for what they refuse.
- A refusal is as narrow as it can honestly be. A rule with three targets, one of them
  impossible, compiles the two that work and reports the one that does not (FR-R2).
- Every message is a translation key with placeholders, never a sentence (CLAUDE.md 7).
  The keys have no `strings.json` entries yet, because nothing surfaces them until the
  Home Assistant layer does, and inventing the copy now would be inventing the UI too.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from custom_components.device_links.models import (
    DeviceCapabilities,
    Diagnostic,
    Direction,
    Emitter,
    Feature,
    HybridLeg,
    Link,
    LinkTarget,
    MirrorChoice,
    Rule,
    RuleTarget,
    SettingWrite,
    Template,
)
from custom_components.device_links.profile_db import SEMANTICS_UNKNOWN

# The setting a two-way rule asks about: whether the source device repeats what the hub
# tells it to its own associations, which is what makes the second switch follow the first.
MIRROR_CAPABILITY: Final = "mirror_hub_commands"

# What is said about a control that cannot carry a feature the rule asked for. Spelled out
# per feature rather than built from the feature's name, so that every key a user can see
# in their own language is a literal somebody can find by searching for it: a key composed
# at runtime is a key nobody notices is missing from `strings.json` until it appears raw in
# the UI, and `tests/test_translations.py` is what makes that impossible.
FEATURE_UNAVAILABLE: Final[Mapping[Feature, str]] = {
    Feature.ON_OFF: "feature_unavailable_on_off",
    Feature.LEVEL_SET: "feature_unavailable_level_set",
    Feature.LEVEL_HOLD: "feature_unavailable_level_hold",
    Feature.SCENE: "feature_unavailable_scene",
    Feature.COLOR: "feature_unavailable_color",
    Feature.STATUS_REPORT: "feature_unavailable_status_report",
}


@dataclass(frozen=True, slots=True)
class CompiledRule:
    """What one rule asks for, resolved against real devices.

    `errors` mean something the rule asked for cannot be done and is not being attempted;
    `warnings` mean it is being done differently from how it was asked for. Links are always
    exactly what will be written, so a caller never has to re-check an error to know whether
    a link is safe.
    """

    links: tuple[Link, ...] = ()
    settings: tuple[SettingWrite, ...] = ()
    hybrid_legs: tuple[HybridLeg, ...] = ()
    warnings: tuple[Diagnostic, ...] = ()
    errors: tuple[Diagnostic, ...] = ()


def compile_rule(rule: Rule, capabilities: Mapping[str, DeviceCapabilities]) -> CompiledRule:
    """Turn one rule into the links and setting writes that express it.

    `capabilities` is keyed by `DeviceHandle.identity`, and describes the devices as they are
    now rather than as they were when the rule was written, so a rule that has outlived its
    hardware reports that instead of compiling something that cannot work.
    """
    if not rule.enabled:
        return CompiledRule()
    return _Compilation(rule, capabilities).run()


@dataclass(frozen=True, slots=True)
class _Leg:
    """One direction of a rule: a control on one device driving one other device.

    Both directions of a two-way rule are the same shape, so both compile through one path
    and the refusals and downgrades cannot drift apart between them.
    """

    writer: DeviceCapabilities
    writer_endpoint: int
    emitter: Emitter
    receiver: DeviceCapabilities
    receiver_endpoint: int | None


@dataclass(slots=True)
class _Compilation:
    """One run of the compiler, holding what it has decided so far.

    The accumulators are mutable because compiling is a sequence of decisions; nothing
    mutable escapes, because `run` freezes everything into the result.
    """

    rule: Rule
    capabilities: Mapping[str, DeviceCapabilities]
    links: list[Link] = field(default_factory=list)
    settings: list[SettingWrite] = field(default_factory=list)
    warnings: list[Diagnostic] = field(default_factory=list)
    errors: list[Diagnostic] = field(default_factory=list)

    def run(self) -> CompiledRule:
        """Compile the rule, in the order a failure makes the rest meaningless."""
        source = self._source_capabilities()
        emitter = None if source is None else self._emitter(source)
        if source is None or emitter is None:
            return self._result()

        actions = self._resolved_actions(emitter)
        for target, target_capabilities in self._targets():
            self._add_links(
                _Leg(
                    writer=source,
                    writer_endpoint=self.rule.source.endpoint,
                    emitter=emitter,
                    receiver=target_capabilities,
                    receiver_endpoint=target.endpoint,
                ),
                actions,
            )
            self._compile_reverse(source, target_capabilities, actions)

        self._check_semantics(source, emitter)
        self._compile_mirror(source)
        self.links.sort(
            key=lambda link: (link.target.handle.identity, link.feature, link.fingerprint)
        )
        return self._result()

    def _result(self) -> CompiledRule:
        """Freeze what has been decided, reporting each distinct message exactly once."""
        return CompiledRule(
            links=tuple(self.links),
            settings=tuple(self.settings),
            warnings=_distinct(self.warnings),
            errors=_distinct(self.errors),
        )

    def _source_capabilities(self) -> DeviceCapabilities | None:
        """Return the control device's capabilities, or report why there are none to use."""
        source = self._capabilities_of(self.rule.source.device.identity)
        if source is None:
            return None
        if source.is_long_range:
            self.errors.append(
                Diagnostic("source_is_long_range", {"device": source.handle.name_at_authoring})
            )
            return None
        return source

    def _capabilities_of(self, identity: str) -> DeviceCapabilities | None:
        """Return one device's capabilities, reporting the device that has none."""
        capabilities = self.capabilities.get(identity)
        if capabilities is None:
            self.errors.append(Diagnostic("unknown_device", {"device": identity}))
        return capabilities

    def _emitter(self, source: DeviceCapabilities) -> Emitter | None:
        """Return the control the rule names, or report that the device does not offer it."""
        for emitter in source.emitters:
            if emitter.emitter_id == self.rule.source.emitter_id:
                return emitter
        self.errors.append(
            Diagnostic(
                "unknown_emitter",
                {"emitter": self.rule.source.emitter_id, "device": source.handle.name_at_authoring},
            )
        )
        return None

    def _resolved_actions(self, emitter: Emitter) -> dict[Feature, str]:
        """Return the group carrying each requested feature, reporting the ones with none.

        A feature the control cannot carry is a warning while anything else still compiles,
        and an error when nothing does: a rule that produces no link at all has not been
        partly honoured, it has been ignored, and the user has to be told that plainly.
        """
        resolved: dict[Feature, str] = {}
        unavailable: list[Diagnostic] = []
        for feature in sorted(self.rule.features):
            group = emitter.actions.get(feature)
            if group is None:
                unavailable.append(
                    Diagnostic(
                        FEATURE_UNAVAILABLE[feature],
                        {"feature": str(feature), "emitter": emitter.label},
                    )
                )
            else:
                resolved[feature] = group
        (self.warnings if resolved else self.errors).extend(unavailable)
        if Feature.LEVEL_HOLD in resolved and Feature.ON_OFF not in resolved:
            self.warnings.append(
                Diagnostic("level_hold_without_on_off", {"emitter": emitter.label})
            )
        return resolved

    def _targets(self) -> list[tuple[RuleTarget, DeviceCapabilities]]:
        """Return the targets that can be linked at all, reporting the ones that cannot."""
        usable: list[tuple[RuleTarget, DeviceCapabilities]] = []
        for target in self.rule.targets:
            if target.device.identity == self.rule.source.device.identity:
                self.errors.append(
                    Diagnostic(
                        "self_association_use_hybrid_leg",
                        {"device": target.device.name_at_authoring},
                    )
                )
                continue
            capabilities = self._capabilities_of(target.device.identity)
            if capabilities is None:
                continue
            if capabilities.is_long_range:
                self.errors.append(
                    Diagnostic(
                        "target_is_long_range", {"device": capabilities.handle.name_at_authoring}
                    )
                )
                continue
            usable.append((target, capabilities))
        return usable

    def _add_links(self, leg: _Leg, features: Iterable[Feature]) -> None:
        """Add this leg's link for each feature, refusing dead ones and downgrading endpoints.

        A link the receiving device cannot act on would be written, accepted by the radio and
        do nothing forever, which is worse than not writing it: nothing about the device
        afterwards says the rule is not working.
        """
        for feature in features:
            if feature not in leg.receiver.receivable:
                self.errors.append(
                    Diagnostic(
                        "target_cannot_receive",
                        {
                            "device": leg.receiver.handle.name_at_authoring,
                            "feature": str(feature),
                        },
                    )
                )
                continue
            self.links.append(
                Link(
                    backend=self.rule.backend,
                    source=leg.writer.handle,
                    source_endpoint=leg.writer_endpoint,
                    emitter_id=leg.emitter.emitter_id,
                    target=LinkTarget(handle=leg.receiver.handle, endpoint=self._endpoint_for(leg)),
                    feature=feature,
                    emitter_group=leg.emitter.actions[feature],
                    rule_id=self.rule.id,
                )
            )

    def _endpoint_for(self, leg: _Leg) -> int | None:
        """Return the endpoint this leg can really target, downgrading when it cannot.

        Writing an endpoint target through a control whose groups have no Multi Channel
        Association is nonsense the device will either reject or silently mangle, so the link
        becomes a plain node association and the user is told that is what happened.
        """
        if leg.receiver_endpoint is None or leg.emitter.supports_endpoint_targets:
            return leg.receiver_endpoint
        self.warnings.append(
            Diagnostic(
                "multi_channel_downgrade",
                {
                    "emitter": leg.emitter.label,
                    "device": leg.receiver.handle.name_at_authoring,
                },
            )
        )
        return None

    def _compile_reverse(
        self,
        source: DeviceCapabilities,
        target: DeviceCapabilities,
        actions: Mapping[Feature, str],
    ) -> None:
        """Compile the other direction of a two-way rule, off one control on the target.

        The reverse leg picks a single emitter that carries every feature the forward leg
        carries, and the first such emitter in the device's own order, which is the control
        the device itself lists first: group 2 is the main paddle on every model Stage 0
        captured. Splitting the reverse leg across several controls would associate buttons
        the user never chose, so a target with no single control that can do the job gets a
        warning and the rule stays one-way.
        """
        if self.rule.direction is not Direction.TWO_WAY or not actions:
            return
        emitter = _emitter_carrying(target.emitters, actions)
        if emitter is None:
            self.warnings.append(
                Diagnostic(
                    "two_way_target_has_no_control",
                    {"device": target.handle.name_at_authoring},
                )
            )
            return
        self._add_links(
            _Leg(
                writer=target,
                writer_endpoint=0,
                emitter=emitter,
                receiver=source,
                receiver_endpoint=self.rule.source.endpoint or None,
            ),
            actions,
        )

    def _check_semantics(self, source: DeviceCapabilities, emitter: Emitter) -> None:
        """Warn when Off-all is asked of a control whose press is not an established OFF.

        Stage 0 item Z7 is open: nobody has observed whether a Zooz small button sends a
        fixed OFF or toggles. If it toggles, an Off-all button turns the lights back on every
        second press, which is the exact opposite of what the user asked for. The warning is
        how that unresolved finding reaches the person pressing the button.
        """
        if self.rule.template is Template.OFF_ALL and emitter.semantics == SEMANTICS_UNKNOWN:
            self.warnings.append(
                Diagnostic(
                    "button_semantics_unknown",
                    {"emitter": emitter.label, "device": source.handle.name_at_authoring},
                )
            )

    def _compile_mirror(self, source: DeviceCapabilities) -> None:
        """Resolve the mirror choice into a parameter write, or say it cannot be made.

        `LEAVE` writes nothing at all. The setting is global to the device, so writing back
        even its current value would make a rule that did not ask about it responsible for it.
        """
        if self.rule.mirror_source is MirrorChoice.LEAVE:
            return
        adapter = source.settings.get(MIRROR_CAPABILITY)
        value = None if adapter is None else adapter.values.get(str(self.rule.mirror_source))
        if adapter is None or value is None:
            self.warnings.append(
                Diagnostic(
                    "settings_not_available",
                    # `setting` rather than `capability`, because the Z-Wave adapter says
                    # the same thing about the same situation and one message has to fit
                    # both: a key whose placeholders depend on which layer produced it is
                    # a key whose message can only be written for one of them.
                    {
                        "device": source.handle.name_at_authoring,
                        "setting": MIRROR_CAPABILITY,
                        "choice": str(self.rule.mirror_source),
                    },
                )
            )
            return
        self.settings.append(
            SettingWrite(
                device=source.handle,
                capability=MIRROR_CAPABILITY,
                parameter=adapter.parameter,
                bitmask=adapter.bitmask,
                value=value,
            )
        )


def _emitter_carrying(emitters: Sequence[Emitter], features: Iterable[Feature]) -> Emitter | None:
    """Return the device's first control that carries every one of these features."""
    wanted = tuple(features)
    for emitter in emitters:
        if all(feature in emitter.actions for feature in wanted):
            return emitter
    return None


def _distinct(diagnostics: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Return these diagnostics in order, with each distinct message reported once.

    Several links can provoke the same message, and a dialog that says the same thing four
    times teaches the reader to skip it.
    """
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    kept: list[Diagnostic] = []
    for diagnostic in diagnostics:
        if diagnostic.identity in seen:
            continue
        seen.add(diagnostic.identity)
        kept.append(diagnostic)
    return tuple(kept)
