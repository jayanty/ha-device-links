"""Value types shared by every layer, and the link identity they are built around.

This module is pure: it imports no Home Assistant, does no I/O and reads no clock, so it can
be exercised by unit tests without the HA harness and reused from `tools/` probe scripts.
Every type here is frozen, because plans are compared and hashed and a mutable value type
would corrupt that silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
import re
from typing import Final


class Backend(StrEnum):
    """A link protocol Device Links can drive."""

    ZWAVE = "zwave"
    ZIGBEE2MQTT = "zigbee2mqtt"
    MATTER = "matter"


class Feature(StrEnum):
    """What a link carries from a control to a target device."""

    ON_OFF = "on_off"
    LEVEL_SET = "level_set"
    LEVEL_HOLD = "level_hold"
    SCENE = "scene"
    COLOR = "color"
    STATUS_REPORT = "status_report"


@dataclass(frozen=True, slots=True)
class ZWaveFingerprint:
    """What identifies a Z-Wave device model, as the driver reports it."""

    manufacturer_id: int
    product_type: int
    product_id: int
    firmware: str


@dataclass(frozen=True, slots=True)
class ZigbeeFingerprint:
    """What identifies a Zigbee device model, as Zigbee2MQTT reports it."""

    manufacturer: str
    model: str


@dataclass(frozen=True, slots=True)
class MatterFingerprint:
    """What identifies a Matter device model, as the Matter server reports it."""

    vendor: str
    product: str


type DeviceFingerprint = ZWaveFingerprint | ZigbeeFingerprint | MatterFingerprint


@dataclass(frozen=True, slots=True)
class DeviceHandle:
    """A device as a rule refers to it, stable across renames and area moves.

    `protocol_id` is the network-level address (`<home id>:<node id>` for Z-Wave, the IEEE
    address for Zigbee, the node id for Matter). `ha_device_id` and `name_at_authoring` are
    convenience only: neither takes part in identity, so renaming a device or rebuilding the
    device registry never invalidates a rule.
    """

    backend: Backend
    protocol_id: str
    ha_device_id: str
    fingerprint: DeviceFingerprint
    name_at_authoring: str

    @property
    def identity(self) -> str:
        """The device's identity: its backend and its protocol address, nothing else."""
        return f"{self.backend}:{self.protocol_id}"


@dataclass(frozen=True, slots=True)
class LinkTarget:
    """The receiving end of a link. `endpoint` is None when the target is the whole device."""

    handle: DeviceHandle
    endpoint: int | None


# A per-group emitter is named after the single group it uses ("g7", or a bare "7"). Any
# other emitter id can span several groups, so its group must be stated rather than guessed.
_SINGLE_GROUP_EMITTER_ID: Final = re.compile(r"g?(\d+)")

# Fingerprint fields are joined with this separator and escaped, so no field value can
# impersonate a field boundary and let two different links share one identity.
_SEPARATOR: Final = "|"
_ESCAPE: Final = "\\"


def _single_group_of(emitter_id: str) -> str | None:
    """Return the group a per-group emitter id names, or None when it names no single group."""
    match = _SINGLE_GROUP_EMITTER_ID.fullmatch(emitter_id)
    return None if match is None else match.group(1)


def _escaped(value: str) -> str:
    """Escape the separator so the joined fingerprint stays unambiguous."""
    return value.replace(_ESCAPE, _ESCAPE * 2).replace(_SEPARATOR, _ESCAPE + _SEPARATOR)


