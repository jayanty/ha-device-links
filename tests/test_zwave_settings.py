"""Settings adapters and the subscription that keeps observed state fresh."""

from __future__ import annotations

import asyncio

import pytest
from zwave_js_server.const import CommandClass

from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.backends.zwave_accessor import ZWaveAccessorError
from custom_components.device_links.models import DeviceHandle
from tests.factories import profiles
from tests.fakes.zwave import FakeValue, build_driver_from_fixture


@pytest.fixture
def backend() -> ZWaveBackend:
    return ZWaveBackend(driver=build_driver_from_fixture(), profiles=profiles())


async def test_reading_a_bitmask_setting_returns_just_that_bit(backend: ZWaveBackend) -> None:
    """Inovelli parameter 59 bit 2 is mirror_hub_commands, and it was 0 at capture."""
    value = await backend.async_read_setting(await _handle(backend, 37), "mirror_hub_commands")

    assert value.value == 0
    assert value.parameter == 59
    assert value.bitmask == 2


async def test_reading_a_whole_parameter_setting_carries_no_bitmask(
    backend: ZWaveBackend,
) -> None:
    """A missing bitmask has to mean the whole parameter, and say so rather than imply it."""
    value = await backend.async_read_setting(await _handle(backend, 37), "smart_bulb_mode")

    assert value.parameter == 52
    assert value.bitmask is None


async def test_reading_a_setting_the_device_has_not_reported_is_not_a_zero(
    backend: ZWaveBackend,
) -> None:
    """Absent and off are different, and reporting one as the other plans the wrong write."""
    node = backend._driver.controller.nodes[37]
    node.values = {
        value_id: value
        for value_id, value in node.values.items()
        if (int(value.property_), value.property_key) != (52, None)
    }

    value = await backend.async_read_setting(await _handle(backend, 37), "smart_bulb_mode")

    assert value.value is None


async def test_reading_a_setting_a_model_does_not_have_says_so(backend: ZWaveBackend) -> None:
    """E31: the ZEN37's config values were never captured, so it has no adapters at all."""
    with pytest.raises(ZWaveAccessorError, match="mirror_hub_commands"):
        await backend.async_read_setting(await _handle(backend, 40), "mirror_hub_commands")


async def test_writing_a_setting_reads_it_back(backend: ZWaveBackend) -> None:
    """PRD Section 8.4: parameter writes are read back after writing."""
    handle = await _handle(backend, 37)
    result = await backend.async_write_setting(handle, "mirror_hub_commands", 1)

    assert result.ok is True
    assert result.read_back == 1


async def test_writing_a_setting_a_model_does_not_have_fails_cleanly(
    backend: ZWaveBackend,
) -> None:
    """E31: an unknown adapter is a clear message, not a traceback."""
    result = await backend.async_write_setting(await _handle(backend, 40), "mirror_hub_commands", 1)

    assert result.ok is False
    assert result.reason is not None
    assert "settings_not_available" in result.reason.translation_key


async def test_writing_a_setting_the_device_has_not_reported_fails_cleanly(
    backend: ZWaveBackend,
) -> None:
    """Nothing to address means nothing to write, and no guess at a value id."""
    node = backend._driver.controller.nodes[37]
    node.values = {}

    result = await backend.async_write_setting(await _handle(backend, 37), "mirror_hub_commands", 1)

    assert result.ok is False
    assert result.reason is not None
    assert "setting_not_reported" in result.reason.translation_key


async def test_a_write_the_device_accepts_and_ignores_is_not_a_success(
    backend: ZWaveBackend,
) -> None:
    """The read-back is the point of the read-back. Without it this reports a lie."""
    node = backend._driver.controller.nodes[37]

    async def _accept_and_forget(*args: object, **kwargs: object) -> None:
        return None

    node.async_set_value = _accept_and_forget  # type: ignore[method-assign]

    result = await backend.async_write_setting(await _handle(backend, 37), "mirror_hub_commands", 1)

    assert result.ok is False
    assert result.read_back == 0
    assert result.reason is not None
    assert "setting_not_applied" in result.reason.translation_key


async def test_a_failing_setting_write_reports_why(backend: ZWaveBackend) -> None:
    driver = backend._driver
    driver.controller.raise_on_write = RuntimeError("ZW0201: transmit failed")

    result = await backend.async_write_setting(await _handle(backend, 37), "mirror_hub_commands", 1)

    assert result.ok is False
    assert result.reason is not None
    assert "setting_write_failed" in result.reason.translation_key


async def test_a_setting_write_never_touches_local_control_unasked(
    backend: ZWaveBackend,
) -> None:
    """Decision D4: parameter 19 is Jayant's deliberate state. Never write it implicitly."""
    await backend.async_write_setting(await _handle(backend, 39), "mirror_hub_commands", 1)

    assert 19 not in backend._driver.controller.written_parameters
    assert backend._driver.controller.written_parameters == {35: [(4, 1)]}


