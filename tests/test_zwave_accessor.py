"""Guards the one coupling to zwave_js internals (PRD Decision D2, Stage 0 Z1).

If Home Assistant moves runtime_data or renames the helper, this test fails in CI
rather than the integration failing on a user's system.

Note that the strongest guard in this file is not a test at all, it is mypy reading the
annotations on zwave_accessor.async_get_driver. The tests below exist to protect the
things mypy cannot see: that the module imports on a system without the Z-Wave library,
that those annotations are still there to be checked, that the @callback promises still
hold, and that the library version CI validates against is the one Home Assistant uses.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from homeassistant.components.zwave_js import helpers, models
from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_links.backends import zwave_accessor
from custom_components.device_links.backends.zwave_accessor import (
    ZWaveAccessorError,
    async_get_driver,
    async_get_node,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

ACCESSOR_MODULE = "custom_components.device_links.backends.zwave_accessor"

# The library zwave_js pulls in, and which is absent on a Zigbee-only or Matter-only
# Home Assistant because zwave_js was never set up there.
ZWAVE_JS_LIBRARY = "zwave_js_server"


# --------------------------------------------------------------------------------------
# The module must import on installs that have no Z-Wave at all
# --------------------------------------------------------------------------------------


def _depends_on_the_zwave_library(module_name: str) -> bool:
    """True for the library itself and for the upstream package that imports it."""
    for root in (ZWAVE_JS_LIBRARY, "homeassistant.components.zwave_js"):
        if module_name == root or module_name.startswith(f"{root}."):
            return True
    return False


class _BlockZWaveLibrary(importlib.abc.MetaPathFinder):
    """Makes `import zwave_js_server` fail the way a real install without it does."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname == ZWAVE_JS_LIBRARY or fullname.startswith(f"{ZWAVE_JS_LIBRARY}."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


@pytest.fixture
def zwave_library_unavailable() -> Iterator[None]:
    """Simulate a Home Assistant where zwave_js was never set up.

    Home Assistant installs an integration's requirements only when that integration is
    set up, so on a Zigbee-only or Matter-only install `zwave_js_server` is simply not
    importable. requirements_test.txt installs it unconditionally, which is why this has
    to be faked rather than observed.

    Everything is restored on teardown: the meta path finder is removed, modules
    imported while it was installed are dropped, and the originals are put back so the
    rest of the suite sees the same module objects it started with.
    """
    saved = {
        name: module
        for name, module in list(sys.modules.items())
        if name == ACCESSOR_MODULE or _depends_on_the_zwave_library(name)
    }
    for name in saved:
        del sys.modules[name]

    finder = _BlockZWaveLibrary()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        for name in [
            name
            for name in list(sys.modules)
            if name == ACCESSOR_MODULE or _depends_on_the_zwave_library(name)
        ]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_accessor_imports_without_the_zwave_js_library(
    zwave_library_unavailable: None,
) -> None:
    """The module must not drag zwave_js_server in at import time.

    device_links supports Zigbee-only and Matter-only installs (the no_backend abort
    reason in strings.json). zwave_js is an after_dependency, which does not force it to
    load, so its requirements are not installed there. A module-scope import of
    zwave_js.helpers would raise ModuleNotFoundError and take the whole integration down
    for those users. Keep the import inside async_get_node.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(ZWAVE_JS_LIBRARY)

    module = importlib.import_module(ACCESSOR_MODULE)

    assert hasattr(module, "async_get_node"), (
        f"{ACCESSOR_MODULE} imported but no longer exposes async_get_node"
    )
    assert hasattr(module, "async_get_driver")
    assert hasattr(module, "ZWaveAccessorError")


# --------------------------------------------------------------------------------------
# The annotations and decorators that are the real guard
# --------------------------------------------------------------------------------------


def test_async_get_driver_annotations_are_pinned() -> None:
    """These two strings are what makes mypy the drift detector for runtime_data.

    `from __future__ import annotations` means they are plain strings at runtime, so
    this is a direct comparison.
    """
    assert async_get_driver.__annotations__ == {
        "zwave_js_entry": "ZwaveJSConfigEntry",
        "return": "Driver",
    }, (
        "zwave_accessor.async_get_driver's annotations changed to "
        f"{async_get_driver.__annotations__}. Most of the protection against a "
        "Home Assistant upgrade moving runtime_data comes from mypy reading exactly "
        "these two annotations, not from this test file. Loosening the parameter to a "
        "bare ConfigEntry makes runtime_data untyped: mypy then has nothing left to "
        "check on .client.driver and says only 'Returning Any', which the next person "
        "silences with a cast, after which the guard is gone and every runtime test "
        "here still passes. If a caller holds a generic ConfigEntry, narrow it at the "
        "call site instead. Restore the annotation, do not relax it. If upstream "
        "genuinely renamed ZwaveJSConfigEntry or Driver, update the TYPE_CHECKING "
        "imports in zwave_accessor and this test together."
    )


@pytest.mark.parametrize(
    "func", [async_get_driver, async_get_node], ids=["async_get_driver", "async_get_node"]
)
def test_accessor_functions_are_still_callbacks(func: Callable[..., Any]) -> None:
    """@callback is a promise to callers, so nothing may quietly drop it."""
    assert getattr(func, "_hass_callback", False), (
        f"zwave_accessor.{func.__name__} lost Home Assistant's @callback decorator. "
        "Callers are entitled to call it directly from the event loop because of that "
        "decorator, and nothing else in this suite notices its removal. Either restore "
        "@callback, or rename the function and move every caller to the executor."
    )


def test_upstream_helper_is_still_a_callback() -> None:
    """Our @callback on async_get_node is only honest while upstream's holds."""
    assert getattr(helpers.async_get_node_from_device_id, "_hass_callback", False), (
        "zwave_js.helpers.async_get_node_from_device_id no longer carries @callback. "
        "zwave_accessor.async_get_node advertises @callback purely because upstream "
        "did nothing but registry lookups; if upstream may now block, our decorator is "
        "lying to every caller and neither mypy nor the iscoroutinefunction check will "
        "say so, because a blocking function is not a coroutine. Remove @callback from "
        "zwave_accessor.async_get_node and move its callers to the executor."
    )