@dataclass(frozen=True, slots=True)
class Link:
    """One link Device Links wants on a device: this control, this target, this feature.

    `emitter_id` is the control the user picked. `emitter_group` is the association group
    that control uses for this feature, which is what actually gets written to the device:
    one emitter can span several groups (the Inovelli paddle is one paddle writing into
    groups 2, 3 and 4), so the group, not the emitter, is what makes two links different
    device writes. Leave `emitter_group` unset only when `emitter_id` names a single group.
    """

    backend: Backend
    source: DeviceHandle
    source_endpoint: int
    emitter_id: str
    target: LinkTarget
    feature: Feature
    emitter_group: str = ""
    rule_id: str | None = None

    def __post_init__(self) -> None:
        """Reject impossible links and resolve the group this link is written to."""
        if self.source.identity == self.target.handle.identity:
            raise ValueError(f"{self.source.identity} cannot control itself")
        if not self.emitter_group:
            group = _single_group_of(self.emitter_id)
            if group is None:
                raise ValueError(
                    f"emitter {self.emitter_id!r} does not name a single group, "
                    "so emitter_group must be given"
                )
            object.__setattr__(self, "emitter_group", group)

    @property
    def fingerprint(self) -> str:
        """The link's identity: exactly what is written to the device, and nothing else.

        Derived from the backend, the source device and endpoint, the association group, the
        target device and endpoint, and the feature. Renaming a device or moving a link to
        another rule leaves it unchanged; changing the group, the target or the endpoint
        changes it. The result is a plain string so it is stable across processes and
        restarts, and readable in storage and diagnostics.
        """
        return _SEPARATOR.join(
            _escaped(part)
            for part in (
                str(self.backend),
                self.source.identity,
                str(self.source_endpoint),
                self.emitter_group,
                self.target.handle.identity,
                "" if self.target.endpoint is None else str(self.target.endpoint),
                str(self.feature),
            )
        )

    def as_kwargs(self) -> dict[str, object]:
        """Return the keyword arguments that reconstruct this link, for copy-with-changes.

        `emitter_group` is omitted when it is only what `emitter_id` already implies, so that
        a copy which overrides `emitter_id` does not silently keep the old group.
        """
        kwargs: dict[str, object] = {f.name: getattr(self, f.name) for f in fields(self)}
        if kwargs["emitter_group"] == _single_group_of(self.emitter_id):
            del kwargs["emitter_group"]
        return kwargs


@dataclass(frozen=True, slots=True)
class ObservedLink(Link):
    """A link read back from a device, carrying who (if anyone) owns it.

    It shares `Link`'s fingerprint derivation, so a desired link and an observed one that
    describe the same device state have the same identity. `is_system` marks the links that
    are never ours to remove (Z-Wave lifelines, Zigbee coordinator bindings, Matter Administer
    ACL entries) and has no default, because defaulting it would let one pass as removable.
    """

    is_system: bool = field(kw_only=True)
    managed_by: str | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class Emitter:
    """One physical control on a device, with the group each of its features uses.

    `actions` is the bridge to `Link.emitter_group`: the compiler looks up the group that
    carries the feature it wants and puts that group on the link it produces. `semantics` is
    set when something about what this control sends is not established, which the compiler
    has to be careful about; see `profile_db.SEMANTICS_MARKERS`.
    """

    emitter_id: str
    label: str
    group_ids: tuple[str, ...]
    actions: Mapping[Feature, str]
    capacity: int
    supports_endpoint_targets: bool
    is_lifeline: bool
    grouping: str
    semantics: str | None = None


@dataclass(frozen=True, slots=True)
class SettingsAdapter:
    """How to reach one named device setting: a parameter, optionally one bit of it."""

    parameter: int
    bitmask: int | None
    values: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    """What a device can do, as the compiler and the planner need to know it.

    `receivable` is what the device can act on when it is a target, so a link that could do
    nothing is rejected at compile time rather than written and left silently dead.
    """

    handle: DeviceHandle
    emitters: tuple[Emitter, ...]
    receivable: frozenset[Feature]
    is_long_range: bool
    settings: Mapping[str, SettingsAdapter] = field(default_factory=dict)


class Template(StrEnum):
    """The intent a rule was authored with, which decides how it compiles."""

    REMOTE = "remote"
    VIRTUAL_3WAY = "virtual_3way"
    SCENE_BUTTON = "scene_button"
    OFF_ALL = "off_all"
    STATUS_FEEDBACK = "status_feedback"
    CUSTOM = "custom"


class Direction(StrEnum):
    """Whether a rule also compiles the reverse links."""

    ONE_WAY = "one_way"
    TWO_WAY = "two_way"


class MirrorChoice(StrEnum):
    """What a rule asks of the source device's "mirror hub commands" setting.

    `LEAVE` is a genuine no-op and the default: the setting is global to the device, so a
    rule that did not ask about it must not write it back, not even to its current value.
    """

    ON = "on"
    OFF = "off"
    LEAVE = "leave"


@dataclass(frozen=True, slots=True)
class RuleSource:
    """The control a rule starts from: a device, an endpoint, and one of its emitters."""

    device: DeviceHandle
    endpoint: int
    emitter_id: str


@dataclass(frozen=True, slots=True)
class RuleTarget:
    """A device a rule drives. `endpoint` is None when the target is the whole device."""

    device: DeviceHandle
    endpoint: int | None


