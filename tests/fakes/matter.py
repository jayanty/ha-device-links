"""A fake Matter fabric, built from the Stage 0 M1 capture of Jayant's real network.

**The read half is faithful and the write half is a model, and that difference is the most
important thing about this file.** `tests/fixtures/m1_matter.json` is a capture of 19 real
Matter nodes: their endpoints, their client and server cluster lists, their Binding lists and
their Access Control lists and capacities, read through `MatterClient.read_attribute` on
2026-09-05. What this fake serves for a read is what the fabric served.

Nothing has ever been written. No `write_attribute` call has been made against a Binding
list or an Access Control list on this fabric or on any other, because Stage 0 item M1 was
read-only and Matter writes stay behind an options flag that defaults to off (FR-B7,
Decision D11). So every response to a write below is taken from the Matter specification and
from the shape the reads came back in, and **a test that passes against this fake proves the
adapter agrees with the model and proves nothing whatever about a device.** That is
assumption **A9** in `docs/open-items.md`, and this file is what gets corrected when a write
is finally attempted against real hardware.

Five behaviours it reproduces on purpose, each because getting it wrong is a way to ship a
Matter bug that looks like it works:

1. **A read returns a mapping keyed by the attribute path**, not the bare value. Reading it
   as the value silently turns every list result into "not a list", which reads as "this
   device has no client clusters" rather than as an error. That bug was hit during Stage 0.
2. **A struct comes back keyed by TLV tag.** An Access Control entry is `{"1": 5, "2": 2,
   "3": [112233], "4": null, "254": 2}` and not a mapping keyed by field name.
3. **Another fabric's entries come back redacted**, carrying a fabric index and nothing else.
   Fifteen of the nineteen nodes have at least one, and they are the reason an Access Control
   list looks fuller than the part of it we can read.
4. **A write is accepted without saying what it did.** `write_attribute` answers with no
   useful result, so the only way to know what happened is to read the attribute back. The
   `silent` knob is the device that accepts a write and ignores it, which is exactly what a
   read-back is for.
5. **A write can do more than it was asked to.** `unscoped_acl_writes` makes an Access
   Control write replace every fabric's entries rather than this fabric's, and
   `drops_administer` makes one lose the controller's own entry. Neither has ever been
   observed and both would be catastrophic, which is why the adapter checks for them on
   every single write rather than trusting that the specification is implemented.

It does one thing deliberately **not** to protect the caller: it writes whatever it is
given, including a list that drops an Administer entry. A real device would. Making the fake
refuse would make the adapter's own refusal untested, and that refusal is what makes Matter
writes safe to ship at all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Final

from custom_components.device_links.backends import matter_protocol as mp

FIXTURE: Final = Path(__file__).resolve().parent.parent / "fixtures" / "m1_matter.json"

# What the M1 capture recorded for the server this fabric runs on.
SDK_VERSION: Final = "matter-server/1.4.0 (matter.js/0.17.9)"

# The compressed fabric id is not in the capture: the probe connected to the server
# directly and never asked for it. This is a plausible one, and the only thing that depends
# on its value is the device registry identifier, which is checked for shape rather than for
# this number.
COMPRESSED_FABRIC_ID: Final = 0x1A2B3C4D5E6F7788

# The controller's own node id on this fabric, as every readable Access Control entry in the
# capture reports it.
CONTROLLER_NODE_ID: Final = 112233


class FakeMatterError(Exception):
    """What the client raises when a node will not answer.

    Modelled on `matter_server.common.errors.MatterError`, which the real client raises for
    a read or a write that failed. The adapter must never let one escape as an unhandled
    exception, so tests raise this rather than something tidier.
    """


@dataclass(slots=True)
class FakeDeviceInfo:
    """The two Basic Information fields a handle is built from."""

    vendorName: str | None  # noqa: N815 - the Matter cluster's field name, not ours
    productName: str | None  # noqa: N815 - the Matter cluster's field name, not ours


@dataclass(slots=True)
class FakeNode:
    """One node, as the client's own node object presents it.

    Deliberately only the four things the adapter reads off a node object: everything else
    it wants, it reads as an attribute. A fake that offered more would let the adapter grow
    a dependency on a shape nobody has checked.
    """

    node_id: int
    available: bool
    name: str | None
    device_info: FakeDeviceInfo | None
    endpoints: Mapping[int, object]


@dataclass(slots=True)
class FakeServerInfo:
    """What the client says about the server and the fabric it is on."""

    compressed_fabric_id: int = COMPRESSED_FABRIC_ID
    sdk_version: str = SDK_VERSION


@dataclass(slots=True)
class _Subscription:
    """One live subscription, with the filters it was registered under."""

    callback: Callable[[Any, Any], None]
    event_filter: object
    node_filter: int | None


@dataclass(slots=True)
class FakeMatterClient:
    """One Matter fabric, holding real attribute values and answering real reads and writes.

    Constructed from the capture by `build_fabric_from_fixture`, or from nodes a test made
    up. Nothing here reaches a network.
    """

    nodes: dict[int, FakeNode] = field(default_factory=dict)
    attributes: dict[int, dict[str, Any]] = field(default_factory=dict)
    server_info: FakeServerInfo | None = field(default_factory=FakeServerInfo)

    # What a test asks the fabric to do wrong. Every one reproduces a failure that is
    # possible rather than an invented one; see the module docstring.
    unresponsive: set[int] = field(default_factory=set)
    reject_writes: set[str] = field(default_factory=set)
    silent: set[str] = field(default_factory=set)
    unscoped_acl_writes: bool = False
    drops_administer: bool = False

    # Every read and every write, so a test can assert that a refusal really refused rather
    # than merely reporting one after the fact.
    reads: list[tuple[int, str]] = field(default_factory=list)
    writes: list[tuple[int, str, Any]] = field(default_factory=list)

    _subscriptions: list[_Subscription] = field(default_factory=list)

    # The surface the adapter is written against.

    def get_nodes(self) -> list[FakeNode]:
        """Return every node on the fabric. No I/O: the client holds these."""
        return list(self.nodes.values())

    async def read_attribute(self, node_id: int, attribute_path: str) -> Any:
        """Read one attribute, answering with a mapping keyed by the path.

        The shape is the point. `read_attribute` does not return the value; it returns
        `{"2/29/2": [3, 6, 8]}`, and an adapter that treats the mapping as the value reads
        every list as "not a list" (Stage 0 M1).
        """
        self.reads.append((node_id, attribute_path))
        if node_id in self.unresponsive:
            raise FakeMatterError(f"node {node_id} did not respond")
        held = self.attributes.get(node_id, {})
        if attribute_path not in held:
            raise FakeMatterError(f"node {node_id} has no attribute {attribute_path}")
        return {attribute_path: deepcopy(held[attribute_path])}

    async def write_attribute(self, node_id: int, attribute_path: str, value: Any) -> Any:
        """Write one attribute, and answer with nothing worth reading.

        NOTE: modelled from the Matter specification, never observed. No attribute has ever
        been written on this fabric. Assumption A9, docs/open-items.md.
        """
        self.writes.append((node_id, attribute_path, deepcopy(value)))
        if node_id in self.unresponsive:
            raise FakeMatterError(f"node {node_id} did not respond")
        if attribute_path in self.reject_writes:
            raise FakeMatterError(f"node {node_id} rejected a write to {attribute_path}")
        if attribute_path in self.silent:
            # Accepted and ignored, which is what a read-back is for.
            return None
        if attribute_path == mp.ACL_PATH:
            self.attributes.setdefault(node_id, {})[attribute_path] = self._written_acl(
                node_id, value
            )
            return None
        self.attributes.setdefault(node_id, {})[attribute_path] = deepcopy(value)
        return None

    def _written_acl(self, node_id: int, value: Any) -> list[Any]:
        """Apply an Access Control write the way a fabric-scoped list attribute behaves.

        A write replaces the accessing fabric's entries and leaves every other fabric's
        alone, and the node stamps each written entry with the fabric the write arrived on.
        That is what the specification says and what nobody has ever watched happen here.

        `unscoped_acl_writes` is the same write on a server that got it wrong and replaced
        the whole list. `drops_administer` is one that lost the controller's own entry.
        Both exist so that the adapter's check for them is exercised rather than assumed.
        """
        written = [
            {**deepcopy(entry), str(mp.ACL_TAG_FABRIC_INDEX): self.fabric_index(node_id)}
            for entry in value
        ]
        if self.drops_administer:
            written = [
                entry
                for entry in written
                if entry.get(str(mp.ACL_TAG_PRIVILEGE)) != mp.PRIVILEGE_ADMINISTER
            ]
        if self.unscoped_acl_writes:
            return written
        foreign = [
            deepcopy(entry)
            for entry in self.attributes[node_id][mp.ACL_PATH]
            if entry.get(str(mp.ACL_TAG_PRIVILEGE)) is None
        ]
        return [*foreign, *written]

    def subscribe_events(
        self,
        callback: Callable[[Any, Any], None],
        event_filter: object = None,
        node_filter: int | None = None,
    ) -> Callable[[], None]:
        """Register a listener, and return the callable that removes it.

        Keyword names match the client's, because the adapter calls it by keyword and a
        fake that accepted anything positionally would let a wrong call pass.
        """
        subscription = _Subscription(callback, event_filter, node_filter)
        self._subscriptions.append(subscription)

        def _unsubscribe() -> None:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

        return _unsubscribe

    # What a test does to the fabric.

    @property
    def subscription_count(self) -> int:
        """Return how many live subscriptions there are, so a leak is visible in a test."""
        return len(self._subscriptions)

    def notify(self, event: object, data: object) -> None:
        """Deliver one event to every subscription that did not filter it out."""
        for subscription in list(self._subscriptions):
            if subscription.event_filter is not None and subscription.event_filter != event:
                continue
            subscription.callback(event, data)

    def fabric_index(self, node_id: int) -> int:
        """Return the fabric index this controller reads under on one node.

        Different on different nodes in the capture (2 on the Inovelli switches, 3 on the
        first Eve Energy), which is why nothing may treat it as a constant.
        """
        entries = mp.parse_acl(self.attributes[node_id][mp.ACL_PATH])
        index = mp.our_fabric_index(entries)
        return 0 if index is None else index

    def acl_of(self, node_id: int) -> tuple[mp.AclEntry, ...]:
        """Return one node's Access Control list as the pure module reads it.

        Convenience for a test that is about what was written rather than about how it is
        spelled. It shares a parser with the code under test, so a test that only ever looks
        through here cannot see a parsing mistake: `raw_acl_of` is what to use when the
        spelling is the point, and `tests/test_matter_writes.py` uses it for the entry the
        integration actually writes.
        """
        return mp.parse_acl(self.attributes[node_id][mp.ACL_PATH])

    def raw_acl_of(self, node_id: int) -> list[Any]:
        """Return one node's Access Control list exactly as it is held, unparsed."""
        held: list[Any] = self.attributes[node_id][mp.ACL_PATH]
        return held

    def bindings_of(self, node_id: int, endpoint: int) -> list[Any]:
        """Return one endpoint's Binding list, raw, as the node holds it."""
        held: list[Any] = self.attributes[node_id][mp.binding_path(endpoint)]
        return held

    def set_acl(self, node_id: int, entries: Sequence[Mapping[str, Any]]) -> None:
        """Replace one node's Access Control list outright, as a second controller would."""
        self.attributes[node_id][mp.ACL_PATH] = [dict(entry) for entry in entries]

    def set_capacity(self, node_id: int, **capacity: int) -> None:
        """Change what a node says it can hold, for the cases the fabric does not contain."""
        paths = {
            "entries_per_fabric": mp.ACL_ENTRIES_PER_FABRIC_PATH,
            "subjects_per_entry": mp.ACL_SUBJECTS_PER_ENTRY_PATH,
            "targets_per_entry": mp.ACL_TARGETS_PER_ENTRY_PATH,
        }
        for name, value in capacity.items():
            self.attributes[node_id][paths[name]] = value

    def add_binding(self, node_id: int, endpoint: int, entry: Mapping[str, Any]) -> None:
        """Put a binding on a node, as somebody else's controller would have."""
        self.attributes[node_id].setdefault(mp.binding_path(endpoint), []).append(dict(entry))

    def go_offline(self, node_id: int) -> None:
        """Mark a node unreachable, which is E29's sleepy or absent node."""
        self.nodes[node_id].available = False

    def remove_node(self, node_id: int) -> None:
        """Take a node off the fabric, as a decommission does."""
        self.nodes.pop(node_id, None)
        self.attributes.pop(node_id, None)

    @property
    def write_count(self) -> int:
        """Return how many writes have been attempted, which a refusal test asserts is zero."""
        return len(self.writes)


