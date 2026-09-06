"""Pure Zigbee interpretation: what the bridge publishes in, the capability model out.

This is the Zigbee half of what `zwave_protocol.py` does for Z-Wave. It reads the
`bridge/devices` payload Zigbee2MQTT retains, works out what each endpoint of a device can
emit and receive, turns the bindings already on a device into links, and builds the request
payloads a bind or an unbind is made of.

It is pure: no Home Assistant import, no I/O, no clock. It is handed already-parsed JSON and
returns value types, which is what lets it be tested directly against
`tests/fixtures/g1_bridge.json`, the Stage 0 G1 capture of Jayant's real bridge.

Two things about Zigbee that shape everything below, and that are genuinely different from
Z-Wave rather than merely spelled differently:

- **A cluster is not an association group.** `genLevelCtrl` carries setting a level and
  holding to dim, both, in one bindable unit. Z-Wave gives those two separate association
  groups, so a Z-Wave emitter can offer one without the other and Zigbee cannot. That is
  modelled honestly here: one cluster, one entry in `Emitter.group_ids`, and two features in
  `Emitter.actions` pointing at it. The consequence is that reading a `genLevelCtrl` binding
  back produces **two** observed links, because the binding really does carry both, and a
  rule that asked for only one of them leaves the other as a link nobody claims.
- **A binding always names a target endpoint.** There is no device-wide binding, so a link
  whose target endpoint is None cannot be expressed. The write path refuses one rather than
  choosing an endpoint on the user's behalf, because a chosen endpoint would read back as
  itself and never match the link that asked for "the whole device", and a plan that can
  never converge is worse than a refusal that says what to do.

**The write payloads here are modelled, not observed.** Stage 0 item G2 was never approved,
so no bind has ever been performed on this network: everything from `bind_payload` down comes
from the Zigbee2MQTT documentation. See assumption A2 in `docs/open-items.md` and issue #6.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, NotRequired, TypedDict

from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceHandle,
    Emitter,
    Feature,
    ZigbeeFingerprint,
)
from custom_components.device_links.profile_db import ZigbeeProfileEmitter, ZigbeeProfileEntry

# Cluster names exactly as Zigbee2MQTT spells them in `clusters.input`, `clusters.output`
# and on every binding. They are the Zigbee cluster names, not ours, and they are what
# reaches the bridge in a bind request.
GEN_ON_OFF: Final = "genOnOff"
GEN_LEVEL_CTRL: Final = "genLevelCtrl"
GEN_SCENES: Final = "genScenes"
LIGHTING_COLOR_CTRL: Final = "lightingColorCtrl"

# What each bindable cluster carries. `genLevelCtrl` carries two features because it really
# does: Move To Level and Move/Step/Stop are commands of one cluster, and binding it binds
# all of them. Offering "set level" without "hold to dim" would be a promise the radio
# cannot keep. Anything not named here contributes no feature at all, so an endpoint that
# emits only `genOta` or `greenPower` is not offered to the user as a control.
FEATURES_BY_CLUSTER: Final[Mapping[str, frozenset[Feature]]] = {
    GEN_ON_OFF: frozenset({Feature.ON_OFF}),
    GEN_LEVEL_CTRL: frozenset({Feature.LEVEL_SET, Feature.LEVEL_HOLD}),
    GEN_SCENES: frozenset({Feature.SCENE}),
    LIGHTING_COLOR_CTRL: frozenset({Feature.COLOR}),
}

# The reverse map, which is single-valued: a feature is carried by exactly one cluster, even
# though a cluster can carry several features. Built from the table above so the two cannot
# disagree, and sorted so it does not depend on how a frozenset iterates.
CLUSTER_BY_FEATURE: Final[Mapping[Feature, str]] = {
    feature: cluster
    for cluster, features in sorted(FEATURES_BY_CLUSTER.items())
    for feature in sorted(features)
}

# What Zigbee2MQTT calls the radio itself in `bridge/devices`. Every binding on Jayant's
# network today targets it: those are Zigbee2MQTT's own reporting setup, and offering them
# for removal would invite a user to delete the thing that makes their devices report at all.
COORDINATOR_TYPE: Final = "Coordinator"

# The two shapes a binding target takes.
TARGET_ENDPOINT: Final = "endpoint"
TARGET_GROUP: Final = "group"

# Decision D5: a one-to-many rule uses a managed Zigbee group, and every group Device Links
# creates carries this prefix. A group without it is a user's own and is never read for
# membership, never written to, and never deleted.
MANAGED_GROUP_PREFIX: Final = "dl_"

# How a group appears in a `DeviceHandle`. A group is not a device, but it is a link target,
# and giving it a handle keeps the whole link model (fingerprints, plans, ownership) working
# without a second kind of target. The prefix cannot collide with an IEEE address, which is
# hexadecimal and starts with `0x`.
GROUP_PROTOCOL_PREFIX: Final = "group:"

# How Zigbee2MQTT identifies a group's fingerprint. Groups have no vendor and no model, and
# a handle needs one, so this is what they get: it is never looked up in the profile
# database, because `lookup` is only ever asked about a real device.
GROUP_FINGERPRINT: Final = ZigbeeFingerprint(manufacturer="Zigbee2MQTT", model="group")

# How an emitter's endpoint was decided, reported on every emitter so the UI can say how
# much was inferred. The same two words the Z-Wave side uses for the same distinction.
GROUPING_ENDPOINT: Final = "endpoint"
GROUPING_PROFILE_DB: Final = "profile_db"

# How many bindings one endpoint's cluster may hold. Zigbee2MQTT does not report a device's
# binding table size, and the Zigbee specification leaves it to the manufacturer, so there
# is no honest number to read: this is a bound rather than a measurement, and it is the
# reason Decision D5 puts a one-to-many rule into a managed group (a group is one entry in
# the table however many members it has). See docs/open-items.md T43.
BINDING_TABLE_CAPACITY: Final = 8


class EndpointTarget(TypedDict):
    """A binding target that is one endpoint of one device."""

    type: Literal["endpoint"]
    ieee_address: str
    endpoint: int


class GroupTarget(TypedDict):
    """A binding target that is a Zigbee group."""

    type: Literal["group"]
    id: int


type BindingTarget = EndpointTarget | GroupTarget


class Binding(TypedDict):
    """One binding on one endpoint, as `bridge/devices` reports it."""

    cluster: str
    target: BindingTarget


class Clusters(TypedDict):
    """The clusters an endpoint serves (`input`) and drives (`output`)."""

    input: Sequence[str]
    output: Sequence[str]


class Endpoint(TypedDict):
    """One endpoint of one device, as `bridge/devices` reports it."""

    bindings: Sequence[Binding]
    clusters: Clusters
    configured_reportings: NotRequired[Sequence[Mapping[str, object]]]
    name: NotRequired[str]
    scenes: NotRequired[Sequence[Mapping[str, object]]]


class Definition(TypedDict):
    """What Zigbee2MQTT's converter says this device is."""

    model: str
    vendor: str
    description: NotRequired[str]


