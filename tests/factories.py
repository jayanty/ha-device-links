"""Test data builders shared across the pure-core test modules.

Every test needs a `DeviceHandle` and almost none of them care what is in it, so building
one here keeps the interesting part of each test visible. `capabilities_for` goes further:
it builds capabilities the same way the Z-Wave adapter will, from the association-group
dump `tests/fixtures/z2_associations.json` captured off Jayant's real network merged with
the shipped profile database, so a compiler or planner test is exercised against the
hardware this is being built for rather than against invented data.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
import json
from pathlib import Path
from typing import Any, Final

from custom_components.device_links.backends.zigbee_protocol import Device as ZigbeeDevice
from custom_components.device_links.backends.zigbee_protocol import handle_of as zigbee_handle_of
from custom_components.device_links.backends.zwave_protocol import (
    AssociationGroup,
    resolve_emitters,
)
from custom_components.device_links.models import (
    Backend,
    DeviceCapabilities,
    DeviceHandle,
    Emitter,
    Feature,
    Link,
    LinkTarget,
    ObservedLink,
    ZWaveFingerprint,
)
from custom_components.device_links.profile_db import ProfileDatabase, load_profiles

FIXTURE = Path(__file__).parent / "fixtures" / "z2_associations.json"
PROFILES_DIR = Path(__file__).parent.parent / "custom_components" / "device_links" / "profiles_db"

# The home id every fixture node is on, so two handles differ only by node id.
HOME_ID = "3538613642"

# Node 36's real fingerprint, kept as a named constant because it is the model most of the
# pure-core tests are written against.
ZEN35_FINGERPRINT = ZWaveFingerprint(
    manufacturer_id=634, product_type=28672, product_id=40984, firmware="1.40.0"
)

# Node 13, "Ceiling Lights Old", the swap fixture PRD scenario S7 is written around. It is
# not in the Z2 capture and never could be: it was already dead and had been replaced by
# node 42 before Stage 0 ran, which is exactly what makes it the real artifact to test
# against. What is known about it is what PRD Section 3.1 recorded, an Inovelli VZW31-SN.
# Inovelli's manufacturer id is from the capture; the product type and id are not, because
# nothing on this network can be asked for them any more, so they are named here as unknown
# rather than invented into a fixture that would look captured. Nothing in the swap depends
# on the values: what matters is that they differ from node 42's VZW32-SN (798, 23, 1),
# which is what makes this a different-model swap.
UNKNOWN_PRODUCT: Final = 0
CEILING_LIGHTS_OLD = 13
CEILING_LIGHTS_OLD_FINGERPRINT = ZWaveFingerprint(
    manufacturer_id=798,
    product_type=UNKNOWN_PRODUCT,
    product_id=UNKNOWN_PRODUCT,
    firmware="1.0.0",
)

# A fingerprint no shipped profile entry claims, so a test can exercise the path where the
# curated database says nothing and only the generic derivation is available.
UNCURATED_FINGERPRINT = ZWaveFingerprint(
    manufacturer_id=1, product_type=1, product_id=1, firmware="0.0.1"
)

# The node id the factory gives that uncurated model, so `handle` and `capabilities_for`
# agree about it without either having to be told twice.
UNCURATED_NODE_ID: Final = 99

# Long Range nodes start here (CLAUDE.md Section 10). The protocol is fixed at inclusion, so
# a node id is enough to know, and both `handle` and `capabilities_for` derive it the same way.
FIRST_LONG_RANGE_NODE_ID: Final = 256

# Every device in these tests is a dimmer as far as receiving goes, which is what the
# fixture's targets (the Inovelli VZW32-SN load switches) really are.
RECEIVABLE: Final = frozenset({Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD})


@dataclass(frozen=True, slots=True)
class _NodeSpec:
    """What the factory knows about one node id: its model and its group layout."""

    fingerprint: ZWaveFingerprint
    groups: dict[str, AssociationGroup]
    name: str

    @property
    def is_uncurated(self) -> bool:
        """Say whether no shipped profile entry describes this model."""
        return self.fingerprint == UNCURATED_FINGERPRINT


@cache
def _fixture_nodes() -> dict[int, _NodeSpec]:
    """Return the real nodes from the Stage 0 capture, keyed by node id."""
    data = json.loads(FIXTURE.read_text())["data"]
    nodes: dict[int, _NodeSpec] = {}
    for node in data["nodes"]:
        fingerprint = node["fingerprint"]
        nodes[node["node_id"]] = _NodeSpec(
            fingerprint=ZWaveFingerprint(
                manufacturer_id=fingerprint["manufacturer_id"],
                product_type=fingerprint["product_type"],
                product_id=fingerprint["product_id"],
                firmware=fingerprint["firmware_version"],
            ),
            groups=node["association_groups"]["0"],
            name=node["name"],
        )
    return nodes


@cache
def profiles() -> ProfileDatabase:
    """Return the shipped profile database, loaded once for the whole test session."""
    return load_profiles(
        {
            path.name: path.read_text()
            for path in PROFILES_DIR.glob("*.json")
            if path.name != "schema.json"
        }
    )


def _spec(node_id: int) -> _NodeSpec:
    """Return the model a node id stands for.

    Fixture nodes are themselves. Node 99 is the model the curated database says nothing
    about. Every other node id is a ZEN35 with a ZEN35's groups, which is enough for a node
    that only ever appears as a link target.
    """
    known = _fixture_nodes()
    if node_id in known:
        return known[node_id]
    zen35 = known[36]
    if node_id == CEILING_LIGHTS_OLD:
        # A dead node keeps the group layout its model had, which is the VZW32-SN's: the
        # two are the same generation of the same Inovelli switch. Nothing reads these,
        # because the device is gone; they are here so a handle for it can be built at all.
        return _NodeSpec(
            fingerprint=CEILING_LIGHTS_OLD_FINGERPRINT,
            groups=known[42].groups,
            name="Ceiling Lights Old",
        )
    if node_id == UNCURATED_NODE_ID:
        return _NodeSpec(
            fingerprint=UNCURATED_FINGERPRINT, groups=zen35.groups, name="Uncurated Model"
        )
    return _NodeSpec(fingerprint=zen35.fingerprint, groups=zen35.groups, name=f"Node {node_id}")


def _is_long_range(node_id: int) -> bool:
    """Say whether this node joined over Long Range, which fixes it out of associations."""
    return node_id >= FIRST_LONG_RANGE_NODE_ID


def handle(
    node_id: int = 36,
    *,
    name: str | None = None,
    long_range: bool = False,
    unknown_model: bool = False,
) -> DeviceHandle:
    """Return a Z-Wave device handle for a node, identified by its protocol address.

    `long_range` and `unknown_model` are declarations, not switches: they say at the call
    site what is interesting about the node so the test reads on its own, and the factory
    refuses a call that disagrees with the node the id names. Keeping one node table means
    `handle` and `capabilities_for` can never describe the same node differently.
    """
    spec = _spec(node_id)
    if long_range is not _is_long_range(node_id):
        raise ValueError(
            f"node {node_id} long_range is {_is_long_range(node_id)}, not {long_range}"
        )
    if unknown_model is not spec.is_uncurated:
        raise ValueError(
            f"node {node_id} unknown_model is {spec.is_uncurated}, not {unknown_model}"
        )
    return DeviceHandle(
        backend=Backend.ZWAVE,
        protocol_id=f"{HOME_ID}:{node_id}",
        ha_device_id="1f50c99924ffdc3f767cdcdb9f6b6294",
        fingerprint=spec.fingerprint,
        name_at_authoring=name or spec.name,
    )


def capabilities_for(*node_ids: int, multi_channel: bool = True) -> dict[str, DeviceCapabilities]:
    """Return capabilities for these nodes, keyed by identity as the compiler expects.

    Emitters are resolved exactly as the Z-Wave adapter will resolve them: the device's own
    association groups, overridden by a curated profile entry when one claims the model.
    `multi_channel=False` reports every group as node-only, which is how a device that
    cannot take an endpoint target looks.
    """
    database = profiles()
    capabilities: dict[str, DeviceCapabilities] = {}
    for node_id in node_ids:
        spec = _spec(node_id)
        device = handle(
            node_id, long_range=_is_long_range(node_id), unknown_model=spec.is_uncurated
        )
        entry = database.lookup(spec.fingerprint)
        capabilities[device.identity] = DeviceCapabilities(
            handle=device,
            emitters=(
                _emitters(node_id)
                if multi_channel
                else tuple(resolve_emitters(_without_multi_channel(spec), entry))
            ),
            receivable=RECEIVABLE,
            is_long_range=_is_long_range(node_id),
            settings=entry.settings if entry is not None else {},
        )
    return capabilities


@cache
def _emitters(node_id: int) -> tuple[Emitter, ...]:
    """Return a node's controls, resolved the way the Z-Wave adapter will resolve them."""
    spec = _spec(node_id)
    return tuple(resolve_emitters(spec.groups, profiles().lookup(spec.fingerprint)))


