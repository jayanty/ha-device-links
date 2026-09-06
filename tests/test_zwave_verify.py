"""Deep verify must actually wait for the device, not just ask nicely.

Stage 0 Z3 found refresh_cc_values is fire and forget. See docs/stage0-report.md.
"""

from __future__ import annotations

from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.models import DeviceHandle
from tests.fakes.zwave import build_driver_from_fixture


async def test_deep_verify_waits_for_the_refresh_to_land() -> None:
    """The fake delays its cache update, exactly as a real device does."""
    driver = build_driver_from_fixture()
    driver.controller.refresh_delay_seconds = 0.05
    driver.controller.stale_group = (36, 7, 38)  # cache lags reality
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle(backend, 36), deep=True)

    assert any(link.emitter_group == "7" for link in observed.links), (
        "deep verify returned the stale cache; it did not wait for the refresh"
    )
    assert observed.deep_verify_timed_out is False
    assert observed.deep_verify_skipped_reason is None


async def test_a_shallow_read_does_not_refresh_at_all() -> None:
    """Refreshing on every read would flood the mesh on a large network (E36)."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    await backend.async_observed(await _handle(backend, 36), deep=False)

    assert driver.controller.refresh_count == 0


async def test_a_shallow_read_never_claims_to_have_verified_anything() -> None:
    """The flags say what was done, so a caller cannot read a cache read as confirmation."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle(backend, 36))

    assert observed.deep_verify_timed_out is False
    assert observed.deep_verify_skipped_reason is None
    assert observed.deep_verified is False


async def test_deep_verify_refreshes_both_association_command_classes() -> None:
    """FR-B4 names Association and Multi Channel Association. A link can live in either."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle(backend, 36), deep=True)

    assert driver.controller.refresh_count == 2
    assert observed.deep_verified is True


async def test_deep_verify_gives_up_after_a_bounded_wait() -> None:
    """A device that never answers must not hang a job forever."""
    driver = build_driver_from_fixture()
    driver.controller.refresh_never_lands = True
    backend = ZWaveBackend(driver=driver, profiles=None, deep_verify_timeout=0.1)

    observed = await backend.async_observed(await _handle(backend, 36), deep=True)

    assert observed.deep_verify_timed_out is True, (
        "a timed-out deep verify must say so, so the caller does not read it as confirmation"
    )
    assert observed.deep_verified is False
    assert observed.links, "the cache is still the best answer available, so it is returned"


async def test_deep_verify_is_skipped_for_a_sleeping_node() -> None:
    """Refreshing a sleeping node cannot succeed and would burn the whole timeout."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle(backend, 40), deep=True)

    assert driver.controller.refresh_count == 0
    assert observed.deep_verify_skipped_reason == "asleep"
    assert observed.deep_verified is False
    assert observed.deep_verify_timed_out is False, "skipped is not the same as tried and failed"


async def test_the_listener_is_gone_once_the_wait_is_over() -> None:
    """A listener per deep verify that outlived it would accumulate one per apply."""
    driver = build_driver_from_fixture()
    driver.controller.refresh_never_lands = True
    backend = ZWaveBackend(driver=driver, profiles=None, deep_verify_timeout=0.05)
    node = driver.controller.nodes[36]

    await backend.async_observed(await _handle(backend, 36), deep=True)

    assert node._listeners.get("value updated", []) == []


async def _handle(backend: ZWaveBackend, node_id: int) -> DeviceHandle:
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))