async def test_subscribing_delivers_a_callback_when_an_association_changes(
    backend: ZWaveBackend,
) -> None:
    """FR-B3 and goal G3: drift is noticed without polling.

    NOTE: whether a real driver emits this for an externally-made change is Stage 0 item
    Z5, which was never run. See docs/open-items.md J4 and issue #8.
    """
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    backend._driver.controller.emit_association_changed(36)

    assert seen == ["zwave:3538613642:36"]
    unsubscribe()


async def test_a_configuration_change_is_noticed_too(backend: ZWaveBackend) -> None:
    """FR-B3 names CC 0x70 as well: a setting changed by hand is drift like any other."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    backend._driver.controller.emit_association_changed(
        37, command_class=CommandClass.CONFIGURATION
    )

    assert seen == ["zwave:3538613642:37"]
    unsubscribe()


async def test_an_unrelated_value_change_wakes_nobody(backend: ZWaveBackend) -> None:
    """A dimmer reporting its level must not re-read every association on the mesh."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    backend._driver.controller.emit_association_changed(
        36, command_class=CommandClass.SWITCH_MULTILEVEL
    )

    assert seen == []
    unsubscribe()


async def test_a_burst_about_one_device_is_debounced(backend: ZWaveBackend) -> None:
    """One refresh emits an event per group. The caller only needs to know to re-read."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    for group in (2, 3, 4):
        backend._driver.controller.emit_association_changed(36, group=group)

    assert seen == ["zwave:3538613642:36"], "the burst behind the first event was not swallowed"
    unsubscribe()


async def test_a_burst_about_two_devices_reports_both(backend: ZWaveBackend) -> None:
    """Debouncing is per device: swallowing another device's change would lose it."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    backend._driver.controller.emit_association_changed(36)
    backend._driver.controller.emit_association_changed(37)

    assert seen == ["zwave:3538613642:36", "zwave:3538613642:37"]
    unsubscribe()


async def test_a_change_after_the_debounce_window_is_delivered() -> None:
    """The window swallows a burst, not the next real change."""
    backend = ZWaveBackend(driver=build_driver_from_fixture(), profiles=None, debounce_seconds=0.01)
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    backend._driver.controller.emit_association_changed(36)
    await asyncio.sleep(0.02)
    backend._driver.controller.emit_association_changed(36)

    assert len(seen) == 2
    unsubscribe()


async def test_unsubscribing_stops_callbacks(backend: ZWaveBackend) -> None:
    """A listener that outlives an unload leaks and fires against a dead entry."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)
    unsubscribe()

    backend._driver.controller.emit_association_changed(36)

    assert seen == []


async def test_unsubscribing_leaves_no_listener_behind(backend: ZWaveBackend) -> None:
    """Not merely quiet: gone, so a reload does not accumulate a listener per load."""
    unsubscribe = backend.subscribe(lambda identity: None)
    unsubscribe()

    assert all(
        node._listeners.get("value updated", []) == []
        for node in backend._driver.controller.nodes.values()
    )


async def test_a_callback_already_dispatched_by_an_emit_does_not_fire_after_unsubscribe(
    backend: ZWaveBackend,
) -> None:
    """`EventBase.emit` iterates a copy of its listeners, so removal mid-emit is not enough.

    A config entry unload happening while the driver is dispatching a burst is exactly
    when a callback would reach a coordinator that has already torn itself down.
    """
    seen: list[str] = []
    node = backend._driver.controller.nodes[36]

    def _unload_everything(event: object) -> None:
        unsubscribe()

    node.on("value updated", _unload_everything)
    unsubscribe = backend.subscribe(seen.append)

    backend._driver.controller.emit_association_changed(36)

    assert seen == []


async def test_an_event_carrying_no_value_is_ignored(backend: ZWaveBackend) -> None:
    """Upstream owns this payload. An unexpected shape goes quiet, it does not throw."""
    seen: list[str] = []
    unsubscribe = backend.subscribe(seen.append)

    backend._driver.controller.nodes[36].emit("value updated", {"nodeId": 36})

    assert seen == []
    unsubscribe()


async def test_an_event_that_names_no_node_is_ignored(backend: ZWaveBackend) -> None:
    """The same defensiveness at the other end: no node, no identity to report."""
    seen: list[str] = []
    node = backend._driver.controller.nodes[36]
    unsubscribe = backend.subscribe(seen.append)

    node.emit(
        "value updated",
        {
            "nodeId": 36,
            "value": FakeValue(
                node_id=36,
                command_class=CommandClass.ASSOCIATION,
                property_="nodeIds",
                property_key=2,
                endpoint=0,
                value=[],
            ),
        },
    )

    assert seen == []
    unsubscribe()


async def test_a_battery_device_has_no_wake_instructions_recorded_yet(
    backend: ZWaveBackend,
) -> None:
    """T4: the ZEN37's wake sequence was never observed, because Z4 was never approved."""
    assert backend.wake_instructions(await _handle(backend, 40)) is None


async def test_a_model_with_no_profile_has_no_wake_instructions(
    backend: ZWaveBackend,
) -> None:
    """The ZEN32 (node 29) has no curated entry at all. See open item T3."""
    assert backend.wake_instructions(await _handle(backend, 29)) is None


async def _handle(backend: ZWaveBackend, node_id: int) -> DeviceHandle:
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))
