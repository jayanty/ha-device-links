"""The curated device profile database: what a model's controls really are.

Deriving controls from Association Group Information is safe but crude, because AGI's
`profile` field is only trustworthy on some hardware. Stage 0 found every Inovelli group
carrying a distinct profile even though three of them are one paddle, so the generic
derivation splits that paddle into three emitters and "paddle controls light, with dimming"
stops being expressible as one rule. A curated entry, keyed by the model fingerprint, puts
the paddle back together and says which parameter carries which setting.

A curated entry **overrides** the generic derivation, which is why loading is strict: a
wrong group number here writes an association to the wrong place with complete confidence
and no error. Every entry is validated on load, and the test suite cross-checks every group
number it names against `tests/fixtures/z2_associations.json`, the byte-for-byte capture of
the real devices.

Phase 2 added a second shape. A Zigbee entry describes different hardware, so it says
different things: an emitter names the **endpoint** it drives from and its actions name
**clusters**, because that is what a Zigbee binding is made of, and a settings adapter names
an MQTT property rather than a configuration parameter. Which shape an entry has is decided
by its `backend` key, which is absent on every entry written before Phase 2 and means Z-Wave
when it is, so no existing file changed. The two are validated separately and looked up
separately (`lookup` and `lookup_zigbee`), because a caller always knows which protocol it
is asking about and a signature that could answer with either would make every caller narrow
it again.

Phase 3 added a third, for the same reason and along the same seam. A Matter entry is the
Zigbee entry's shape with numbers where Zigbee has names: an emitter names the endpoint it
drives from and its actions name **cluster ids**, because a Matter binding names a cluster
by number and nothing on the fabric ever spells it out. It carries no settings adapters at
all, which is a fact about the protocol rather than an omission: a Matter device's settings
are attributes of its own clusters, not a numbered parameter list, and nothing in this
integration writes one yet.

This module is pure: it imports no Home Assistant and does no file I/O. It is handed
already-read text keyed by filename, so the caller owns reading files and this stays
testable without a filesystem. Validation is hand written rather than delegated to
`voluptuous`, which would be a Home Assistant import.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Final

from custom_components.device_links.models import (
    Feature,
    MatterFingerprint,
    SettingsAdapter,
    ZigbeeFingerprint,
    ZWaveFingerprint,
)

# Keys each object in a profile file may carry. They are frozensets rather than inline
# literals because `tests/test_profile_db.py` compares them against `profiles_db/schema.json`,
# so the documented schema cannot drift away from the validator that actually enforces it.
TOP_REQUIRED_KEYS: Final = frozenset({"devices"})
TOP_OPTIONAL_KEYS: Final = frozenset({"$schema", "notes"})
DEVICE_REQUIRED_KEYS: Final = frozenset({"model", "manufacturer", "fingerprints", "emitters"})
DEVICE_OPTIONAL_KEYS: Final = frozenset({"backend", "settings", "wake_instruction", "notes"})
FINGERPRINT_REQUIRED_KEYS: Final = frozenset({"manufacturer_id", "product_type", "product_id"})
EMITTER_REQUIRED_KEYS: Final = frozenset({"emitter_id", "label", "kind", "actions"})
EMITTER_OPTIONAL_KEYS: Final = frozenset(
    {"capacity_override", "semantics", "scene_id", "indicator_id"}
)

# The same three things for a Zigbee entry, which describes a different kind of hardware and
# so has a different shape. An emitter names the **endpoint** it lives on, because that is
# what a Zigbee binding is written from, and its actions name **clusters** rather than
# association group numbers. A settings adapter names an MQTT property rather than a
# configuration parameter, because that is how Zigbee2MQTT is written to.
ZIGBEE_DEVICE_REQUIRED_KEYS: Final = frozenset(
    {"backend", "model", "manufacturer", "fingerprints", "emitters"}
)
ZIGBEE_DEVICE_OPTIONAL_KEYS: Final = frozenset({"settings", "wake_instruction", "notes"})
ZIGBEE_FINGERPRINT_REQUIRED_KEYS: Final = frozenset({"vendor", "model"})
ZIGBEE_EMITTER_REQUIRED_KEYS: Final = frozenset(
    {"emitter_id", "label", "kind", "endpoint", "actions"}
)
ZIGBEE_EMITTER_OPTIONAL_KEYS: Final = frozenset({"semantics"})
ZIGBEE_ADAPTER_REQUIRED_KEYS: Final = frozenset({"property", "values", "payloads"})

# The same three things for a Matter entry. It is keyed by the vendor and product names the
# Matter server reports, and its emitters name cluster **ids**, because a Matter binding
# carries a number and there is no name to write. `settings` is absent from both sets: a
# Matter device has no numbered parameter list, so an entry that offered one would be
# describing hardware that does not exist.
MATTER_DEVICE_REQUIRED_KEYS: Final = frozenset(
    {"backend", "model", "manufacturer", "fingerprints", "emitters"}
)
MATTER_DEVICE_OPTIONAL_KEYS: Final = frozenset({"wake_instruction", "notes"})
MATTER_FINGERPRINT_REQUIRED_KEYS: Final = frozenset({"vendor", "product"})
MATTER_EMITTER_REQUIRED_KEYS: Final = frozenset(
    {"emitter_id", "label", "kind", "endpoint", "actions"}
)
MATTER_EMITTER_OPTIONAL_KEYS: Final = frozenset({"semantics"})

# Which protocol an entry describes. Absent means Z-Wave, because every entry written before
# Phase 2 is one and a default that rewrote history would be worse than a default that
# matches it.
BACKEND_ZWAVE: Final = "zwave"
BACKEND_ZIGBEE2MQTT: Final = "zigbee2mqtt"
BACKEND_MATTER: Final = "matter"
PROFILE_BACKENDS: Final = frozenset({BACKEND_ZWAVE, BACKEND_ZIGBEE2MQTT, BACKEND_MATTER})
# `bitmask` is required and nullable rather than optional: a missing bitmask silently
# meaning "the whole parameter" is exactly the ambiguity this database exists to remove.
ADAPTER_REQUIRED_KEYS: Final = frozenset({"parameter", "bitmask", "values"})

# What kind of physical control an emitter is, for icons and for wording in the UI.
EMITTER_KINDS: Final = frozenset({"paddle", "button", "gesture", "config_button"})

# Markers on an emitter whose behavior the compiler has to be careful about.
# `unknown`: what this control sends on a press is not established as a fixed OFF, so the
# Off-all template cannot be compiled onto it safely. See Stage 0 item Z7. A new marker here
# needs matching compiler support, which is why the set is closed.
SEMANTICS_UNKNOWN: Final = "unknown"
SEMANTICS_MARKERS: Final = frozenset({SEMANTICS_UNKNOWN})

# Group 1 is the lifeline on every Z-Wave device, and is never ours to write.
_LIFELINE_GROUP: Final = "1"

# Feature names by value, so validation does not depend on how an enum member hashes.
_FEATURE_NAMES: Final = frozenset(str(feature) for feature in Feature)


@dataclass(frozen=True, slots=True)
class ProfileFingerprint:
    """The model identity an entry matches on: manufacturer and product ids, no firmware.

    Firmware is deliberately absent, so one entry covers every firmware of a model. Matching
    is by exact triple with no wildcards and no ranges: an entry overrides what the hardware
    reports about itself, so a wildcard would spread one contributor's mistake across a whole
    manufacturer's catalogue.
    """

    manufacturer_id: int
    product_type: int
    product_id: int

    @classmethod
    def of(cls, fingerprint: ZWaveFingerprint) -> ProfileFingerprint:
        """Return the model identity of a device the driver reported."""
        return cls(
            manufacturer_id=fingerprint.manufacturer_id,
            product_type=fingerprint.product_type,
            product_id=fingerprint.product_id,
        )


@dataclass(frozen=True, slots=True)
class ProfileEmitter:
    """One physical control, as a curated entry describes it.

    `actions` maps a feature to the association group that carries it, which is what makes
    the Inovelli paddle one control instead of three. `semantics` is set when something about
    what this control sends is not established; see `SEMANTICS_MARKERS`.

    `scene_id` and `indicator_id` are the two facts a hybrid leg needs and nothing else in
    this integration uses (PRD Section 6.7): the Central Scene number this control reports
    when it is pressed, and the Indicator CC id of the little light on it. They are curated
    rather than derived because neither is discoverable by reading a device: association
    group information carries neither, and a guessed scene number is a leg that fires on
    somebody else's button.
    """

    emitter_id: str
    label: str
    kind: str
    actions: Mapping[Feature, str]
    capacity_override: int | None = None
    semantics: str | None = None
    scene_id: int | None = None
    indicator_id: int | None = None


@dataclass(frozen=True, slots=True)
class ProfileEntry:
    """Everything the curated database knows about one device model."""

    fingerprints: tuple[ProfileFingerprint, ...]
    emitters: tuple[ProfileEmitter, ...]
    settings: Mapping[str, SettingsAdapter]
    wake_instruction: str | None
    notes: str


@dataclass(frozen=True, slots=True)
class ZigbeeProfileFingerprint:
    """The model identity a Zigbee entry matches on: the converter's vendor and model.

    Zigbee2MQTT's `definition` is what decides how a device is driven, so it is what an
    entry is keyed by, and it is stable across firmware in the way the device's own
    `model_id` is not.
    """

    vendor: str
    model: str

    @classmethod
    def of(cls, fingerprint: ZigbeeFingerprint) -> ZigbeeProfileFingerprint:
        """Return the model identity of a device the bridge reported."""
        return cls(vendor=fingerprint.manufacturer, model=fingerprint.model)


@dataclass(frozen=True, slots=True)
class ZigbeeProfileEmitter:
    """One physical control on a Zigbee device, as a curated entry describes it.

    `endpoint` is what a binding is written from, and `actions` maps a feature to the
    **cluster** that carries it. Two features can name one cluster, because `genLevelCtrl`
    really does carry both setting a level and holding to dim.
    """

    emitter_id: str
    label: str
    kind: str
    endpoint: int
    actions: Mapping[Feature, str]
    semantics: str | None = None


@dataclass(frozen=True, slots=True)
class ZigbeeSettingsAdapter:
    """How to reach one named setting over MQTT, and what the two ends call its values.

    Zigbee2MQTT is written to by publishing `{property: payload}` to a device's `set` topic,
    and the payloads are its own labels ("Disabled", "Enabled") rather than numbers. The
    `Backend` protocol carries settings as integers, because that is what a configuration
    parameter is, so an adapter has to hold both: `values` maps a choice name to the integer
    the rest of the system uses, and `payloads` maps the same choice name to the string the
    bridge expects. The two must name exactly the same choices, which `load_profiles`
    enforces, because a choice with a number and no payload could be asked for and not sent.
    """

    property_name: str
    values: Mapping[str, int]
    payloads: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ZigbeeProfileEntry:
    """Everything the curated database knows about one Zigbee device model."""

    fingerprints: tuple[ZigbeeProfileFingerprint, ...]
    emitters: tuple[ZigbeeProfileEmitter, ...]
    settings: Mapping[str, ZigbeeSettingsAdapter]
    wake_instruction: str | None
    notes: str


@dataclass(frozen=True, slots=True)
class MatterProfileFingerprint:
    """The model identity a Matter entry matches on: the vendor and product names.

    What the Matter server reports for a node's Basic Information cluster, which is what the
    M1 capture recorded ("Inovelli", "VTM31-SN"). Names rather than the vendor and product
    **ids** that are also on that cluster, so that an entry can be read and checked by a
    contributor holding the device rather than a packet capture.
    """

    vendor: str
    product: str

    @classmethod
    def of(cls, fingerprint: MatterFingerprint) -> MatterProfileFingerprint:
        """Return the model identity of a node the Matter server reported."""
        return cls(vendor=fingerprint.vendor, product=fingerprint.product)


@dataclass(frozen=True, slots=True)
class MatterProfileEmitter:
    """One physical control on a Matter node, as a curated entry describes it.

    `endpoint` is what a binding is written from and `actions` maps a feature to the
    **cluster id** that carries it. Two features can name one cluster, because LevelControl
    really does carry both setting a level and holding to dim.
    """

    emitter_id: str
    label: str
    kind: str
    endpoint: int
    actions: Mapping[Feature, int]
    semantics: str | None = None


@dataclass(frozen=True, slots=True)
class MatterProfileEntry:
    """Everything the curated database knows about one Matter device model.

    No settings, unlike the other two shapes. A Matter device is configured through the
    attributes of its own clusters rather than through a numbered parameter list, and
    nothing in this integration writes one, so an entry that carried adapters would be
    describing a mechanism that does not exist here.
    """

    fingerprints: tuple[MatterProfileFingerprint, ...]
    emitters: tuple[MatterProfileEmitter, ...]
    wake_instruction: str | None
    notes: str


@dataclass(frozen=True, slots=True)
class ProfileDatabase:
    """Every curated entry that was loaded, and the lookups over them.

    Two collections and two lookups rather than one of each with a union return type: a
    caller always knows which protocol it is asking about, and a signature that could
    answer with either kind would make every caller narrow it again.
    """

    entries: tuple[ProfileEntry, ...]
    zigbee_entries: tuple[ZigbeeProfileEntry, ...] = ()
    matter_entries: tuple[MatterProfileEntry, ...] = ()

    def lookup(self, fingerprint: ZWaveFingerprint) -> ProfileEntry | None:
        """Return the entry describing this device model, or None when none does.

        Firmware is ignored. `load_profiles` refuses two entries claiming one model, so at
        most one entry can ever match and the answer does not depend on iteration order.
        """
        wanted = ProfileFingerprint.of(fingerprint)
        for entry in self.entries:
            if wanted in entry.fingerprints:
                return entry
        return None

    def lookup_zigbee(self, fingerprint: ZigbeeFingerprint) -> ZigbeeProfileEntry | None:
        """Return the Zigbee entry describing this device model, or None when none does."""
        wanted = ZigbeeProfileFingerprint.of(fingerprint)
        for entry in self.zigbee_entries:
            if wanted in entry.fingerprints:
                return entry
        return None

    def lookup_matter(self, fingerprint: MatterFingerprint) -> MatterProfileEntry | None:
        """Return the Matter entry describing this device model, or None when none does."""
        wanted = MatterProfileFingerprint.of(fingerprint)
        for entry in self.matter_entries:
            if wanted in entry.fingerprints:
                return entry
        return None


def load_profiles(files: Mapping[str, str]) -> ProfileDatabase:
    """Parse and validate profile JSON text into a database.

    `files` maps a filename to its contents; this module never opens a file itself. Anything
    malformed raises `ValueError` naming the file and the offending field, because a
    contributor's mistake reaching apply time is the failure this validation exists to
    prevent. Files are read in name order, so an error is the same one every run.
    """
    entries: list[ProfileEntry] = []
    zigbee_entries: list[ZigbeeProfileEntry] = []
    matter_entries: list[MatterProfileEntry] = []
    claimed: dict[object, str] = {}
    for filename in sorted(files):
        for entry, where in _entries_in(filename, files[filename]):
            for fingerprint in entry.fingerprints:
                claimed_by = claimed.get(fingerprint)
                if claimed_by is not None:
                    raise ValueError(
                        f"{where}: fingerprint {_named(fingerprint)} is already claimed by "
                        f"{claimed_by}, and two entries matching one device would make the "
                        "lookup ambiguous"
                    )
                claimed[fingerprint] = where
            if isinstance(entry, ZigbeeProfileEntry):
                zigbee_entries.append(entry)
            elif isinstance(entry, MatterProfileEntry):
                matter_entries.append(entry)
            else:
                entries.append(entry)
    return ProfileDatabase(
        entries=tuple(entries),
        zigbee_entries=tuple(zigbee_entries),
        matter_entries=tuple(matter_entries),
    )


def _named(
    fingerprint: ProfileFingerprint | ZigbeeProfileFingerprint | MatterProfileFingerprint,
) -> str:
    """Return a model identity in the form the protocol that owns it is written in."""
    if isinstance(fingerprint, ZigbeeProfileFingerprint):
        return f"{fingerprint.vendor} {fingerprint.model}"
    if isinstance(fingerprint, MatterProfileFingerprint):
        return f"{fingerprint.vendor} {fingerprint.product}"
    return f"{fingerprint.manufacturer_id}:{fingerprint.product_type}:{fingerprint.product_id}"


def _entries_in(
    filename: str, text: str
) -> Iterator[tuple[ProfileEntry | ZigbeeProfileEntry | MatterProfileEntry, str]]:
    """Yield each entry in one file, with the label error messages should use for it.

    Which shape an entry has is decided by its `backend` key, which is absent on every entry
    written before Phase 2 and means Z-Wave when it is. A file may hold all three.
    """
    document = _document(filename, text)
    for position, raw in enumerate(_list(f"{filename}: 'devices'", document["devices"])):
        device = _object(f"{filename} device {position}", raw)
        model = device.get("model")
        where = f"{filename} {model}" if isinstance(model, str) and model else filename
        backend = _one_of(
            f"{where}: 'backend'", device.get("backend", BACKEND_ZWAVE), PROFILE_BACKENDS
        )
        if backend == BACKEND_ZIGBEE2MQTT:
            yield _zigbee_entry(where, device), where
        elif backend == BACKEND_MATTER:
            yield _matter_entry(where, device), where
        else:
            yield _entry(where, device), where


def _document(filename: str, text: str) -> Mapping[str, object]:
    """Parse one file's text into a checked top-level object."""
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError as err:
        raise ValueError(f"{filename}: is not valid JSON: {err}") from err
    document = _object(filename, parsed)
    _checked_keys(filename, document, TOP_REQUIRED_KEYS, TOP_OPTIONAL_KEYS)
    return document