@dataclass(frozen=True, slots=True)
class Rule:
    """One unit of user intent, and the unit of enable and disable.

    A rule says what should happen, not what to write: the compiler turns it into links and
    setting writes against a device's real capabilities. It is frozen and validated on
    construction, so a rule that could never compile into anything cannot be stored.
    """

    id: str
    name: str
    template: Template
    backend: Backend
    source: RuleSource
    targets: tuple[RuleTarget, ...]
    features: frozenset[Feature]
    direction: Direction = Direction.ONE_WAY
    mirror_source: MirrorChoice = MirrorChoice.LEAVE
    enabled: bool = True

    def __post_init__(self) -> None:
        """Reject a rule that could not compile into a single link."""
        if not self.targets:
            raise ValueError(f"rule {self.id} needs at least one target")
        if not self.features:
            raise ValueError(f"rule {self.id} needs at least one feature")
        seen: set[RuleTarget] = set()
        for target in self.targets:
            if target in seen:
                raise ValueError(
                    f"rule {self.id} has a duplicate target: "
                    f"{target.device.identity} endpoint {target.endpoint}"
                )
            seen.add(target)

    def with_enabled(self, enabled: bool) -> Rule:
        """Return a copy of this rule, enabled or disabled.

        Disabling is not deleting (FR-R5): the links a disabled rule owns are planned for
        removal, but the intent is kept so re-enabling restores it exactly.
        """
        return replace(self, enabled=enabled)


@dataclass(frozen=True, slots=True)
class Profile:
    """A named set of rules, of which one is active at a time (Decision D10)."""

    id: str
    name: str
    rules: tuple[Rule, ...]

    def __post_init__(self) -> None:
        """Reject two rules sharing an id, which would make the rule id ambiguous."""
        seen: set[str] = set()
        for rule in self.rules:
            if rule.id in seen:
                raise ValueError(f"profile {self.id} has a duplicate rule id: {rule.id}")
            seen.add(rule.id)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Something the user has to be told, as a key rather than a sentence.

    `translation_key` names the message in `strings.json` and `placeholders` fills it in, so
    every warning, error and blocked reason this core produces is translatable (CLAUDE.md
    Section 7). Nothing in here is ever an English sentence.
    """

    translation_key: str
    placeholders: Mapping[str, str] = field(default_factory=dict)

    @property
    def identity(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        """A hashable form of this diagnostic, for reporting one exactly once."""
        return (self.translation_key, tuple(sorted(self.placeholders.items())))


@dataclass(frozen=True, slots=True)
class SettingWrite:
    """One device setting a rule needs, resolved to the parameter that carries it.

    `capability` is the name the profile database gives the setting; `parameter`, `bitmask`
    and `value` are what actually reaches the device. `bitmask` is None when the setting owns
    the whole parameter.
    """

    device: DeviceHandle
    capability: str
    parameter: int
    bitmask: int | None
    value: int


@dataclass(frozen=True, slots=True)
class HybridLeg:
    """A leg of a rule no link can express, which an automation has to carry instead.

    Decision D3 puts hybrid legs in Phase 2, so nothing compiles one yet. The type exists
    because `CompiledRule` reports them, and a rule that needs one has to be able to say so
    without the result type changing shape later.
    """

    rule_id: str
    source: DeviceHandle
    emitter_id: str
    feature: Feature
    target: LinkTarget


class PlanOp(StrEnum):
    """What one step of a plan does to a device."""

    ADD = "add"
    REMOVE = "remove"
    SET_PARAM = "set_param"
    BLOCKED = "blocked"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class PlanItem:
    """One step of a plan, against one device.

    A `REMOVE` always carries the link as it was observed, never a rebuilt desired one, so
    that whoever applies it can see `is_system` and `managed_by` for the entry it is about
    to take off the device.
    """

    op: PlanOp
    device_identity: str
    link: Link | ObservedLink | None = None
    setting: SettingWrite | None = None
    reason: Diagnostic | None = None


@dataclass(frozen=True, slots=True)
class Plan:
    """Everything that would happen if this plan were applied, and nothing that would not.

    `token` identifies the inputs the plan was built from, so applying a plan built against
    a device state that has since changed is refused rather than performed (FR-A3).
    `unmanaged` reports links Device Links did not create: they are never in `items` unless
    the user selected them by fingerprint (Decision D9).
    """

    token: str
    items: tuple[PlanItem, ...]
    unmanaged: tuple[ObservedLink, ...]
    unchanged_count: int

    @property
    def is_empty(self) -> bool:
        """Say whether applying this plan would do nothing at all."""
        return not self.items

    def by_device(self) -> Mapping[str, tuple[PlanItem, ...]]:
        """Group the items by the device they are written to, in plan order.

        The apply dialog and the executor both work a device at a time: one device is one
        radio conversation, and one device is what a user decides about.
        """
        grouped: dict[str, list[PlanItem]] = {}
        for item in self.items:
            grouped.setdefault(item.device_identity, []).append(item)
        return {identity: tuple(items) for identity, items in grouped.items()}