class Device(TypedDict):
    """One device, as `bridge/devices` reports it.

    Only the keys this module reads are declared. The real payload carries a great deal
    more, and `definition.exposes` in particular was trimmed out of the G1 capture because
    it was 92% of the bytes and says nothing about bindings.
    """

    ieee_address: str
    friendly_name: str
    type: str
    endpoints: Mapping[str, Endpoint]
    definition: NotRequired[Definition | None]
    disabled: NotRequired[bool]
    interview_completed: NotRequired[bool]
    manufacturer: NotRequired[str]
    model_id: NotRequired[str]
    power_source: NotRequired[str]


class GroupMember(TypedDict):
    """One endpoint that is a member of a Zigbee group."""

    ieee_address: str
    endpoint: int


class Group(TypedDict):
    """One Zigbee group, as `bridge/groups` reports it."""

    id: int
    friendly_name: str
    members: Sequence[GroupMember]


def features_of_cluster(cluster: str) -> frozenset[Feature]:
    """Return what binding this cluster gives the user, which may be more than one thing."""
    return FEATURES_BY_CLUSTER.get(cluster, frozenset())


def features_of_binding(cluster: str) -> frozenset[Feature]:
    """Return what a binding on this cluster does, for a binding that is already there.

    The same answer as `features_of_cluster` for a cluster Device Links can bind, and
    `STATUS_REPORT` for one it cannot. The two questions are different and the difference
    matters: what a control can be **offered** for is what a user could pick, and an
    endpoint that only drives `genOta` must not be offered at all. What an existing binding
    **is** is another thing entirely, and Zigbee2MQTT's own reporting setup is made of
    exactly those clusters (`seMetering`, `haElectricalMeasurement`, `manuSpecificInovelli`).
    Dropping them would leave a device's binding table half described: a user could not see
    them, a group's capacity would be counted short, and a device-to-device binding on a
    manufacturer cluster could never be reported at all.

    `STATUS_REPORT` is the same answer the Z-Wave side gives a group that issues nothing it
    can use, and it means the same thing there: this entry reports rather than controls.
    """
    return features_of_cluster(cluster) or frozenset({Feature.STATUS_REPORT})


