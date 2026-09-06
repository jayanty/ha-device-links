"""Writing. Every refusal is tested, because each one protects a working home."""

from __future__ import annotations

from custom_components.device_links.backends.base import LinkResultStatus
from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.models import DeviceHandle, Feature, Link, LinkTarget
from tests.factories import handle, link
from tests.fakes.zwave import build_driver_from_fixture


async def test_adding_a_link_writes_it_and_reports_applied() -> None:
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.APPLIED
    observed = await backend.async_observed(await _handle(backend, 36))
    assert any(link.emitter_group == "7" for link in observed.links)


async def test_adding_a_link_that_is_already_present_is_not_a_write() -> None:
    """E12. Re-writing an existing entry wastes a radio round trip on a busy mesh."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    await backend.async_add_link(_link(36, "7", 38))

    before = driver.controller.write_count
    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert driver.controller.write_count == before, "a redundant write reached the radio"


async def test_removing_a_lifeline_is_refused_even_when_asked_directly() -> None:
    """Defence in depth. The planner will not ask, but a service call could.

    Removing a lifeline stops the device reporting to Home Assistant entirely, and the
    user has no easy way to notice or to undo it.
    """
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_remove_link(_link(36, "1", 1))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert "lifeline" in result.reason.translation_key
    assert driver.controller.write_count == before, "a lifeline removal reached the radio"


async def test_adding_to_a_lifeline_is_refused_too() -> None:
    """Group 1 is the driver's to manage. Ours to read, never ours to write."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_add_link(_link(36, "1", 38))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert "lifeline" in result.reason.translation_key
    assert driver.controller.write_count == before


async def test_a_self_association_is_blocked_before_any_write() -> None:
    """E7. The driver would refuse it too, but we must not spend a round trip finding out.

    `Link` itself refuses to build one, so this reaches past that to hand the adapter what
    a caller who did not go through `Link.__post_init__` could hand it: deserialized
    storage, a service call, a future model. Defence in depth means the adapter refuses
    on its own, not because something upstream already did.
    """
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_add_link(_self_association(36, "7"))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert "self_association" in result.reason.translation_key
    assert driver.controller.write_count == before


async def test_a_check_refusal_blocks_and_translates_the_reason() -> None:
    """FR-B2: any non-OK check result blocks with the enum reason as a message."""
    driver = build_driver_from_fixture()
    driver.controller.force_check_result = 6  # destination security class not granted
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.BLOCKED
    assert result.reason is not None
    assert "security_class" in result.reason.translation_key


async def test_an_unknown_check_result_fails_closed() -> None:
    """A future driver value must never be read as permission to write."""
    driver = build_driver_from_fixture()
    driver.controller.force_check_result = 99
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.BLOCKED
    assert driver.controller.write_count == before


async def test_a_sleeping_node_reports_pending_wakeup_rather_than_failing() -> None:
    """E5. Node 40 is a battery remote. A queued write is not an error.

    NOTE: this behaviour is modelled from the library signature, not observed. Stage 0
    item Z4 was not approved, so the real behaviour of a queued write is unproven. See
    docs/open-items.md J1 and issue #5.
    """
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(40, "6", 38))

    assert result.status is LinkResultStatus.PENDING_WAKEUP
    assert driver.controller.last_add_options["wait_for_result"] is False


async def test_a_write_to_a_listening_node_waits_for_the_radio() -> None:
    """The counterpart: a node that is awake answers now, so the result means something."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    await backend.async_add_link(_link(36, "7", 38))

    assert driver.controller.last_add_options["wait_for_result"] is True


async def test_a_driver_exception_becomes_a_failed_result_with_the_raw_error() -> None:
    """E13. The raw text goes under an expander for issue reports, never as the message."""
    driver = build_driver_from_fixture()
    driver.controller.raise_on_write = RuntimeError("ZW0201: transmit failed")
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.FAILED
    assert result.raw_error is not None
    assert "ZW0201" in result.raw_error
    assert result.reason is not None
    assert "ZW0201" not in result.reason.translation_key


async def test_force_is_never_passed_to_the_driver() -> None:
    """CLAUDE.md Section 3 rule 6. force skips the driver's own safety checks."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    await backend.async_add_link(_link(36, "7", 38))

    assert driver.controller.last_add_options.get("force") in (None, False)


