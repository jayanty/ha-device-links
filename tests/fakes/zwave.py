"""Fake Z-Wave driver objects, built from the Stage 0 capture of Jayant's real network.

These fakes are the contract with `zwave-js-server-python` 0.73.0. Everything in Phase 1B
and much of Phase 1C is tested against them rather than against real hardware, so a fake
that is more permissive or more convenient than the library makes every test built on it
prove less than it appears to. Three rules follow from that:

1. **Use the real classes wherever they are usable.** `AssociationAddress`,
   `AssociationGroup`, `SetValueResult`, `EventBase`, the `AssociationCheckResult`,
   `NodeStatus`, `Protocols`, `SecurityClass` and `CommandClass` enums and the
   `FailedZWaveCommand` / `NotFoundError` exceptions all come from the library, so their
   shapes cannot drift away from it. Only `Driver`, `Controller`, `Node` and the value
   objects are faked, because those need a live WebSocket client to exist at all.
2. **Reproduce the surprises.** The two association reads sit at different nesting depths:
   `get_all_association_groups` gives `{endpoint: {group: AssociationGroup}}` and
   `get_all_associations` gives `{node: {endpoint: {group: [address]}}}`, one level deeper.
   Reading the second at the first's depth returns plausible-looking empty groups rather
   than an error, which is a bug that hides; Stage 0 hit exactly that. Both depths are
   reproduced here so the adapter is written against the shape it will really meet.
3. **Refuse what the hardware refuses.** Group capacity is enforced, self-association and
   Long Range and security-class refusals come back from the check, and a refused batch
   leaves the group exactly as it was.

Where the fake deliberately differs from the library, it says so at the method.

Data comes from `tests/fixtures/z2_associations.json` (the Stage 0 Z2 capture) plus the
shipped profile database, which is what decides which configuration parameters each model
exposes. Nothing here reaches the network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
import json
from pathlib import Path
from typing import Final

from zwave_js_server.const import (
    AssociationCheckResult,
    CommandClass,
    NodeStatus,
    Protocols,
    SecurityClass,
    SetValueStatus,
)
from zwave_js_server.event import EventBase
from zwave_js_server.exceptions import FailedZWaveCommand, NotFoundError
from zwave_js_server.model.association import AssociationAddress, AssociationGroup
from zwave_js_server.model.value import SetValueResult

from custom_components.device_links.backends.zwave import INDICATION_PROPERTY_BINARY
from custom_components.device_links.models import ZWaveFingerprint
from tests.factories import HOME_ID, profiles

FIXTURE: Final = Path(__file__).resolve().parent.parent / "fixtures" / "z2_associations.json"

# Every node in the capture is on the root endpoint, which is the only endpoint this
# network uses. Keeping it named makes the endpoint level of the shapes below readable.
ROOT_ENDPOINT: Final = 0

# The S2 classes, which are the ones that constrain what a source may associate with.
S2_CLASSES: Final = frozenset(
    {
        SecurityClass.S2_UNAUTHENTICATED,
        SecurityClass.S2_AUTHENTICATED,
        SecurityClass.S2_ACCESS_CONTROL,
    }
)

# The group `emit_association_changed` reports a change on when the caller does not care
# which group changed. Group 2 exists on every model in the capture; group 1 is the
# lifeline and naming it would read as a lifeline edit.
DEFAULT_CHANGED_GROUP: Final = 2


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """One node exactly as the Stage 0 capture recorded it."""

    node_id: int
    name: str
    label: str
    manufacturer: str
    manufacturer_id: int
    product_type: int
    product_id: int
    firmware_version: str
    protocol: int
    is_listening: bool
    highest_security_class: int
    groups: Mapping[int, Mapping[int, AssociationGroup]]
    associations: Mapping[int, Mapping[int, tuple[tuple[int, int | None], ...]]]


@dataclass(slots=True)
class FakeValue:
    """One node value, carrying the surface the adapter reads off a real `Value`.

    Faked rather than real because `zwave_js_server.model.value.Value` needs a real `Node`
    and a full `ValueDataType` dict from the server. `value_id` reproduces the real format
    (`node-cc-endpoint-property[-propertyKey]`) so an adapter that addresses a value by id
    is exercised against the string it will really build.
    """

    node_id: int
    command_class: int
    property_: int | str
    property_key: int | str | None
    endpoint: int
    value: int | list[int] | None

    @property
    def value_id(self) -> str:
        """Return the value id, in the format `zwave_js_server.model.value` builds."""
        value_id = f"{self.node_id}-{self.command_class}-{self.endpoint}-{self.property_}"
        if self.property_key is not None:
            value_id += f"-{self.property_key}"
        return value_id


class FakeNode(EventBase):
    """A Z-Wave node, with the attributes the adapter reads and the events it listens to.

    Inherits the library's own `EventBase`, so `on`, `once` and `emit` behave exactly as
    they do on a real `Node` and an unsubscribe that does not unsubscribe would show up
    here rather than in production.
    """

    def __init__(self, controller: FakeController, spec: NodeSpec) -> None:
        """Build a node from its captured spec, attached to the controller that owns it."""
        super().__init__()
        self.controller = controller
        self.node_id = spec.node_id
        self.name = spec.name
        self.label = spec.label
        self.manufacturer = spec.manufacturer
        self.manufacturer_id = spec.manufacturer_id
        self.product_type = spec.product_type
        self.product_id = spec.product_id
        self.firmware_version = spec.firmware_version
        self.protocol = spec.protocol
        self.is_listening = spec.is_listening
        self.highest_security_class = spec.highest_security_class
        # Status is its own attribute, as it is on a real node, rather than derived from
        # `is_listening`: the two are independent there (a listening node can be dead), and
        # a test that needs a dead or awake node sets this without the fake fighting it.
        # In the capture the only sleeper is node 40, the ZEN37 battery remote, which is
        # the subject of every pending_wakeup test.
        self.status = NodeStatus.ALIVE if spec.is_listening else NodeStatus.ASLEEP
        self.values: dict[str, FakeValue] = {
            value.value_id: value
            for value in (*_config_values_for(spec), *_indicator_values_for(spec))
        }

    def get_configuration_values(self) -> dict[str, FakeValue]:
        """Return this node's configuration values, as the real `Node` method does."""
        return {
            value_id: value
            for value_id, value in self.values.items()
            if value.command_class == CommandClass.CONFIGURATION
        }

    async def async_refresh_cc_values(self, command_class: CommandClass) -> None:
        """Ask the device to re-report a command class, and return before it has.

        Fire and forget, exactly as the real method is: it sends with
        `wait_for_result=False`, so it returns before the device has answered and a read
        issued immediately afterwards gets the same cache it would have got anyway. Stage 0
        measured this at 0 ms. Deep verify has to wait for the answer, not for this call.
        """
        self.controller.note_refresh(self, command_class)

    async def async_set_value(
        self,
        val: FakeValue | str,
        new_value: int,
        options: Mapping[str, int] | None = None,
        wait_for_result: bool | None = None,
    ) -> SetValueResult:
        """Write one value and report success, mirroring the real `Node.async_set_value`.

        A real write can also come back `NO_DEVICE_SUPPORT`, `FAIL` or `INVALID_VALUE`;
        this fake always succeeds unless `FakeController.raise_on_write` is set, which
        makes this raise the way a transport failure would. The value is updated in place,
        so the read-back PRD Section 8.4 requires sees the new value.

        `options` and `wait_for_result` are accepted and ignored, so the call site matches
        the real signature rather than a narrowed one.
        """
        value = self._resolve(val)
        if self.controller.raise_on_write is not None:
            raise self.controller.raise_on_write
        self.controller.note_parameter_write(value, new_value)
        value.value = new_value
        return SetValueResult({"status": SetValueStatus.SUCCESS})

    def _resolve(self, val: FakeValue | str) -> FakeValue:
        """Return the value a caller named, by object or by value id."""
        if isinstance(val, str):
            if val not in self.values:
                raise NotFoundError(f"node {self.node_id} has no value {val}")
            return self.values[val]
        return val


