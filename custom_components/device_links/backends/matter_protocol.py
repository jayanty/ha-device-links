"""Pure Matter interpretation: what the fabric reports in, the capability model out.

The Matter half of what `zwave_protocol.py` and `zigbee_protocol.py` do for the other two
protocols. It reads the attribute values a Matter node reports, works out which endpoints
can drive something and which can be driven, turns Binding entries into links, and builds
the Access Control and Binding lists a write is made of.

It is pure: no Home Assistant import, no I/O, no clock. It is handed already-read attribute
values and returns value types, which is what lets it be tested directly against
`tests/fixtures/m1_matter.json`, the Stage 0 M1 capture of Jayant's real fabric.

Three things about Matter shape everything below, and all three come from that capture
rather than from the specification:

- **A client cluster is not a control.** Every one of the 19 nodes advertises client cluster
  41 on endpoint 0, which is the OTA Software Update Provider: firmware distribution, not a
  button. A capability model that treated any client cluster as an emitter would offer every
  sensor, lock and thermostat on the fabric as a usable remote. So this module works from an
  **allowlist** (`FEATURES_BY_CLUSTER`) rather than from a list of exclusions: a cluster that
  is not named there contributes nothing wherever it appears, which is why moving cluster 41
  to another endpoint on some future device would still offer nobody a firmware updater as a
  light switch. Endpoint 0 is excluded on top of that, because the root endpoint is the
  node's own administration and is never a control.
- **A control needs somewhere to put the binding.** An endpoint that drives OnOff but serves
  no Binding cluster cannot hold a link, so it is not offered as an emitter. That is what
  makes the Aqara H2 switch and the IKEA BILRESA button non-sources on this fabric (PRD
  Section 3.1 lists both; neither has a Binding cluster on any endpoint), and it is why the
  only real sources here are the two Inovelli VTM31-SN switches, on endpoint 2.
- **Access is a second table, on the other device.** A binding on the source says where to
  send; an Access Control entry on the **target** says who may send. Both have to be right,
  the ACL has to be right first (E27), and ACL headroom is 2 entries on the fixture's Eve
  Energy rather than a theoretical concern. `grant_for` merges into an existing entry when
  it can, and `GrantReceipt` is what makes the ordering structural rather than a matter of
  writing the two calls the right way round.

**Every write payload here is modelled, not observed.** No binding and no ACL entry has ever
been written on this fabric: Stage 0 M1 was read-only and Matter writes stay behind an
options flag that defaults to off (FR-B7, Decision D11). Everything from `acl_payload` down
comes from the Matter specification and from the shape the M1 read came back in. See
assumption A9 in `docs/open-items.md`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, TypedDict

from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceHandle,
    Emitter,
    Feature,
    MatterFingerprint,
)
from custom_components.device_links.profile_db import MatterProfileEmitter, MatterProfileEntry

# Cluster ids, as the Matter specification numbers them and as an attribute path spells
# them. Named here once because a bare 31 in a path is unreadable and a wrong one is a read
# of somebody else's cluster.
DESCRIPTOR_CLUSTER: Final = 29
DESCRIPTOR_SERVER_LIST: Final = 1
DESCRIPTOR_CLIENT_LIST: Final = 2

BINDING_CLUSTER: Final = 30
BINDING_ATTRIBUTE: Final = 0

ACCESS_CONTROL_CLUSTER: Final = 31
ACL_ATTRIBUTE: Final = 0
ACL_SUBJECTS_PER_ENTRY: Final = 2
ACL_TARGETS_PER_ENTRY: Final = 3
ACL_ENTRIES_PER_FABRIC: Final = 4

# The OTA Software Update Provider, which every node on this fabric advertises as a client
# on endpoint 0. Named for what it is so that a reader of a capture knows why 41 is
# everywhere, and deliberately **not** used as an exclusion: the allowlist below is what
# keeps it out, so a device that advertises it somewhere else is handled by the same rule.
OTA_PROVIDER_CLUSTER: Final = 41

# The control clusters, and the one that is a control and carries nothing we can use.
IDENTIFY_CLUSTER: Final = 3
ON_OFF_CLUSTER: Final = 6
LEVEL_CONTROL_CLUSTER: Final = 8
SCENES_MANAGEMENT_CLUSTER: Final = 98
COLOR_CONTROL_CLUSTER: Final = 768

# The root endpoint, which holds the node's own administration (Access Control, Basic
# Information, Operational Credentials) and is never a control a rule can start from.
ROOT_ENDPOINT: Final = 0

# What each bindable cluster carries. LevelControl carries two features because it really
# does: Move To Level and Move/Step/Stop are commands of one cluster and binding it binds
# all of them, exactly as `genLevelCtrl` does on Zigbee. Anything not named here contributes
# no feature at all, which is the whole guard against cluster 41: this is an allowlist, so a
# cluster nobody has taught this module about is not a control wherever it turns up.
FEATURES_BY_CLUSTER: Final[Mapping[int, frozenset[Feature]]] = {
    ON_OFF_CLUSTER: frozenset({Feature.ON_OFF}),
    LEVEL_CONTROL_CLUSTER: frozenset({Feature.LEVEL_SET, Feature.LEVEL_HOLD}),
    SCENES_MANAGEMENT_CLUSTER: frozenset({Feature.SCENE}),
    COLOR_CONTROL_CLUSTER: frozenset({Feature.COLOR}),
}

# The reverse map, which is single valued: a feature is carried by exactly one cluster, even
# though a cluster can carry several features. Built from the table above so the two cannot
# disagree, and sorted so it does not depend on how a frozenset iterates.
CLUSTER_BY_FEATURE: Final[Mapping[Feature, int]] = {
    feature: cluster
    for cluster, features in sorted(FEATURES_BY_CLUSTER.items())
    for feature in sorted(features)
}

# Access Control privileges, as the specification numbers them. Only two are ever named in
# this integration: the one it grants, and the one it must never touch.
PRIVILEGE_VIEW: Final = 1
PRIVILEGE_PROXY_VIEW: Final = 2
PRIVILEGE_OPERATE: Final = 3
PRIVILEGE_MANAGE: Final = 4
PRIVILEGE_ADMINISTER: Final = 5

# Authentication modes. CASE is the certificate-authenticated session a commissioned node
# uses to talk to another node, which is what a bound control does.
AUTH_MODE_PASE: Final = 1
AUTH_MODE_CASE: Final = 2
AUTH_MODE_GROUP: Final = 3

# The TLV tags an Access Control entry and its targets serialize by. The current Matter
# server hands a struct back as a mapping keyed by tag number rather than by field name
# (PRD Section 8.6, confirmed by the M1 capture), so these are the field names.
ACL_TAG_PRIVILEGE: Final = 1
ACL_TAG_AUTH_MODE: Final = 2
ACL_TAG_SUBJECTS: Final = 3
ACL_TAG_TARGETS: Final = 4
ACL_TAG_FABRIC_INDEX: Final = 254

ACL_TARGET_TAG_CLUSTER: Final = 0
ACL_TARGET_TAG_ENDPOINT: Final = 1
ACL_TARGET_TAG_DEVICE_TYPE: Final = 2

# The TLV tags a Binding entry serializes by, which are a different set from the ACL's and
# are numbered from 1 rather than from 0.
BINDING_TAG_NODE: Final = 1
BINDING_TAG_GROUP: Final = 2
BINDING_TAG_ENDPOINT: Final = 3
BINDING_TAG_CLUSTER: Final = 4
BINDING_TAG_FABRIC_INDEX: Final = 254

# How many entries one endpoint's Binding list may hold. Matter reports no capacity
# attribute for it and the specification sets no minimum, so there is no honest number to
# read: this is a bound rather than a measurement, exactly as the Zigbee binding table
# capacity is (docs/open-items.md T43). Both Inovelli binding lists are empty today, so
# nothing on this fabric is near it.
BINDING_TABLE_CAPACITY: Final = 8

# How an emitter's endpoint was decided, reported on every emitter so the UI can say how
# much was inferred. The same two words the other two protocols use for the same thing.
GROUPING_ENDPOINT: Final = "endpoint"
GROUPING_PROFILE_DB: Final = "profile_db"


class EndpointClusters(TypedDict):
    """The clusters one endpoint serves (`server_list`) and drives (`client_list`).

    Declared as the lists they are meant to be. What actually arrives is narrowed by the
    accessors below rather than trusted, because a probe records a failed read as an error
    record in the same slot and an adapter reads them off a server.
    """

    client_list: Sequence[int]
    server_list: Sequence[int]


class AclCapacity(TypedDict):
    """What a node says it can hold in its Access Control list."""

    entries_per_fabric: int
    subjects_per_entry: int
    targets_per_entry: int


class Node(TypedDict, total=False):
    """One Matter node, in the shape the M1 capture recorded and the adapter rebuilds.

    Deliberately the capture's shape rather than the client library's. It is what
    `tests/fixtures/m1_matter.json` holds, so the pure tests run against the real fabric
    without a server, and the adapter's only job is to fill this in from the attribute
    reads that Stage 0 proved.
    """

    node_id: int
    available: bool
    name: str
    vendor: str
    product: str
    endpoints: Mapping[str, EndpointClusters]
    bindings: Mapping[str, object]
    acl: object
    acl_capacity: AclCapacity


def _int_list(raw: object) -> tuple[int, ...]:
    """Return a list of whole numbers from a value that is supposed to be one.

    Anything else reads as empty rather than raising. A cluster list that came back as an
    error record is a list nobody can act on, and taking down a read of the whole node over
    one endpoint would lose the endpoints that did answer. `bool` is excluded because JSON
    `true` parses to a Python `bool`, which is an `int`, and a cluster 1 that got there that
    way would be a cluster nobody advertised.
    """
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(item for item in raw if isinstance(item, int) and not isinstance(item, bool))


def _whole_number(raw: object) -> int | None:
    """Return a value as a whole number when it is one, and None otherwise."""
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def attribute_path(endpoint: int, cluster: int, attribute: int) -> str:
    """Return the path one attribute is read and written by.

    `<endpoint>/<cluster>/<attribute>`, which is what `MatterClient.read_attribute` and
    `write_attribute` take (Stage 0 M1). Built here rather than formatted at each call site
    so that the read path and the write path can never disagree about a device's address.
    """
    return f"{endpoint}/{cluster}/{attribute}"


def client_list_path(endpoint: int) -> str:
    """Return the path of one endpoint's client cluster list."""
    return attribute_path(endpoint, DESCRIPTOR_CLUSTER, DESCRIPTOR_CLIENT_LIST)