def _entry(where: str, device: Mapping[str, object]) -> ProfileEntry:
    """Validate one device object and turn it into an entry."""
    _checked_keys(where, device, DEVICE_REQUIRED_KEYS, DEVICE_OPTIONAL_KEYS)
    _text(f"{where}: 'model'", device["model"])
    _text(f"{where}: 'manufacturer'", device["manufacturer"])
    fingerprints = tuple(
        _fingerprint(f"{where} fingerprint {position}", raw)
        for position, raw in enumerate(_list(f"{where}: 'fingerprints'", device["fingerprints"]))
    )
    emitters = tuple(
        _emitter(where, raw) for raw in _list(f"{where}: 'emitters'", device["emitters"])
    )
    _reject_repeated_emitter_ids(where, emitters)
    return ProfileEntry(
        fingerprints=fingerprints,
        emitters=emitters,
        settings=_settings(where, device.get("settings")),
        wake_instruction=_optional_text(
            f"{where}: 'wake_instruction'", device.get("wake_instruction")
        ),
        notes=_optional_text(f"{where}: 'notes'", device.get("notes")) or "",
    )


def _zigbee_entry(where: str, device: Mapping[str, object]) -> ZigbeeProfileEntry:
    """Validate one Zigbee device object and turn it into an entry.

    The same shape of validation as the Z-Wave path and deliberately not shared with it:
    the two describe different hardware, and a validator written to cover both would have
    to accept a key for one protocol on an entry for the other.
    """
    _checked_keys(where, device, ZIGBEE_DEVICE_REQUIRED_KEYS, ZIGBEE_DEVICE_OPTIONAL_KEYS)
    _text(f"{where}: 'model'", device["model"])
    _text(f"{where}: 'manufacturer'", device["manufacturer"])
    fingerprints = tuple(
        _zigbee_fingerprint(f"{where} fingerprint {position}", raw)
        for position, raw in enumerate(_list(f"{where}: 'fingerprints'", device["fingerprints"]))
    )
    emitters = tuple(
        _zigbee_emitter(where, raw) for raw in _list(f"{where}: 'emitters'", device["emitters"])
    )
    _reject_repeated_emitter_ids(where, emitters)
    return ZigbeeProfileEntry(
        fingerprints=fingerprints,
        emitters=emitters,
        settings=_zigbee_settings(where, device.get("settings")),
        wake_instruction=_optional_text(
            f"{where}: 'wake_instruction'", device.get("wake_instruction")
        ),
        notes=_optional_text(f"{where}: 'notes'", device.get("notes")) or "",
    )