class FakeController(EventBase):
    """The Z-Wave controller: the node list, the association state, and the write path.

    The association state is real state, so an add is visible on the next read (Stage 0
    confirmed the driver cache reflects our own writes immediately) and a remove really
    removes. Capacity is enforced from the captured `max_nodes`, because a fake that
    accepted a sixth entry into a five-slot ZEN37 group would make every capacity test
    vacuous.

    The public attributes below the node list are test hooks. They exist so a test can
    describe a network condition without patching anything.
    """

    def __init__(self, home_id: int) -> None:
        """Build an empty controller. `build_driver_from_fixture` populates it."""
        super().__init__()
        self.home_id = home_id
        self.nodes: dict[int, FakeNode] = {}

        # node id -> endpoint -> group id -> group
        self._groups: dict[int, dict[int, dict[int, AssociationGroup]]] = {}
        # node id -> endpoint -> group id -> addresses
        self._associations: dict[int, dict[int, dict[int, list[AssociationAddress]]]] = {}

        # How many association add or remove calls reached the radio, redundant ones
        # included. A test asserts this does not move when the adapter should have refused
        # before writing. Parameter writes are counted separately, in written_parameters.
        self.write_count = 0
        # The keyword arguments of the last add and the last remove, so a test can prove
        # `force` was never passed (CLAUDE.md Section 3 rule 6).
        self.last_add_options: dict[str, object] = {}
        self.last_remove_options: dict[str, object] = {}
        # Set to an exception to make every write fail, association or parameter, for
        # the E13 path.
        self.raise_on_write: Exception | None = None
        # Set to an int to make every check return it, including a value no current driver
        # returns, so an adapter can be shown to fail closed on one.
        self.force_check_result: int | None = None
        # Node ids that are on the network and will not answer a read. A node that has been
        # excluded leaves `nodes` entirely; this is the other state, and the one nothing
        # could reproduce before: listed, and silent. It is what an unreachable device
        # really looks like to the coordinator (E1), and it is what a swap onto a device
        # that stopped answering has to be tested against.
        self.unreadable: set[int] = set()

        # How many times a CC value refresh was asked for.
        self.refresh_count = 0
        # How long the device takes to answer a refresh.
        self.refresh_delay_seconds = 0.0
        # `(node id, group, target node id)`: something that is on the device but not in
        # the cache, which lands when a refresh for that node lands.
        self.stale_group: tuple[int, int, int] | None = None
        # A device that never answers a refresh, so a bounded wait can be shown to give up.
        self.refresh_never_lands = False
        # parameter -> the (bitmask, value) pairs written to it. Keyed by parameter so a
        # test can say `19 not in written_parameters` (Decision D4).
        self.written_parameters: dict[int, list[tuple[int | None, int]]] = {}
        # Every Indicator CC write, in order, as `(indicator id, value)`. What a test about
        # hybrid leg write hygiene counts: each of these is one radio frame.
        self.written_indicators: list[tuple[int, bool]] = []

        self._refresh_tasks: set[asyncio.Task[None]] = set()

    # Reads.

    async def async_get_all_association_groups(
        self, node: FakeNode
    ) -> dict[int, dict[int, AssociationGroup]]:
        """Return every association group of a node: `{endpoint: {group: group}}`.

        Two levels. The associations call below is three. See the module docstring.
        """
        self._require_answering(node.node_id)
        return self.get_all_association_groups_sync(node.node_id)

    async def async_get_all_associations(
        self, node: FakeNode
    ) -> dict[int, dict[int, dict[int, list[AssociationAddress]]]]:
        """Return every association of a node: `{node: {endpoint: {group: [address]}}}`.

        Three levels, one deeper than the groups call. Reading this at the groups call's
        depth yields plausible empty groups instead of an error.
        """
        self._require_answering(node.node_id)
        return self.get_all_associations_sync(node.node_id)

    def _require_answering(self, node_id: int) -> None:
        """Raise the way a node that is on the network and silent makes a read raise."""
        if node_id in self.unreadable:
            raise FailedZWaveCommand(
                "controller.get_all_association_groups",
                201,
                f"node {node_id} did not respond",
            )

    async def async_get_association_groups(
        self, source: AssociationAddress
    ) -> dict[int, AssociationGroup]:
        """Return one source endpoint's groups, keyed by group id."""
        return dict(self._groups_of(source.node_id)[_endpoint_of(source)])

    async def async_get_associations(
        self, source: AssociationAddress
    ) -> dict[int, list[AssociationAddress]]:
        """Return one source endpoint's associations, keyed by group id."""
        return {
            group_id: list(addresses)
            for group_id, addresses in self._associations_of(source.node_id)[
                _endpoint_of(source)
            ].items()
        }

    def get_all_association_groups_sync(
        self, node_id: int
    ) -> dict[int, dict[int, AssociationGroup]]:
        """Return the group dump without awaiting, for inspection from a test."""
        return {endpoint: dict(groups) for endpoint, groups in self._groups_of(node_id).items()}

    def get_all_associations_sync(
        self, node_id: int
    ) -> dict[int, dict[int, dict[int, list[AssociationAddress]]]]:
        """Return the association dump without awaiting, at the real three-level depth."""
        return {
            node_id: {
                endpoint: {group_id: list(addresses) for group_id, addresses in groups.items()}
                for endpoint, groups in self._associations_of(node_id).items()
            }
        }

    # The check.

    async def async_check_association(
        self, source: AssociationAddress, group: int, association: AssociationAddress
    ) -> int:
        """Say whether this association may be written, as the driver would.

        Modelled on the driver's own order: self-association, then Long Range at either
        end, then the source's security class. An S2 source may only reach a node that was
        granted the same class, which is why node 21 (the only S2 node in the capture) is
        refused when it reaches an unsecured node. Security is modelled rather than merely
        forced because an adapter whose E9 and E34 handling is only ever reached through
        `force_check_result` has not been shown to handle a refusal the network can
        actually produce.

        Not modelled: `FORBIDDEN_NO_SUPPORTED_CCS`, which needs the target's command class
        list, and the S0 rules, which this network has no node for. Reach those through
        `force_check_result`.

        Returns `int` rather than `AssociationCheckResult` on purpose, so
        `force_check_result` can return a value the enum does not have. A future driver
        could add one, and an adapter must fail closed on it rather than read it as
        permission; the real library would raise on constructing that enum member, so this
        is the one place the fake is deliberately wider than the library.
        """
        if self.force_check_result is not None:
            return self.force_check_result
        if source.node_id == association.node_id:
            return AssociationCheckResult.FORBIDDEN_SELF_ASSOCIATION
        if self._is_long_range(source.node_id):
            return AssociationCheckResult.FORBIDDEN_SOURCE_IS_LONG_RANGE
        if self._is_long_range(association.node_id):
            return AssociationCheckResult.FORBIDDEN_DESTINATION_IS_LONG_RANGE
        return self._security_check(source.node_id, association.node_id)

    def _is_long_range(self, node_id: int) -> bool:
        """Say whether a node joined over Long Range, which fixes it out of associations."""
        node = self.nodes.get(node_id)
        return node is not None and node.protocol == Protocols.ZWAVE_LONG_RANGE

    def _security_check(self, source_id: int, target_id: int) -> int:
        """Return the check result the source's security class implies."""
        source = self.nodes.get(source_id)
        target = self.nodes.get(target_id)
        if source is None or target is None:
            return AssociationCheckResult.OK
        if source.highest_security_class not in S2_CLASSES:
            return AssociationCheckResult.OK
        if target.highest_security_class < source.highest_security_class:
            return AssociationCheckResult.FORBIDDEN_DESTINATION_SECURITY_CLASS_NOT_GRANTED
        return AssociationCheckResult.OK

    # Writes.

    async def async_add_associations(
        self,
        source: AssociationAddress,
        group: int,
        associations: list[AssociationAddress],
        wait_for_result: bool = False,
        **options: object,
    ) -> None:
        """Add associations to a group, refusing to exceed its capacity.

        `**options` is a deliberate widening: the real 0.73.0 signature has no `force`, so
        passing one would raise `TypeError` there and the guard test would fail on an
        unrelated error instead of on the thing it guards. Accepting and recording it lets
        `last_add_options` show a violation for what it is.

        A write to a sleeping node is applied immediately here, the same as to a listening
        one. On real hardware it is queued until the device wakes, which Stage 0 item Z4
        was never approved to measure: see docs/open-items.md J1 and issue #5. Nothing that
        passes against this fake is evidence about that path.
        """
        self._note_write(self.last_add_options, wait_for_result, options)
        current = self._group_state(source, group)
        room = self._capacity_of(source, group) - len(current)
        additions = [address for address in associations if not _contains(current, address)]
        if len(additions) > room:
            # Refused whole, never half applied: a partial add would make the adapter's
            # read-back agree with a write that did not entirely happen.
            raise FailedZWaveCommand(
                "controller.add_associations",
                100,
                f"node {source.node_id} association group {group} is at capacity: "
                f"{len(current)} of {self._capacity_of(source, group)} slots used and "
                f"{len(additions)} more requested",
            )
        current.extend(additions)

    async def async_remove_associations(
        self,
        source: AssociationAddress,
        group: int,
        associations: list[AssociationAddress],
        wait_for_result: bool = False,
        **options: object,
    ) -> None:
        """Remove associations from a group. Removing what is not there is a no-op."""
        self._note_write(self.last_remove_options, wait_for_result, options)
        current = self._group_state(source, group)
        removals = {(address.node_id, address.endpoint) for address in associations}
        current[:] = [
            address for address in current if (address.node_id, address.endpoint) not in removals
        ]

    def _note_write(
        self,
        recorded: dict[str, object],
        wait_for_result: bool,
        options: Mapping[str, object],
    ) -> None:
        """Count a write that reached the radio and record how it was called."""
        self.write_count += 1
        recorded.clear()
        recorded.update({"wait_for_result": wait_for_result, **options})
        if self.raise_on_write is not None:
            raise self.raise_on_write

    def _group_state(self, source: AssociationAddress, group: int) -> list[AssociationAddress]:
        """Return the mutable list of addresses in one group of one source endpoint."""
        groups = self._associations_of(source.node_id)[_endpoint_of(source)]
        if group not in groups:
            raise NotFoundError(f"node {source.node_id} has no association group {group}")
        return groups[group]

    def _capacity_of(self, source: AssociationAddress, group: int) -> int:
        """Return how many entries a group holds, as the device reported it."""
        return self._groups_of(source.node_id)[_endpoint_of(source)][group].max_nodes

    # Refresh, and the events a landed refresh produces.

    def note_refresh(self, node: FakeNode, command_class: CommandClass) -> None:
        """Record a refresh request and schedule the device's answer, or never answer."""
        self.refresh_count += 1
        if self.refresh_never_lands:
            return
        task = asyncio.get_running_loop().create_task(self._land_refresh(node, command_class))
        self._refresh_tasks.add(task)
        task.add_done_callback(self._refresh_tasks.discard)

    async def _land_refresh(self, node: FakeNode, command_class: CommandClass) -> None:
        """Deliver what the device really has, after however long it takes to answer."""
        await asyncio.sleep(self.refresh_delay_seconds)
        group = DEFAULT_CHANGED_GROUP
        stale = self.stale_group
        if stale is not None and stale[0] == node.node_id:
            node_id, group, target_id = stale
            self.stale_group = None
            self._group_state(AssociationAddress(self, node_id=node_id), group).append(
                AssociationAddress(self, node_id=target_id)
            )
        self.emit_association_changed(node.node_id, group=group, command_class=command_class)

    # Test hooks that stand in for the network doing something on its own.

    def emit_association_changed(
        self,
        node_id: int,
        group: int = DEFAULT_CHANGED_GROUP,
        command_class: CommandClass = CommandClass.ASSOCIATION,
        endpoint: int = ROOT_ENDPOINT,
    ) -> None:
        """Announce that a node's associations changed, as a value updated event.

        This is how drift reaches the integration without polling (FR-B3). Whether a real
        driver emits one for a change made outside Home Assistant is Stage 0 item Z5,
        which was never run: see docs/open-items.md J4 and issue #8. A real refresh may
        also stay silent when nothing changed, which was not measured either, so an
        adapter that waits only for this event may wait out its timeout on real hardware
        where nothing was stale.
        """
        node = self.nodes[node_id]
        present = self._associations_of(node_id).get(endpoint, {}).get(group, [])
        value = FakeValue(
            node_id=node_id,
            command_class=command_class,
            property_="nodeIds",
            property_key=group,
            endpoint=endpoint,
            value=[address.node_id for address in present],
        )
        node.values[value.value_id] = value
        node.emit(
            "value updated",
            {
                "source": "node",
                "event": "value updated",
                "nodeId": node_id,
                "node": node,
                "value": value,
            },
        )

    def note_parameter_write(self, value: FakeValue, new_value: int) -> None:
        """Record a configuration parameter write, keyed by parameter.

        Keyed by parameter rather than by value id so a test can assert that a parameter
        was never touched: `19 not in written_parameters` is Decision D4 in one line.

        Indicator writes are counted separately and not here, because they are the other
        half of the same Stage 0 finding: an indicator set does not touch device NVM and a
        configuration write does, so a test about hybrid leg write hygiene has to be able
        to count the frames without the count meaning "this many flash writes".
        """
        if value.command_class == CommandClass.INDICATOR:
            self.written_indicators.append((int(value.property_), bool(new_value)))
            return
        if value.command_class != CommandClass.CONFIGURATION:
            return
        parameter = int(value.property_)
        bitmask = None if value.property_key is None else int(value.property_key)
        self.written_parameters.setdefault(parameter, []).append((bitmask, new_value))

    def add_long_range_node(self, node_id: int) -> FakeNode:
        """Add a Long Range node, which the capture has none of.

        The whole network is classic Z-Wave today, so without this the LR refusal in
        `async_check_association` could never be reached and the D13 guard could not be
        tested against the fake at all.
        """
        template = _node_specs()[36]
        spec = NodeSpec(
            node_id=node_id,
            name=f"Long Range Node {node_id}",
            label=template.label,
            manufacturer=template.manufacturer,
            manufacturer_id=template.manufacturer_id,
            product_type=template.product_type,
            product_id=template.product_id,
            firmware_version=template.firmware_version,
            protocol=Protocols.ZWAVE_LONG_RANGE,
            is_listening=True,
            highest_security_class=SecurityClass.S2_AUTHENTICATED,
            groups=template.groups,
            associations=template.associations,
        )
        self.install(spec)
        return self.nodes[node_id]

    # Construction.

    def install(self, spec: NodeSpec) -> None:
        """Add one node and its association state to this controller."""
        self.nodes[spec.node_id] = FakeNode(self, spec)
        self._groups[spec.node_id] = {
            endpoint: dict(groups) for endpoint, groups in spec.groups.items()
        }
        self._associations[spec.node_id] = {
            endpoint: {
                group_id: [
                    AssociationAddress(self, node_id=node_id, endpoint=address_endpoint)
                    for node_id, address_endpoint in addresses
                ]
                for group_id, addresses in groups.items()
            }
            for endpoint, groups in spec.associations.items()
        }

    def _groups_of(self, node_id: int) -> dict[int, dict[int, AssociationGroup]]:
        """Return a node's groups, or say the node is unknown rather than return nothing."""
        if node_id not in self._groups:
            raise NotFoundError(f"node {node_id} is not on this network")
        return self._groups[node_id]

    def _associations_of(self, node_id: int) -> dict[int, dict[int, list[AssociationAddress]]]:
        """Return a node's association state, or say the node is unknown."""
        if node_id not in self._associations:
            raise NotFoundError(f"node {node_id} is not on this network")
        return self._associations[node_id]