def server_list_path(endpoint: int) -> str:
    """Return the path of one endpoint's server cluster list."""
    return attribute_path(endpoint, DESCRIPTOR_CLUSTER, DESCRIPTOR_SERVER_LIST)


def binding_path(endpoint: int) -> str:
    """Return the path of one endpoint's Binding list."""
    return attribute_path(endpoint, BINDING_CLUSTER, BINDING_ATTRIBUTE)


ACL_PATH: Final = attribute_path(ROOT_ENDPOINT, ACCESS_CONTROL_CLUSTER, ACL_ATTRIBUTE)
ACL_ENTRIES_PER_FABRIC_PATH: Final = attribute_path(
    ROOT_ENDPOINT, ACCESS_CONTROL_CLUSTER, ACL_ENTRIES_PER_FABRIC
)
ACL_SUBJECTS_PER_ENTRY_PATH: Final = attribute_path(
    ROOT_ENDPOINT, ACCESS_CONTROL_CLUSTER, ACL_SUBJECTS_PER_ENTRY
)
ACL_TARGETS_PER_ENTRY_PATH: Final = attribute_path(
    ROOT_ENDPOINT, ACCESS_CONTROL_CLUSTER, ACL_TARGETS_PER_ENTRY
)


def features_of_cluster(cluster: int) -> frozenset[Feature]:
    """Return what binding this cluster gives the user, which may be more than one thing."""
    return FEATURES_BY_CLUSTER.get(cluster, frozenset())


def features_of_binding(cluster: int) -> frozenset[Feature]:
    """Return what a binding on this cluster does, for a binding that is already there.

    The same answer as `features_of_cluster` for a cluster Device Links can bind, and
    `STATUS_REPORT` for one it cannot, which is the answer both other protocols give for the
    same question. What a control can be **offered** for and what an existing entry **is**
    are different questions: an endpoint that only drives cluster 41 must never be offered,
    and a binding somebody else wrote on a cluster this version does not know still has to
    be described, or a device's binding list would be half reported and half invisible.
    """
    return features_of_cluster(cluster) or frozenset({Feature.STATUS_REPORT})