def _without_multi_channel(spec: _NodeSpec) -> dict[str, AssociationGroup]:
    """Return a node's groups as a device that cannot take an endpoint target reports them."""
    return {
        group_id: {**group, "multi_channel": False}  # type: ignore[typeddict-item]
        for group_id, group in spec.groups.items()
    }


def link(source_node: int, emitter_id: str, target_node: int, feature: Feature) -> Link:
    """Return one desired link, the unit the planner diffs.

    The association group is looked up from the source device's real emitters, so a control
    that spans several groups (the Inovelli paddle) puts the right one on the link. An
    emitter id no device offers falls back to the group the id itself names, which is how a
    test names the lifeline group without pretending it is a control.
    """
    emitter = next((e for e in _emitters(source_node) if e.emitter_id == emitter_id), None)
    return Link(
        backend=Backend.ZWAVE,
        source=handle(source_node, long_range=_is_long_range(source_node)),
        source_endpoint=0,
        emitter_id=emitter_id,
        target=LinkTarget(
            handle=handle(target_node, long_range=_is_long_range(target_node)), endpoint=None
        ),
        feature=feature,
        emitter_group="" if emitter is None else emitter.actions.get(feature, ""),
    )


def observed(desired: Link, *, rule_id: str | None, system: bool = False) -> ObservedLink:
    """Return the same link as read back from a device, with who owns it.

    `rule_id` is None for a link Device Links did not create, which is the state D9 protects.
    """
    kwargs: dict[str, Any] = desired.as_kwargs()
    kwargs["rule_id"] = rule_id
    return ObservedLink(**kwargs, is_system=system, managed_by=rule_id)


