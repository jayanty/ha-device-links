"""The contract between `serialize.py` and the panel's TypeScript types.

The panel's types are hand written. That is a decision rather than laziness: generating
them would mean a code generator, a schema and a build step in the middle of the one place
where being able to read what a field means matters most, and a generator that runs from
Python type hints could not describe `str(enum)` or the flattening `serialize.py` does
anyway. Hand written types are only safe if something checks them, though, and "somebody
will notice" is not something. This is that something.

Three checks, all from the Python side so they run in the same suite as the change that
would break them:

1. **Every string union matches its `StrEnum`.** `Backend` is `zigbee2mqtt`, not `zigbee`,
   and `Template` has a `virtual_3way` member. Both of those were wrong in the first draft
   of the panel's types and neither would have failed anything until a user saw it.

2. **Every payload matches its interface, field by field and type by type.** Real objects
   go through the real `Serializer`, and the result is checked against the declared
   interface: a field the payload has and the interface does not is drift, a field the
   interface requires and the payload lacks is drift, and a field whose JSON type is not
   one the interface allows is drift. This is what catches a rename in `serialize.py`.

3. **Every command the panel sends exists.** The command strings are read out of `api.ts`
   and checked against `websocket.COMMANDS`, so a renamed command fails here rather than
   in somebody's browser, and a command on `DEFERRED_COMMANDS` cannot be called by
   accident.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
import pytest
from zwave_js_server.model.association import AssociationAddress

from custom_components.device_links.coordinator import RuleState
from custom_components.device_links.executor import JobStatus, LinkOutcome
from custom_components.device_links.models import (
    Backend,
    Diagnostic,
    Direction,
    Feature,
    MirrorChoice,
    PlanOp,
    SettingWrite,
    Template,
)
from custom_components.device_links.serialize import Serializer, diagnostic
from custom_components.device_links.storage import JobLinkResult, JobSummary, Snapshot
from custom_components.device_links.websocket import COMMANDS, DEFERRED_COMMANDS
from tests.conftest import CONTROLLER, LOBBY, a_profile, a_rule, activate
from tests.factories import handle
from tests.fakes.zwave import FakeDriver

if TYPE_CHECKING:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
TYPES_TS = FRONTEND / "src" / "types.ts"
API_TS = FRONTEND / "src" / "api.ts"


# --------------------------------------------------------------------------------------
# Reading the TypeScript
# --------------------------------------------------------------------------------------
#
# A real parser would be overkill and a fragile one would be worse than nothing, so
# `types.ts` is deliberately written to be readable by these three expressions: every
# interface is flat, every field is on its own line, and every union is string literals.
# The docstring at the top of that file says so, which is what keeps it true.

_INTERFACE = re.compile(
    r"^export interface (?P<name>\w+)(?: extends (?P<base>\w+))? \{\n(?P<body>.*?)^\}$",
    re.MULTILINE | re.DOTALL,
)
_FIELD = re.compile(r"^  (?P<name>\w+)(?P<optional>\??): (?P<type>.+?);$", re.MULTILINE)
_UNION = re.compile(r"^export type (?P<name>\w+) =(?P<body>.*?);$", re.MULTILINE | re.DOTALL)
_LITERAL = re.compile(r'"([^"]*)"')


def _source(path: Path) -> str:
    assert path.is_file(), f"{path} is missing; the panel source is part of this repository"
    return path.read_text()


def _interfaces() -> dict[str, dict[str, tuple[str, bool]]]:
    """Return every interface as `{field: (type text, optional)}`, `extends` resolved."""
    raw: dict[str, tuple[str | None, dict[str, tuple[str, bool]]]] = {}
    for match in _INTERFACE.finditer(_source(TYPES_TS)):
        fields = {
            field["name"]: (field["type"], bool(field["optional"]))
            for field in _FIELD.finditer(match["body"])
        }
        raw[match["name"]] = (match["base"], fields)
    resolved: dict[str, dict[str, tuple[str, bool]]] = {}

    def resolve(name: str) -> dict[str, tuple[str, bool]]:
        if name not in resolved:
            base, fields = raw[name]
            resolved[name] = {**(resolve(base) if base else {}), **fields}
        return resolved[name]

    for name in raw:
        resolve(name)
    return resolved


def _unions() -> dict[str, set[str]]:
    """Return every `export type X = "a" | "b"` as its set of members."""
    return {
        match["name"]: set(_LITERAL.findall(match["body"]))
        for match in _UNION.finditer(_source(TYPES_TS))
        if _LITERAL.search(match["body"])
    }


INTERFACES = _interfaces()
UNIONS = _unions()


def _alternatives(text: str) -> list[str]:
    """Split a union type at the `|` that are not inside angle brackets."""
    parts: list[str] = []
    depth = 0
    current = ""
    for character in text:
        if character in "<([":
            depth += 1
        elif character in ">)]":
            depth -= 1
        if character == "|" and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += character
    parts.append(current.strip())
    return [part for part in parts if part]


def _matches(value: Any, type_text: str, path: str) -> bool:
    """True when this JSON value is one of the things this type text allows."""
    return any(_matches_one(value, part, path) for part in _alternatives(type_text))


# The scalar types, and what a JSON value has to be to satisfy each. `bool` is checked
# before `number` because in Python a bool is an int, and True would otherwise pass as a
# number wherever a count is declared.
_SCALARS: dict[str, Any] = {
    "unknown": lambda value: True,
    "null": lambda value: value is None,
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "number": lambda value: isinstance(value, int) and not isinstance(value, bool),
}


def _matches_one(value: Any, text: str, path: str) -> bool:
    """True when this JSON value satisfies one alternative of a type."""
    if text in _SCALARS:
        return bool(_SCALARS[text](value))
    if text.startswith('"') and text.endswith('"'):
        return value == text[1:-1]
    if text.endswith("[]"):
        element = text[:-2]
        return isinstance(value, list) and all(
            _matches(item, element, f"{path}[]") for item in value
        )
    if text.startswith(("Record<", "Partial<Record<")):
        return isinstance(value, dict)
    if text in UNIONS:
        return value in UNIONS[text]
    if text in INTERFACES:
        # Recursion, so a nested object is checked as thoroughly as a top level one.
        is_object = isinstance(value, dict)
        if is_object:
            assert_shape(value, text, path)
        return is_object
    raise AssertionError(f"{path}: nothing in this test knows how to check the type {text!r}")


def assert_shape(payload: Any, interface: str, path: str = "") -> None:
    """Assert that one serialized payload is exactly what one interface declares.

    Exactly: a key the interface does not declare fails as loudly as a key it declares and
    the payload does not have. An extra key is the more dangerous of the two, because it is
    a field somebody added on the Python side that no view will ever render.
    """
    assert interface in INTERFACES, f"{interface} is not declared in {TYPES_TS.name}"
    fields = INTERFACES[interface]
    where = path or interface
    assert isinstance(payload, dict), f"{where} is not an object"

    extra = set(payload) - set(fields)
    assert not extra, f"{where}: {sorted(extra)} in the payload but not in {interface}"
    for name, (type_text, optional) in fields.items():
        if name not in payload:
            assert optional, f"{where}: {interface}.{name} is missing from the payload"
            continue
        assert _matches(payload[name], type_text, f"{where}.{name}"), (
            f"{where}.{name} is {payload[name]!r}, which is not {type_text}"
        )


# --------------------------------------------------------------------------------------
# 1. The enumerations
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("union", "enum"),
    [
        ("Backend", Backend),
        ("Feature", Feature),
        ("TemplateId", Template),
        ("Direction", Direction),
        ("MirrorChoice", MirrorChoice),
        ("PlanOp", PlanOp),
        ("RuleState", RuleState),
        ("JobStatus", JobStatus),
        ("LinkOutcome", LinkOutcome),
    ],
)
def test_every_union_has_exactly_the_members_of_the_enum_it_mirrors(
    union: str, enum: type[Any]
) -> None:
    """A member added on the Python side is a member the panel cannot render."""
    assert union in UNIONS, f"{union} is not declared in {TYPES_TS.name}"
    assert UNIONS[union] == {member.value for member in enum}


# --------------------------------------------------------------------------------------
# 2. The payloads
# --------------------------------------------------------------------------------------


@pytest.fixture
async def loaded(
    hass: HomeAssistant, device_links_entry: MockConfigEntry, zwave_js_devices: dict[int, Any]
) -> MockConfigEntry:
    """An integration set up with one active profile, as the panel would find it."""
    activate(
        device_links_entry,
        a_profile(a_rule(), a_rule("lobby", emitter_id="g5", target_node=LOBBY)),
    )
    await hass.async_block_till_done()
    return device_links_entry


def serializer(hass: HomeAssistant, entry: MockConfigEntry) -> Serializer:
    return Serializer(hass, entry)  # type: ignore[arg-type]


async def test_a_device_row_matches_the_device_row_interface(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    coordinator = loaded.runtime_data.coordinator
    rows = [serializer(hass, loaded).device(device) for device in coordinator.devices.values()]
    assert rows
    for row in rows:
        assert_shape(row, "DeviceRow")


async def test_an_emitter_matches_the_emitter_interface(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    coordinator = loaded.runtime_data.coordinator
    seen = 0
    for identity in coordinator.devices:
        capabilities = coordinator.capabilities_for(identity)
        if capabilities is None:
            continue
        for emitter in serializer(hass, loaded).capabilities(capabilities):
            assert_shape(emitter, "Emitter")
            seen += 1
    assert seen, "no device in the fixture reported an emitter, so nothing was checked"


async def test_an_observed_link_matches_the_link_row_interface(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    coordinator = loaded.runtime_data.coordinator
    seen = 0
    for identity, device in coordinator.devices.items():
        observed = coordinator.observed_for(device)
        assert identity
        if observed is None:
            continue
        for link in observed.links:
            assert_shape(serializer(hass, loaded).link(link), "LinkRow")
            seen += 1
    assert seen, "the fixture network holds no links, so nothing was checked"


async def test_a_plan_matches_the_plan_interface_all_the_way_down(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    """The most important one: the plan dialog renders every level of this."""
    plan = await loaded.runtime_data.coordinator.async_plan()
    payload = serializer(hass, loaded).plan(plan)
    assert_shape(payload, "Plan")
    assert payload["counts"]["add"], "the fixture planned no work, so nothing was checked"
    assert any(device["add"] for device in payload["devices"])


async def test_an_unmanaged_link_matches_the_unmanaged_link_interface(
    hass: HomeAssistant, loaded: MockConfigEntry, zwave_driver: FakeDriver
) -> None:
    """Decision D9's list, which is the one with the tick boxes in front of it."""
    # Somebody's hand-made association, which is the only way one of these exists.
    controller = zwave_driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=CONTROLLER, endpoint=0),
        7,
        [AssociationAddress(controller, node_id=LOBBY, endpoint=None)],
    )
    await loaded.runtime_data.coordinator.async_refresh()

    plan = await loaded.runtime_data.coordinator.async_plan()
    unmanaged = [
        link
        for device in serializer(hass, loaded).plan(plan)["devices"]
        for link in device["unmanaged"]
    ]
    assert unmanaged, "the fixture network holds no unmanaged links, so nothing was checked"
    for link in unmanaged:
        assert_shape(link, "UnmanagedLink")