def fingerprint_of(node: Node) -> MatterFingerprint:
    """Return what identifies this node's model, which is what a profile is keyed by."""
    return MatterFingerprint(vendor=node.get("vendor") or "", product=node.get("product") or "")


def handle_of(node: Node) -> DeviceHandle:
    """Return the handle a rule refers to this node by.

    **The node id is the identity and the compressed fabric id is not.** Home Assistant's
    own Matter device identifier embeds the compressed fabric id, which changes when a
    fabric is re-commissioned and would orphan every stored handle (Stage 0 item P2). So a
    handle keys on the node id alone, and a fabric change is treated the way E21 treats a
    new Z-Wave home id: a re-map rather than a silent loss.

    `ha_device_id` is left empty for the reason `models.DeviceHandle` gives: it is
    convenience only, and resolving it needs the device registry, which needs `hass`.
    """
    return DeviceHandle(
        backend=BackendId.MATTER,
        protocol_id=str(node["node_id"]),
        ha_device_id="",
        fingerprint=fingerprint_of(node),
        name_at_authoring=node.get("name") or f"Matter node {node['node_id']}",
    )


# How a Matter group appears in a `DeviceHandle`. A group is not a device, but a binding can
# point at one, and giving it a handle keeps the whole link model working without a second
# kind of target. The prefix cannot collide with a node id, which is decimal digits.
#
# Device Links never writes one. A Matter group binding needs the group's key distributed to
# every member at commissioning time, which is an act of commissioning rather than a link,
# so a group entry is only ever read: reported so that a device's Binding list is described
# whole, and refused on the write path.
GROUP_PROTOCOL_PREFIX: Final = "group:"

# What a group's fingerprint is. Groups have no vendor and no product, and a handle needs
# one, so this is what they get. It is never looked up in the profile database, because
# `lookup_matter` is only ever asked about a real node.
GROUP_FINGERPRINT: Final = MatterFingerprint(vendor="Matter", product="group")


def group_handle(group_id: int) -> DeviceHandle:
    """Return the handle a link uses when its target is a Matter group rather than a node."""
    return DeviceHandle(
        backend=BackendId.MATTER,
        protocol_id=f"{GROUP_PROTOCOL_PREFIX}{group_id}",
        ha_device_id="",
        fingerprint=GROUP_FINGERPRINT,
        name_at_authoring=f"Matter group {group_id}",
    )


def group_id_of(handle: DeviceHandle) -> int | None:
    """Return the group a handle names, or None when it names a node."""
    protocol_id = handle.protocol_id
    if not protocol_id.startswith(GROUP_PROTOCOL_PREFIX):
        return None
    rest = protocol_id.removeprefix(GROUP_PROTOCOL_PREFIX)
    return int(rest) if rest.isascii() and rest.isdecimal() else None


def node_id_of(handle: DeviceHandle) -> int | None:
    """Return the node a handle names, or None when its address is not a node id."""
    protocol_id = handle.protocol_id
    if not protocol_id.isascii() or not protocol_id.isdecimal():
        return None
    return int(protocol_id)


def endpoint_ids(node: Node) -> tuple[int, ...]:
    """Return this node's endpoint numbers, lowest first."""
    return tuple(
        sorted(
            int(endpoint)
            for endpoint in node.get("endpoints", {})
            if endpoint.isascii() and endpoint.isdecimal()
        )
    )


def _endpoint(node: Node, endpoint: int) -> EndpointClusters | None:
    """Return one endpoint of a node, or None when it does not report one."""
    return node.get("endpoints", {}).get(str(endpoint))


def client_clusters(node: Node, endpoint: int) -> tuple[int, ...]:
    """Return the clusters this endpoint drives, as the node reports them."""
    reported = _endpoint(node, endpoint)
    return () if reported is None else _int_list(reported.get("client_list"))


def server_clusters(node: Node, endpoint: int) -> tuple[int, ...]:
    """Return the clusters this endpoint serves, as the node reports them."""
    reported = _endpoint(node, endpoint)
    return () if reported is None else _int_list(reported.get("server_list"))


def has_binding_cluster(node: Node, endpoint: int) -> bool:
    """Say whether this endpoint has somewhere to hold a binding.

    The Binding cluster is a server cluster on the endpoint whose client clusters it
    directs, so an endpoint that drives OnOff without one has no table for a link to go in.
    """
    return BINDING_CLUSTER in server_clusters(node, endpoint)


def emits(node: Node, endpoint: int, cluster: int) -> bool:
    """Say whether this endpoint really drives this cluster as a control.

    Three conditions, and each rules out something the fixture actually contains: the
    endpoint is not the root (which administers the node rather than controlling anything),
    the cluster is one Device Links can bind (which keeps the OTA provider out wherever it
    is advertised), and the node says the endpoint drives it.
    """
    return (
        endpoint != ROOT_ENDPOINT
        and bool(features_of_cluster(cluster))
        and cluster in client_clusters(node, endpoint)
    )


def accepts(node: Node, endpoint: int, cluster: int) -> bool:
    """Say whether this endpoint serves this cluster, which is what a binding target needs."""
    return endpoint != ROOT_ENDPOINT and cluster in server_clusters(node, endpoint)


def receivable_features(node: Node) -> frozenset[Feature]:
    """Return everything any endpoint of this node can be made to do by a binding.

    The union across endpoints, because `DeviceCapabilities.receivable` is about the device
    and the compiler asks it before it knows which endpoint a rule names. The endpoint is
    checked again on the write path, where the answer actually decides something.
    """
    found: set[Feature] = set()
    for endpoint in endpoint_ids(node):
        if endpoint == ROOT_ENDPOINT:
            continue
        for cluster in server_clusters(node, endpoint):
            found |= features_of_cluster(cluster)
    return frozenset(found)