@dataclass(slots=True)
class FakeDriver:
    """The driver object the adapter is handed, which is a controller and nothing else."""

    controller: FakeController = field(default_factory=lambda: FakeController(int(HOME_ID)))


def build_driver_from_fixture() -> FakeDriver:
    """Return a driver holding every node of the Stage 0 capture, in its captured state."""
    driver = FakeDriver()
    for spec in _node_specs().values():
        driver.controller.install(spec)
    return driver


def _endpoint_of(source: AssociationAddress) -> int:
    """Return the endpoint an address names, treating an unset endpoint as the root."""
    return ROOT_ENDPOINT if source.endpoint is None else source.endpoint


def _contains(addresses: Sequence[AssociationAddress], address: AssociationAddress) -> bool:
    """Say whether this exact node and endpoint is already in the group."""
    return any(
        (existing.node_id, existing.endpoint) == (address.node_id, address.endpoint)
        for existing in addresses
    )


def _config_values_for(spec: NodeSpec) -> list[FakeValue]:
    """Return the configuration values this model exposes, per the profile database.

    The capture recorded associations, not parameters, so the parameters come from the
    curated entry for the model: exactly the ones an adapter will look for, plus the ones
    it must be shown never to touch (Decision D4's parameter 19 on the ZEN35). They all
    start at 0, which is what parameter 59 bit 2 read at capture time.
    """
    entry = profiles().lookup(
        ZWaveFingerprint(
            manufacturer_id=spec.manufacturer_id,
            product_type=spec.product_type,
            product_id=spec.product_id,
            firmware=spec.firmware_version,
        )
    )
    if entry is None:
        return []
    seen: set[tuple[int, int | None]] = set()
    values: list[FakeValue] = []
    for adapter in entry.settings.values():
        key = (adapter.parameter, adapter.bitmask)
        if key in seen:
            continue
        seen.add(key)
        values.append(
            FakeValue(
                node_id=spec.node_id,
                command_class=CommandClass.CONFIGURATION,
                property_=adapter.parameter,
                property_key=adapter.bitmask,
                endpoint=ROOT_ENDPOINT,
                value=0,
            )
        )
    return values