def _zigbee_fingerprint(where: str, raw: object) -> ZigbeeProfileFingerprint:
    """Validate one Zigbee model identity, which is the converter's vendor and model."""
    mapping = _object(where, raw)
    _checked_keys(where, mapping, ZIGBEE_FINGERPRINT_REQUIRED_KEYS, frozenset())
    return ZigbeeProfileFingerprint(
        vendor=_text(f"{where}: 'vendor'", mapping["vendor"]),
        model=_text(f"{where}: 'model'", mapping["model"]),
    )


def _zigbee_emitter(where: str, raw: object) -> ZigbeeProfileEmitter:
    """Validate one Zigbee emitter object."""
    mapping = _object(f"{where} emitter", raw)
    _checked_keys(
        f"{where} emitter", mapping, ZIGBEE_EMITTER_REQUIRED_KEYS, ZIGBEE_EMITTER_OPTIONAL_KEYS
    )
    emitter_id = _text(f"{where} emitter: 'emitter_id'", mapping["emitter_id"])
    named = f"{where} emitter {emitter_id!r}"
    semantics = mapping.get("semantics")
    return ZigbeeProfileEmitter(
        emitter_id=emitter_id,
        label=_text(f"{named}: 'label'", mapping["label"]),
        kind=_one_of(f"{named}: 'kind'", mapping["kind"], EMITTER_KINDS),
        endpoint=_integer(f"{named}: 'endpoint'", mapping["endpoint"], minimum=1),
        actions=_zigbee_actions(named, mapping["actions"]),
        semantics=(
            None
            if semantics is None
            else _one_of(f"{named}: 'semantics'", semantics, SEMANTICS_MARKERS)
        ),
    )