def receiving_endpoint(node: Node) -> int | None:
    """Return the endpoint a binding should address when nothing has named one.

    The lowest endpoint above the root that serves a cluster Device Links can bind, which on
    both Inovelli switches in the M1 capture is endpoint 1, the load. None when the node can
    act on nothing a binding could send, which is the same answer `receivable_features`
    gives as an empty set.

    A Matter binding always names a target endpoint, so this is not a nicety: it is what
    fills in the reverse leg of a two-way rule and the panel's targets step, neither of
    which asks the user for one (open items T50 and T56).
    """
    for endpoint in endpoint_ids(node):
        if endpoint == ROOT_ENDPOINT:
            continue
        if any(features_of_cluster(cluster) for cluster in server_clusters(node, endpoint)):
            return endpoint
    return None


def derive_emitters(node: Node, *, warnings: list[str] | None = None) -> list[Emitter]:
    """Return the controls this node offers, one per endpoint that can hold a link.

    One emitter per endpoint rather than per cluster, because an endpoint is the physical
    control: the Inovelli VTM31-SN's paddle is endpoint 2 and it drives OnOff and
    LevelControl together, exactly as the Zigbee derivation reads an Inovelli Blue's paddle.

    An endpoint is offered only when all three of these hold, and each of the three drops
    something that is really on this fabric:

    - it is not the root endpoint, which every node has and which drives cluster 41,
    - it drives at least one cluster in `FEATURES_BY_CLUSTER`, which keeps out an endpoint
      whose only client is the OTA provider or Identify,
    - it serves the Binding cluster, so there is a table for the link to live in.

    Everything dropped for the second or third reason is reported to `warnings`, because
    "this device is not a binding source" is the single most surprising thing about Matter
    on this fabric and a user picking a switch that turns out not to be one deserves a
    reason rather than an empty list.
    """
    emitters: list[Emitter] = []
    for endpoint in endpoint_ids(node):
        if endpoint == ROOT_ENDPOINT:
            continue
        actions = {
            feature: str(cluster)
            for cluster in sorted(client_clusters(node, endpoint))
            for feature in sorted(features_of_cluster(cluster))
        }
        if not actions:
            _warn_no_control(node, endpoint, warnings)
            continue
        if not has_binding_cluster(node, endpoint):
            if warnings is not None:
                warnings.append(
                    f"endpoint {endpoint} drives {sorted(client_clusters(node, endpoint))} "
                    "but serves no Binding cluster, so there is nowhere to write a link and "
                    "it is not offered as a control"
                )
            continue
        emitters.append(
            _emitter(
                emitter_id=f"ep{endpoint}",
                label=f"Endpoint {endpoint}",
                endpoint=endpoint,
                actions=actions,
                grouping=GROUPING_ENDPOINT,
            )
        )
    return emitters


def _warn_no_control(node: Node, endpoint: int, warnings: list[str] | None) -> None:
    """Report an endpoint that drives something, none of which is a control."""
    driven = client_clusters(node, endpoint)
    if warnings is None or not driven:
        return
    warnings.append(
        f"endpoint {endpoint} drives {sorted(driven)}, none of which Device Links can bind, "
        "so it is not offered as a control"
    )


def resolve_emitters(
    node: Node,
    entry: MatterProfileEntry | None = None,
    *,
    warnings: list[str] | None = None,
) -> list[Emitter]:
    """Return a node's controls, preferring a curated entry over the generic derivation.

    A curated entry contributes the label, the kind of control it is and any semantics
    marker; it does not restate what the device already reports, because the device is the
    better authority. The same one-at-a-time drop the Zigbee side uses: an emitter that
    names an endpoint the node does not have, a cluster that endpoint does not drive, or a
    feature that cluster cannot carry, is dropped with the contradiction appended to
    `warnings`, and the rest of the entry stands. Firmware differences within a model are
    the usual cause, and setting a whole entry aside to punish it for one would cost a
    correct paddle on the devices that do have one.

    A curated emitter covering exactly the endpoint and clusters a derived one covers is the
    same control described twice, so it keeps the derived id: adding a curated entry for a
    model whose derivation was already right must not rename controls out from under the
    rules already written against them.
    """
    derived = derive_emitters(node, warnings=warnings)
    if entry is None:
        return derived
    derived_ids = {
        (emitter.endpoint, frozenset(emitter.group_ids)): emitter.emitter_id for emitter in derived
    }
    curated: list[Emitter] = []
    for profile_emitter in entry.emitters:
        conflicts = _emitter_conflicts(profile_emitter, node)
        if conflicts:
            if warnings is not None:
                warnings.extend(conflicts)
            continue
        clusters = frozenset(str(cluster) for cluster in profile_emitter.actions.values())
        curated.append(
            _emitter(
                emitter_id=derived_ids.get(
                    (profile_emitter.endpoint, clusters), profile_emitter.emitter_id
                ),
                label=profile_emitter.label,
                endpoint=profile_emitter.endpoint,
                actions={
                    feature: str(cluster)
                    for feature, cluster in sorted(profile_emitter.actions.items())
                },
                grouping=GROUPING_PROFILE_DB,
                semantics=profile_emitter.semantics,
            )
        )
    if not curated:
        return derived
    return sorted(curated, key=lambda emitter: emitter.endpoint)


def _emitter_conflicts(profile_emitter: MatterProfileEmitter, node: Node) -> list[str]:
    """Return every way this curated emitter disagrees with what the node reports."""
    conflicts: list[str] = []
    endpoint = profile_emitter.endpoint
    for feature, cluster in sorted(profile_emitter.actions.items()):
        named = (
            f"profile entry maps {profile_emitter.emitter_id}.{feature} to cluster "
            f"{cluster} on endpoint {endpoint}"
        )
        if _endpoint(node, endpoint) is None:
            conflicts.append(f"{named}, which this node does not report")
        elif not emits(node, endpoint, cluster):
            conflicts.append(f"{named}, which that endpoint does not drive")
        elif feature not in features_of_cluster(cluster):
            conflicts.append(f"{named}, which cannot carry it")
    if not conflicts and not has_binding_cluster(node, endpoint):
        conflicts.append(
            f"profile entry puts {profile_emitter.emitter_id} on endpoint {endpoint}, "
            "which serves no Binding cluster"
        )
    return conflicts