def coordinator_address(info: Mapping[str, object]) -> str | None:
    """Return the coordinator's IEEE address as `bridge/info` reports it.

    The authoritative source, and the reason it is worth having a second one: the fallback
    scans `bridge/devices` for a device whose `type` is `Coordinator`, and that string is
    Zigbee2MQTT's, not ours. If it ever changes, or the coordinator is missing from the
    listing, the fallback quietly finds nothing and every reporting binding on the network
    stops being a system link, which is the one classification that must not fail open.
    """
    coordinator = info.get("coordinator")
    if not isinstance(coordinator, dict):
        return None
    address = coordinator.get("ieee_address")
    return address if isinstance(address, str) and address else None


def is_coordinator(device: Device) -> bool:
    """Say whether this device is the radio itself, whose bindings are never ours."""
    return device["type"] == COORDINATOR_TYPE


def fingerprint_of(device: Device) -> ZigbeeFingerprint:
    """Return what identifies this device's model, which is what a profile is keyed by.

    Read from `definition`, which is the converter Zigbee2MQTT matched, rather than from the
    device's own `manufacturer` and `model_id`: the converter is what decides how the device
    is driven, and the coordinator has no definition at all.
    """
    definition = device.get("definition")
    if definition is None:
        return ZigbeeFingerprint(
            manufacturer=device.get("manufacturer", ""), model=device.get("model_id", "")
        )
    return ZigbeeFingerprint(manufacturer=definition["vendor"], model=definition["model"])


def handle_of(device: Device) -> DeviceHandle:
    """Return the handle a rule refers to this device by.

    **The IEEE address is the identity and the friendly name is not** (E23). Friendly names
    are renameable from the Zigbee2MQTT UI, and a handle keyed on one breaks silently the
    first time a user tidies their names up: the rule stops matching any device, the links
    it wrote become unmanaged, and nothing says why. So the name is carried as
    `name_at_authoring`, which takes no part in identity, and the request path resolves the
    current friendly name from the IEEE address at the moment it needs it.

    `ha_device_id` is left empty, for the reason `models.DeviceHandle` gives: it is
    convenience only, and resolving it needs the device registry, which needs `hass`.
    """
    return DeviceHandle(
        backend=BackendId.ZIGBEE2MQTT,
        protocol_id=device["ieee_address"],
        ha_device_id="",
        fingerprint=fingerprint_of(device),
        name_at_authoring=device["friendly_name"],
    )


def group_handle(group_id: int, friendly_name: str) -> DeviceHandle:
    """Return the handle a link uses when its target is a Zigbee group rather than a device."""
    return DeviceHandle(
        backend=BackendId.ZIGBEE2MQTT,
        protocol_id=f"{GROUP_PROTOCOL_PREFIX}{group_id}",
        ha_device_id="",
        fingerprint=GROUP_FINGERPRINT,
        name_at_authoring=friendly_name,
    )