def _zigbee_actions(where: str, raw: object) -> Mapping[Feature, str]:
    """Validate the feature to cluster map, which is the part that reaches the bridge."""
    mapping = _object(f"{where}: 'actions'", raw)
    if not mapping:
        raise ValueError(f"{where}: 'actions' must name at least one feature")
    actions: dict[Feature, str] = {}
    for name, raw_cluster in mapping.items():
        if name not in _FEATURE_NAMES:
            known = ", ".join(sorted(_FEATURE_NAMES))
            raise ValueError(f"{where}: {name!r} is not a feature; known features are {known}")
        actions[Feature(name)] = _cluster(f"{where}: '{name}'", raw_cluster)
    return actions


def _cluster(where: str, raw: object) -> str:
    """Validate one Zigbee cluster name.

    Structural only. Whether the cluster is one Device Links can bind, and whether it can
    carry the feature the entry claims for it, is decided against the device's own reported
    output clusters in `zigbee_protocol.resolve_emitters`: the device is a better authority
    than a list in this module would be, and this module must not import that one.
    """
    if not isinstance(raw, str):
        raise _wrong_type(where, "a cluster name to be a string", raw)
    if not raw or not raw.isascii() or not raw.isalnum():
        raise ValueError(f"{where}: {raw!r} is not a cluster name Zigbee2MQTT could report")
    return raw