def _emitter(  # noqa: PLR0913
    *,
    emitter_id: str,
    label: str,
    endpoint: int,
    actions: Mapping[Feature, str],
    grouping: str,
    semantics: str | None = None,
) -> Emitter:
    """Assemble one emitter over the clusters it drives.

    `group_ids` holds the cluster ids as text, because that is what `Link.emitter_group`
    carries for Matter and what the planner counts capacity against. Two features pointing
    at one cluster appear once here and twice in `actions`, which is the honest shape:
    binding LevelControl is one entry in the Binding list that gives the user two things.
    """
    return Emitter(
        emitter_id=emitter_id,
        label=label,
        endpoint=endpoint,
        group_ids=tuple(sorted(set(actions.values()), key=int)),
        actions=dict(actions),
        capacity=BINDING_TABLE_CAPACITY,
        supports_endpoint_targets=True,
        is_lifeline=False,
        grouping=grouping,
        semantics=semantics,
    )


# --------------------------------------------------------------------------------------
# Bindings: what is on a source endpoint now, and what it should become.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BindingEntry:
    """One entry of a Binding list, read off a node or about to be written to one.

    A unicast entry names `node`, `endpoint` and `cluster`. A group entry names `group` and
    no node, and Device Links writes none: Matter multicast needs group keys distributed to
    every member, which is a commissioning act rather than a link. One that is already there
    is still reported, because it is on the device.
    """

    node: int | None = None
    group: int | None = None
    endpoint: int | None = None
    cluster: int | None = None

    @property
    def is_unicast(self) -> bool:
        """Say whether this entry names one endpoint of one node."""
        return self.node is not None and self.endpoint is not None and self.cluster is not None


def parse_bindings(node: Node, endpoint: int) -> tuple[BindingEntry, ...]:
    """Return the Binding list on one endpoint, in the order the node reports it.

    Defensive about everything, because a probe records a failed read in the same slot and a
    server may add a field. An entry that carries nothing this version understands still
    becomes a `BindingEntry` with every field None, so a list of five is reported as five:
    silently dropping one would make a binding list shorter than it is, and capacity is
    counted off that length.
    """
    raw = node.get("bindings", {}).get(str(endpoint))
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(_binding_entry(item) for item in raw if isinstance(item, Mapping))


def _binding_entry(raw: Mapping[object, object]) -> BindingEntry:
    """Read one Binding entry out of its tag-keyed mapping."""
    return BindingEntry(
        node=_tag(raw, BINDING_TAG_NODE),
        group=_tag(raw, BINDING_TAG_GROUP),
        endpoint=_tag(raw, BINDING_TAG_ENDPOINT),
        cluster=_tag(raw, BINDING_TAG_CLUSTER),
    )


def _tag(raw: Mapping[object, object], tag: int) -> int | None:
    """Return one TLV-tagged field of a struct, whichever way its key is spelled.

    Keys arrive as integers from the client and as strings from anything that has been
    through JSON, which the M1 capture has: `json.dumps` turns an integer key into a string
    one. Both are the same tag, and a reader that understood only one of them would work
    against the fixture and fail against the fabric, or the other way round.
    """
    if tag in raw:
        return _whole_number(raw[tag])
    return _whole_number(raw.get(str(tag)))


def _tag_list(raw: Mapping[object, object], tag: int) -> object:
    """Return one TLV-tagged field without narrowing it, for the fields that are lists."""
    return raw[tag] if tag in raw else raw.get(str(tag))


def binding_payload(entries: Iterable[BindingEntry]) -> list[dict[str, object]]:
    """Return a Binding list in the shape a write takes.

    Keys are the TLV tags as text, which is what the M1 read came back as and what JSON
    makes of an integer key anyway, so this is the observed spelling rather than a choice.
    A group entry is written back with its group tag and a unicast entry with its three, so
    an entry this integration did not create survives a write of ours unchanged.

    NOTE: modelled, never observed. No Binding list has ever been written on this fabric.
    Assumption A9 in docs/open-items.md.
    """
    payload: list[dict[str, object]] = []
    for entry in entries:
        written: dict[str, object] = {}
        if entry.node is not None:
            written[str(BINDING_TAG_NODE)] = entry.node
        if entry.group is not None:
            written[str(BINDING_TAG_GROUP)] = entry.group
        if entry.endpoint is not None:
            written[str(BINDING_TAG_ENDPOINT)] = entry.endpoint
        if entry.cluster is not None:
            written[str(BINDING_TAG_CLUSTER)] = entry.cluster
        payload.append(written)
    return payload


# --------------------------------------------------------------------------------------
# Access Control: who may operate what, and the two rules that are never bent.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AclTarget:
    """What one Access Control entry grants access to.

    All three fields are optional in the specification and a target that names none is a
    grant over the whole node. Device Links only ever writes a target that names both a
    cluster and an endpoint, which is the narrowest grant a bound control needs.
    """

    cluster: int | None = None
    endpoint: int | None = None
    device_type: int | None = None

    @property
    def is_targeted(self) -> bool:
        """Say whether this names one cluster on one endpoint, rather than everything."""
        return self.cluster is not None and self.endpoint is not None


@dataclass(frozen=True, slots=True)
class AclEntry:
    """One Access Control entry, read off a node or about to be written to one.

    `privilege` and `auth_mode` are None for an entry that belongs to another fabric. A read
    that is not fabric filtered returns those with every field but the fabric index removed,
    which is what the M1 capture holds: 15 of the 19 nodes report between one and three of
    them. They are not ours to read, not ours to count as ours, and not ours to write back.
    """

    privilege: int | None
    auth_mode: int | None
    subjects: tuple[int, ...]
    targets: tuple[AclTarget, ...]
    fabric_index: int | None

    @property
    def is_redacted(self) -> bool:
        """Say whether this entry belongs to a fabric that did not let us read it."""
        return self.privilege is None or self.auth_mode is None

    @property
    def is_administer(self) -> bool:
        """Say whether this is an administrative entry, which is never ours to touch.

        The controller's own entry on every node of this fabric is one: privilege
        Administer, CASE, subject the controller's node id. Removing it would orphan the
        device from Home Assistant entirely, which is why CLAUDE.md Section 3 rule 4 puts it
        beside the Z-Wave lifeline and the Zigbee coordinator binding.
        """
        return self.privilege == PRIVILEGE_ADMINISTER

    def grants(self, subject: int, target: AclTarget) -> bool:
        """Say whether this entry already lets `subject` operate on `target`.

        An entry with no targets covers the whole node, so it covers this target too, and an
        entry with a privilege above Operate covers what Operate would have granted. Both
        matter for the same reason: a grant that is already there must be recognised, or
        every apply would add a second entry into a list with two free slots.
        """
        if self.is_redacted or subject not in self.subjects:
            return False
        if self.privilege is None or self.privilege < PRIVILEGE_OPERATE:
            return False
        return not self.targets or target in self.targets

    def is_managed_grant(self, target: AclTarget) -> bool:
        """Say whether this entry is the exact grant Device Links writes for this target.

        Operate, CASE, and a target list that is exactly this one target. Nothing labels an
        Access Control entry with who created it, so this is a description of shape rather
        than a claim of ownership, and it is chosen so that the claim is not needed:
        **adding a subject to an entry of this shape grants that subject precisely what a
        separate entry of ours would have granted it, and nothing else.** Merging is
        therefore safe whoever wrote the entry, which is what makes it usable at the two
        entries of headroom the fixture's Eve Energy actually has.
        """
        return (
            not self.is_redacted
            and self.privilege == PRIVILEGE_OPERATE
            and self.auth_mode == AUTH_MODE_CASE
            and self.targets == (target,)
        )