def group_id_of(handle: DeviceHandle) -> int | None:
    """Return the group a handle names, or None when it names a device."""
    protocol_id = handle.protocol_id
    if not protocol_id.startswith(GROUP_PROTOCOL_PREFIX):
        return None
    rest = protocol_id.removeprefix(GROUP_PROTOCOL_PREFIX)
    return int(rest) if rest.isascii() and rest.isdecimal() else None


def managed_group_name(rule_id: str) -> str:
    """Return the name of the managed group belonging to one rule."""
    return f"{MANAGED_GROUP_PREFIX}{rule_id}"


def is_managed_group_name(friendly_name: str) -> bool:
    """Say whether this group is one of ours, which is the only kind we ever write to.

    The prefix is the whole of the test, deliberately. A user's own group is not ours to
    change, and there is nothing else about a group that says who made it, so the name is
    both the claim and the guard.
    """
    return friendly_name.startswith(MANAGED_GROUP_PREFIX)


def endpoint_ids(device: Device) -> tuple[int, ...]:
    """Return this device's endpoint numbers, lowest first."""
    return tuple(sorted(int(endpoint_id) for endpoint_id in device["endpoints"]))


def endpoint_of(device: Device, endpoint: int) -> Endpoint | None:
    """Return one endpoint of a device, or None when it does not report one."""
    return device["endpoints"].get(str(endpoint))


def emits(device: Device, endpoint: int, cluster: str) -> bool:
    """Say whether this endpoint drives this cluster, which is what a binding source needs."""
    reported = endpoint_of(device, endpoint)
    return reported is not None and cluster in reported["clusters"]["output"]


def accepts(device: Device, endpoint: int, cluster: str) -> bool:
    """Say whether this endpoint serves this cluster, which is what a binding target needs."""
    reported = endpoint_of(device, endpoint)
    return reported is not None and cluster in reported["clusters"]["input"]


def receivable_features(device: Device) -> frozenset[Feature]:
    """Return everything any endpoint of this device can be made to do by a binding.

    The union across endpoints, because `DeviceCapabilities.receivable` is about the device
    and the compiler asks it before it knows which endpoint a rule names. The endpoint is
    checked again on the write path, where the answer actually decides something.
    """
    found: set[Feature] = set()
    for reported in device["endpoints"].values():
        for cluster in reported["clusters"]["input"]:
            found |= features_of_cluster(cluster)
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class Control:
    """One control of a device: the emitter the compiler sees, and where it drives from.

    The endpoint is not on `Emitter`, because a Z-Wave control has no endpoint and the
    compiler must not learn about one. It is carried here instead, because the adapter needs
    it twice: to name the emitter an observed binding belongs to, and to check that a link's
    source endpoint really drives the cluster it claims.
    """

    emitter: Emitter
    endpoint: int


def derive_controls(device: Device, *, warnings: list[str] | None = None) -> list[Control]:
    """Return the controls this device offers, one per endpoint that drives something.

    One emitter per endpoint rather than per cluster, because an endpoint is the physical
    control: the Inovelli paddle is endpoint 2 and it drives `genOnOff` and `genLevelCtrl`
    together. An endpoint that drives nothing Device Links can use is dropped and reported
    to `warnings`, so `genOta` and `greenPower` never reach a user as a control they could
    pick and then find does nothing.
    """
    controls: list[Control] = []
    for endpoint in endpoint_ids(device):
        reported = device["endpoints"][str(endpoint)]
        actions = {
            feature: cluster
            for cluster in sorted(reported["clusters"]["output"])
            for feature in sorted(features_of_cluster(cluster))
        }
        if not actions:
            if warnings is not None and reported["clusters"]["output"]:
                warnings.append(
                    f"endpoint {endpoint} drives {sorted(reported['clusters']['output'])}, "
                    "none of which Device Links can bind, so it is not offered as a control"
                )
            continue
        controls.append(
            Control(
                emitter=_emitter(
                    emitter_id=f"ep{endpoint}",
                    label=reported.get("name") or f"Endpoint {endpoint}",
                    actions=actions,
                    grouping=GROUPING_ENDPOINT,
                ),
                endpoint=endpoint,
            )
        )
    return controls