def _indicator_values_for(spec: NodeSpec) -> list[FakeValue]:
    """Return the per-button indicator values this model reports, per the curated entry.

    The Z8 capture found these on node 36: one writeable Indicator CC value per button,
    ids 67 to 71 on property 2, all reading false. They are here rather than in the
    association capture because the association capture did not record node values at all,
    and the entry is the only place that says which id belongs to which button.
    """
    entry = profiles().lookup(
        ZWaveFingerprint(
            manufacturer_id=spec.manufacturer_id,
            product_type=spec.product_type,
            product_id=spec.product_id,
            firmware=spec.firmware_version,
        )
    )
    if entry is None:
        return []
    return [
        FakeValue(
            node_id=spec.node_id,
            command_class=CommandClass.INDICATOR,
            property_=emitter.indicator_id,
            property_key=INDICATION_PROPERTY_BINARY,
            endpoint=ROOT_ENDPOINT,
            value=0,
        )
        for emitter in entry.emitters
        if emitter.indicator_id is not None
    ]


@cache
def _node_specs() -> dict[int, NodeSpec]:
    """Parse the Stage 0 capture into node specs, once for the whole test session."""
    data = json.loads(FIXTURE.read_text())["data"]
    specs: dict[int, NodeSpec] = {}
    for node in data["nodes"]:
        fingerprint = node["fingerprint"]
        specs[node["node_id"]] = NodeSpec(
            node_id=node["node_id"],
            name=node["name"],
            label=node["label"],
            manufacturer=node["manufacturer"],
            manufacturer_id=fingerprint["manufacturer_id"],
            product_type=fingerprint["product_type"],
            product_id=fingerprint["product_id"],
            firmware_version=fingerprint["firmware_version"],
            protocol=node["protocol"],
            is_listening=node["is_listening"],
            highest_security_class=node["highest_security_class"],
            groups=_groups_of_node(node["association_groups"]),
            associations=_associations_of_node(node["associations"]),
        )
    return specs


