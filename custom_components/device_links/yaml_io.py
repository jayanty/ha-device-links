"""Profile export and import: the file a user keeps in git, and reading it back.

This module is pure. It imports no Home Assistant, opens no file and reads no clock: text
comes in, text goes out, and the caller owns the file. `yaml` is a third-party package that
Home Assistant already ships, so importing it adds no requirement and breaks no rule;
`homeassistant.util.yaml` would, and is not used.

Two properties are load-bearing, and everything else here follows from them.

**The same profile always produces the same bytes.** An export exists so a design can live
in version control (FR-P2), and a file that churns on every save makes a diff worthless.
Nothing is written in the order it happened to be built: mappings are sorted by
`yaml.safe_dump(sort_keys=True)`, the device block is assembled in sorted key order so the
JSON form storage keeps is stable too, and every `frozenset` (rule features) is sorted
before it is written. The only ordered thing in the file is the rule list, which is the
user's own order and is theirs to keep.

**Identity is `protocol_id`, and names are for the reader.** `ha_device_id` is the local
device registry's id: it means nothing on the instance the file is imported into, so it is
not exported at all, and an imported handle carries an empty one until the coordinator
resolves it here. `name_at_authoring` is exported, because a file of bare node ids is
unreadable in a diff and reviewing the diff is half the reason to keep one. It is written
under a `name` key, said to be informational in the file's own header, and never matched
on: renaming a device in the file changes what a human reads and nothing about which
device a rule means.

The same conversion serves storage, through `profile_to_data`, `profile_from_data` and the
observed-link pair snapshots are built from. Keeping one codec is deliberate: two would
drift, and the way a second serializer drifts from the first is by quietly losing a field
somebody's rules depended on. It lives here, in the pure module, because turning a value
type into plain data is exactly as pure as the value types themselves, and because this is
where the narrowing that makes reading untrusted data safe already is.

Error messages here are English rather than translation keys, unlike the `Diagnostic`s the
compiler and planner produce. They are about the text of a file: a line number, a key name
and a rule id. The Home Assistant layer surfaces them as the detail of one translated
"import failed" message rather than translating "line 4, column 8" itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import StrEnum
from typing import Final

import yaml

from custom_components.device_links.models import (
    Backend,
    DeviceFingerprint,
    DeviceHandle,
    Direction,
    Feature,
    HybridKind,
    LinkTarget,
    MatterFingerprint,
    MirrorChoice,
    ObservedLink,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
    ZigbeeFingerprint,
    ZWaveFingerprint,
)

SCHEMA_VERSION: Final = 1

# What every exported profile begins with, **without the schema version**. Named because
# it is load-bearing beyond documentation: the YAML mirror deletes a file only when it
# starts with this, so "is this file one of ours" is a fact about the file rather than
# about what somebody remembers writing, and a mirror pointed at the wrong directory
# cannot delete anything else.
#
# The version is deliberately not in it. A file this integration wrote at schema version 1
# is still a file this integration wrote when the schema goes to 2, and a prefix carrying
# the version would make every existing mirror file unrecognisable, and therefore
# unprunable, on the day it changes.
HEADER_PREFIX: Final = "# Device Links profile, schema version "

# The header is fixed text, so it costs the export nothing in determinism, and it is the
# only place the file can explain itself to somebody reading a pull request.
_HEADER: Final = f"""\
{HEADER_PREFIX}{SCHEMA_VERSION}.
#
# A device is identified by its `protocol_id`, the address it has on its own network
# ("<home id>:<node id>" for Z-Wave). The `name` on each device is informational: it is
# what the device was called when the rule was written, so this file reads as something
# about a home rather than about node numbers. Nothing matches on it, so renaming a device
# here changes what a person reads and nothing about what the rules mean.
#
# Nothing local to one Home Assistant is exported, so this file means the same thing on
# another instance: the device registry id a rule was authored against is left out on
# purpose, and is resolved from the network address on import.
"""


class ProfileFormatError(ValueError):
    """A profile file that cannot be read, and exactly which part of it cannot be.

    Raised with everything wrong that could be found rather than only the first thing, so
    one import produces one round of editing. "Invalid profile" in a file with forty rules
    is unactionable, so every message names the rule it is about, by id where the file
    gives a usable one and by index where it does not.
    """


def dump_profile(profile: Profile) -> str:
    """Return this profile as the YAML text a user keeps in version control.

    Deterministic: the same profile produces byte-identical text, in this process and in
    any other, so a diff moves only when the profile really changed.
    """
    payload = {"version": SCHEMA_VERSION, "profile": profile_to_data(profile)}
    return _HEADER + yaml.safe_dump(
        payload, sort_keys=True, default_flow_style=False, allow_unicode=True, width=100
    )


def parse_profile(text: str) -> Profile:
    """Return the profile this text describes, or say what is wrong with it.

    Reading is the dangerous direction: this is the one place a file somebody edited by
    hand becomes rules that will be written to radios, so everything is checked here and
    nothing downstream has to re-check it.
    """
    try:
        loaded: object = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ProfileFormatError(f"this is not valid YAML: {error}") from error

    document = _require_mapping(loaded, "the file")
    if "version" not in document:
        raise ProfileFormatError(
            f"the file has no schema version; this Home Assistant writes version {SCHEMA_VERSION}"
        )
    version = _require_int(document["version"], "the schema version")
    if version != SCHEMA_VERSION:
        raise ProfileFormatError(
            f"the file is schema version {version}, and this Home Assistant supports "
            f"version {SCHEMA_VERSION}. A newer file is not guessed at: upgrade Home "
            f"Assistant, or export the profile again from the instance that wrote it"
        )
    if "profile" not in document:
        raise ProfileFormatError("the file has no profile in it")
    return profile_from_data(document["profile"])


def profile_to_data(profile: Profile, *, keep_local_ids: bool = False) -> dict[str, object]:
    """Return this profile as plain data, ready to be dumped as YAML or stored as JSON.

    `keep_local_ids` keeps `ha_device_id`, which storage wants (it is this instance's own
    registry, and re-resolving it on every restart is work for nothing) and an export must
    not have (it is meaningless anywhere else).
    """
    devices: dict[str, dict[str, object]] = {}
    for handle in _handles_of(profile):
        devices.setdefault(handle.identity, _device_to_data(handle, keep_local_ids=keep_local_ids))
    return {
        "id": profile.id,
        "name": profile.name,
        "devices": dict(sorted(devices.items())),
        "rules": [_rule_to_data(rule) for rule in profile.rules],
    }


def profile_from_data(data: object) -> Profile:
    """Return the profile this data describes, reporting everything wrong with it."""
    payload = _require_mapping(data, "the profile")
    devices = _devices_from_data(payload.get("devices"))
    rules: list[Rule] = []
    problems: list[str] = []
    for index, raw in enumerate(_require_sequence(payload.get("rules"), "the profile's rules")):
        try:
            rules.append(_rule_from_data(raw, index, devices))
        except ProfileFormatError as error:
            problems.append(str(error))
    if problems:
        raise ProfileFormatError("; ".join(problems))
    try:
        profile = Profile(
            id=_require_str(payload.get("id"), "the profile id"),
            name=_require_str(payload.get("name"), "the profile name"),
            rules=tuple(rules),
        )
    except ValueError as error:
        raise ProfileFormatError(f"this is not a usable profile: {error}") from error
    return profile


def devices_to_data(handles: Iterable[DeviceHandle]) -> dict[str, object]:
    """Return these devices keyed by identity, as the rule reader expects to be given them.

    The WebSocket API takes a rule that refers to devices by identity and resolves those
    identities against the network rather than against a device block the client sent.
    That is what makes a rule naming a device this network does not have a refusal (E38)
    rather than a rule about a device somebody described in a payload.
    """
    return {handle.identity: _device_to_data(handle, keep_local_ids=False) for handle in handles}


def rule_to_data(rule: Rule) -> dict[str, object]:
    """Return one rule as plain data, referring to its devices by identity."""
    return _rule_to_data(rule)


def rule_from_data(value: object, devices: Mapping[str, DeviceHandle]) -> Rule:
    """Return the rule this data describes, or say exactly what is wrong with it."""
    return _rule_from_data(value, 0, devices)


def observed_link_to_data(link: ObservedLink) -> dict[str, object]:
    """Return one observed link as plain data, devices and all.

    Snapshots are what a rollback is rebuilt from, so this keeps the whole link rather than
    its fingerprint: `is_system` and `managed_by` decide what may be done to an entry, and a
    snapshot that dropped them would come back as a set of links nobody knows the status of.
    Each device is written inline rather than referenced, so one link is readable and
    restorable on its own.
    """
    return {
        "backend": str(link.backend),
        "source": _device_to_data(link.source, keep_local_ids=True),
        "source_endpoint": link.source_endpoint,
        "emitter_id": link.emitter_id,
        "emitter_group": link.emitter_group,
        "target": {
            "device": _device_to_data(link.target.handle, keep_local_ids=True),
            "endpoint": link.target.endpoint,
        },
        "feature": str(link.feature),
        "rule_id": link.rule_id,
        "is_system": link.is_system,
        "managed_by": link.managed_by,
    }


def observed_link_from_data(value: object) -> ObservedLink:
    """Return the observed link this data describes."""
    fields = _require_mapping(value, "the link")
    target = _require_mapping(fields.get("target"), "the link target")
    managed_by = fields.get("managed_by")
    rule_id = fields.get("rule_id")
    try:
        link = ObservedLink(
            backend=_enum(Backend, fields.get("backend"), "the link backend"),
            source=_device_from_data(fields.get("source"), "the link source"),
            source_endpoint=_require_int(fields.get("source_endpoint"), "the link source endpoint"),
            emitter_id=_require_str(fields.get("emitter_id"), "the link control"),
            emitter_group=_require_str(fields.get("emitter_group"), "the link group"),
            target=LinkTarget(
                handle=_device_from_data(target.get("device"), "the link target"),
                endpoint=_optional_int(target.get("endpoint"), "the link target endpoint"),
            ),
            feature=_enum(Feature, fields.get("feature"), "the link feature"),
            rule_id=None if rule_id is None else _require_str(rule_id, "the link rule"),
            is_system=_require_bool(fields.get("is_system"), "the link system flag"),
            managed_by=None if managed_by is None else _require_str(managed_by, "the link owner"),
        )
    except ValueError as error:
        if isinstance(error, ProfileFormatError):
            raise
        raise ProfileFormatError(f"this is not a usable link: {error}") from error
    return link


# Writing.


def _handles_of(profile: Profile) -> Iterator[DeviceHandle]:
    """Yield every device handle the profile mentions, in the order the rules mention them."""
    for rule in profile.rules:
        yield rule.source.device
        for target in rule.targets:
            yield target.device


def _device_to_data(handle: DeviceHandle, *, keep_local_ids: bool) -> dict[str, object]:
    """Return one device as the file describes it, under its identity."""
    data: dict[str, object] = {
        "backend": str(handle.backend),
        "protocol_id": handle.protocol_id,
        "name": handle.name_at_authoring,
        "fingerprint": _fingerprint_to_data(handle.fingerprint),
    }
    if keep_local_ids:
        data["ha_device_id"] = handle.ha_device_id
    return data


def _fingerprint_to_data(fingerprint: DeviceFingerprint) -> dict[str, object]:
    """Return the model identity of a device, in the shape its protocol reports it."""
    if isinstance(fingerprint, ZWaveFingerprint):
        return {
            "manufacturer_id": fingerprint.manufacturer_id,
            "product_type": fingerprint.product_type,
            "product_id": fingerprint.product_id,
            "firmware": fingerprint.firmware,
        }
    if isinstance(fingerprint, ZigbeeFingerprint):
        return {"manufacturer": fingerprint.manufacturer, "model": fingerprint.model}
    return {"vendor": fingerprint.vendor, "product": fingerprint.product}


def _rule_to_data(rule: Rule) -> dict[str, object]:
    """Return one rule as the file describes it, referring to devices by identity."""
    return {
        "id": rule.id,
        "name": rule.name,
        "template": str(rule.template),
        "backend": str(rule.backend),
        "enabled": rule.enabled,
        "direction": str(rule.direction),
        "mirror_source": str(rule.mirror_source),
        "features": sorted(str(feature) for feature in rule.features),
        # Always written, even when empty, so a file says out loud that this rule asks
        # nothing of Home Assistant rather than leaving it to be inferred from silence.
        "hybrid": sorted(str(kind) for kind in rule.hybrid),
        "source": {
            "device": rule.source.device.identity,
            "endpoint": rule.source.endpoint,
            "emitter_id": rule.source.emitter_id,
        },
        "targets": [
            {"device": target.device.identity, "endpoint": target.endpoint}
            for target in rule.targets
        ],
    }


# Reading.


def _device_from_data(value: object, what: str) -> DeviceHandle:
    """Return the device this data describes."""
    fields = _require_mapping(value, what)
    backend = _enum(Backend, fields.get("backend"), f"{what} backend")
    return DeviceHandle(
        backend=backend,
        protocol_id=_require_str(fields.get("protocol_id"), f"{what} address"),
        ha_device_id=_require_str(fields.get("ha_device_id", ""), f"{what} id"),
        fingerprint=_fingerprint_from_data(backend, fields.get("fingerprint"), f"{what} model"),
        name_at_authoring=_require_str(fields.get("name", ""), f"{what} name"),
    )


def _devices_from_data(value: object) -> dict[str, DeviceHandle]:
    """Return the devices the file describes, keyed by the identity it files them under."""
    entries = _require_mapping(value, "the profile's devices")
    devices: dict[str, DeviceHandle] = {}
    for identity, raw in entries.items():
        handle = _device_from_data(raw, f"device {identity!r}")
        if handle.identity != identity:
            raise ProfileFormatError(
                f"device {identity!r} is filed under an address it disagrees with: it says "
                f"it is {handle.identity!r}"
            )
        devices[identity] = handle
    return devices


def _fingerprint_from_data(backend: Backend, value: object, what: str) -> DeviceFingerprint:
    """Return the model identity this data describes, in the shape its backend uses."""
    fields = _require_mapping(value, what)
    if backend is Backend.ZWAVE:
        return ZWaveFingerprint(
            manufacturer_id=_require_int(fields.get("manufacturer_id"), f"{what} manufacturer"),
            product_type=_require_int(fields.get("product_type"), f"{what} product type"),
            product_id=_require_int(fields.get("product_id"), f"{what} product id"),
            firmware=_require_str(fields.get("firmware"), f"{what} firmware"),
        )
    if backend is Backend.ZIGBEE2MQTT:
        return ZigbeeFingerprint(
            manufacturer=_require_str(fields.get("manufacturer"), f"{what} manufacturer"),
            model=_require_str(fields.get("model"), f"{what} model"),
        )
    return MatterFingerprint(
        vendor=_require_str(fields.get("vendor"), f"{what} vendor"),
        product=_require_str(fields.get("product"), f"{what} product"),
    )


def _rule_from_data(value: object, index: int, devices: Mapping[str, DeviceHandle]) -> Rule:
    """Return one rule, named in every message by its id or, failing that, by its index."""
    raw = value if isinstance(value, Mapping) else None
    label = _rule_label(None if raw is None else raw.get("id"), index)
    fields = _require_mapping(value, label)

    targets = _require_sequence(fields.get("targets"), f"{label} targets")
    if not targets:
        raise ProfileFormatError(f"{label} has no targets, so it could never do anything")
    features = _require_sequence(fields.get("features"), f"{label} features")
    if not features:
        raise ProfileFormatError(f"{label} has no features, so it could never do anything")

    try:
        rule = Rule(
            id=_require_str(fields.get("id"), f"{label} id"),
            name=_require_str(fields.get("name"), f"{label} name"),
            template=_enum(Template, fields.get("template"), f"{label} template"),
            backend=_enum(Backend, fields.get("backend"), f"{label} backend"),
            source=_source_from_data(fields.get("source"), label, devices),
            targets=tuple(
                RuleTarget(
                    device=_device_of(
                        _require_mapping(target, f"{label} target").get("device"), label, devices
                    ),
                    endpoint=_optional_int(
                        _require_mapping(target, f"{label} target").get("endpoint"),
                        f"{label} target endpoint",
                    ),
                )
                for target in targets
            ),
            features=frozenset(_enum(Feature, feature, f"{label} feature") for feature in features),
            direction=_enum(Direction, fields.get("direction"), f"{label} direction"),
            mirror_source=_enum(
                MirrorChoice, fields.get("mirror_source"), f"{label} mirror choice"
            ),
            enabled=_require_bool(fields.get("enabled"), f"{label} enabled flag"),
            # Absent means none, which is what every file written before hybrid legs
            # existed means: the schema version does not move for a key whose absence has
            # exactly one honest reading (PRD Section 6.7, Decision D3).
            hybrid=frozenset(
                _enum(HybridKind, kind, f"{label} hybrid leg")
                for kind in _require_sequence(fields.get("hybrid", []), f"{label} hybrid legs")
            ),
        )
    except ValueError as error:
        if isinstance(error, ProfileFormatError):
            raise
        raise ProfileFormatError(f"{label} is not a usable rule: {error}") from error
    return rule


def _source_from_data(value: object, label: str, devices: Mapping[str, DeviceHandle]) -> RuleSource:
    """Return the control a rule starts from."""
    fields = _require_mapping(value, f"{label} source")
    return RuleSource(
        device=_device_of(fields.get("device"), label, devices),
        endpoint=_require_int(fields.get("endpoint"), f"{label} source endpoint"),
        emitter_id=_require_str(fields.get("emitter_id"), f"{label} source control"),
    )


def _device_of(value: object, label: str, devices: Mapping[str, DeviceHandle]) -> DeviceHandle:
    """Return the device this reference names, or say the file never described it (E38)."""
    identity = _require_str(value, f"{label} device")
    if identity in devices:
        return devices[identity]
    raise ProfileFormatError(f"{label} refers to {identity!r}, which the file does not describe")


def _rule_label(raw_id: object, index: int) -> str:
    """Return how every message about this rule names it."""
    if isinstance(raw_id, str) and raw_id:
        return f"rule {raw_id!r}"
    return f"the rule at index {index}"


# Narrowing. Everything a file yields is `object` until one of these has looked at it.


def _require_mapping(value: object, what: str) -> dict[str, object]:
    """Return this value as a mapping, or say what was found instead."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    raise ProfileFormatError(f"{what} must be a mapping, not {_kind(value)}")


