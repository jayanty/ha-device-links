"""Every user-facing string, checked against the source rather than against a list.

This file closes open item S5, and the way it does it is the point. A hand-written list of
keys goes stale the first time somebody adds one in a hurry, which is exactly the moment a
user sees `feature_unavailable_level_set` in their UI instead of a sentence. So the keys
are collected from the source: every `_attr_translation_key`, every `translation_key=`, and
the first argument of every `Diagnostic` and `BlockedReason`, read out of the syntax tree.

Both directions are checked. A missing entry is a raw key in somebody's interface; a
leftover entry is a sentence about something that no longer exists, which is worse than
nothing because it reads as documentation.

The collector understands three shapes and no more: a string literal, a conditional between
string literals, and a module-level constant that is a string literal. That is a deliberate
limit rather than an omission. A key composed at runtime cannot be found by searching the
source either, so the fix for one is not a cleverer collector, it is a literal in the code,
which is what `compiler.FEATURE_UNAVAILABLE` and `repairs.ISSUE_PENDING_WAKEUP_INSTRUCTED`
are.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import string
from typing import Any

import pytest

from custom_components.device_links import const
from custom_components.device_links.services import SERVICE_SCHEMAS
from tests.test_services import load_services_yaml

COMPONENT = Path(__file__).parent.parent / "custom_components" / "device_links"

# Modules that are entity platforms: the file name is the platform an entity key sits
# under in `strings.json`, which is how `entity.sensor.health.name` gets its middle part.
PLATFORMS = frozenset({"binary_sensor", "button", "select", "sensor", "switch"})

# Where issue keys come from. Everything else that carries a `translation_key` is an
# exception, because Home Assistant looks both up in different sections.
ISSUES_MODULE = "repairs"


def source_files() -> list[Path]:
    """Return every source file of the integration, backends included."""
    return sorted(COMPONENT.rglob("*.py"))


def load_json(name: str) -> dict[str, Any]:
    """Return one of the integration's JSON files."""
    loaded: dict[str, Any] = json.loads((COMPONENT / name).read_text())
    return loaded


def _constants(tree: ast.Module) -> dict[str, set[str]]:
    """Return what each module-level constant can be, when it can only be strings.

    A plain string constant is itself; a table of them (`compiler.FEATURE_UNAVAILABLE`) is
    all of its values, because an expression that indexes one can produce any of them.
    """
    found: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            possible = {value.value}
        elif isinstance(value, ast.Dict) and all(
            isinstance(entry, ast.Constant) and isinstance(entry.value, str)
            for entry in value.values
        ):
            possible = {entry.value for entry in value.values}  # type: ignore[attr-defined]
        else:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = possible
    return found


def _strings_in(node: ast.AST, constants: dict[str, set[str]]) -> set[str]:
    """Return every key this expression could evaluate to, of the shapes we accept."""
    keys: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            keys.add(child.value)
        elif isinstance(child, ast.Name) and child.id in constants:
            keys |= constants[child.id]
    return keys


def collected() -> dict[str, set[str]]:
    """Return every translation key the source uses, by the section it belongs in."""
    entity: set[str] = set()
    exceptions: set[str] = set()
    issues: set[str] = set()
    for path in source_files():
        tree = ast.parse(path.read_text())
        constants = _constants(tree)
        section = issues if path.stem == ISSUES_MODULE else exceptions
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Attribute) and target.attr == "_attr_translation_key"
                for target in node.targets
            ):
                entity.update(f"{path.stem}.{key}" for key in _strings_in(node.value, constants))
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_attr_translation_key"
                for target in node.targets
            ):
                entity.update(f"{path.stem}.{key}" for key in _strings_in(node.value, constants))
            if isinstance(node, ast.Call):
                if _called(node) in {"Diagnostic", "BlockedReason"} and node.args:
                    exceptions.update(_strings_in(node.args[0], constants))
                for keyword in node.keywords:
                    if keyword.arg == "translation_key":
                        section.update(_strings_in(keyword.value, constants))
    return {"entity": entity, "exceptions": exceptions, "issues": issues}