def _zigbee_settings(where: str, raw: object) -> Mapping[str, ZigbeeSettingsAdapter]:
    """Validate the named Zigbee settings adapters, of which a device may have none."""
    if raw is None:
        return {}
    mapping = _object(f"{where}: 'settings'", raw)
    return {
        name: _zigbee_adapter(f"{where}: setting {name!r}", value)
        for name, value in mapping.items()
    }


def _zigbee_adapter(where: str, raw: object) -> ZigbeeSettingsAdapter:
    """Validate one Zigbee settings adapter, and that its two value maps agree.

    A choice with an integer and no payload is a choice the compiler could ask for and the
    adapter could not send, which would fail at the bridge rather than at load.
    """
    mapping = _object(where, raw)
    _checked_keys(where, mapping, ZIGBEE_ADAPTER_REQUIRED_KEYS, frozenset())
    values = _values(f"{where}: 'values'", mapping["values"])
    payloads = _payloads(f"{where}: 'payloads'", mapping["payloads"])
    if set(values) != set(payloads):
        raise ValueError(
            f"{where}: 'values' names {sorted(values)} and 'payloads' names "
            f"{sorted(payloads)}; every choice needs both"
        )
    return ZigbeeSettingsAdapter(
        property_name=_text(f"{where}: 'property'", mapping["property"]),
        values=values,
        payloads=payloads,
    )