def derive_emitters(device: Device, *, warnings: list[str] | None = None) -> list[Emitter]:
    """Return just the emitters of `derive_controls`, for a caller with no endpoint to place."""
    return [control.emitter for control in derive_controls(device, warnings=warnings)]


def resolve_controls(
    device: Device,
    entry: ZigbeeProfileEntry | None = None,
    *,
    warnings: list[str] | None = None,
) -> list[Control]:
    """Return a device's controls, preferring a curated entry over the generic derivation.

    A curated entry contributes the label, the kind of control it is, and any semantics
    marker; it does not restate what the device already reports, because the device is the
    better authority. An emitter that names an endpoint the device does not have, a cluster
    that endpoint does not drive, or a feature that cluster cannot carry, is dropped with the
    contradiction appended to `warnings`.

    **Dropped one emitter at a time, which is where this differs from the Z-Wave path.**
    There, an entry that contradicts the device is set aside whole, because its group numbers
    are what reach the radio and an entry shown to be wrong about one of them has not earned
    trust in the rest. Here the contradiction is nearly always a fact about the firmware
    rather than a mistake in the entry: two of the nine VZM31-SN switches in the G1 capture
    are on software 2.00 and report no endpoint 3 at all, while endpoint 2 is exactly as the
    entry describes it. Setting the whole entry aside would cost those two devices a correct
    paddle to punish the entry for describing a config button they do not have. If every
    emitter is dropped, the entry has said nothing usable and the generic derivation stands.

    A curated emitter covering exactly the endpoint and clusters a derived one covers is the
    same control described twice, so it keeps the derived id: adding a curated entry for a
    model whose derivation was already right must not rename controls out from under the
    rules already written against them.
    """
    derived = derive_controls(device, warnings=warnings)
    if entry is None:
        return derived
    derived_ids = {
        (control.endpoint, frozenset(control.emitter.group_ids)): control.emitter.emitter_id
        for control in derived
    }
    curated: list[Control] = []
    for profile_emitter in entry.emitters:
        conflicts = _emitter_conflicts(profile_emitter, device)
        if conflicts:
            if warnings is not None:
                warnings.extend(conflicts)
            continue
        clusters = frozenset(profile_emitter.actions.values())
        curated.append(
            Control(
                emitter=_emitter(
                    emitter_id=derived_ids.get(
                        (profile_emitter.endpoint, clusters), profile_emitter.emitter_id
                    ),
                    label=profile_emitter.label,
                    actions=profile_emitter.actions,
                    grouping=GROUPING_PROFILE_DB,
                    semantics=profile_emitter.semantics,
                ),
                endpoint=profile_emitter.endpoint,
            )
        )
    if not curated:
        return derived
    return sorted(curated, key=lambda control: control.endpoint)


def _emitter_conflicts(profile_emitter: ZigbeeProfileEmitter, device: Device) -> list[str]:
    """Return every way this curated emitter disagrees with what the device reports."""
    conflicts: list[str] = []
    endpoint = profile_emitter.endpoint
    for feature, cluster in sorted(profile_emitter.actions.items()):
        named = (
            f"profile entry maps {profile_emitter.emitter_id}.{feature} to {cluster} "
            f"on endpoint {endpoint}"
        )
        if endpoint_of(device, endpoint) is None:
            conflicts.append(f"{named}, which this device does not report")
        elif not emits(device, endpoint, cluster):
            conflicts.append(f"{named}, which that endpoint does not drive")
        elif feature not in features_of_cluster(cluster):
            conflicts.append(f"{named}, which cannot carry it")
    return conflicts


