"""Guards the one coupling to `matter` internals (PRD Decision D2 applied to Phase 3).

If Home Assistant moves `runtime_data` or renames the adapter's client, this fails in CI
rather than the integration failing on a user's system, which is exactly what
`tests/test_zwave_accessor.py` does for the other borrowed connection.

There is one thing that file can lean on and this one cannot: the Z-Wave accessor's real
guard is mypy reading `async_get_driver`'s annotations, because `zwave_js_server` is
installed in the test environment and mypy can therefore check what `runtime_data.client`
holds. `matter_server` is **not** installed here (Home Assistant installs an integration's
requirements only when that integration is set up, and nothing sets Matter up in this
suite), so mypy sees `Any` from `runtime_data` onwards and the `cast` in `async_get_client`
is where the verified shape is asserted rather than checked. That makes the tests below the
whole of the guard rather than a supplement to it, and it is why they check the upstream
dataclass field by field.
"""

from __future__ import annotations

import ast
import importlib
import importlib.abc
import importlib.machinery
from pathlib import Path
import sys
from types import ModuleType
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_links.backends.matter_client import (
    MatterAccessorError,
    async_get_client,
    async_matter_is_available,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

ACCESSOR_MODULE = "custom_components.device_links.backends.matter_client"

# The library the `matter` integration pulls in, which is absent on a Z-Wave-only or
# Zigbee-only Home Assistant because `matter` was never set up there. The distribution is
# `matter-python-client`, renamed from `python-matter-server`, and the package it installs
# still has the old name (Stage 0 M1, amending PRD Appendix C).
MATTER_LIBRARY = "matter_server"


# --------------------------------------------------------------------------------------
# The module must import on installs that have no Matter at all
# --------------------------------------------------------------------------------------


def _depends_on_the_matter_library(module_name: str) -> bool:
    """True for the library itself and for the upstream package that imports it."""
    for root in (MATTER_LIBRARY, "homeassistant.components.matter"):
        if module_name == root or module_name.startswith(f"{root}."):
            return True
    return False


class _BlockMatterLibrary(importlib.abc.MetaPathFinder):
    """Makes `import matter_server` fail the way a real install without it does."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname == MATTER_LIBRARY or fullname.startswith(f"{MATTER_LIBRARY}."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


@pytest.fixture
def matter_library_unavailable() -> Iterator[None]:
    """Simulate a Home Assistant where `matter` was never set up.

    Everything is restored on teardown: the meta path finder is removed, modules imported
    while it was installed are dropped, and the originals are put back so the rest of the
    suite sees the same module objects it started with.
    """
    saved = {
        name: module
        for name, module in list(sys.modules.items())
        if name == ACCESSOR_MODULE or _depends_on_the_matter_library(name)
    }
    for name in saved:
        del sys.modules[name]

    finder = _BlockMatterLibrary()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        for name in [
            name
            for name in list(sys.modules)
            if name == ACCESSOR_MODULE or _depends_on_the_matter_library(name)
        ]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_the_seam_imports_without_the_matter_library(
    matter_library_unavailable: None,
) -> None:
    """The module must not drag `matter_server` in at import time.

    This integration supports Z-Wave-only and Zigbee-only installs (the `no_backend` abort
    reason in `strings.json`). `matter` is an after-dependency, which does not force it to
    load, so its requirements are not installed there, and
    `homeassistant.components.matter` imports `matter_server` at module scope. A
    module-scope import here would raise `ModuleNotFoundError` and take the whole
    integration down for those users.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(MATTER_LIBRARY)

    module = importlib.import_module(ACCESSOR_MODULE)

    assert hasattr(module, "async_get_client")
    assert hasattr(module, "async_matter_is_available")
    assert hasattr(module, "MatterAccessorError")


def test_the_adapter_imports_without_the_matter_library(
    matter_library_unavailable: None,
) -> None:
    """The same for the adapter itself, which `__init__.py` imports unconditionally."""
    module = importlib.import_module("custom_components.device_links.backends.matter")

    assert hasattr(module, "MatterBackend")


# --------------------------------------------------------------------------------------
# Upstream shape, which is the whole guard here
# --------------------------------------------------------------------------------------


def _matter_source(name: str) -> ast.Module:
    """Return one module of the installed `matter` integration, parsed rather than imported.

    Parsed because it cannot be imported: `homeassistant.components.matter.__init__` imports
    `matter_server` at module scope, and that library is not installed here. Reading the
    source is the strongest guard available in this environment, and it is a real one: it is
    the source Home Assistant will run.
    """
    from homeassistant import components  # noqa: PLC0415

    path = Path(next(iter(components.__path__))) / "matter" / name
    return ast.parse(path.read_text())


def _class_named(tree: ast.Module, name: str) -> ast.ClassDef:
    """Return one class from a parsed module, or fail saying it has gone."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    pytest.fail(f"the matter integration no longer defines {name}")


def test_upstream_runtime_data_still_holds_an_adapter() -> None:
    """`MatterEntryData.adapter` is the first step of the path `async_get_client` walks."""
    entry_data = _class_named(_matter_source("helpers.py"), "MatterEntryData")

    declared = {
        node.target.id
        for node in entry_data.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assert "adapter" in declared, (
        "matter.helpers.MatterEntryData no longer declares an 'adapter' field, so "
        "matter_client.async_get_client walks a path that does not exist. Either upstream "
        "renamed it, in which case the accessor and docs/stage0-report.md must change, or "
        "it exposes the client some other way. Confirm which before editing."
    )


def test_upstream_adapter_still_holds_the_client_under_the_name_we_read() -> None:
    """`MatterAdapter.matter_client` is the second step, and it is an attribute we read."""
    adapter = _class_named(_matter_source("adapter.py"), "MatterAdapter")

    assigned = {
        target.attr
        for node in ast.walk(adapter)
        for target in getattr(node, "targets", [])
        if isinstance(target, ast.Attribute)
    }

    assert "matter_client" in assigned, (
        "matter.adapter.MatterAdapter no longer assigns self.matter_client, so "
        "matter_client.async_get_client cannot reach a client through it."
    )


def test_upstream_still_registers_the_device_identifier_this_adapter_reproduces() -> None:
    """Stage 0 item P2's format, which `registry_identifier` has to match exactly.

    Getting it wrong makes an orphaned device rather than an error: our entities would
    attach to a device nobody else registered, and nothing would say why.
    """
    source = _matter_source("helpers.py")
    constants = _matter_source("const.py")

    text = ast.unparse(source)

    assert "f'{server_info.compressed_fabric_id:016X}'" in text
    assert "f'{node.node_id:016X}'" in text
    assert "f'{fabric_id_hex}-{node_id_hex}'" in text
    assert "'MatterNodeDevice'" in text
    assert "ID_TYPE_DEVICE_ID = 'deviceid'" in ast.unparse(constants), (
        "matter.const.ID_TYPE_DEVICE_ID is no longer 'deviceid', so the identifier "
        "backends/matter.py builds no longer matches the one upstream registers."
    )


def test_the_client_type_cannot_be_checked_here_and_the_seam_says_so() -> None:
    """Pins the reason the tests above are the guard rather than a supplement to mypy.

    If `matter_server` ever becomes installed in this environment, that is worth knowing:
    the `cast` in `async_get_client` could then be replaced by a checked annotation, which
    is what makes the Z-Wave accessor's guard strong, and this test is where that is
    noticed rather than never.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(MATTER_LIBRARY)


def test_matter_is_available_only_says_whether_the_component_is_loaded(
    hass: HomeAssistant,
) -> None:
    """A membership test, because it must be answerable where the package cannot import."""
    assert not async_matter_is_available(hass)

    hass.config.components.add("matter")

    assert async_matter_is_available(hass)


# --------------------------------------------------------------------------------------
# Our own behaviour
# --------------------------------------------------------------------------------------


def test_async_get_client_returns_the_entry_client() -> None:
    matter_entry = MagicMock()
    matter_entry.runtime_data.adapter.matter_client = sentinel = object()

    assert async_get_client(matter_entry) is sentinel


def test_async_get_client_raises_a_typed_error_when_there_is_no_client() -> None:
    matter_entry = MagicMock()
    matter_entry.runtime_data.adapter.matter_client = None

    with pytest.raises(MatterAccessorError, match="not connected"):
        async_get_client(matter_entry)


def test_async_get_client_names_what_it_could_not_find() -> None:
    """A Home Assistant that moved `runtime_data` must produce a message naming it."""

    class _NoAdapter:
        """A runtime data object of the shape an upstream refactor could leave behind."""

    matter_entry = MagicMock()
    matter_entry.runtime_data = _NoAdapter()
    matter_entry.entry_id = "abc123"

    with pytest.raises(MatterAccessorError, match="does not hold a client"):
        async_get_client(matter_entry)


def test_the_accessor_is_still_a_callback() -> None:
    """@callback is a promise to callers, so nothing may quietly drop it."""
    assert getattr(async_get_client, "_hass_callback", False), (
        "matter_client.async_get_client lost Home Assistant's @callback decorator. "
        "Callers are entitled to call it directly from the event loop because of it."
    )


def test_the_client_protocol_names_only_what_the_adapter_uses() -> None:
    """A seam that grew would be a coupling nobody reviewed.

    Four methods and one property. Anything else the adapter wants, it reads as an
    attribute through `read_attribute`, which is the call Stage 0 M1 exercised.
    """
    from custom_components.device_links.backends.matter_client import (  # noqa: PLC0415
        MatterClient,
    )

    named = {name for name in vars(MatterClient) if not name.startswith("_")}

    assert named == {
        "get_nodes",
        "read_attribute",
        "write_attribute",
        "subscribe_events",
        "server_info",
    }
