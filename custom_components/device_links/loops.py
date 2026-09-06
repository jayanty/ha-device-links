"""Loop analysis: which of these links, together, can chase each other around a house.

FR-R7. One link cannot loop. Two switches that each repeat what they receive to the other
can, and the symptom is a room that will not settle: the lights flicker, the mesh fills with
traffic, and nothing in either device's own configuration looks wrong, because neither of
them is wrong on its own. It is a property of the whole graph, which is why it lives here
rather than in `compiler.py`: the compiler sees one rule at a time and by construction
cannot see this.

It is pure. Links and forwarding devices in, cycles out, no Home Assistant and no I/O, so
it can be property-tested against generated graphs rather than against a house.

**Two conditions, and the second is the one that keeps this quiet.** A cycle in the control
graph is not a loop: a two-way pair is a cycle, and a two-way pair is the ordinary Virtual
3-way that half this product exists to build. What makes a cycle run away is every node on
it **forwarding what it receives**: the Zooz parameter 35 bit 4, the Inovelli parameter 59
bit 2, "repeat commands received from the hub to my associations". So the graph is narrowed
to the devices that forward before a cycle is looked for, and a cycle through a device that
does not relay is not reported at all.

**It is a warning and never a block** (E30). The analysis knows what the links say and not
what the devices do: a switch may be configured in a way no profile of ours describes, a
target may ignore what it receives, and the user may know something this does not. So it
says what it found, names the devices and the rules, and lets the rule be saved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from custom_components.device_links.compiler import MIRROR_CAPABILITY, CompiledRule
from custom_components.device_links.models import (
    DeviceHandle,
    Link,
    MirrorChoice,
    Rule,
)


@dataclass(frozen=True, slots=True)
class Loop:
    """One set of devices that can pass a command round between them forever.

    `devices` are the handles on the cycle, in a stable order rather than in the order a
    command would travel: a cycle has no first node, and picking one would make the same
    loop read differently depending on which rule was compiled first.

    `rule_ids` and `rule_names` are what makes this actionable. "These four devices form a
    loop" is a fact; "and it is these two rules that join them" is something a user can go
    and change.
    """

    devices: tuple[DeviceHandle, ...]
    rule_ids: tuple[str, ...]
    rule_names: tuple[str, ...]

    @property
    def identity(self) -> tuple[str, ...]:
        """The loop's identity: the devices on it, and nothing about how it was made."""
        return tuple(device.identity for device in self.devices)


def forwarding_devices(
    rules: Iterable[Rule], observed: Mapping[str, Mapping[str, int]] | None = None
) -> frozenset[str]:
    """Return every device that repeats what it receives, as far as anything here knows.

    Two sources, and both are needed. A rule that asks for mirroring says the device will
    forward once the rule is applied, which is what makes a loop visible **before** it is
    written. What a device already holds says it forwards now, whether or not any rule of
    ours asked, which is the case the desired state cannot see: somebody turned it on in
    Z-Wave JS UI years ago, and the rule being written today is the second half of a loop
    that has been waiting for it.

    `observed` is the settings each device reported, by identity and capability name, which
    is exactly what the coordinator's observed state holds. A non-zero mirror setting reads
    as forwarding: every adapter in the profile database maps `on` to a non-zero value, and
    a device whose setting was never read simply is not in the mapping.
    """
    forwarding = {
        rule.source.device.identity for rule in rules if rule.mirror_source is MirrorChoice.ON
    }
    for identity, settings in (observed or {}).items():
        if settings.get(MIRROR_CAPABILITY, 0):
            forwarding.add(identity)
    return frozenset(forwarding)


@dataclass(slots=True)
class _Graph:
    """The control graph, narrowed to the devices that relay what they receive.

    Narrowed as it is built rather than after the search, which is what makes FR-R7's
    second condition exact: a path that leaves the forwarding set cannot re-enter it
    through the node it left by, so every cycle in this graph is a cycle whose every node
    relays, which is precisely what has to be flagged.
    """

    forwarding: frozenset[str]
    edges: dict[str, set[str]] = field(default_factory=dict)
    handles: dict[str, DeviceHandle] = field(default_factory=dict)
    owners: dict[tuple[str, str], set[str]] = field(default_factory=dict)

    def add(self, link: Link, rule_id: str) -> None:
        """Record one link as an edge, when both of its ends relay."""
        source = link.source.identity
        target = link.target.handle.identity
        if source not in self.forwarding or target not in self.forwarding:
            return
        self.handles[source] = link.source
        self.handles[target] = link.target.handle
        self.edges.setdefault(source, set()).add(target)
        self.owners.setdefault((source, target), set()).add(rule_id)

    def rules_inside(self, component: set[str]) -> list[str]:
        """Return the rules whose links join the devices of one component."""
        return sorted(
            {
                rule_id
                for source in component
                for target in self.edges.get(source, ())
                if target in component
                for rule_id in self.owners[(source, target)]
            }
        )


def find_loops(
    compiled: Mapping[str, CompiledRule],
    rules: Sequence[Rule],
    *,
    forwarding: frozenset[str],
) -> tuple[Loop, ...]:
    """Return every set of forwarding devices that can pass a command round between them.

    `compiled` is what each rule compiled to, by rule id, and `rules` is the profile in its
    own order so that a loop can name the rules that make it. Only enabled rules take part:
    a disabled rule's links are on their way off the devices, and reporting a loop that
    exists only in a rule somebody has already switched off is the kind of warning that
    teaches people to stop reading them.
    """
    enabled = {rule.id for rule in rules if rule.enabled}
    graph = _Graph(forwarding=forwarding)
    for rule_id, result in compiled.items():
        if rule_id not in enabled:
            continue
        for link in result.links:
            graph.add(link, rule_id)

    names = {rule.id: rule.name for rule in rules}
    loops: list[Loop] = []
    for component in _components(graph.edges):
        rule_ids = graph.rules_inside(component)
        loops.append(
            Loop(
                devices=tuple(graph.handles[identity] for identity in sorted(component)),
                rule_ids=tuple(rule_ids),
                rule_names=tuple(names.get(rule_id, rule_id) for rule_id in rule_ids),
            )
        )
    return tuple(sorted(loops, key=lambda loop: loop.identity))


def _components(edges: Mapping[str, set[str]]) -> list[set[str]]:
    """Return every strongly connected group of two or more devices.

    Tarjan's algorithm, written iteratively because a house is a graph somebody builds by
    hand and a recursion limit is a strange thing to meet while saving a rule. A component
    of one is not a loop: it is one device, and a link from a device to itself cannot exist
    (`Link` refuses one).
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[set[str]] = []
    counter = 0

    for root in sorted(edges):
        if root in index:
            continue
        # Each frame is a node and how far through its successors we have got.
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, position = work[-1]
            if position == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            successors = sorted(edges.get(node, ()))
            if position < len(successors):
                work[-1] = (node, position + 1)
                successor = successors[position]
                if successor not in index:
                    work.append((successor, 0))
                elif successor in on_stack:
                    low[node] = min(low[node], index[successor])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                component: set[str] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.add(member)
                    if member == node:
                        break
                if len(component) > 1:
                    found.append(component)
    return found


__all__ = ["Loop", "find_loops", "forwarding_devices"]