def _payloads(where: str, raw: object) -> Mapping[str, str]:
    """Validate the strings Zigbee2MQTT is written with, one per named choice."""
    mapping = _object(where, raw)
    if not mapping:
        raise ValueError(f"{where}: must name at least one value")
    return {name: _text(f"{where}: {name!r}", value) for name, value in mapping.items()}


def _matter_entry(where: str, device: Mapping[str, object]) -> MatterProfileEntry:
    """Validate one Matter device object and turn it into an entry.

    Separate from the other two for the reason `_zigbee_entry` gives: a validator written to
    cover several protocols has to accept a key for one of them on an entry for another, and
    the whole value of this database is that a wrong entry cannot load.
    """
    _checked_keys(where, device, MATTER_DEVICE_REQUIRED_KEYS, MATTER_DEVICE_OPTIONAL_KEYS)
    _text(f"{where}: 'model'", device["model"])
    _text(f"{where}: 'manufacturer'", device["manufacturer"])
    fingerprints = tuple(
        _matter_fingerprint(f"{where} fingerprint {position}", raw)
        for position, raw in enumerate(_list(f"{where}: 'fingerprints'", device["fingerprints"]))
    )
    emitters = tuple(
        _matter_emitter(where, raw) for raw in _list(f"{where}: 'emitters'", device["emitters"])
    )
    _reject_repeated_emitter_ids(where, emitters)
    return MatterProfileEntry(
        fingerprints=fingerprints,
        emitters=emitters,
        wake_instruction=_optional_text(
            f"{where}: 'wake_instruction'", device.get("wake_instruction")
        ),
        notes=_optional_text(f"{where}: 'notes'", device.get("notes")) or "",
    )


def _matter_fingerprint(where: str, raw: object) -> MatterProfileFingerprint:
    """Validate one Matter model identity, which is the vendor and product the node reports."""
    mapping = _object(where, raw)
    _checked_keys(where, mapping, MATTER_FINGERPRINT_REQUIRED_KEYS, frozenset())
    return MatterProfileFingerprint(
        vendor=_text(f"{where}: 'vendor'", mapping["vendor"]),
        product=_text(f"{where}: 'product'", mapping["product"]),
    )


def _matter_emitter(where: str, raw: object) -> MatterProfileEmitter:
    """Validate one Matter emitter object."""
    mapping = _object(f"{where} emitter", raw)
    _checked_keys(
        f"{where} emitter", mapping, MATTER_EMITTER_REQUIRED_KEYS, MATTER_EMITTER_OPTIONAL_KEYS
    )
    emitter_id = _text(f"{where} emitter: 'emitter_id'", mapping["emitter_id"])
    named = f"{where} emitter {emitter_id!r}"
    semantics = mapping.get("semantics")
    return MatterProfileEmitter(
        emitter_id=emitter_id,
        label=_text(f"{named}: 'label'", mapping["label"]),
        kind=_one_of(f"{named}: 'kind'", mapping["kind"], EMITTER_KINDS),
        # Endpoint 0 is the root, which administers the node and controls nothing, so an
        # entry naming it is describing a control that cannot exist.
        endpoint=_integer(f"{named}: 'endpoint'", mapping["endpoint"], minimum=1),
        actions=_matter_actions(named, mapping["actions"]),
        semantics=(
            None
            if semantics is None
            else _one_of(f"{named}: 'semantics'", semantics, SEMANTICS_MARKERS)
        ),
    )


