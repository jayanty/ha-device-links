"""Guards the one coupling to zwave_js internals (PRD Decision D2, Stage 0 Z1).

If Home Assistant moves runtime_data or renames the helper, this test fails in CI
rather than the integration failing on a user's system.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from homeassistant.components.zwave_js import helpers, models
from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_links.backends.zwave_accessor import (
    ZWaveAccessorError,
    async_get_node,
    get_driver,
)


def test_upstream_runtime_data_shape_is_unchanged() -> None:
    """ZwaveJSData must still carry a client whose driver we can reach."""
    assert "client" in models.ZwaveJSData.__dataclass_fields__, (
        "zwave_js.models.ZwaveJSData no longer exposes 'client'; "
        "update zwave_accessor.get_driver and docs/stage0-report.md"
    )


def test_upstream_config_entry_alias_still_exists() -> None:
    """get_driver is typed against this alias, so mypy sees an upstream rename."""
    assert hasattr(models, "ZwaveJSConfigEntry"), (
        "zwave_js.models.ZwaveJSConfigEntry disappeared; "
        "update zwave_accessor.get_driver and docs/stage0-report.md"
    )


def test_upstream_helper_still_exists() -> None:
    """The device-id to Node helper must still exist with a compatible signature."""
    fn = getattr(helpers, "async_get_node_from_device_id", None)
    assert fn is not None, "zwave_js.helpers.async_get_node_from_device_id disappeared"

    params = list(inspect.signature(fn).parameters)
    assert params[:2] == ["hass", "device_id"], f"unexpected signature: {params}"

    assert not inspect.iscoroutinefunction(fn), (
        "async_get_node_from_device_id became a coroutine; "
        "zwave_accessor.async_get_node must be awaited now"
    )


def test_get_driver_returns_the_entry_driver() -> None:
    entry = MagicMock()
    entry.runtime_data.client.driver = sentinel = object()

    assert get_driver(entry) is sentinel


def test_get_driver_raises_a_typed_error_when_the_client_has_no_driver() -> None:
    entry = MagicMock()
    entry.runtime_data.client.driver = None

    with pytest.raises(ZWaveAccessorError, match="not connected"):
        get_driver(entry)


async def test_async_get_node_returns_the_upstream_node(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the success path so a refactor cannot make the wrapper return None."""
    node = object()

    def fake(*args: object, **kwargs: object) -> object:
        return node

    monkeypatch.setattr(
        "custom_components.device_links.backends.zwave_accessor."
        "zwave_js_helpers.async_get_node_from_device_id",
        fake,
    )

    assert async_get_node(hass, "some-device-id") is node


async def test_async_get_node_wraps_upstream_failures(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing device must surface as our error type, not an upstream one."""

    def boom(*args: object, **kwargs: object) -> None:
        raise ValueError("Device ID not found")

    monkeypatch.setattr(
        "custom_components.device_links.backends.zwave_accessor."
        "zwave_js_helpers.async_get_node_from_device_id",
        boom,
    )

    with pytest.raises(ZWaveAccessorError, match="not a Z-Wave device"):
        async_get_node(hass, "missing-device-id")


async def test_upstream_still_signals_a_missing_device_with_value_error(
    hass: HomeAssistant,
) -> None:
    """Pin the exception contract that zwave_accessor.async_get_node catches.

    Every other node test replaces the upstream helper with a fake that raises
    ValueError by construction, so those tests only prove our except clause works
    against our own fake. This one calls the real helper against a real, empty device
    registry. If Home Assistant ever changes this to a different exception type, the
    except clause in zwave_accessor.async_get_node stops catching it and users see an
    unwrapped upstream error, so that change must fail here first.
    """
    with pytest.raises(ValueError, match="is not valid"):
        helpers.async_get_node_from_device_id(hass, "device-id-that-does-not-exist")


async def test_async_get_node_wraps_the_real_upstream_helper(hass: HomeAssistant) -> None:
    """End-to-end proof of the wrap, with nothing monkeypatched."""
    with pytest.raises(ZWaveAccessorError, match="not a Z-Wave device"):
        async_get_node(hass, "device-id-that-does-not-exist")