async def test_force_is_never_passed_to_a_removal_either() -> None:
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    await backend.async_add_link(_link(36, "7", 38))

    await backend.async_remove_link(_link(36, "7", 38))

    assert driver.controller.last_remove_options.get("force") in (None, False)


async def test_removing_a_link_takes_it_off_the_device() -> None:
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    await backend.async_add_link(_link(36, "7", 38))

    result = await backend.async_remove_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.APPLIED
    observed = await backend.async_observed(await _handle(backend, 36))
    assert not [link for link in observed.links if link.emitter_group == "7"]


async def test_removing_a_link_that_is_not_there_is_not_a_write() -> None:
    """Nothing to do is not a failure, and it must not cost a radio round trip."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    result = await backend.async_remove_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.ALREADY_PRESENT
    assert driver.controller.write_count == before


async def test_removing_from_a_sleeping_node_is_pending_rather_than_applied() -> None:
    """Same modelled path as the add: see docs/open-items.md J1 and issue #5."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    await backend.async_add_link(_link(40, "6", 38))

    result = await backend.async_remove_link(_link(40, "6", 38))

    assert result.status is LinkResultStatus.PENDING_WAKEUP


async def test_a_failing_removal_reports_the_raw_error_too() -> None:
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    await backend.async_add_link(_link(36, "7", 38))
    driver.controller.raise_on_write = RuntimeError("ZW0203: no route")

    result = await backend.async_remove_link(_link(36, "7", 38))

    assert result.status is LinkResultStatus.FAILED
    assert result.raw_error is not None
    assert "ZW0203" in result.raw_error


async def test_a_link_whose_source_is_not_on_this_network_fails_rather_than_raising() -> None:
    """The executor asks one link at a time and must get an answer for every one."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    result = await backend.async_add_link(_link(250, "7", 38))

    assert result.status is LinkResultStatus.FAILED
    assert result.raw_error is not None
    assert "250" in result.raw_error


async def test_checking_a_link_asks_the_driver_without_writing_anything() -> None:
    """PRD Section 8.3: the plan dialog needs the answer before anyone commits to it."""
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)
    before = driver.controller.write_count

    check = await backend.async_check_link(_link(36, "7", 38))

    assert check.ok is True
    assert check.reason is None
    assert driver.controller.write_count == before


async def test_checking_a_lifeline_refuses_without_asking_the_driver() -> None:
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    check = await backend.async_check_link(_link(36, "1", 38))

    assert check.ok is False
    assert check.reason is not None
    assert "lifeline" in check.reason.translation_key


async def test_a_check_the_driver_refuses_comes_back_with_its_reason() -> None:
    driver = build_driver_from_fixture()
    driver.controller.force_check_result = 4  # self association
    backend = ZWaveBackend(driver=driver, profiles=None)

    check = await backend.async_check_link(_link(36, "7", 38))

    assert check.ok is False
    assert check.reason is not None
    assert "self_association" in check.reason.translation_key


async def test_a_check_that_cannot_reach_the_driver_is_a_refusal_not_a_traceback() -> None:
    driver = build_driver_from_fixture()
    backend = ZWaveBackend(driver=driver, profiles=None)

    check = await backend.async_check_link(_link(250, "7", 38))

    assert check.ok is False
    assert check.reason is not None
    assert "check_failed" in check.reason.translation_key


def _link(source: int, group: str, target: int, feature: Feature = Feature.ON_OFF) -> Link:
    """Return one desired link, named by the group it is written to.

    The plan's version of this helper took no feature, but `factories.link` needs one: a
    link's fingerprint carries the feature, so there is no such thing as a featureless
    link. Every case here is about which group is written and who refuses it, so the
    feature is the one every group named below actually carries.
    """
    return link(source, f"g{group}", target, feature)


def _self_association(node_id: int, group: str) -> Link:
    """Return a link pointing a device at itself, which `Link` will not build.

    Reaching past `__post_init__` is the point: the adapter's own refusal has to hold for
    a caller that did not come through `Link`, which is what defence in depth means here.
    """
    built = _link(node_id, group, 38)
    object.__setattr__(built, "target", LinkTarget(handle=_handle_of(node_id), endpoint=None))
    return built


def _handle_of(node_id: int) -> DeviceHandle:
    return handle(node_id)


async def _handle(backend: ZWaveBackend, node_id: int) -> DeviceHandle:
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))