def _matter_actions(where: str, raw: object) -> Mapping[Feature, int]:
    """Validate the feature to cluster id map, which is the part that reaches the fabric.

    Structural only, exactly as `_cluster` is for Zigbee. Whether the node really drives the
    cluster, and whether that cluster can carry the feature claimed for it, is decided
    against what the node itself reports in `matter_protocol.resolve_emitters`.
    """
    mapping = _object(f"{where}: 'actions'", raw)
    if not mapping:
        raise ValueError(f"{where}: 'actions' must name at least one feature")
    actions: dict[Feature, int] = {}
    for name, raw_cluster in mapping.items():
        if name not in _FEATURE_NAMES:
            known = ", ".join(sorted(_FEATURE_NAMES))
            raise ValueError(f"{where}: {name!r} is not a feature; known features are {known}")
        actions[Feature(name)] = _integer(f"{where}: '{name}'", raw_cluster, minimum=1)
    return actions


def _fingerprint(where: str, raw: object) -> ProfileFingerprint:
    """Validate one fingerprint triple."""
    mapping = _object(where, raw)
    _checked_keys(where, mapping, FINGERPRINT_REQUIRED_KEYS, frozenset())
    return ProfileFingerprint(
        manufacturer_id=_integer(f"{where}: 'manufacturer_id'", mapping["manufacturer_id"]),
        product_type=_integer(f"{where}: 'product_type'", mapping["product_type"]),
        product_id=_integer(f"{where}: 'product_id'", mapping["product_id"]),
    )


def _emitter(where: str, raw: object) -> ProfileEmitter:
    """Validate one emitter object."""
    mapping = _object(f"{where} emitter", raw)
    _checked_keys(f"{where} emitter", mapping, EMITTER_REQUIRED_KEYS, EMITTER_OPTIONAL_KEYS)
    emitter_id = _text(f"{where} emitter: 'emitter_id'", mapping["emitter_id"])
    named = f"{where} emitter {emitter_id!r}"
    capacity_override = mapping.get("capacity_override")
    semantics = mapping.get("semantics")
    scene_id = mapping.get("scene_id")
    indicator_id = mapping.get("indicator_id")
    return ProfileEmitter(
        emitter_id=emitter_id,
        label=_text(f"{named}: 'label'", mapping["label"]),
        kind=_one_of(f"{named}: 'kind'", mapping["kind"], EMITTER_KINDS),
        actions=_actions(named, mapping["actions"]),
        capacity_override=(
            None
            if capacity_override is None
            else _integer(f"{named}: 'capacity_override'", capacity_override, minimum=1)
        ),
        semantics=(
            None
            if semantics is None
            else _one_of(f"{named}: 'semantics'", semantics, SEMANTICS_MARKERS)
        ),
        scene_id=(
            None if scene_id is None else _integer(f"{named}: 'scene_id'", scene_id, minimum=1)
        ),
        indicator_id=(
            None
            if indicator_id is None
            else _integer(f"{named}: 'indicator_id'", indicator_id, minimum=1)
        ),
    )


def _actions(where: str, raw: object) -> Mapping[Feature, str]:
    """Validate the feature to group map, which is the part that reaches the device."""
    mapping = _object(f"{where}: 'actions'", raw)
    if not mapping:
        raise ValueError(f"{where}: 'actions' must name at least one feature")
    actions: dict[Feature, str] = {}
    for name, raw_group in mapping.items():
        if name not in _FEATURE_NAMES:
            known = ", ".join(sorted(_FEATURE_NAMES))
            raise ValueError(f"{where}: {name!r} is not a feature; known features are {known}")
        actions[Feature(name)] = _group_id(f"{where}: '{name}'", raw_group)
    return actions


def _group_id(where: str, raw: object) -> str:
    """Validate one association group id.

    Group ids are plain decimal strings, exactly as the driver reports them and as
    `Link.emitter_group` carries them. An accidental JSON integer is rejected rather than
    coerced, and so is any spelling that would never compare equal to what the driver says:
    "07" and a non-ASCII digit both read as a group number but match nothing.
    """
    if not isinstance(raw, str):
        raise _wrong_type(where, "a group id to be a string", raw)
    if not (raw.isascii() and raw.isdecimal() and not raw.startswith("0")):
        raise ValueError(f"{where}: {raw!r} is not a group id the driver could report")
    if raw == _LIFELINE_GROUP:
        raise ValueError(f"{where}: group 1 is the lifeline, which is never ours to write")
    return raw


def _settings(where: str, raw: object) -> Mapping[str, SettingsAdapter]:
    """Validate the named settings adapters, of which a device may have none."""
    if raw is None:
        return {}
    mapping = _object(f"{where}: 'settings'", raw)
    return {name: _adapter(f"{where}: setting {name!r}", value) for name, value in mapping.items()}