def _emitter(
    *,
    emitter_id: str,
    label: str,
    actions: Mapping[Feature, str],
    grouping: str,
    semantics: str | None = None,
) -> Emitter:
    """Assemble one emitter over the clusters it drives.

    `group_ids` holds the clusters, because that is what `Link.emitter_group` carries for
    Zigbee and what the planner counts capacity against. Two features pointing at one
    cluster appear once here and twice in `actions`, which is the honest shape: binding
    `genLevelCtrl` is one entry in the binding table that gives the user two things.
    """
    return Emitter(
        emitter_id=emitter_id,
        label=label,
        group_ids=tuple(sorted(set(actions.values()))),
        actions=dict(actions),
        capacity=BINDING_TABLE_CAPACITY,
        supports_endpoint_targets=True,
        is_lifeline=False,
        grouping=grouping,
        semantics=semantics,
    )


@dataclass(frozen=True, slots=True)
class ParsedBinding:
    """One binding read off a device, with its target resolved to one of the two shapes.

    Exactly one of `target_ieee` and `group_id` is set. `target_endpoint` accompanies
    `target_ieee`, because an endpoint target always names one.
    """

    endpoint: int
    cluster: str
    target_ieee: str | None
    target_endpoint: int | None
    group_id: int | None


def parse_bindings(device: Device) -> list[ParsedBinding]:
    """Return every binding on this device, in endpoint then declaration order.

    A target shape this version does not recognise is dropped rather than guessed at: a
    binding nobody can address is a binding nobody should be offered the chance to remove.
    """
    parsed: list[ParsedBinding] = []
    for endpoint in endpoint_ids(device):
        for binding in device["endpoints"][str(endpoint)]["bindings"]:
            target = binding["target"]
            if target["type"] == TARGET_ENDPOINT:
                parsed.append(
                    ParsedBinding(
                        endpoint=endpoint,
                        cluster=binding["cluster"],
                        target_ieee=target["ieee_address"],
                        target_endpoint=target["endpoint"],
                        group_id=None,
                    )
                )
            elif target["type"] == TARGET_GROUP:
                parsed.append(
                    ParsedBinding(
                        endpoint=endpoint,
                        cluster=binding["cluster"],
                        target_ieee=None,
                        target_endpoint=None,
                        group_id=target["id"],
                    )
                )
    return parsed


# --------------------------------------------------------------------------------------
# Requests. Everything below this line is modelled from the Zigbee2MQTT documentation and
# has never been performed against hardware: Stage 0 item G2 was not approved. See
# assumption A2 in docs/open-items.md and issue #6. When G2 runs, this is what gets
# corrected, together with the fake bridge that these payloads are currently proved against.
# --------------------------------------------------------------------------------------

# The request and response topics, relative to the configured base topic.
BIND_REQUEST: Final = "bridge/request/device/bind"
UNBIND_REQUEST: Final = "bridge/request/device/unbind"
BIND_RESPONSE: Final = "bridge/response/device/bind"
UNBIND_RESPONSE: Final = "bridge/response/device/unbind"
GROUP_ADD_REQUEST: Final = "bridge/request/group/add"
GROUP_REMOVE_REQUEST: Final = "bridge/request/group/remove"
GROUP_MEMBER_ADD_REQUEST: Final = "bridge/request/group/members/add"
GROUP_MEMBER_REMOVE_REQUEST: Final = "bridge/request/group/members/remove"
GROUP_ADD_RESPONSE: Final = "bridge/response/group/add"
GROUP_REMOVE_RESPONSE: Final = "bridge/response/group/remove"
GROUP_MEMBER_ADD_RESPONSE: Final = "bridge/response/group/members/add"
GROUP_MEMBER_REMOVE_RESPONSE: Final = "bridge/response/group/members/remove"

# The retained topics the read path is built on, all of which the G1 capture confirmed are
# retained and arrive on subscribe.
DEVICES_TOPIC: Final = "bridge/devices"
GROUPS_TOPIC: Final = "bridge/groups"
INFO_TOPIC: Final = "bridge/info"
STATE_TOPIC: Final = "bridge/state"