def _called(node: ast.Call) -> str:
    """Return the name of the thing being called, however it was reached."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


# --------------------------------------------------------------------------------------
# The collector itself, because everything below trusts it
# --------------------------------------------------------------------------------------


def test_the_collector_finds_the_keys_it_is_supposed_to_find() -> None:
    """A collector that quietly found nothing would make every test below pass.

    One key of each shape it accepts: an entity key on a platform, a diagnostic from the
    compiler, an exception raised with a literal, and an issue whose key is a module
    constant.
    """
    keys = collected()

    assert "sensor.health" in keys["entity"]
    assert "feature_unavailable_level_set" in keys["exceptions"]
    assert "unknown_profile" in keys["exceptions"]
    assert "lifeline_is_protected" in keys["exceptions"]
    assert "pending_wakeup_instructed" in keys["issues"]
    assert len(keys["exceptions"]) > 20


# --------------------------------------------------------------------------------------
# Every key resolves, and every entry is used
# --------------------------------------------------------------------------------------


def test_every_entity_key_has_a_name_and_an_icon() -> None:
    """An entity whose name does not resolve has no name, and so no stable entity id."""
    strings = load_json("strings.json")
    icons = load_json("icons.json")

    for key in sorted(collected()["entity"]):
        platform, _, name = key.partition(".")
        assert platform in PLATFORMS, key
        assert strings["entity"][platform][name]["name"], key
        assert icons["entity"][platform][name]["default"], key


def test_every_named_entity_belongs_to_something_that_exists() -> None:
    """The other direction: a name for an entity nobody builds any more."""
    strings = load_json("strings.json")
    icons = load_json("icons.json")
    keys = collected()["entity"]

    for section in (strings, icons):
        for platform, entries in section["entity"].items():
            for name in entries:
                assert f"{platform}.{name}" in keys, f"{platform}.{name}"


def test_every_exception_and_diagnostic_key_has_a_message() -> None:
    """This is S5. Every refusal the compiler, planner, adapter and executor can produce."""
    messages = load_json("strings.json")["exceptions"]

    missing = sorted(key for key in collected()["exceptions"] if key not in messages)

    assert not missing, f"no message in strings.json for: {missing}"


def test_no_message_is_left_over_from_something_that_was_removed() -> None:
    messages = load_json("strings.json")["exceptions"]

    unused = sorted(set(messages) - collected()["exceptions"])

    assert not unused, f"strings.json has messages nothing produces: {unused}"


def test_every_repairs_issue_has_a_title_and_a_description() -> None:
    """A Repairs issue is read by somebody who is already having a bad day."""
    issues = load_json("strings.json")["issues"]
    keys = collected()["issues"]

    assert set(issues) == keys
    for key, entry in issues.items():
        assert entry["title"], key
        assert entry["description"], key


@pytest.mark.parametrize("section", ["exceptions", "issues"])
def test_no_message_is_an_unfinished_sentence(section: str) -> None:
    """The register is plain and specific: a message a user cannot act on is not done.

    A title is a label and is left as one; everything else is prose, and prose that stops
    without a full stop is prose somebody truncated. The em dash check is CLAUDE.md's
    style rule, and this is the file where the rule is easiest to break by accident.
    """
    entries = load_json("strings.json")[section]

    for key, entry in entries.items():
        for field, text in entry.items():
            assert text[0].isupper() or text.startswith(("'", "{")), f"{key}.{field}: {text}"
            assert "\u2014" not in text, f"{key}.{field} uses an em dash"
            if field != "title":
                assert text.rstrip().endswith((".", "?")), f"{key}.{field}: {text}"


# --------------------------------------------------------------------------------------
# Services, config and options
# --------------------------------------------------------------------------------------


def test_every_service_and_field_is_described() -> None:
    """`services.yaml` carries the shape and `strings.json` carries the words.

    Home Assistant shows the text from here, so a field documented in the YAML and missing
    here is a field the user meets in the developer tools with no label at all.
    """
    services = load_json("strings.json")["services"]
    documented = load_services_yaml()

    assert set(services) == set(SERVICE_SCHEMAS)
    for name, service in services.items():
        assert service["name"], name
        assert service["description"], name
        assert set(service.get("fields", {})) == set(documented[name].get("fields", {})), name
        for field, entry in service.get("fields", {}).items():
            assert entry["name"], f"{name}.{field}"
            assert entry["description"], f"{name}.{field}"


def test_every_config_and_options_step_is_described() -> None:
    """Including the abort reasons, which are the only thing a refused setup can say."""
    strings = load_json("strings.json")
    reasons = _abort_reasons()

    assert strings["config"]["step"]["user"]["title"]
    assert strings["config"]["step"]["user"]["description"]
    assert set(strings["config"]["abort"]) == reasons
    init = strings["options"]["step"]["init"]
    assert init["title"]
    assert set(init["data"]) == _option_names()
    assert set(init["data_description"]) == _option_names()


def _abort_reasons() -> set[str]:
    """Return the reasons the config flow can abort with.

    `already_configured` is Home Assistant's own, produced by
    `_abort_if_unique_id_configured` rather than by a literal of ours, so it is named here
    and the rest are read out of the source.
    """
    tree = ast.parse((COMPONENT / "config_flow.py").read_text())
    reasons = {"already_configured"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called(node) == "async_abort":
            for keyword in node.keywords:
                if keyword.arg == "reason":
                    reasons |= _strings_in(keyword.value, {})
    return reasons


def _option_names() -> set[str]:
    """Return every config entry option this integration defines."""
    return {
        value
        for name, value in vars(const).items()
        if name.startswith("OPTION_") and isinstance(value, str)
    }


def test_the_english_translations_match_the_strings_file() -> None:
    """`strings.json` is the source and `translations/en.json` is what is shipped.

    Home Assistant reads the second one at runtime, so a difference between them is a
    string that is right in the repository and wrong in the product.
    """
    assert load_json("strings.json") == json.loads(
        (COMPONENT / "translations" / "en.json").read_text()
    )


# --------------------------------------------------------------------------------------
# The placeholders a message uses have to be there when it is shown
# --------------------------------------------------------------------------------------

# Helpers that build a placeholder dict, and what each one puts in it. Two, both defined
# in this integration, named here because a syntax tree cannot follow a function call. A
# third would have to be added here, which is the point: the alternative is a check that
# quietly stops covering the message it was written for.
PLACEHOLDER_HELPERS = {
    "_about": {"device", "target", "group"},
    "_group_placeholders": {"device", "target", "group"},
}


def _placeholders_at(node: ast.AST | None) -> set[str] | None:
    """Return what this expression supplies, or None when it cannot be read statically."""
    if node is None:
        return set()
    supplied: set[str] = set()
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values, strict=True):
            # A `None` key is `**something`, which is a dict of its own to read.
            nested = _placeholders_at(value) if key is None else _name_of(key)
            if nested is None:
                return None
            supplied |= nested
        return supplied
    if isinstance(node, ast.Call) and _called(node) in PLACEHOLDER_HELPERS:
        return set(PLACEHOLDER_HELPERS[_called(node)])
    if isinstance(node, ast.IfExp):
        left = _placeholders_at(node.body)
        right = _placeholders_at(node.orelse)
        return None if left is None or right is None else left & right
    return None


def _name_of(key: ast.AST) -> set[str] | None:
    """Return the one placeholder this dictionary key names, or None when it is not a name."""
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return {key.value}
    return None


def raise_sites() -> list[tuple[str, str, set[str]]]:
    """Return every place a message is produced with placeholders that can be read.

    A site whose placeholders are built at runtime is left out rather than guessed at: the
    `BlockedReason` table is the main one, and the Z-Wave adapter merges its own
    placeholders into every reason it re-emits, so that key is covered by the merge rather
    than by the table.

    Each site carries the section it belongs to, because one key can be both: the stored
    profiles being unreadable is an exception when it stops a setup and an issue in the
    Repairs panel, and the two are told different things about it.
    """
    sites: list[tuple[str, str, set[str]]] = []
    for path in source_files():
        tree = ast.parse(path.read_text())
        constants = _constants(tree)
        section = "issues" if path.stem == ISSUES_MODULE else "exceptions"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _called(node) == "Diagnostic" and node.args:
                supplied = _placeholders_at(node.args[1] if len(node.args) > 1 else None)
                if supplied is not None:
                    sites += [
                        (section, key, supplied) for key in _strings_in(node.args[0], constants)
                    ]
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            if "translation_key" in keywords:
                # `placeholders` is the name our own `repairs._Issue` uses for the same
                # thing, and it is a site like any other: what it holds is what the
                # Repairs panel will be handed.
                supplied = _placeholders_at(
                    keywords.get("translation_placeholders", keywords.get("placeholders"))
                )
                if supplied is not None:
                    sites += [
                        (section, key, supplied)
                        for key in _strings_in(keywords["translation_key"], constants)
                    ]
    return sites


def test_every_placeholder_a_message_uses_is_there_when_it_is_shown() -> None:
    """A message with a hole in it reads worse than an untranslated one.

    Home Assistant swallows the error and shows the raw `{device}` instead, so this is not
    a crash anybody would see in a log: it is a sentence with a curly brace in it, in a
    user's own language, and nothing else says why.
    """
    strings = load_json("strings.json")

    for section, key, supplied in raise_sites():
        entry = strings[section].get(key, {})
        for field, text in entry.items():
            used = {name for _, name, _, _ in string.Formatter().parse(text) if name}
            assert used <= supplied, (
                f"{section}.{key}.{field} uses {sorted(used - supplied)}, "
                f"which the code does not supply where it raises it"
            )
