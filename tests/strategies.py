"""Hypothesis strategies: whole small networks, built out of the Stage 0 capture.

`networks()` produces a `Network`: two to five real devices from
`tests/fixtures/z2_associations.json` with their real emitters and their real group
capacities, a handful of rules over them, and a starting device state that always holds a
lifeline per device and sometimes holds associations somebody made by hand.

`Network.apply` is the fake radio. It does exactly two things, adds and removes, and it
refuses to overfill a group, because a fake that is more permissive than a real device would
let the capacity property pass while a user's last association silently vanished. Everything
else a real device refuses is refused before a `Link` exists at all: `Link` itself rejects a
self-association, and the compiler rejects a Long Range source or target, so no such write
can reach the radio and the fake does not pretend to guard against one.

Everything drawn here is drawn from a fixed vocabulary of node ids, emitter ids and features,
so a counterexample reads as "node 36 group 11" rather than as a random string, and `Network`
prints itself in that shorthand rather than dumping every dataclass it holds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from hypothesis import strategies as st

from custom_components.device_links.compiler import compile_rule
from custom_components.device_links.models import (
    Backend,
    DeviceCapabilities,
    DeviceHandle,
    Direction,
    Emitter,
    Feature,
    Link,
    ObservedLink,
    Plan,
    PlanOp,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from tests.factories import (
    FIRST_LONG_RANGE_NODE_ID,
    capabilities_for,
    group_capacities,
    handle,
    link,
    observed,
)

# The devices a generated network is drawn from, most ordinary first: Hypothesis shrinks
# `sampled_from` towards the front of the list, so the smallest counterexample is a scene
# controller and a light rather than the exotic hardware later in the pool.
#
# 36 ZEN35 scene controller, 38 Inovelli load switch, 30 a second ZEN35 whose groups 11 and
# 12 really do hold one entry each, which is the cheapest way to reach a full group, 40 the
# ZEN37 remote whose groups hold five, 21 another Inovelli and 29 the older ZEN34.
DEVICE_NODE_IDS: Final = (36, 38, 30, 40, 21, 29)

# A node that joined over Long Range, which Decision D13 refuses as an association source and
# as a target. It is added on its own and rarely, because it can hold no link at all: a pool
# member would be in half of all networks and would spend the generation budget on a device
# every property is trivially true of.
LONG_RANGE_NODE_ID: Final = 300

# Nodes a hand-made association can point at that are not part of the generated network. A
# group holds five or ten entries, so filling one needs more targets than the network has.
OUTSIDE_NODE_IDS: Final = (2, 3, 4, 5, 6, 7, 8, 9)

# The controller every lifeline reports to.
CONTROLLER_NODE_ID: Final = 1

# The features the fixture devices actually carry, which is what makes a generated rule
# compile into something rather than into a warning.
FEATURES: Final = (Feature.ON_OFF, Feature.LEVEL_HOLD, Feature.LEVEL_SET)

TEMPLATES: Final = (Template.CUSTOM, Template.REMOTE, Template.OFF_ALL)
DIRECTIONS: Final = (Direction.ONE_WAY, Direction.TWO_WAY)
ENDPOINTS: Final = (None, 1)

MAX_RULES: Final = 3
MAX_TARGETS: Final = 2

# Hand-made associations arrive in clusters: one control somebody wired to several devices,
# which is both what a real network looks like and the only way a group ever gets full.
MAX_CROWDS: Final = 3

# One in this many draws takes the unusual branch: a Long Range device in the network, a rule
# that has since been disabled. Rare, because the interesting states are the ordinary ones.
UNUSUAL: Final = 4


class RadioRefusedError(Exception):
    """What the fake radio raises when a plan asks a device to do what it cannot do.

    A real device answers a full group with an error, so the fake does too. Swallowing it
    would leave `test_group_capacity_is_never_exceeded` asserting about a state that the
    simulation had already quietly repaired.
    """


@dataclass(frozen=True, slots=True, order=True, repr=False)
class GroupKey:
    """One association group on one device: the unit capacity is counted in."""

    node_id: int
    group: str

    def __repr__(self) -> str:
        """Name the group the way a person reading a failure would say it out loud."""
        return f"node {self.node_id} group {self.group}"


def node_id_of(identity: str) -> int:
    """Return the node id inside a `DeviceHandle.identity` (`zwave:<home id>:<node id>`)."""
    return int(identity.rsplit(":", 1)[1])


def group_key(entry: Link) -> GroupKey:
    """Return the group a link occupies on its source device."""
    return GroupKey(node_id_of(entry.source.identity), entry.emitter_group)


class Network:
    """A generated network: what it is made of, what is wanted, and what is on the devices.

    `desired` is what the enabled rules compile to, so the compiler is exercised by every
    property rather than being bypassed with hand-built links.

    This is deliberately not a dataclass. Hypothesis prints a falsifying example by walking
    `__dataclass_fields__` when it finds them, which would bury the one line a reader needs
    under every emitter of every device, and `__repr__` here is the whole counterexample.
    """

    __slots__ = ("capabilities", "desired", "node_ids", "observed", "remove_unmanaged", "rules")

    def __init__(
        self,
        *,
        node_ids: tuple[int, ...],
        capabilities: Mapping[str, DeviceCapabilities],
        rules: tuple[Rule, ...],
        observed: tuple[ObservedLink, ...],
        remove_unmanaged: frozenset[str],
    ) -> None:
        """Hold one generated network, and compile its rules into what it wants.

        A disabled rule compiles to nothing, which is what makes its links show up as
        removals against a device that still holds them.
        """
        self.node_ids = node_ids
        self.capabilities = capabilities
        self.rules = rules
        self.observed = observed
        self.remove_unmanaged = remove_unmanaged
        self.desired = tuple(
            wanted for rule in rules for wanted in compile_rule(rule, capabilities).links
        )

    def plan_inputs(
        self,
        *,
        observed: Sequence[ObservedLink] | None = None,
        remove_everything: bool = False,
    ) -> dict[str, Any]:
        """Return the keyword arguments `build_plan` takes for this network.

        `observed` replaces the starting state, which is how a property plans again against
        what applying produced. `remove_everything` selects every entry on every device,
        including the lifelines, which is the worst thing a user could ask for and the input
        the lifeline property needs.
        """
        entries = self.observed if observed is None else tuple(observed)
        selected = (
            frozenset(entry.fingerprint for entry in entries)
            if remove_everything
            else self.remove_unmanaged
        )
        return {
            "desired": self.desired,
            "observed": entries,
            "capabilities": self.capabilities,
            "remove_unmanaged": selected,
        }

    def apply(self, plan: Plan) -> tuple[ObservedLink, ...]:
        """Run this plan against the fake radio and return what the devices then hold.

        The state it starts from is the state the network starts in, which is the state every
        property builds its plan against.

        Adds and removes, in plan order, and nothing else. A removal is performed even on a
        system link: refusing one here would hide the very mistake
        `test_a_lifeline_is_never_removed` exists to catch, which is the planner's to avoid
        and not the radio's.
        """
        state = {entry.fingerprint: entry for entry in self.observed}
        for item in plan.items:
            if item.op not in (PlanOp.ADD, PlanOp.REMOVE):
                continue
            if item.link is None:
                raise RadioRefusedError(f"a {item.op} item carried no link")
            if item.op is PlanOp.REMOVE:
                state.pop(item.link.fingerprint, None)
            else:
                self._write(state, item.link)
        return tuple(state.values())

    def _write(self, state: dict[str, ObservedLink], wanted: Link) -> None:
        """Add one association, refusing the write when the group is already full."""
        key = group_key(wanted)
        capacity = self.capacity_of(key)
        held = sum(1 for entry in state.values() if group_key(entry) == key)
        if held >= capacity:
            raise RadioRefusedError(
                f"{key} holds {held} of {capacity}: refusing to add {render_link(wanted)}"
            )
        state[wanted.fingerprint] = ObservedLink(
            **wanted.as_kwargs(), is_system=False, managed_by=wanted.rule_id
        )

    def entries_by_group(
        self, state: Sequence[ObservedLink]
    ) -> Mapping[GroupKey, tuple[Link, ...]]:
        """Return the entries a device state puts in each association group."""
        grouped: dict[GroupKey, list[Link]] = {}
        for entry in state:
            grouped.setdefault(group_key(entry), []).append(entry)
        return {key: tuple(entries) for key, entries in sorted(grouped.items())}

    def capacity_of(self, key: GroupKey) -> int:
        """Return how many entries this group holds, as the device itself reports it."""
        return group_capacities(key.node_id)[key.group]

    def unmanaged_fingerprints(self) -> frozenset[str]:
        """Return the hand-made links that nobody asked to remove, which must all survive."""
        return frozenset(
            entry.fingerprint
            for entry in self.observed
            if is_unmanaged(entry) and entry.fingerprint not in self.remove_unmanaged
        )

    def selected_fingerprints(self) -> frozenset[str]:
        """Return the hand-made links the user did select, which must come off.

        A link a rule also wants is left out: it is accounted for, so it is not foreign, and
        the planner keeps it whatever the selection says.
        """
        wanted = {entry.fingerprint for entry in self.desired}
        return frozenset(
            entry.fingerprint
            for entry in self.observed
            if is_unmanaged(entry)
            and entry.fingerprint in self.remove_unmanaged
            and entry.fingerprint not in wanted
        )

    def __repr__(self) -> str:
        """Print the network in the shorthand a failure has to be readable in."""
        selected = [
            render_link(entry)
            for entry in self.observed
            if entry.fingerprint in self.remove_unmanaged
        ]
        return (
            "Network(\n"
            f"  devices={[f'node {node_id}' for node_id in self.node_ids]}\n"
            f"  rules={[render_rule(rule) for rule in self.rules]}\n"
            f"  observed={[render_observed(entry) for entry in self.observed]}\n"
            f"  desired={[render_link(entry) for entry in self.desired]}\n"
            f"  remove_unmanaged={selected}\n"
            ")"
        )


def is_unmanaged(entry: ObservedLink) -> bool:
    """Say whether this entry is somebody's own work rather than ours or the system's."""
    return not entry.is_system and entry.managed_by is None


def render_link(entry: Link) -> str:
    """Return one link as "n36 g9 -> n38 on_off", which is what it is on the device."""
    endpoint = "" if entry.target.endpoint is None else f".{entry.target.endpoint}"
    return (
        f"n{node_id_of(entry.source.identity)} g{entry.emitter_group} "
        f"-> n{node_id_of(entry.target.handle.identity)}{endpoint} {entry.feature}"
    )


def render_observed(entry: ObservedLink) -> str:
    """Return one observed entry as its link plus who, if anyone, owns it."""
    owner = "system" if entry.is_system else (entry.managed_by or "unmanaged")
    return f"{render_link(entry)} [{owner}]"


def render_rule(rule: Rule) -> str:
    """Return one rule as the intent it carries, in one line."""
    targets = ",".join(
        f"n{node_id_of(target.device.identity)}"
        + ("" if target.endpoint is None else f".{target.endpoint}")
        for target in rule.targets
    )
    features = ",".join(sorted(str(feature) for feature in rule.features))
    return (
        f"{rule.id} {'enabled' if rule.enabled else 'disabled'} {rule.template} "
        f"{rule.direction}: n{node_id_of(rule.source.device.identity)}/{rule.source.emitter_id} "
        f"-> [{targets}] {features}"
    )


def _rarely() -> st.SearchStrategy[bool]:
    """Return a strategy that is true about one time in `UNUSUAL`, and shrinks to false."""
    return st.integers(min_value=0, max_value=UNUSUAL - 1).map(lambda drawn: drawn == UNUSUAL - 1)


def _device(node_id: int) -> DeviceHandle:
    """Return the handle for a node id, declaring Long Range the way the factory demands."""
    return handle(node_id, long_range=node_id >= FIRST_LONG_RANGE_NODE_ID)


def _identity(node_id: int) -> str:
    """Return the capabilities key for a node id."""
    return _device(node_id).identity


@st.composite
def networks(draw: st.DrawFn) -> Network:
    """Return a small network: real devices, some rules, and a state they start in."""
    node_ids = tuple(
        draw(st.lists(st.sampled_from(DEVICE_NODE_IDS), min_size=2, max_size=4, unique=True))
    )
    if draw(_rarely()):
        node_ids += (LONG_RANGE_NODE_ID,)
    capabilities = capabilities_for(*node_ids)
    rules = tuple(
        _rule(draw, index, node_ids, capabilities)
        for index in range(draw(st.integers(min_value=1, max_value=MAX_RULES)))
    )
    compiled = {
        rule.id: compile_rule(rule.with_enabled(True), capabilities).links for rule in rules
    }
    entries = _observed(draw, node_ids, capabilities, rules, compiled)
    unmanaged = sorted(entry.fingerprint for entry in entries if is_unmanaged(entry))
    selection = (
        draw(st.lists(st.sampled_from(unmanaged), unique=True, max_size=len(unmanaged)))
        if unmanaged
        else []
    )
    return Network(
        node_ids=node_ids,
        capabilities=capabilities,
        rules=rules,
        observed=entries,
        remove_unmanaged=frozenset(selection),
    )


def _rule(
    draw: st.DrawFn,
    index: int,
    node_ids: Sequence[int],
    capabilities: Mapping[str, DeviceCapabilities],
) -> Rule:
    """Draw one rule over these devices, including ones the compiler will have to refuse."""
    source_node = draw(st.sampled_from(sorted(node_ids)))
    emitters = capabilities[_identity(source_node)].emitters
    targets = draw(
        st.lists(st.sampled_from(sorted(node_ids)), min_size=1, max_size=MAX_TARGETS, unique=True)
    )
    return Rule(
        id=f"rule-{index}",
        name=f"Rule {index}",
        template=draw(st.sampled_from(TEMPLATES)),
        backend=Backend.ZWAVE,
        source=RuleSource(
            device=_device(source_node),
            endpoint=0,
            emitter_id=draw(st.sampled_from([emitter.emitter_id for emitter in emitters])),
        ),
        targets=tuple(
            RuleTarget(device=_device(node), endpoint=draw(st.sampled_from(ENDPOINTS)))
            for node in targets
        ),
        features=frozenset(draw(st.lists(st.sampled_from(FEATURES), min_size=1, unique=True))),
        direction=draw(st.sampled_from(DIRECTIONS)),
        enabled=not draw(_rarely()),
    )


def _observed(
    draw: st.DrawFn,
    node_ids: Sequence[int],
    capabilities: Mapping[str, DeviceCapabilities],
    rules: Sequence[Rule],
    compiled: Mapping[str, tuple[Link, ...]],
) -> tuple[ObservedLink, ...]:
    """Draw the state the devices start in: lifelines, our own links, and foreign ones.

    Every device holds its lifeline, because a device that has none is not reporting to Home
    Assistant at all and is not a state this integration can be run against. Our own links
    come from the rules, so a network can start already applied, half applied, or holding the
    links of a rule that has since been disabled. Foreign links are what somebody made by
    hand in Z-Wave JS UI, and can point outside the network entirely.

    One fingerprint is one entry on one device, so an entry that is drawn twice is kept once,
    and a group never receives more than it holds: see `_place`.
    """
    entries: dict[str, ObservedLink] = {}
    for node_id in node_ids:
        _place(
            entries,
            observed(
                link(node_id, "g1", CONTROLLER_NODE_ID, Feature.STATUS_REPORT),
                rule_id=None,
                system=True,
            ),
        )
    for rule_id, links in sorted(compiled.items()):
        for wanted in links:
            if draw(st.booleans()):
                _place(entries, observed(wanted, rule_id=rule_id))
    for _ in range(draw(st.integers(min_value=0, max_value=MAX_CROWDS))):
        for foreign in _crowd(draw, node_ids, capabilities, rules):
            _place(entries, foreign)
    return tuple(entries.values())


def _place(entries: dict[str, ObservedLink], entry: ObservedLink) -> None:
    """Put one entry on the device, unless it is already there or its group is full.

    A device cannot report more entries in a group than the group holds, so a generated
    starting state that said otherwise would describe a network that cannot exist, and every
    property measured against it would be measuring an impossible world. Hypothesis found
    this the first time the properties ran: three overlapping hand-made clusters put eleven
    entries in a group of ten, and the capacity property failed against a state the planner
    had never touched.
    """
    key = group_key(entry)
    if entry.fingerprint in entries:
        return
    held = sum(1 for other in entries.values() if group_key(other) == key)
    if held >= group_capacities(key.node_id)[key.group]:
        return
    entries[entry.fingerprint] = entry


def _emitter_of(
    capabilities: Mapping[str, DeviceCapabilities], node_id: int, emitter_id: str
) -> Emitter:
    """Return one named control of one device."""
    return next(
        emitter
        for emitter in capabilities[_identity(node_id)].emitters
        if emitter.emitter_id == emitter_id
    )


def _crowd(
    draw: st.DrawFn,
    node_ids: Sequence[int],
    capabilities: Mapping[str, DeviceCapabilities],
    rules: Sequence[Rule],
) -> list[ObservedLink]:
    """Draw one control somebody wired by hand to several devices.

    Half the time the control is one a rule also uses, carrying a feature that rule also
    asks for, which is what puts a group under pressure: a group a user has already filled
    themselves has no room for the link a rule wants, and that is the state the capacity
    property has to be given to mean anything. Drawing each entry independently spreads them
    over a dozen groups and reaches a full one about never.

    A Long Range node is left out as both ends: the protocol never let one into an
    association group, so a state holding one would describe a network that cannot exist.
    """
    linkable = sorted(node for node in node_ids if node < FIRST_LONG_RANGE_NODE_ID)
    contested = [rule for rule in rules if node_id_of(rule.source.device.identity) in linkable]
    if contested and draw(st.booleans()):
        rule = draw(st.sampled_from(contested))
        source_node = node_id_of(rule.source.device.identity)
        emitter = _emitter_of(capabilities, source_node, rule.source.emitter_id)
        wanted = sorted(feature for feature in rule.features if feature in emitter.actions)
    else:
        source_node = draw(st.sampled_from(linkable))
        controls = capabilities[_identity(source_node)].emitters
        emitter = _emitter_of(
            capabilities,
            source_node,
            draw(st.sampled_from([control.emitter_id for control in controls])),
        )
        wanted = []
    emitter_id = emitter.emitter_id
    feature = draw(st.sampled_from(wanted or sorted(emitter.actions)))
    candidates = [node for node in [*linkable, *OUTSIDE_NODE_IDS] if node != source_node]
    # The size is drawn on its own rather than left to `st.lists`, whose lists are short by
    # design, and half of these crowds fill the group to the brim. The boundary is the whole
    # point: a group of ten that is never given ten entries is a case the capacity property
    # would never reach, and measuring said it reached one about twice in a hundred networks
    # when the size was left to chance.
    brim = min(len(candidates), emitter.capacity)
    size = brim if draw(st.booleans()) else draw(st.integers(min_value=1, max_value=brim))
    targets = draw(st.lists(st.sampled_from(candidates), min_size=size, max_size=size, unique=True))
    return [
        observed(link(source_node, emitter_id, target, feature), rule_id=None) for target in targets
    ]