class AclError(ValueError):
    """A write was about to do something to an Access Control list that is never allowed.

    Raised rather than returned, because there is no legitimate caller and no useful way for
    one to carry on. This is the guard that makes Matter writes safe to ship, so it lives in
    the pure module where every payload passes through it and no adapter can route around
    it, exactly as `zigbee_protocol.ForeignGroupError` does for managed groups.
    """


class GrantNotConfirmedError(AclError):
    """A binding was about to be written without a confirmed access grant behind it (E27)."""


class AclRefusal(StrEnum):
    """Why a grant could not be made, in terms the adapter turns into a message.

    Not a `Diagnostic`, because a pure module has no business owning the wording; the
    adapter maps each of these to a translation key and the placeholders that go with it.
    """

    ENTRIES_FULL = "entries_full"
    SUBJECTS_FULL = "subjects_full"
    NO_TARGETED_ENTRIES = "no_targeted_entries"
    FABRIC_UNKNOWN = "fabric_unknown"


@dataclass(frozen=True, slots=True)
class AclOutcome:
    """What an Access Control list should become, or why it cannot.

    `entries` is what to write and is None when `refusal` is set. `changed` is False when
    the grant is already there, which is the common case on a second apply and must not
    spend a write. `used` and `capacity` are carried whatever the outcome, because the
    message a user sees when a list is full has to say how full it is (E27).
    """

    entries: tuple[AclEntry, ...] | None
    refusal: AclRefusal | None
    changed: bool
    used: int
    capacity: int


def parse_acl(raw: object) -> tuple[AclEntry, ...]:
    """Return the Access Control list a node reported, redacted entries included.

    Anything that is not a list reads as no entries at all, which is what a failed read
    looks like in the capture. That is safe in the one direction that matters: an empty
    read makes every subsequent write refuse to touch anything, because there is then no
    fabric index to write under.
    """
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(_acl_entry(item) for item in raw if isinstance(item, Mapping))


def _acl_entry(raw: Mapping[object, object]) -> AclEntry:
    """Read one Access Control entry out of its tag-keyed mapping."""
    subjects = _tag_list(raw, ACL_TAG_SUBJECTS)
    targets = _tag_list(raw, ACL_TAG_TARGETS)
    return AclEntry(
        privilege=_tag(raw, ACL_TAG_PRIVILEGE),
        auth_mode=_tag(raw, ACL_TAG_AUTH_MODE),
        subjects=_int_list(subjects),
        targets=_acl_targets(targets),
        fabric_index=_tag(raw, ACL_TAG_FABRIC_INDEX),
    )


def _acl_targets(raw: object) -> tuple[AclTarget, ...]:
    """Read the target list of one entry, which is null for a whole-node grant."""
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(
        AclTarget(
            cluster=_tag(item, ACL_TARGET_TAG_CLUSTER),
            endpoint=_tag(item, ACL_TARGET_TAG_ENDPOINT),
            device_type=_tag(item, ACL_TARGET_TAG_DEVICE_TYPE),
        )
        for item in raw
        if isinstance(item, Mapping)
    )


def our_fabric_index(entries: Iterable[AclEntry]) -> int | None:
    """Return the fabric index this controller reads under, or None when it is not certain.

    The entries we can read are ours, because a read that is not fabric filtered redacts
    every other fabric's. So the fabric index is whatever those carry, and None when there
    are none of them or when they disagree.

    Disagreement is not a case that should ever happen and is refused rather than resolved:
    two readable fabric indices mean this read is not what this function assumes it is, and
    guessing which of them to write under would put an entry on somebody else's fabric.
    """
    indices = {entry.fabric_index for entry in entries if not entry.is_redacted}
    indices.discard(None)
    return next(iter(indices)) if len(indices) == 1 else None


def entries_of_fabric(entries: Iterable[AclEntry], fabric_index: int) -> tuple[AclEntry, ...]:
    """Return the entries this fabric owns, in the order the node reported them."""
    return tuple(
        entry for entry in entries if not entry.is_redacted and entry.fabric_index == fabric_index
    )


def foreign_entries(entries: Iterable[AclEntry], fabric_index: int) -> tuple[AclEntry, ...]:
    """Return the entries that belong to another fabric, which are never written back.

    An Access Control list is fabric scoped: a write replaces the accessing fabric's entries
    and leaves every other fabric's alone, and an entry of another fabric's cannot be
    written at all because it comes back with no privilege on it. So they are left out of a
    write and counted only as evidence, which is what `GrantReceipt` checks afterwards.
    """
    return tuple(
        entry for entry in entries if entry.is_redacted or entry.fabric_index != fabric_index
    )


def grant_entry(subject: int, target: AclTarget, fabric_index: int) -> AclEntry:
    """Return the entry Device Links writes to let one control operate one cluster.

    **Operate, never Administer, and always targeted** (PRD Section 10, CLAUDE.md Section 3
    rule 4). Operate is what a bound control needs and is the least this can be; Administer
    would let the control re-commission the device it is bound to.
    """
    return AclEntry(
        privilege=PRIVILEGE_OPERATE,
        auth_mode=AUTH_MODE_CASE,
        subjects=(subject,),
        targets=(target,),
        fabric_index=fabric_index,
    )


