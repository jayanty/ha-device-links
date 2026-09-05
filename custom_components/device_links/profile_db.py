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

from custom_components.device_links.models import Feature, SettingsAdapter, ZWaveFingerprint

# Keys each object in a profile file may carry. They are frozensets rather than inline
# literals because `tests/test_profile_db.py` compares them against `profiles_db/schema.json`,
# so the documented schema cannot drift away from the validator that actually enforces it.
TOP_REQUIRED_KEYS: Final = frozenset({"devices"})
TOP_OPTIONAL_KEYS: Final = frozenset({"$schema", "notes"})
DEVICE_REQUIRED_KEYS: Final = frozenset({"model", "manufacturer", "fingerprints", "emitters"})
DEVICE_OPTIONAL_KEYS: Final = frozenset({"settings", "wake_instruction", "notes"})
FINGERPRINT_REQUIRED_KEYS: Final = frozenset({"manufacturer_id", "product_type", "product_id"})
EMITTER_REQUIRED_KEYS: Final = frozenset({"emitter_id", "label", "kind", "actions"})
EMITTER_OPTIONAL_KEYS: Final = frozenset({"capacity_override", "semantics"})
# `bitmask` is required and nullable rather than optional: a missing bitmask silently
# meaning "the whole parameter" is exactly the ambiguity this database exists to remove.
ADAPTER_REQUIRED_KEYS: Final = frozenset({"parameter", "bitmask", "values"})

# What kind of physical control an emitter is, for icons and for wording in the UI.
EMITTER_KINDS: Final = frozenset({"paddle", "button", "gesture", "config_button"})

# Markers on an emitter whose behavior the compiler has to be careful about.
# `unknown`: what this control sends on a press is not established as a fixed OFF, so the
# Off-all template cannot be compiled onto it safely. See Stage 0 item Z7. A new marker here
# needs matching compiler support, which is why the set is closed.
SEMANTICS_MARKERS: Final = frozenset({"unknown"})

# Group 1 is the lifeline on every Z-Wave device, and is never ours to write.
_LIFELINE_GROUP: Final = "1"


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
    """

    emitter_id: str
    label: str
    kind: str
    actions: Mapping[Feature, str]
    capacity_override: int | None = None
    semantics: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileEntry:
    """Everything the curated database knows about one device model."""

    fingerprints: tuple[ProfileFingerprint, ...]
    emitters: tuple[ProfileEmitter, ...]
    settings: Mapping[str, SettingsAdapter]
    wake_instruction: str | None
    notes: str


@dataclass(frozen=True, slots=True)
class ProfileDatabase:
    """Every curated entry that was loaded, and the lookup over them."""

    entries: tuple[ProfileEntry, ...]

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


def load_profiles(files: Mapping[str, str]) -> ProfileDatabase:
    """Parse and validate profile JSON text into a database.

    `files` maps a filename to its contents; this module never opens a file itself. Anything
    malformed raises `ValueError` naming the file and the offending field, because a
    contributor's mistake reaching apply time is the failure this validation exists to
    prevent. Files are read in name order, so an error is the same one every run.
    """
    entries: list[ProfileEntry] = []
    claimed: dict[ProfileFingerprint, str] = {}
    for filename in sorted(files):
        for entry, where in _entries_in(filename, files[filename]):
            for fingerprint in entry.fingerprints:
                claimed_by = claimed.get(fingerprint)
                if claimed_by is not None:
                    raise ValueError(
                        f"{where}: fingerprint {fingerprint.manufacturer_id}:"
                        f"{fingerprint.product_type}:{fingerprint.product_id} is already "
                        f"claimed by {claimed_by}, and two entries matching one device would "
                        "make the lookup ambiguous"
                    )
                claimed[fingerprint] = where
            entries.append(entry)
    return ProfileDatabase(entries=tuple(entries))


def _entries_in(filename: str, text: str) -> Iterator[tuple[ProfileEntry, str]]:
    """Yield each entry in one file, with the label error messages should use for it."""
    document = _document(filename, text)
    for position, raw in enumerate(_list(f"{filename}: 'devices'", document["devices"])):
        device = _object(f"{filename} device {position}", raw)
        model = device.get("model")
        where = f"{filename} {model}" if isinstance(model, str) and model else filename
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
    )


def _actions(where: str, raw: object) -> Mapping[Feature, str]:
    """Validate the feature to group map, which is the part that reaches the device."""
    mapping = _object(f"{where}: 'actions'", raw)
    if not mapping:
        raise ValueError(f"{where}: 'actions' must name at least one feature")
    actions: dict[Feature, str] = {}
    for name, raw_group in mapping.items():
        if name not in set(Feature):
            known = ", ".join(sorted(str(feature) for feature in Feature))
            raise ValueError(f"{where}: {name!r} is not a feature; known features are {known}")
        actions[Feature(name)] = _group_id(f"{where}: '{name}'", raw_group)
    return actions


def _group_id(where: str, raw: object) -> str:
    """Validate one association group id.

    Group ids are decimal strings, matching `Link.emitter_group`, so an accidental JSON
    integer is rejected rather than coerced into a value that would never compare equal.
    """
    if not isinstance(raw, str):
        raise _wrong_type(where, "a group id to be a string", raw)
    if not raw.isdigit():
        raise ValueError(f"{where}: {raw!r} is not a decimal group id")
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


def _reject_repeated_emitter_ids(where: str, emitters: Sequence[ProfileEmitter]) -> None:
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