def group_capacities(node_id: int) -> dict[str, int]:
    """Return how many entries each association group of a node holds, group 1 included.

    The emitter model leaves the lifeline group out on purpose, because no control claims it.
    A radio does not: it knows how big group 1 is. A fake that simulates a device therefore
    needs the raw numbers rather than the capabilities view of them.
    """
    return {group_id: group["max_nodes"] for group_id, group in _spec(node_id).groups.items()}


# --------------------------------------------------------------------------------------
# Zigbee, from the Stage 0 G1 capture of the real bridge
# --------------------------------------------------------------------------------------

G1_FIXTURE = Path(__file__).parent / "fixtures" / "g1_bridge.json"

# The coordinator's masked IEEE address, which every binding on the network today targets.
COORDINATOR_IEEE = "<redacted:...fd4a>"

# The pair Stage 0 item G2 would have bound, confirmed unbound by the capture. Scenario S8
# is written against exactly these two, so they are named once here.
AUX_IEEE = "<redacted:...4340>"  # Entrance Inside Lights Aux, VZM31-SN, paddle on ep2
LIGHT_IEEE = "<redacted:...64ce>"  # Entrance Inside Lights, VZM32-SN, load on ep1
SECOND_LIGHT_IEEE = "<redacted:...f7f8>"  # Kitchen Lights, VZM31-SN, load on ep1
OLD_FIRMWARE_IEEE = "<redacted:...9536>"  # Hallway Side Lights, VZM31-SN sw 2.00, no ep3


@cache
def g1_bridge() -> dict[str, Any]:
    """Return the whole G1 capture payload, read once for the session."""
    data: dict[str, Any] = json.loads(G1_FIXTURE.read_text())["data"]
    return data


def zigbee_devices() -> dict[str, ZigbeeDevice]:
    """Return every device the bridge reported, keyed by IEEE address."""
    return {device["ieee_address"]: device for device in g1_bridge()["devices"]}


def zigbee_device(ieee: str) -> ZigbeeDevice:
    """Return one device from the capture by its IEEE address."""
    return zigbee_devices()[ieee]


def zigbee_handle(ieee: str) -> DeviceHandle:
    """Return the handle the Zigbee adapter would build for a captured device.

    Built through the adapter's own path rather than by hand, so a rule in a test names the
    device the same way `async_devices` does. A handle assembled independently could agree
    by luck and diverge the moment the real one changed.
    """
    return zigbee_handle_of(zigbee_device(ieee))


def zigbee_devices_of(model: str) -> list[ZigbeeDevice]:
    """Return every device in the capture whose converter matched this model."""
    return [
        device
        for device in zigbee_devices().values()
        if (device.get("definition") or {}).get("model") == model
    ]