# What `bridge/state` says when the bridge is up. Anything else means the backend cannot
# answer for its devices, and E26 wants that logged once rather than on every read.
STATE_ONLINE: Final = "online"

# The two values `status` takes in a response.
STATUS_OK: Final = "ok"
STATUS_ERROR: Final = "error"


@dataclass(frozen=True, slots=True)
class BindRequest:
    """One bind or unbind, as the bridge is addressed for it.

    Named parts rather than six positional arguments, because five of them are strings and
    integers that would swap silently. `target` is a friendly name (a device's or a group's)
    and never an IEEE address: Zigbee2MQTT's request API is addressed by name, which is
    exactly why the handle keeps the IEEE address and the name is resolved here, at the
    moment the request is made (E23).

    `target_endpoint` is None for a group target, which has no endpoint, and set for an
    endpoint target, which always has one.
    """

    source_name: str
    source_endpoint: int
    target: str
    target_endpoint: int | None
    clusters: tuple[str, ...]
    transaction: str


def bind_payload(request: BindRequest) -> dict[str, object]:
    """Return the body of a bind request.

    `clusters` is always listed explicitly and never left out. Zigbee2MQTT binds every
    supported cluster when the key is absent, which on an Inovelli switch means binding
    `manuSpecificInovelli` and the metering clusters as well as the two the rule asked for.
    A rule that says "on/off and dimming" must produce exactly that and nothing else.

    NOTE: modelled from the Zigbee2MQTT documentation, never observed. Assumption A2,
    issue #6.
    """
    if not request.clusters:
        raise ValueError("a bind request must name at least one cluster")
    payload: dict[str, object] = {
        "from": request.source_name,
        "from_endpoint": request.source_endpoint,
        "to": request.target,
        "clusters": list(request.clusters),
        "transaction": request.transaction,
    }
    if request.target_endpoint is not None:
        payload["to_endpoint"] = request.target_endpoint
    return payload


def unbind_payload(
    request: BindRequest, *, skip_disable_reporting: bool = False
) -> dict[str, object]:
    """Return the body of an unbind request.

    `skip_disable_reporting` is the one field an unbind has that a bind does not, and it
    matters: unbinding removes the attribute reporting Zigbee2MQTT configured on that
    cluster unless it is set (CLAUDE.md Section 10), which is why the plan says so before a
    user confirms one. It defaults to False, which is Zigbee2MQTT's own default, so what
    Device Links does is what the bridge would do rather than a quiet divergence.

    NOTE: modelled from the Zigbee2MQTT documentation, never observed. Assumption A2,
    issue #6.
    """
    payload = bind_payload(request)
    if skip_disable_reporting:
        payload["skip_disable_reporting"] = True
    return payload


def group_add_payload(*, friendly_name: str, transaction: str) -> dict[str, object]:
    """Return the body of a request to create one managed group.

    NOTE: modelled, never observed. Assumption A2, issue #6.
    """
    _refuse_foreign_group(friendly_name)
    return {"friendly_name": friendly_name, "transaction": transaction}


def group_remove_payload(*, friendly_name: str, transaction: str) -> dict[str, object]:
    """Return the body of a request to delete one managed group.

    NOTE: modelled, never observed. Assumption A2, issue #6.
    """
    _refuse_foreign_group(friendly_name)
    return {"id": friendly_name, "transaction": transaction}


def group_member_payload(
    *,
    friendly_name: str,
    device_name: str,
    endpoint: int,
    transaction: str,
) -> dict[str, object]:
    """Return the body of a request to add or remove one member of a managed group.

    NOTE: modelled, never observed. Assumption A2, issue #6.
    """
    _refuse_foreign_group(friendly_name)
    return {
        "group": friendly_name,
        "device": device_name,
        "endpoint": endpoint,
        "transaction": transaction,
    }