async def test_a_compiled_rule_matches_the_compiled_rule_interface(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    coordinator = loaded.runtime_data.coordinator
    compiled = coordinator.compile_rule(a_rule())
    assert_shape(serializer(hass, loaded).compiled(compiled), "CompiledRule")


async def test_a_rule_row_matches_the_rule_row_interface(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    payload = serializer(hass, loaded).rule(a_rule())
    assert_shape(payload, "RuleRow")


async def test_a_profile_row_matches_the_profile_row_interface(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    profile = a_profile()
    assert_shape(
        serializer(hass, loaded).profile(profile, active_profile_id=profile.id), "ProfileRow"
    )


async def test_a_device_detail_matches_the_device_detail_interface(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    from custom_components.device_links.websocket import _device_detail  # noqa: PLC0415

    detail = _device_detail(hass, loaded, handle(CONTROLLER))  # type: ignore[arg-type]
    assert_shape(detail, "DeviceDetail")
    assert detail["emitters"], "the controller reported no emitters, so nothing was checked"


def test_a_setting_write_matches_the_setting_write_interface() -> None:
    assert_shape(
        Serializer.setting(
            SettingWrite(
                device=handle(CONTROLLER), capability="led_mode", parameter=3, bitmask=None, value=1
            )
        ),
        "SettingWrite",
    )


def test_a_diagnostic_matches_the_diagnostic_interface() -> None:
    assert_shape(
        diagnostic(Diagnostic("group_full", {"group": "7", "device": "036"})), "Diagnostic"
    )
    assert diagnostic(None) is None


def test_a_job_summary_matches_the_job_interface() -> None:
    job = JobSummary(
        id="j1",
        created_at="2026-09-05T12:00:00+00:00",
        scope="profile",
        status=str(JobStatus.PARTIAL),
        results=(
            JobLinkResult(fingerprint="fp1", status=str(LinkOutcome.APPLIED)),
            JobLinkResult(fingerprint="fp2", status=str(LinkOutcome.FAILED), reason="check_failed"),
        ),
    )
    assert_shape(Serializer.job(job), "Job")


def test_a_snapshot_matches_the_snapshot_interface() -> None:
    snapshot = Snapshot(
        id="s1", created_at="2026-09-05T12:00:00+00:00", reason="pre_apply", devices=("zwave:1:36",)
    )
    assert_shape(Serializer.snapshot(snapshot), "Snapshot")


# --------------------------------------------------------------------------------------
# 3. The commands
# --------------------------------------------------------------------------------------


def _commands_the_panel_sends() -> set[str]:
    """Every `device_links/...` literal in the API client."""
    return set(re.findall(r'"(device_links/[a-z_/]+)"', _source(API_TS)))


def test_every_command_the_panel_sends_is_one_the_backend_registers() -> None:
    """A renamed command should fail here, not in a browser with no error message."""
    sent = _commands_the_panel_sends()
    assert sent, "no commands were found in api.ts, so this test is checking nothing"
    registered = {f"device_links/{command}" for command in COMMANDS}
    assert sent <= registered, (
        f"the panel sends commands nobody serves: {sorted(sent - registered)}"
    )


def test_the_panel_never_sends_a_deliberately_deferred_command() -> None:
    """`unmanaged/adopt` and the swap commands are Phase 2. Calling one can only fail."""
    deferred = {f"device_links/{command}" for command in DEFERRED_COMMANDS}
    assert not _commands_the_panel_sends() & deferred


def test_the_panel_uses_every_command_the_backend_implements() -> None:
    """A command with no caller is either a gap in the panel or dead code in the backend.

    Phase 1E's panel is the only client of this API, so the two sets should be equal. If
    a command is deliberately left uncalled, name it here with the reason rather than
    loosening the assertion.
    """
    unused = {f"device_links/{command}" for command in COMMANDS} - _commands_the_panel_sends()
    assert unused == set(), (
        f"the backend implements commands the panel never calls: {sorted(unused)}"
    )


def test_the_bundle_version_the_panel_compares_against_is_the_manifest_version() -> None:
    """E33 only means anything if both halves read the same field."""
    import json  # noqa: PLC0415

    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "custom_components"
            / "device_links"
            / "manifest.json"
        ).read_text()
    )
    defines = _source(FRONTEND / "build-defines.ts")
    assert "manifest.json" in defines
    assert "__DL_BUNDLE_VERSION__" in defines
    assert manifest["version"]