def _adapter(where: str, raw: object) -> SettingsAdapter:
    """Validate one settings adapter."""
    mapping = _object(where, raw)
    _checked_keys(where, mapping, ADAPTER_REQUIRED_KEYS, frozenset())
    bitmask = mapping["bitmask"]
    return SettingsAdapter(
        parameter=_integer(f"{where}: 'parameter'", mapping["parameter"], minimum=1),
        bitmask=None if bitmask is None else _integer(f"{where}: 'bitmask'", bitmask, minimum=1),
        values=_values(f"{where}: 'values'", mapping["values"]),
    )


def _values(where: str, raw: object) -> Mapping[str, int]:
    """Validate an adapter's named values, which must name at least one."""
    mapping = _object(where, raw)
    if not mapping:
        raise ValueError(f"{where}: must name at least one value")
    return {name: _integer(f"{where}: {name!r}", value) for name, value in mapping.items()}


def _reject_repeated_emitter_ids(
    where: str, emitters: Sequence[ProfileEmitter | ZigbeeProfileEmitter | MatterProfileEmitter]
) -> None:
    """Two emitters with one id would make the rule's `emitter_id` ambiguous."""
    seen: set[str] = set()
    for emitter in emitters:
        if emitter.emitter_id in seen:
            raise ValueError(f"{where}: emitter id {emitter.emitter_id!r} appears twice")
        seen.add(emitter.emitter_id)


def _checked_keys(
    where: str,
    mapping: Mapping[str, object],
    required: frozenset[str],
    optional: frozenset[str],
) -> None:
    """Reject a missing or unexpected key, reporting every one of them at once.

    Unknown keys are rejected rather than ignored: a typed key name is a contributor's
    intent that would otherwise be silently dropped and only noticed on a device.
    """
    missing = sorted(required - mapping.keys())
    unknown = sorted(mapping.keys() - required - optional)
    if not missing and not unknown:
        return
    problems: list[str] = []
    if missing:
        problems.append("missing required key(s) " + ", ".join(repr(key) for key in missing))
    if unknown:
        problems.append("unknown key(s) " + ", ".join(repr(key) for key in unknown))
    raise ValueError(f"{where}: " + "; ".join(problems))


def _object(where: str, raw: object) -> Mapping[str, object]:
    """Narrow a parsed value to a JSON object, or say what it was instead."""
    if not isinstance(raw, dict):
        raise _wrong_type(where, "an object", raw)
    return raw


def _list(where: str, raw: object) -> Sequence[object]:
    """Narrow a parsed value to a non-empty JSON list."""
    if not isinstance(raw, list):
        raise _wrong_type(where, "a list", raw)
    if not raw:
        raise ValueError(f"{where}: must not be empty")
    return raw


def _text(where: str, raw: object) -> str:
    """Narrow a parsed value to a non-empty string."""
    if not isinstance(raw, str):
        raise _wrong_type(where, "a string", raw)
    if not raw:
        raise ValueError(f"{where}: must not be empty")
    return raw


def _optional_text(where: str, raw: object) -> str | None:
    """Narrow an absent, null or non-empty string value."""
    return None if raw is None else _text(where, raw)


def _one_of(where: str, raw: object, allowed: frozenset[str]) -> str:
    """Narrow a parsed value to one of a closed set of strings."""
    value = _text(where, raw)
    if value not in allowed:
        raise ValueError(f"{where}: {value!r} is not one of {', '.join(sorted(allowed))}")
    return value


def _integer(where: str, raw: object, *, minimum: int = 0) -> int:
    """Narrow a parsed value to an integer at or above a floor.

    `bool` is excluded explicitly, because JSON `true` parses to a Python `bool` and `bool`
    is a subclass of `int`, so a typo would otherwise become the parameter number 1.
    """
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise _wrong_type(where, "an integer", raw)
    if raw < minimum:
        raise ValueError(f"{where}: expected an integer of at least {minimum}, got {raw}")
    return raw


def _wrong_type(where: str, wanted: str, raw: object) -> ValueError:
    """Return the error for a value of the wrong JSON type.

    A malformed file is a value problem and not a programming error, so every rejection in
    this module is a `ValueError` naming the file and the field, including the ones that are
    about a type. Building it here keeps that one decision in one place.
    """
    return ValueError(f"{where}: expected {wanted}, got {_kind_of(raw)}")


def _kind_of(raw: object) -> str:
    """Name a value's JSON type, so an error says what was found and not only what was wanted."""
    return _JSON_TYPES.get(type(raw), type(raw).__name__)


# Keyed by exact type, so `True` reads as a boolean rather than as the number 1.
_JSON_TYPES: Final[Mapping[type, str]] = {
    type(None): "null",
    bool: "a boolean",
    int: "a number",
    float: "a number",
    str: "a string",
    list: "a list",
    dict: "an object",
}
