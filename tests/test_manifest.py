"""Repository-level invariants that must hold from the very first commit."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from custom_components.device_links import DOMAIN, const

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "device_links"

# Modules that must never import Home Assistant, so they stay unit-testable
# without the HA harness and reusable from tools/ probe scripts.
PURE_MODULES = (
    "models.py",
    "compiler.py",
    "planner.py",
    "yaml_io.py",
    "profile_db.py",
    "backends/zwave_protocol.py",
    "backends/zigbee_protocol.py",
    "backends/matter_protocol.py",
)


def test_manifest_has_required_hacs_keys() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    for key in ("domain", "name", "version", "codeowners", "documentation", "issue_tracker"):
        assert manifest[key], f"manifest.json is missing {key}"
    assert manifest["domain"] == "device_links"
    assert manifest["requirements"] == [], "no new Python requirements without a decision"


def test_hacs_json_matches_manifest() -> None:
    hacs = json.loads((REPO_ROOT / "hacs.json").read_text())
    assert hacs["name"] == "Device Links"
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "device_links.zip"


@pytest.mark.parametrize("relative", PURE_MODULES)
def test_pure_modules_never_import_home_assistant(relative: str) -> None:
    """Guards the core architecture invariant. Skips modules not written yet."""
    path = COMPONENT / relative
    if not path.exists():
        pytest.skip(f"{relative} does not exist yet")

    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not name.startswith("homeassistant"), (
                f"{relative} imports {name}; pure modules must not import Home Assistant"
            )


def test_no_em_dash_in_tracked_text() -> None:
    """Style rule from the PRD: no em dash anywhere in generated text.

    The panel's TypeScript and the built bundle are in scope as well as the Python: a UI
    string is the most visible generated text there is, and the bundle is what a user
    actually runs, so a source file that slipped through would be caught twice.
    """
    suffixes = {".py", ".md", ".json", ".yaml", ".yml", ".ts", ".js", ".mjs", ".html"}
    offenders: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in {".git", "node_modules", ".venv", "dist"} for part in path.parts):
            continue
        if path.name == "test_manifest.py":
            continue
        if "—" in path.read_text(errors="ignore"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"em dash found in: {offenders}"


def test_package_imports_and_domain_matches_manifest() -> None:
    """The package must import cleanly and agree with its own manifest."""

    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == DOMAIN
    assert const.PANEL_URL_PATH == DOMAIN
    assert f"{DOMAIN}.profiles" == const.STORAGE_KEY
    assert const.STORAGE_VERSION >= 1
    assert const.STATIC_URL_BASE.startswith("/")