def _groups_of_node(
    captured: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> dict[int, dict[int, AssociationGroup]]:
    """Return `{endpoint: {group: AssociationGroup}}`, built with the library's own class.

    Integer keys and integer command class keys, because that is what
    `Controller.async_get_all_association_groups` produces from the wire's string keys.
    """
    return {
        int(endpoint): {
            int(group_id): AssociationGroup(
                max_nodes=int(group["max_nodes"]),  # type: ignore[arg-type]
                is_lifeline=bool(group["is_lifeline"]),
                multi_channel=bool(group["multi_channel"]),
                label=str(group["label"]),
                profile=group["profile"],  # type: ignore[arg-type]
                issued_commands={
                    int(command_class): list(commands)
                    for command_class, commands in group["issued_commands"].items()  # type: ignore[union-attr]
                },
            )
            for group_id, group in groups.items()
        }
        for endpoint, groups in captured.items()
    }


def _associations_of_node(
    captured: Mapping[str, Mapping[str, Sequence[Mapping[str, int | None]]]],
) -> dict[int, dict[int, tuple[tuple[int, int | None], ...]]]:
    """Return `{endpoint: {group: ((node id, endpoint), ...)}}` from the capture.

    Addresses are kept as plain tuples here and turned into real `AssociationAddress`
    objects when a controller installs them, because the real class needs the controller
    as its first positional argument and the specs are parsed before one exists.
    """
    return {
        int(endpoint): {
            int(group_id): tuple(
                (int(address["node_id"] or 0), address["endpoint"]) for address in addresses
            )
            for group_id, addresses in groups.items()
        }
        for endpoint, groups in captured.items()
    }
