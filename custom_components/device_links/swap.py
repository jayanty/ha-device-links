"""Device swap: a switch failed, a new one is in the wall, and every rule has to follow it.

FR-S1 is what makes this possible at all: a rule refers to a device by a handle whose
identity is `backend:protocol_id`, so a rename or an area move never breaks anything. What
a rename cannot survive is the device itself being replaced, because the replacement has a
different address, and that is the whole of what this module rewrites.

It is pure. Rules in, rewritten rules out, no I/O and no Home Assistant, for the same reason
`compiler.py` is: this decides what somebody's entire configuration is about to become, and
a decision that can be property-tested without a house attached is a decision that can be
checked exhaustively before it reaches one.

**Nothing here writes and nothing here stores.** `propose` returns a description of a swap;
the caller shows it, gets a confirmation, and only then stores the rewritten rules and
applies the plan they produce (FR-S2). That separation is not tidiness: a swap rewrites a
user's whole configuration in one move, and a move that cannot be looked at first is a move
nobody can decline.

**A control that maps to nothing stops the swap for that rule rather than guessing.** The
mapping is pre-filled two ways, in this order: the same emitter id on the replacement (a
same-model swap maps every control this way and needs no choice at all), and failing that
the one control that carries every feature the rules ask of the old one. PRD Section 6.5
also names the AGI profile as a pre-fill basis; the Stage 0 amendment to PRD Section 5.1 is
why it is not used, having found that AGI `profile` is unreliable on two of the three models
on this network. When neither pre-fill lands, the control is reported unmapped and the user
picks (FR-S2's mapping step) rather than having a control chosen for them.

**Loss is named, never absorbed.** The replacement may not do everything the old device did:
fewer features on the equivalent control, a target it cannot receive on. Every one of those
is reported per rule, computed by compiling the rewritten rule against the replacement's real
capabilities and asking which of the features the rule was authored with produce no link.
That question is answerable whether or not the old device can still be read, which matters
because the usual reason for a swap is that it cannot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from custom_components.device_links.compiler import CompiledRule, compile_rule
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Diagnostic,
    Emitter,
    Feature,
    Rule,
    RuleSource,
    RuleTarget,
)


class MappingBasis(StrEnum):
    """Why one control on the replacement was proposed for one control on the old device.

    Carried to the panel so a pre-filled mapping says how confident it is. "The ids agree"
    and "this is the only control that can do what the rules asked" are different claims,
    and a wizard that presented them identically would invite a user to accept the second
    as casually as the first.
    """

    SAME_EMITTER_ID = "same_emitter_id"
    SAME_FEATURES = "same_features"
    CHOSEN = "chosen"
    UNMAPPED = "unmapped"


@dataclass(frozen=True, slots=True)
class EmitterMapping:
    """One control the rules use on the old device, and what takes over from it.

    `features_needed` is what the rules ask of the old control and `features_carried` is
    what the proposed replacement can actually do, so the difference between them is the
    loss this one mapping causes, visible before the rule it belongs to is compiled.
    """

    old_emitter_id: str
    new_emitter_id: str | None
    new_label: str | None
    new_endpoint: int | None
    basis: MappingBasis
    features_needed: tuple[Feature, ...]
    features_carried: tuple[Feature, ...]

    @property
    def is_mapped(self) -> bool:
        """Say whether a control on the replacement has been settled on for this one."""
        return self.new_emitter_id is not None


@dataclass(frozen=True, slots=True)
class RuleRewrite:
    """One rule as it stands and as the swap would leave it, with what it would cost.

    `losses` are the features the rule was authored with that the rewritten rule compiles
    no link for. `notes` are changes the rewrite had to make that the user did not ask for
    and has to see: a target merged away, an endpoint moved.
    """

    rule_id: str
    before: Rule
    after: Rule
    losses: tuple[Diagnostic, ...] = ()
    notes: tuple[Diagnostic, ...] = ()
    errors: tuple[Diagnostic, ...] = ()

    @property
    def is_lossy(self) -> bool:
        """Say whether this rewrite would leave the rule doing less than it was asked to."""
        return bool(self.losses or self.errors)


@dataclass(frozen=True, slots=True)
class SwapProposal:
    """Everything one swap would do, and everything it would fail to do.

    `errors` stop the swap: nothing in here can be applied while one stands. `rewrites`
    carry their own per-rule losses, which do not stop it but must be acknowledged, because
    a swap that quietly leaves half a configuration behind is the failure this whole module
    is arranged around.
    """

    old: DeviceHandle
    new: DeviceHandle
    same_model: bool
    mappings: tuple[EmitterMapping, ...] = ()
    rewrites: tuple[RuleRewrite, ...] = ()
    errors: tuple[Diagnostic, ...] = ()

    @property
    def unmapped(self) -> tuple[str, ...]:
        """Return the controls the rules use that nothing on the replacement answers for."""
        return tuple(mapping.old_emitter_id for mapping in self.mappings if not mapping.is_mapped)

    @property
    def is_lossy(self) -> bool:
        """Say whether applying this would leave any rule doing less than it was asked to."""
        return any(rewrite.is_lossy for rewrite in self.rewrites)

    @property
    def is_applicable(self) -> bool:
        """Say whether this could be applied at all, mapping and all."""
        return not self.errors and not self.unmapped and bool(self.rewrites)

    def rules_after(self, rules: Sequence[Rule]) -> tuple[Rule, ...]:
        """Return a profile's rules with this swap's rewrites substituted in.

        The whole list rather than only what changed, and in the profile's own order: rule
        order is the user's and a rewrite is not a reason to disturb it.
        """
        rewritten = {rewrite.rule_id: rewrite.after for rewrite in self.rewrites}
        return tuple(rewritten.get(rule.id, rule) for rule in rules)


def references(rule: Rule, identity: str) -> bool:
    """Say whether one rule names this device at all, as its source or as a target."""
    return rule.source.device.identity == identity or any(
        target.device.identity == identity for target in rule.targets
    )


def emitters_used(rules: Iterable[Rule], identity: str) -> dict[str, frozenset[Feature]]:
    """Return each control the rules drive this device from, with the features they need.

    Only the source side: a device that is only ever a target has no control anybody uses,
    so it needs no mapping and swaps on its address alone.
    """
    used: dict[str, frozenset[Feature]] = {}
    for rule in rules:
        if rule.source.device.identity != identity:
            continue
        emitter_id = rule.source.emitter_id
        used[emitter_id] = used.get(emitter_id, frozenset()) | rule.features
    return used


def propose(
    *,
    old: DeviceHandle,
    new: DeviceHandle,
    rules: Sequence[Rule],
    capabilities: Mapping[str, DeviceCapabilities],
    chosen: Mapping[str, str] | None = None,
) -> SwapProposal:
    """Return what swapping `old` for `new` would do to these rules, and write nothing.

    `capabilities` describes the network as it is now, keyed by identity, and must hold the
    replacement: swapping onto a device nobody can read would be swapping onto a claim.
    The old device is deliberately not required to be in there, because the ordinary reason
    for a swap is that it is gone.

    `chosen` is the mapping the user made in the wizard, by old emitter id. It wins over
    both pre-fills, always: a pre-fill is a suggestion and the user is the one who knows
    which paddle is which.
    """
    same_model = old.fingerprint.model_key == new.fingerprint.model_key
    errors = _refusals(old, new, rules, capabilities)
    new_capabilities = capabilities.get(new.identity)
    if errors or new_capabilities is None:
        return SwapProposal(old=old, new=new, same_model=same_model, errors=errors)

    affected = [rule for rule in rules if references(rule, old.identity)]
    mappings = tuple(
        _map_emitter(
            old_emitter_id=old_emitter_id,
            needed=needed,
            new_capabilities=new_capabilities,
            chosen=(chosen or {}).get(old_emitter_id),
        )
        for old_emitter_id, needed in sorted(emitters_used(affected, old.identity).items())
    )
    rewriter = _Rewriter(
        old=old,
        new=new,
        new_capabilities=new_capabilities,
        mappings={mapping.old_emitter_id: mapping for mapping in mappings},
        capabilities=capabilities,
    )
    rewrites = tuple(
        rewrite for rule in affected if (rewrite := rewriter.rewrite(rule)) is not None
    )
    return SwapProposal(
        old=old,
        new=new,
        same_model=same_model,
        mappings=mappings,
        rewrites=rewrites,
    )


def _refusals(
    old: DeviceHandle,
    new: DeviceHandle,
    rules: Sequence[Rule],
    capabilities: Mapping[str, DeviceCapabilities],
) -> tuple[Diagnostic, ...]:
    """Return what stops this swap before any rule is looked at.

    A cross-protocol replacement is refused rather than attempted. Every link a rule
    compiles lives in one protocol, and a Z-Wave source replaced by a Zigbee one changes
    the address of every link, the endpoint of every target and whether each target can be
    reached at all, which is a new rule rather than a rewritten one. Refusing says so;
    rewriting would produce a profile whose every rule silently compiled to nothing.
    """
    errors: list[Diagnostic] = []
    if old.identity == new.identity:
        errors.append(Diagnostic("swap_same_device", {"device": new.name_at_authoring}))
    if old.backend is not new.backend:
        errors.append(
            Diagnostic(
                "swap_across_backends",
                {"old": str(old.backend), "new": str(new.backend)},
            )
        )
    if new.identity not in capabilities:
        errors.append(Diagnostic("swap_replacement_unreadable", {"device": new.name_at_authoring}))
    if not any(references(rule, old.identity) for rule in rules):
        errors.append(Diagnostic("swap_device_not_referenced", {"device": old.name_at_authoring}))
    return tuple(errors)


def _map_emitter(
    *,
    old_emitter_id: str,
    needed: frozenset[Feature],
    new_capabilities: DeviceCapabilities,
    chosen: str | None,
) -> EmitterMapping:
    """Return the control on the replacement that takes over from one on the old device."""
    offered = {emitter.emitter_id: emitter for emitter in new_capabilities.emitters}
    ordered = tuple(sorted(needed))

    if chosen is not None and chosen in offered:
        return _mapping(old_emitter_id, offered[chosen], MappingBasis.CHOSEN, ordered)
    if old_emitter_id in offered:
        # The id wins even when the control it names carries less than the rules asked for.
        # An id is a claim about which physical control this is, which is a stronger thing
        # to know than which controls happen to fit, and the shortfall is reported as a
        # loss rather than absorbed. Silently re-pointing a rule at a different button
        # because it fits better is the one outcome nobody would expect from a swap.
        return _mapping(
            old_emitter_id, offered[old_emitter_id], MappingBasis.SAME_EMITTER_ID, ordered
        )
    # The one control that carries everything the rules ask for. One, not the first of
    # several: two paddles that can both do it is exactly the case where guessing puts a
    # rule on the wrong half of a device, and the user is right there to say which.
    covering = [
        emitter for emitter in new_capabilities.emitters if needed <= frozenset(emitter.actions)
    ]
    if len(covering) == 1:
        return _mapping(old_emitter_id, covering[0], MappingBasis.SAME_FEATURES, ordered)
    return EmitterMapping(
        old_emitter_id=old_emitter_id,
        new_emitter_id=None,
        new_label=None,
        new_endpoint=None,
        basis=MappingBasis.UNMAPPED,
        features_needed=ordered,
        features_carried=(),
    )


def _mapping(
    old_emitter_id: str,
    emitter: Emitter,
    basis: MappingBasis,
    needed: tuple[Feature, ...],
) -> EmitterMapping:
    """Return one settled mapping, saying what the chosen control can really carry."""
    return EmitterMapping(
        old_emitter_id=old_emitter_id,
        new_emitter_id=emitter.emitter_id,
        new_label=emitter.label,
        new_endpoint=emitter.endpoint,
        basis=basis,
        features_needed=needed,
        features_carried=tuple(feature for feature in needed if feature in emitter.actions),
    )


@dataclass(frozen=True, slots=True)
class _Rewriter:
    """One swap, applied to one rule at a time.

    A class rather than a function taking six arguments, and the six are the point: a
    rewrite needs the pair being swapped, the replacement's capabilities, the mapping the
    user settled on and the rest of the network to compile against. Holding them once means
    every rule is rewritten against exactly the same picture, which is what stops two rules
    disagreeing about the same device.
    """

    old: DeviceHandle
    new: DeviceHandle
    new_capabilities: DeviceCapabilities
    mappings: Mapping[str, EmitterMapping]
    capabilities: Mapping[str, DeviceCapabilities]

    def rewrite(self, rule: Rule) -> RuleRewrite | None:
        """Return one rule as the swap would leave it, or None when it cannot be rewritten.

        None means the control this rule drives from has no mapping yet, which is a
        question for the user rather than an answer this module can produce.
        `SwapProposal.unmapped` is what says so, and it is what stops the swap being
        applied at all.
        """
        notes: list[Diagnostic] = []
        source = rule.source
        if source.device.identity == self.old.identity:
            mapping = self.mappings.get(source.emitter_id)
            if mapping is None or mapping.new_emitter_id is None:
                return None
            source = RuleSource(
                device=self.new,
                endpoint=(
                    source.endpoint if mapping.new_endpoint is None else mapping.new_endpoint
                ),
                emitter_id=mapping.new_emitter_id,
            )
        after = replace(rule, source=source, targets=self._targets(rule, notes))
        return RuleRewrite(
            rule_id=rule.id,
            before=rule,
            after=after,
            losses=self._losses(rule, after),
            notes=tuple(notes),
            errors=self._compiled(after).errors,
        )

    def _compiled(self, after: Rule) -> CompiledRule:
        """Compile a rewritten rule against the network the replacement is really on.

        Forced enabled, because a disabled rule compiles to nothing and a swap has to say
        what a rule will do once it is switched back on rather than that it currently does
        nothing. That is the same reason the coordinator compiles for ownership that way.
        """
        return compile_rule(after.with_enabled(True), self.capabilities)

    def _losses(self, rule: Rule, after: Rule) -> tuple[Diagnostic, ...]:
        """Return the features the rule asked for that the replacement will not carry.

        Measured against what the rule was **authored** with rather than against what it
        used to compile to, and that is deliberate: the old device is usually gone, so its
        capabilities cannot be read, and "does the replacement still do what I asked for"
        is the question a user is actually asking. It is also the stricter of the two,
        because a feature the old device could not carry either is reported again rather
        than forgotten.
        """
        carried = {link.feature for link in self._compiled(after).links}
        return tuple(
            Diagnostic(
                "swap_feature_lost",
                {
                    "feature": str(feature),
                    "rule": rule.name,
                    "device": self.new.name_at_authoring,
                },
            )
            for feature in sorted(rule.features - carried)
        )

    def _targets(self, rule: Rule, notes: list[Diagnostic]) -> tuple[RuleTarget, ...]:
        """Return this rule's targets with the old device replaced, and no duplicates.

        Two things the substitution can produce that a `Rule` refuses to hold, both of them
        real rather than theoretical on a house where one switch drives another:

        - **The rule already targets the replacement.** A rule that drove both the old
          device and the new one now names one device twice, which `Rule.__post_init__`
          rejects. The duplicate is merged and said so, because a target quietly
          disappearing is a link the user thinks they still have.
        - **The endpoint moves.** A link lands where the replacement says it receives,
          which is what the rule editor's targets step already does when nobody was offered
          the choice (open items T53 and T56). On Z-Wave that is None, the whole node, and
          nothing changes; on Zigbee it is the load endpoint, and a swap between two
          different models is exactly where it can differ.
        """
        rewritten: list[RuleTarget] = []
        seen: set[tuple[str, int | None]] = set()
        for target in rule.targets:
            candidate = self._target(target, rule, notes)
            key = (candidate.device.identity, candidate.endpoint)
            if key in seen:
                notes.append(
                    Diagnostic(
                        "swap_duplicate_target_merged",
                        {"device": self.new.name_at_authoring, "rule": rule.name},
                    )
                )
                continue
            seen.add(key)
            rewritten.append(candidate)
        return tuple(rewritten)

    def _target(self, target: RuleTarget, rule: Rule, notes: list[Diagnostic]) -> RuleTarget:
        """Return one target as the swap leaves it, noting an endpoint that had to move."""
        if target.device.identity != self.old.identity:
            return target
        moved = RuleTarget(device=self.new, endpoint=self.new_capabilities.receiving_endpoint)
        if moved.endpoint != target.endpoint:
            notes.append(
                Diagnostic(
                    "swap_target_endpoint_moved",
                    {
                        "device": self.new.name_at_authoring,
                        "endpoint": _endpoint_text(moved.endpoint),
                        "rule": rule.name,
                    },
                )
            )
        return moved


def _endpoint_text(endpoint: int | None) -> str:
    """Return an endpoint as a placeholder, saying "the whole device" for None.

    A message cannot translate a placeholder (open item T27), and this one is a number in
    every case that matters. None is the Z-Wave answer and is written as the word rather
    than as an empty string, which would read as a sentence with a hole in it.
    """
    return "-" if endpoint is None else str(endpoint)


@dataclass(frozen=True, slots=True)
class Replacement:
    """A device a rule names that is gone or changed, and what could take over from it.

    `changed_in_place` separates the two cases FR-S3 lists, which need different words:
    the device left the network and something else with its model appeared, or a Z-Wave
    "replace failed node" put a different model on the same node id, so the address is
    unchanged and the fingerprint is not.
    """

    old: DeviceHandle
    candidates: tuple[DeviceHandle, ...]
    changed_in_place: bool
    rule_ids: tuple[str, ...]


def find_replacements(
    *,
    rules: Sequence[Rule],
    listed: Mapping[str, DeviceHandle],
    answering: Iterable[BackendId],
    require_candidate: bool = True,
) -> tuple[Replacement, ...]:
    """Return each device the rules name that looks replaced, with what could replace it.

    This is FR-S3's whole trigger, and it is written to be quiet, because a Repairs issue
    that appears whenever a battery device goes briefly unreachable is one that trains
    people to dismiss Repairs. Three conditions, all required:

    - **The backend is answering.** `listed` is only ever built from a read that worked, so
      asking this question of a restarting Z-Wave JS would name every device in the house.
    - **The device is absent from the network's own listing, or its model changed.** Not
      "unreachable": a sleeping ZEN37 and a node whose mesh route is down are both still
      listed, and neither is a swap. A device leaving a driver's node list is not transient,
      and neither is a manufacturer id changing under a node id, which is what Z-Wave's
      "replace failed node" leaves behind (E20).
    - **Something could actually take over.** A device with the same fingerprint that no
      rule already names. Without one there is nothing to offer, and E19's "these rules name
      a device that is not there" is the honest report instead.

    `answering` is the set of backend ids whose adapter answered its last listing; a handle
    on any other backend is skipped entirely.

    `require_candidate` is the third condition, and it is only for the unprompted offer. The
    panel asks with it off, because a user who has opened the swap screen has already
    decided something is wrong and needs to see the device that is gone even when nothing
    on the network looks like it: on this very network, node 13 was a VZW31-SN and its
    replacement node 42 is a VZW32-SN, so the swap that really happened here is one nothing
    would have volunteered. Volunteering it anyway, on the strength of any unused switch
    being present, is the noise this whole function is arranged to avoid.
    """
    up = frozenset(answering)
    referenced = {
        handle.identity
        for rule in rules
        for handle in (rule.source.device, *(target.device for target in rule.targets))
    }
    found: dict[str, Replacement] = {}
    for rule in rules:
        for handle in (rule.source.device, *(target.device for target in rule.targets)):
            if handle.backend not in up or handle.identity in found:
                continue
            replacement = _replacement_for(handle, listed, referenced, rules)
            if replacement is not None and (replacement.candidates or not require_candidate):
                found[handle.identity] = replacement
    return tuple(found[identity] for identity in sorted(found))


def _replacement_for(
    handle: DeviceHandle,
    listed: Mapping[str, DeviceHandle],
    referenced: set[str],
    rules: Sequence[Rule],
) -> Replacement | None:
    """Return what could replace one device a rule names, or None when nothing looks wrong."""
    here = listed.get(handle.identity)
    rule_ids = tuple(sorted(rule.id for rule in rules if references(rule, handle.identity)))
    if here is not None:
        if here.fingerprint.model_key == handle.fingerprint.model_key:
            return None
        # The address did not move and the model did, which is a node that was replaced in
        # place. The candidate is the device now at that address and there is no other.
        return Replacement(old=handle, candidates=(here,), changed_in_place=True, rule_ids=rule_ids)
    candidates = tuple(
        candidate
        for identity, candidate in sorted(listed.items())
        if identity not in referenced
        and candidate.backend is handle.backend
        and candidate.fingerprint.model_key == handle.fingerprint.model_key
    )
    return Replacement(old=handle, candidates=candidates, changed_in_place=False, rule_ids=rule_ids)