def _require_sequence(value: object, what: str) -> list[object]:
    """Return this value as a list, or say what was found instead."""
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return list(value)
    raise ProfileFormatError(f"{what} must be a list, not {_kind(value)}")


def _require_str(value: object, what: str) -> str:
    """Return this value as text, or say what was found instead."""
    if isinstance(value, str):
        return value
    raise ProfileFormatError(f"{what} must be text, not {_kind(value)}")


def _require_int(value: object, what: str) -> int:
    """Return this value as a whole number, or say what was found instead."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ProfileFormatError(f"{what} must be a whole number, not {_kind(value)}")


def _optional_int(value: object, what: str) -> int | None:
    """Return this value as a whole number, or None where the file says nothing."""
    return None if value is None else _require_int(value, what)


def _require_bool(value: object, what: str) -> bool:
    """Return this value as a flag, or say what was found instead."""
    if isinstance(value, bool):
        return value
    raise ProfileFormatError(f"{what} must be true or false, not {_kind(value)}")


def _enum[E: StrEnum](enum: type[E], value: object, what: str) -> E:
    """Return the enum member this text names, or list the ones that exist."""
    raw = _require_str(value, what)
    try:
        return enum(raw)
    except ValueError as error:
        allowed = ", ".join(sorted(str(member) for member in enum))
        raise ProfileFormatError(f"{what} is {raw!r}, which is not one of: {allowed}") from error


def _kind(value: object) -> str:
    """Return what was found, said in a way that helps rather than a Python type name."""
    return "nothing" if value is None else type(value).__name__