def grant_for(
    existing: Sequence[AclEntry],
    *,
    subject: int,
    target: AclTarget,
    capacity: AclCapacity,
) -> AclOutcome:
    """Return what a node's Access Control list must become to let one control drive it.

    The order is the whole design, and each step is there because of a number in the M1
    capture rather than because of the specification:

    1. **Already granted?** Then nothing is written. A second apply of the same rule must
       not add a second entry into a list with two free slots.
    2. **Can this device express a targeted grant at all?** Every node in the capture
       reports `TargetsPerAccessControlEntry` 3, so this never fires today. If one ever
       reported 0, the only entry it could hold would be a whole-node grant, and this
       refuses rather than widening what a control is given.
    3. **Merge into an existing entry for this exact target.** Load bearing rather than an
       optimisation: the fixture's Eve Energy reports 6 entries per fabric and already holds
       4, so a second rule pointing at it would not fit as a new entry. Merging adds a
       subject to an entry that already grants exactly this, so it can never grant more than
       a separate entry would have.
    4. **Otherwise append**, if the list has room. If it has not, refuse and say by how much
       (E27, E28).

    `existing` is everything the node reported, other fabrics' redacted entries included.
    They are counted against capacity and never written back; see `foreign_entries` and
    assumption A9 for what is assumed there and what it would cost to be wrong.
    """
    fabric_index = our_fabric_index(existing)
    used = len(existing)
    limit = capacity["entries_per_fabric"]
    if fabric_index is None:
        return AclOutcome(None, AclRefusal.FABRIC_UNKNOWN, changed=False, used=used, capacity=limit)
    ours = entries_of_fabric(existing, fabric_index)
    if any(entry.grants(subject, target) for entry in ours):
        return AclOutcome(ours, None, changed=False, used=used, capacity=limit)
    if capacity["targets_per_entry"] < 1:
        return AclOutcome(
            None, AclRefusal.NO_TARGETED_ENTRIES, changed=False, used=used, capacity=limit
        )
    merged = _merged_into_existing(ours, subject, target, capacity["subjects_per_entry"])
    if merged is not None:
        return AclOutcome(_checked(ours, merged), None, changed=True, used=used, capacity=limit)
    if used >= limit:
        refusal = (
            AclRefusal.SUBJECTS_FULL
            if any(entry.is_managed_grant(target) for entry in ours)
            else AclRefusal.ENTRIES_FULL
        )
        return AclOutcome(None, refusal, changed=False, used=used, capacity=limit)
    appended = (*ours, grant_entry(subject, target, fabric_index))
    return AclOutcome(_checked(ours, appended), None, changed=True, used=used, capacity=limit)


def _merged_into_existing(
    ours: Sequence[AclEntry], subject: int, target: AclTarget, subjects_per_entry: int
) -> tuple[AclEntry, ...] | None:
    """Return the list with `subject` added to an entry for this target, or None.

    None means there was no entry of exactly this shape, or the one there was is already
    holding as many subjects as the device allows. Both are answered by trying to append
    instead, which is what the caller does.
    """
    for position, entry in enumerate(ours):
        if not entry.is_managed_grant(target):
            continue
        if len(entry.subjects) >= subjects_per_entry:
            return None
        widened = replace(entry, subjects=(*entry.subjects, subject))
        return (*ours[:position], widened, *ours[position + 1 :])
    return None


def revoke_for(existing: Sequence[AclEntry], *, subject: int, target: AclTarget) -> AclOutcome:
    """Return what a node's Access Control list must become when a link goes away.

    The mirror of `grant_for`, and narrower than it in one deliberate way: only an entry of
    the exact shape Device Links writes is touched. A whole-node grant that happens to cover
    this target is somebody else's arrangement and is left exactly as it is, even though it
    is what makes `grants` answer True.

    **An entry whose last subject is removed is removed with it.** An Access Control entry
    with an empty subject list grants every node on the fabric, so leaving one behind would
    turn a revocation into the widest grant on the device.
    """
    fabric_index = our_fabric_index(existing)
    used = len(existing)
    if fabric_index is None:
        return AclOutcome(None, AclRefusal.FABRIC_UNKNOWN, changed=False, used=used, capacity=0)
    ours = entries_of_fabric(existing, fabric_index)
    narrowed: list[AclEntry] = []
    changed = False
    for entry in ours:
        if not entry.is_managed_grant(target) or subject not in entry.subjects:
            narrowed.append(entry)
            continue
        changed = True
        remaining = tuple(held for held in entry.subjects if held != subject)
        if remaining:
            narrowed.append(replace(entry, subjects=remaining))
    return AclOutcome(_checked(ours, tuple(narrowed)), None, changed=changed, used=used, capacity=0)


def _checked(before: Sequence[AclEntry], after: Sequence[AclEntry]) -> tuple[AclEntry, ...]:
    """Refuse a list that would drop or alter an administrative entry.

    The one rule this module exists to keep. Every path that produces an Access Control list
    goes through here, so an entry with Administer privilege cannot be lost to a mistake in
    the merge, to a future caller, or to an adapter that builds a list of its own: there is
    no way to reach `acl_payload` with a list that has not been through this.

    Compared by value rather than by position, because a merge changes the order of nothing
    but is allowed to. An entry that is present before and absent after, or present with any
    field changed, is refused.
    """
    kept = list(after)
    for entry in before:
        if not entry.is_administer:
            continue
        if entry in kept:
            kept.remove(entry)
            continue
        raise AclError(
            "this write would remove or alter an Access Control entry with Administer "
            "privilege, which is the controller's own entry and is never ours to touch"
        )
    return tuple(after)


def acl_payload(entries: Iterable[AclEntry]) -> list[dict[str, object]]:
    """Return an Access Control list in the shape a write takes.

    Keys are the TLV tags as text, for the reason `binding_payload` gives. The fabric index
    is deliberately **not** written: it is assigned by the node from the session the write
    arrived on, and sending one would be telling a device which fabric it is talking to.

    A redacted entry cannot be written and reaching here with one is a mistake worth
    stopping for rather than a value to skip, because a list that silently lost an entry is
    a list that granted less than the caller thought it did.

    NOTE: modelled, never observed. No ACL has ever been written on this fabric. Assumption
    A9 in docs/open-items.md.
    """
    payload: list[dict[str, object]] = []
    for entry in entries:
        if entry.is_redacted:
            raise AclError(
                "an Access Control entry belonging to another fabric cannot be written "
                "back, because the fabric that owns it did not let us read it"
            )
        written: dict[str, object] = {
            str(ACL_TAG_PRIVILEGE): entry.privilege,
            str(ACL_TAG_AUTH_MODE): entry.auth_mode,
            str(ACL_TAG_SUBJECTS): list(entry.subjects),
            str(ACL_TAG_TARGETS): [_target_payload(target) for target in entry.targets] or None,
        }
        payload.append(written)
    return payload