class ForeignGroupError(ValueError):
    """A group without the `dl_` prefix was about to be written to.

    Raised rather than returned, because there is no legitimate caller: every group Device
    Links touches it created, and a group it did not create is somebody's own work. This is
    the guard that makes managed groups safe to ship, so it lives in the pure module where
    every payload builder passes through it and no adapter can route around it.
    """


def _refuse_foreign_group(friendly_name: str) -> None:
    """Refuse to build a request that would change a group Device Links did not create."""
    if not is_managed_group_name(friendly_name):
        raise ForeignGroupError(
            f"{friendly_name!r} does not start with {MANAGED_GROUP_PREFIX!r}, so it is not a "
            "group Device Links created and is never ours to change"
        )


@dataclass(frozen=True, slots=True)
class BridgeResponse:
    """One `bridge/response/...` message, read the way the documentation describes it.

    The whole reason this is a type rather than a dictionary lookup is `succeeded`.
    Zigbee2MQTT reports `status: "error"` **only when every cluster failed**. A bind where
    `genOnOff` was written and `genLevelCtrl` was not comes back as `status: "ok"` with
    `genLevelCtrl` in `failed`, so the naive check reports the link as applied while the
    user has a paddle that switches a light on and cannot dim it, and the panel says
    everything is fine. Nothing in this codebase may compare `status` to `"ok"` directly.

    NOTE: modelled from the Zigbee2MQTT documentation, never observed. Assumption A2,
    issue #6. `tests/fakes/zigbee.py` is the model this is proved against, and it is what
    gets corrected when G2 finally runs.
    """

    status: str
    failed: tuple[str, ...]
    requested: tuple[str, ...]
    error: str | None
    transaction: str | None
    group_id: int | None

    @property
    def succeeded(self) -> bool:
        """Say whether everything asked for actually happened, and nothing less."""
        return self.status == STATUS_OK and not self.failed

    @property
    def partly_failed(self) -> bool:
        """Say whether the bridge reported success while some clusters did not bind."""
        return self.status == STATUS_OK and bool(self.failed)

    @property
    def written(self) -> tuple[str, ...]:
        """Return the clusters that were asked for and are not in `failed`."""
        return tuple(cluster for cluster in self.requested if cluster not in self.failed)


def parse_response(payload: Mapping[str, object]) -> BridgeResponse:
    """Read one bridge response, defensively, because it arrives off a broker.

    Anything missing or of the wrong type is read as absent rather than raising: a response
    that cannot be understood must leave the caller waiting for one it can, not take down
    the subscription that would deliver it.
    """
    data = payload.get("data")
    data_map: Mapping[str, object] = data if isinstance(data, dict) else {}
    return BridgeResponse(
        status=_text(payload.get("status")) or "",
        failed=_clusters(data_map.get("failed")),
        requested=_clusters(data_map.get("clusters")),
        error=_text(payload.get("error")),
        transaction=_text(payload.get("transaction")) or _text(data_map.get("transaction")),
        # A group creation answers with the id it allocated. Read here rather than looked
        # up in `bridge/groups` afterwards, because the request path would otherwise depend
        # on the bridge republishing its retained state before it answers, which nobody has
        # measured (assumption A2 again).
        group_id=_whole_number(data_map.get("id")),
    )


def _clusters(raw: object) -> tuple[str, ...]:
    """Return a list of cluster names from a payload field, or nothing at all."""
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


def _text(raw: object) -> str | None:
    """Return a payload field as text when it is text, and None otherwise."""
    return raw if isinstance(raw, str) else None


def _whole_number(raw: object) -> int | None:
    """Return a payload field as a whole number when it is one, and None otherwise.

    `bool` is excluded because JSON `true` parses to a Python `bool`, which is an `int`,
    and a group whose id came out as 1 that way would be the wrong group.
    """
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def clusters_for(features: Iterable[Feature]) -> tuple[str, ...]:
    """Return the clusters that carry these features, each named once, in a stable order."""
    named = {CLUSTER_BY_FEATURE[feature] for feature in features if feature in CLUSTER_BY_FEATURE}
    return tuple(sorted(named))