def _captured() -> list[dict[str, Any]]:
    """Return the 19 nodes the M1 capture recorded, exactly as the fabric reported them."""
    nodes: list[dict[str, Any]] = json.loads(FIXTURE.read_text())["data"]["devices"]
    return nodes


def build_fabric_from_fixture() -> FakeMatterClient:
    """Return a fabric holding Jayant's Matter network as the M1 capture found it.

    Every attribute value here came off a real device. The Binding lists are empty because
    they really are empty: nothing on this fabric has ever been bound.
    """
    client = FakeMatterClient()
    for captured in deepcopy(_captured()):
        node_id = int(captured["node_id"])
        client.nodes[node_id] = FakeNode(
            node_id=node_id,
            available=bool(captured["available"]),
            name=captured.get("name") or None,
            device_info=FakeDeviceInfo(
                vendorName=captured.get("vendor"), productName=captured.get("product")
            ),
            endpoints={int(endpoint): object() for endpoint in captured["endpoints"]},
        )
        held: dict[str, Any] = {}
        for endpoint, clusters in captured["endpoints"].items():
            number = int(endpoint)
            held[mp.client_list_path(number)] = clusters["client_list"]
            held[mp.server_list_path(number)] = clusters["server_list"]
            if mp.BINDING_CLUSTER in clusters["server_list"]:
                held[mp.binding_path(number)] = captured["bindings"].get(endpoint, [])
        held[mp.ACL_PATH] = captured["acl"]
        capacity = captured["acl_capacity"]
        held[mp.ACL_ENTRIES_PER_FABRIC_PATH] = capacity["entries_per_fabric"]
        held[mp.ACL_SUBJECTS_PER_ENTRY_PATH] = capacity["subjects_per_entry"]
        held[mp.ACL_TARGETS_PER_ENTRY_PATH] = capacity["targets_per_entry"]
        client.attributes[node_id] = held
    return client