# --------------------------------------------------------------------------------------
# Upstream shape
# --------------------------------------------------------------------------------------


def test_upstream_runtime_data_shape_is_unchanged() -> None:
    """ZwaveJSData must still carry a client whose driver async_get_driver can reach."""
    data = models.ZwaveJSData
    exposes_client = (
        "client" in getattr(data, "__dataclass_fields__", {})
        or "client" in getattr(data, "_fields", ())
        or "client" in getattr(data, "__annotations__", {})
        or hasattr(data, "client")
    )
    assert exposes_client, (
        "zwave_js.models.ZwaveJSData no longer reaches 'client' in any form this test "
        f"recognises (it is a {type(data).__name__} exposing {dir(data)}). Either "
        "upstream removed the attribute, in which case zwave_accessor.async_get_driver "
        "must change and docs/stage0-report.md is stale, or upstream exposes it some "
        "other way, in which case widen this check. Confirm which before editing."
    )


def test_upstream_helper_still_exists() -> None:
    """The device-id to Node helper must still exist and accept the call we make."""
    fn = getattr(helpers, "async_get_node_from_device_id", None)
    assert fn is not None, "zwave_js.helpers.async_get_node_from_device_id disappeared"

    signature = inspect.signature(fn)
    try:
        # Exactly what zwave_accessor.async_get_node passes: two positional arguments.
        # Binding rather than inspecting the first two parameter names means a newly
        # required third parameter upstream fails here instead of slipping through.
        signature.bind(MagicMock(spec=HomeAssistant), "device-id")
    except TypeError as err:
        pytest.fail(
            "zwave_accessor.async_get_node calls "
            "async_get_node_from_device_id(hass, device_id) with two positional "
            f"arguments and upstream no longer accepts that: {err}. Upstream signature "
            f"is now {signature}. Fix the call site in zwave_accessor.async_get_node."
        )

    assert not inspect.iscoroutinefunction(fn), (
        "async_get_node_from_device_id became a coroutine; "
        "zwave_accessor.async_get_node must be awaited now"
    )