def _target_payload(target: AclTarget) -> dict[str, object]:
    """Return one Access Control target in the shape a write takes."""
    return {
        str(ACL_TARGET_TAG_CLUSTER): target.cluster,
        str(ACL_TARGET_TAG_ENDPOINT): target.endpoint,
        str(ACL_TARGET_TAG_DEVICE_TYPE): target.device_type,
    }


@dataclass(frozen=True, slots=True)
class GrantReceipt:
    """Proof that a target's Access Control list really carries the grant a binding needs.

    **This is how E27's ordering is made structural rather than remembered.** E27 says the
    binding entry is written only after the access grant succeeds, so that a rejection
    leaves no partial state. Writing the two calls in the right order satisfies that today
    and says nothing about tomorrow, so instead `binding_for` will not build a binding list
    without one of these, and one of these cannot be built without an Access Control list,
    read back from the device after the write, that actually contains the grant. There is no
    argument that skips the ACL: the type system asks for the receipt and the receipt asks
    for the evidence.

    It checks three things, and the second and third are about damage rather than about this
    link. `confirmed` is what the target's list reads as **now**:

    - the grant is there, so the binding about to be written will be honoured,
    - every Administer entry that was there before is still there, so the controller has not
      been locked out by our own write,
    - the same number of other fabrics' entries are there, so a write that turned out not to
      be fabric scoped is caught by the write that did it rather than by a user whose Apple
      Home stopped working.
    """

    node_id: int
    subject: int
    target: AclTarget
    confirmed: tuple[AclEntry, ...]

    def __post_init__(self) -> None:
        """Refuse a receipt whose evidence does not show the grant."""
        if not any(entry.grants(self.subject, self.target) for entry in self.confirmed):
            raise GrantNotConfirmedError(
                f"node {self.node_id} does not report a grant letting {self.subject} operate "
                f"cluster {self.target.cluster} on endpoint {self.target.endpoint}, so no "
                "binding may be written for it"
            )

    def covers(self, *, node_id: int, subject: int, target: AclTarget) -> bool:
        """Say whether this receipt is about exactly this grant and no other."""
        return self.node_id == node_id and self.subject == subject and self.target == target


def confirm_grant(
    *,
    node_id: int,
    subject: int,
    target: AclTarget,
    before: Sequence[AclEntry],
    after: Sequence[AclEntry],
) -> GrantReceipt:
    """Return the receipt for a grant, having checked what the write actually did.

    `before` is the list as it was read before the write and `after` is the list read back
    from the device afterwards. Raises rather than returning something falsy: a caller that
    could carry on without noticing is the failure mode this whole mechanism exists to
    remove.
    """
    fabric_index = our_fabric_index(after)
    if fabric_index is None:
        raise GrantNotConfirmedError(
            f"node {node_id} answered with an Access Control list this controller cannot "
            "find itself in, so nothing about the write can be confirmed"
        )
    kept = list(after)
    for entry in before:
        if not entry.is_administer:
            continue
        if entry in kept:
            kept.remove(entry)
            continue
        raise GrantNotConfirmedError(
            f"node {node_id} no longer reports an Access Control entry with Administer "
            "privilege that it reported before this write, so the write did more than it "
            "was asked to and no binding may follow it"
        )
    was = len(foreign_entries(before, fabric_index))
    now = len(foreign_entries(after, fabric_index))
    if was != now:
        raise GrantNotConfirmedError(
            f"node {node_id} reported {was} Access Control entries belonging to other "
            f"fabrics before this write and {now} after it, so the write was not scoped to "
            "this fabric and no binding may follow it"
        )
    return GrantReceipt(node_id=node_id, subject=subject, target=target, confirmed=tuple(after))


def binding_for(
    existing: Sequence[BindingEntry],
    *,
    wanted: BindingEntry,
    source_node_id: int,
    receipt: GrantReceipt,
) -> tuple[BindingEntry, ...] | None:
    """Return what a source endpoint's Binding list must become, or None when it is there.

    The **only** way to build a Binding list that adds an entry, and it takes a
    `GrantReceipt` because of that: E27's ordering is enforced by there being no other
    function to call. The receipt has to be about this exact grant, so a receipt for one
    target cannot be reused to write a binding to another.

    Merged rather than replaced: entries this integration did not write are carried through
    untouched, which is FR-B7's requirement and is the same rule the Zigbee and Z-Wave
    adapters follow for their own tables.
    """
    if not wanted.is_unicast:
        raise AclError(
            "a Matter binding Device Links writes always names a node, endpoint and cluster"
        )
    target = AclTarget(cluster=wanted.cluster, endpoint=wanted.endpoint)
    if not receipt.covers(node_id=wanted.node or 0, subject=source_node_id, target=target):
        raise GrantNotConfirmedError(
            f"the access grant confirmed for node {receipt.node_id} is not the one this "
            f"binding to node {wanted.node} endpoint {wanted.endpoint} cluster "
            f"{wanted.cluster} depends on"
        )
    if wanted in existing:
        return None
    return (*existing, wanted)


def binding_without(
    existing: Sequence[BindingEntry], *, wanted: BindingEntry
) -> tuple[BindingEntry, ...] | None:
    """Return the Binding list without one entry, or None when it does not hold it.

    No receipt, because taking a link away needs no grant: the access entry is narrowed
    afterwards rather than before, so a failure to narrow it leaves a permission that
    permits nothing rather than a binding that is refused.
    """
    if wanted not in existing:
        return None
    return tuple(entry for entry in existing if entry != wanted)


def cluster_for(feature: Feature) -> int | None:
    """Return the cluster that carries this feature, or None when none does."""
    return CLUSTER_BY_FEATURE.get(feature)