def test_test_environment_pins_the_zwave_library_version_home_assistant_uses() -> None:
    """CI must validate the guards against the library the real Home Assistant loads.

    requirements_test.txt pins zwave-js-server-python explicitly, and pip honours our
    pin over the one zwave_js asks for. Bumping homeassistant to a release whose
    zwave_js needs a newer library would otherwise leave every guard in this file
    validating against a version no user runs, silently.
    """
    package = "zwave-js-server-python"
    manifest_path = Path(helpers.__file__).parent / "manifest.json"
    requirements = json.loads(manifest_path.read_text())["requirements"]

    required = [req for req in requirements if req.replace("_", "-").startswith(package)]
    assert len(required) == 1, (
        f"zwave_js's manifest.json no longer requires exactly one {package} "
        f"(requirements are {requirements}); update requirements_test.txt by hand and "
        "adjust this test to match the new shape."
    )

    requirement = required[0]
    assert "==" in requirement, (
        f"zwave_js now requires {package} as {requirement!r} rather than an exact pin; "
        "pick a version inside that range for requirements_test.txt and adjust this test."
    )
    wanted = requirement.split("==", 1)[1].strip()
    installed = importlib.metadata.version(package)

    assert installed == wanted, (
        f"zwave_js in the installed Home Assistant requires {package}=={wanted} but the "
        f"test environment has {installed}. Bump the {package} pin in "
        "requirements_test.txt to "
        f"{wanted}, otherwise every guard in this file validates the accessor against a "
        "library version Home Assistant does not use."
    )


# --------------------------------------------------------------------------------------
# Our own behaviour
# --------------------------------------------------------------------------------------


def test_async_get_driver_returns_the_entry_driver() -> None:
    zwave_js_entry = MagicMock()
    zwave_js_entry.runtime_data.client.driver = sentinel = object()

    assert async_get_driver(zwave_js_entry) is sentinel


def test_async_get_driver_raises_a_typed_error_when_the_client_has_no_driver() -> None:
    zwave_js_entry = MagicMock()
    zwave_js_entry.runtime_data.client.driver = None

    with pytest.raises(ZWaveAccessorError, match="not connected"):
        async_get_driver(zwave_js_entry)


async def test_async_get_node_returns_the_upstream_node(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the success path so a refactor cannot make the wrapper return None."""
    node = object()

    def fake(*args: object, **kwargs: object) -> object:
        return node

    # async_get_node imports the helpers module lazily and looks the attribute up on it
    # at call time, so patching upstream's module is what the accessor actually sees.
    monkeypatch.setattr(helpers, "async_get_node_from_device_id", fake)

    assert async_get_node(hass, "some-device-id") is node


async def test_upstream_still_signals_a_missing_device_with_value_error(
    hass: HomeAssistant,
) -> None:
    """Pin the exception contract that zwave_accessor.async_get_node catches.

    The monkeypatched test above replaces the upstream helper with a fake, so it only
    proves our code path against our own fake. This one calls the real helper against a
    real, empty device registry. If Home Assistant ever changes this to a different
    exception type, the except clause in zwave_accessor.async_get_node stops catching
    it and users see an unwrapped upstream error, so that change must fail here first.
    """
    try:
        helpers.async_get_node_from_device_id(hass, "device-id-that-does-not-exist")
    except ValueError as err:
        message = str(err)
    except Exception as err:
        pytest.fail(
            "zwave_js.helpers.async_get_node_from_device_id raised "
            f"{type(err).__name__} instead of ValueError for an unknown device id. "
            "This is the serious case: zwave_accessor.async_get_node only catches "
            "ValueError, so this now escapes unwrapped to users. Fix the except clause "
            "there rather than widening this test."
        )
    else:
        pytest.fail(
            "zwave_js.helpers.async_get_node_from_device_id no longer raises for an "
            "unknown device id. zwave_accessor.async_get_node relies on it raising; "
            "find out what it returns now and handle that."
        )

    assert "is not valid" in message, (
        "zwave_js still raises ValueError, so the except clause in "
        "zwave_accessor.async_get_node still works and nothing is broken for users. "
        f"Only the wording changed, to {message!r}. Update this match string."
    )


async def test_async_get_node_wraps_the_real_upstream_helper(hass: HomeAssistant) -> None:
    """End-to-end proof of the wrap, with nothing monkeypatched.

    The message must not claim a cause. Upstream reports five different situations with
    a bare ValueError, three of which are about a device that genuinely is a Z-Wave
    device, so "is not a Z-Wave device" was wrong for most of them.
    """
    with pytest.raises(ZWaveAccessorError, match="Cannot resolve device"):
        async_get_node(hass, "device-id-that-does-not-exist")


def test_module_exports_only_the_supported_surface() -> None:
    """Nothing may reach zwave_js internals by importing them back out of here."""
    assert zwave_accessor.__all__ == [
        "ZWaveAccessorError",
        "async_get_driver",
        "async_get_node",
    ]
