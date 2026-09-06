"""The fakes must reproduce the real library's shapes, including its inconsistencies."""

from __future__ import annotations

import asyncio

import pytest
from zwave_js_server.const import AssociationCheckResult, CommandClass, NodeStatus, Protocols
from zwave_js_server.exceptions import FailedZWaveCommand, NotFoundError
from zwave_js_server.model.association import AssociationAddress

from tests.fakes.zwave import FakeDriver, build_driver_from_fixture


@pytest.fixture
def driver() -> FakeDriver:
    return build_driver_from_fixture()


def test_the_fixture_nodes_are_all_present(driver: FakeDriver) -> None:
    assert set(driver.controller.nodes) >= {21, 29, 30, 35, 36, 37, 38, 39, 40, 42}


def test_association_groups_are_keyed_by_endpoint_then_group(driver: FakeDriver) -> None:
    """Two levels, as get_all_association_groups really returns."""
    groups = driver.controller.get_all_association_groups_sync(36)

    assert set(groups) == {0}, "outer key must be the endpoint"
    assert 1 in groups[0], "inner key must be the group id"
    assert groups[0][1].is_lifeline is True


def test_associations_are_keyed_by_node_then_endpoint_then_group(driver: FakeDriver) -> None:
    """Three levels. Stage 0 found this differs from the groups call by one level.

    Reading it at the groups depth returns plausible empty groups rather than an error,
    which is a bug that hides. The fake reproduces the real depth so the adapter is
    written against the shape it will actually meet.
    """
    associations = driver.controller.get_all_associations_sync(36)

    assert set(associations) == {36}, "outer key must be the node id"
    assert set(associations[36]) == {0}, "then the endpoint"
    assert 1 in associations[36][0], "then the group id"


async def test_the_two_association_reads_really_do_differ_by_one_level(
    driver: FakeDriver,
) -> None:
    """Pin the depth difference on the async methods the adapter actually calls."""
    node = driver.controller.nodes[36]
    groups = await driver.controller.async_get_all_association_groups(node)
    associations = await driver.controller.async_get_all_associations(node)

    assert _depth(groups) == 2
    assert _depth(associations) == 3


def test_the_lifeline_contains_the_controller(driver: FakeDriver) -> None:
    lifeline = driver.controller.get_all_associations_sync(36)[36][0][1]

    assert [address.node_id for address in lifeline] == [1]


def test_an_association_address_resolves_back_to_its_node(driver: FakeDriver) -> None:
    """The real AssociationAddress.node walks the controller, so the fake must satisfy it."""
    lifeline = driver.controller.get_all_associations_sync(36)[36][0][1]

    assert lifeline[0].controller is driver.controller
    assert lifeline[0].node is None, "node 1 is the controller and is not in the node list"
    assert AssociationAddress(driver.controller, node_id=38).node is driver.controller.nodes[38]


def test_a_sleeping_node_is_marked_asleep(driver: FakeDriver) -> None:
    """Node 40 was asleep during capture and is the pending_wakeup test subject."""
    assert driver.controller.nodes[40].status == 1
    assert driver.controller.nodes[36].status == 4


def test_node_protocol_is_available_for_the_long_range_guard(driver: FakeDriver) -> None:
    assert driver.controller.nodes[36].protocol == 0


def test_fingerprints_match_the_capture(driver: FakeDriver) -> None:
    node = driver.controller.nodes[36]

    assert (node.manufacturer_id, node.product_type, node.product_id) == (634, 28672, 40984)
    assert node.firmware_version == "1.40.0"


def test_config_values_are_exposed_for_the_settings_adapters(driver: FakeDriver) -> None:
    node = driver.controller.nodes[37]
    keys = {(value.property_, value.property_key) for value in node.values.values()}

    assert (59, 1) in keys
    assert (59, 2) in keys


def test_config_values_carry_the_real_value_id_shape(driver: FakeDriver) -> None:
    """The adapter may address a value by id, so the id must look like the real one."""
    node = driver.controller.nodes[37]
    value = next(v for v in node.values.values() if (v.property_, v.property_key) == (59, 2))

    assert value.value_id == "37-112-0-59-2"
    assert value.command_class == CommandClass.CONFIGURATION
    assert value.value == 0


def test_a_zen35_exposes_the_parameters_its_profile_entry_names(driver: FakeDriver) -> None:
    """Node 39 is the D4 subject: parameter 19 must exist so a stray write is visible."""
    keys = {
        (value.property_, value.property_key)
        for value in driver.controller.nodes[39].get_configuration_values().values()
    }

    assert (35, 4) in keys
    assert (19, None) in keys


def test_an_unknown_node_is_not_silently_empty(driver: FakeDriver) -> None:
    with pytest.raises(NotFoundError):
        driver.controller.get_all_associations_sync(999)


async def test_adding_an_association_is_visible_on_the_next_read(driver: FakeDriver) -> None:
    """The fake radio must behave like the real one: our own writes are visible at once."""
    controller = driver.controller
    source = AssociationAddress(controller, node_id=36)
    target = AssociationAddress(controller, node_id=38)

    await controller.async_add_associations(source, 7, [target])
    associations = await controller.async_get_associations(source)

    assert [address.node_id for address in associations[7]] == [38]


async def test_the_group_read_is_keyed_by_group_for_one_source(driver: FakeDriver) -> None:
    """async_get_association_groups is per source, one level, unlike the get_all form."""
    groups = await driver.controller.async_get_association_groups(
        AssociationAddress(driver.controller, node_id=36)
    )

    assert groups[1].is_lifeline is True
    assert groups[2].max_nodes == 10, "the ZEN35 reports 10 slots on group 2"


async def test_removing_an_association_takes_it_off_the_device(driver: FakeDriver) -> None:
    controller = driver.controller
    source = AssociationAddress(controller, node_id=36)
    target = AssociationAddress(controller, node_id=38)
    await controller.async_add_associations(source, 7, [target])

    await controller.async_remove_associations(source, 7, [target])

    assert (await controller.async_get_associations(source))[7] == []


async def test_adding_an_entry_twice_does_not_duplicate_it(driver: FakeDriver) -> None:
    """A real device holds a set. A fake that duplicated would fake up capacity pressure."""
    controller = driver.controller
    source = AssociationAddress(controller, node_id=36)
    target = AssociationAddress(controller, node_id=38)

    await controller.async_add_associations(source, 7, [target])
    await controller.async_add_associations(source, 7, [target])

    assert len((await controller.async_get_associations(source))[7]) == 1


async def test_every_write_is_counted_including_a_redundant_one(driver: FakeDriver) -> None:
    """write_count counts what reached the radio, which is what the adapter must not do."""
    controller = driver.controller
    source = AssociationAddress(controller, node_id=36)
    target = AssociationAddress(controller, node_id=38)

    await controller.async_add_associations(source, 7, [target])
    await controller.async_add_associations(source, 7, [target])
    await controller.async_remove_associations(source, 7, [target])

    assert controller.write_count == 3


async def test_the_write_options_are_recorded_so_force_cannot_pass_unnoticed(
    driver: FakeDriver,
) -> None:
    controller = driver.controller
    source = AssociationAddress(controller, node_id=36)

    await controller.async_add_associations(
        source, 7, [AssociationAddress(controller, node_id=38)], wait_for_result=True
    )

    assert controller.last_add_options == {"wait_for_result": True}


async def test_raise_on_write_makes_the_radio_fail(driver: FakeDriver) -> None:
    controller = driver.controller
    controller.raise_on_write = RuntimeError("ZW0201: transmit failed")
    source = AssociationAddress(controller, node_id=36)

    with pytest.raises(RuntimeError, match="ZW0201"):
        await controller.async_add_associations(
            source, 7, [AssociationAddress(controller, node_id=38)]
        )


async def test_the_fake_refuses_to_exceed_group_capacity(driver: FakeDriver) -> None:
    """A fake more permissive than the hardware proves less than it appears to."""
    controller = driver.controller
    source = AssociationAddress(controller, node_id=40)  # ZEN37, capacity 5

    for node_id in (21, 29, 30, 35, 36):
        await controller.async_add_associations(
            source, 2, [AssociationAddress(controller, node_id=node_id)]
        )

    with pytest.raises(FailedZWaveCommand, match="capacity"):
        await controller.async_add_associations(
            source, 2, [AssociationAddress(controller, node_id=37)]
        )


async def test_a_full_group_is_left_exactly_as_it_was(driver: FakeDriver) -> None:
    """A refused batch must not half-apply, or the adapter's read-back would lie."""
    controller = driver.controller
    source = AssociationAddress(controller, node_id=40)
    for node_id in (21, 29, 30, 35):
        await controller.async_add_associations(
            source, 2, [AssociationAddress(controller, node_id=node_id)]
        )

    with pytest.raises(FailedZWaveCommand, match="capacity"):
        await controller.async_add_associations(
            source,
            2,
            [
                AssociationAddress(controller, node_id=36),
                AssociationAddress(controller, node_id=37),
            ],
        )

    assert len((await controller.async_get_associations(source))[2]) == 4


async def test_the_check_allows_an_ordinary_association(driver: FakeDriver) -> None:
    controller = driver.controller

    result = await controller.async_check_association(
        AssociationAddress(controller, node_id=36),
        7,
        AssociationAddress(controller, node_id=38),
    )

    assert result == AssociationCheckResult.OK


async def test_the_check_refuses_a_self_association(driver: FakeDriver) -> None:
    controller = driver.controller

    result = await controller.async_check_association(
        AssociationAddress(controller, node_id=36),
        7,
        AssociationAddress(controller, node_id=36),
    )

    assert result == AssociationCheckResult.FORBIDDEN_SELF_ASSOCIATION


async def test_the_check_refuses_long_range_at_either_end(driver: FakeDriver) -> None:
    """D13. The capture has no Long Range node, so the fake can make one."""
    controller = driver.controller
    long_range = controller.add_long_range_node(256)

    assert long_range.protocol == Protocols.ZWAVE_LONG_RANGE
    source_result = await controller.async_check_association(
        AssociationAddress(controller, node_id=256),
        2,
        AssociationAddress(controller, node_id=38),
    )
    target_result = await controller.async_check_association(
        AssociationAddress(controller, node_id=36),
        7,
        AssociationAddress(controller, node_id=256),
    )

    assert source_result == AssociationCheckResult.FORBIDDEN_SOURCE_IS_LONG_RANGE
    assert target_result == AssociationCheckResult.FORBIDDEN_DESTINATION_IS_LONG_RANGE


async def test_the_check_refuses_a_secure_source_reaching_an_unsecured_target(
    driver: FakeDriver,
) -> None:
    """Node 21 is the only S2 node in the capture, so E9 has a natural subject."""
    controller = driver.controller

    result = await controller.async_check_association(
        AssociationAddress(controller, node_id=21),
        2,
        AssociationAddress(controller, node_id=38),
    )

    assert result == AssociationCheckResult.FORBIDDEN_DESTINATION_SECURITY_CLASS_NOT_GRANTED


async def test_an_unsecured_source_may_reach_a_secure_target(driver: FakeDriver) -> None:
    """Only the source's security class constrains the association."""
    controller = driver.controller

    result = await controller.async_check_association(
        AssociationAddress(controller, node_id=36),
        7,
        AssociationAddress(controller, node_id=21),
    )

    assert result == AssociationCheckResult.OK


async def test_force_check_result_overrides_every_rule(driver: FakeDriver) -> None:
    """Including a value no current driver returns, so fail-closed can be exercised."""
    controller = driver.controller
    controller.force_check_result = 99

    result = await controller.async_check_association(
        AssociationAddress(controller, node_id=36),
        7,
        AssociationAddress(controller, node_id=38),
    )

    assert result == 99


async def test_a_refresh_is_fire_and_forget_and_lands_later(driver: FakeDriver) -> None:
    """Stage 0's most consequential finding, reproduced.

    A read issued straight after the refresh returns the cache it would have returned
    anyway. Only after the device answers does the new value appear.
    """
    controller = driver.controller
    controller.refresh_delay_seconds = 0.01
    controller.stale_group = (36, 7, 38)
    source = AssociationAddress(controller, node_id=36)

    await controller.nodes[36].async_refresh_cc_values(CommandClass.ASSOCIATION)
    immediately = (await controller.async_get_associations(source))[7]
    await asyncio.sleep(0.05)
    later = (await controller.async_get_associations(source))[7]

    assert immediately == []
    assert [address.node_id for address in later] == [38]
    assert controller.refresh_count == 1


async def test_a_landed_refresh_announces_itself(driver: FakeDriver) -> None:
    """Deep verify has to be able to wait for something, so landing emits an event."""
    controller = driver.controller
    controller.refresh_delay_seconds = 0.01
    seen: list[int] = []
    controller.nodes[36].on(
        "value updated", lambda event: seen.append(event["value"].command_class)
    )

    await controller.nodes[36].async_refresh_cc_values(CommandClass.ASSOCIATION)
    await asyncio.sleep(0.05)

    assert seen == [CommandClass.ASSOCIATION]


async def test_a_refresh_that_never_lands_never_announces_anything(driver: FakeDriver) -> None:
    controller = driver.controller
    controller.refresh_never_lands = True
    controller.stale_group = (36, 7, 38)
    seen: list[int] = []
    controller.nodes[36].on("value updated", lambda event: seen.append(1))

    await controller.nodes[36].async_refresh_cc_values(CommandClass.ASSOCIATION)
    await asyncio.sleep(0.05)

    assert seen == []
    assert (await controller.async_get_associations(AssociationAddress(controller, node_id=36)))[
        7
    ] == []
    assert controller.refresh_count == 1


def test_emit_association_changed_delivers_a_value_updated_event(driver: FakeDriver) -> None:
    """FR-B3: the drift subscription is driven by these, so a test must be able to fire one."""
    seen: list[dict[str, object]] = []
    driver.controller.nodes[36].on("value updated", seen.append)

    driver.controller.emit_association_changed(36)

    assert len(seen) == 1
    assert seen[0]["node"] is driver.controller.nodes[36]
    value = seen[0]["value"]
    assert value.command_class == CommandClass.ASSOCIATION  # type: ignore[union-attr]
    assert value.property_key == 2, "the event names the group that changed"  # type: ignore[union-attr]
    assert value.value == [], "and carries what that group holds now"  # type: ignore[union-attr]


async def test_writing_a_config_value_records_the_parameter_and_reads_back(
    driver: FakeDriver,
) -> None:
    """D4 depends on this: a parameter nobody asked for must be visibly absent."""
    controller = driver.controller
    node = controller.nodes[39]
    value = next(
        v
        for v in node.get_configuration_values().values()
        if (v.property_, v.property_key) == (35, 4)
    )

    await node.async_set_value(value, 1)

    assert value.value == 1
    assert 35 in controller.written_parameters
    assert controller.written_parameters[35] == [(4, 1)]
    assert 19 not in controller.written_parameters


async def test_a_config_write_can_be_addressed_by_value_id(driver: FakeDriver) -> None:
    node = driver.controller.nodes[39]

    await node.async_set_value("39-112-0-19", 1)

    assert driver.controller.written_parameters[19] == [(None, 1)]


async def test_writing_an_unknown_value_id_is_an_error_not_a_silent_no_op(
    driver: FakeDriver,
) -> None:
    with pytest.raises(NotFoundError):
        await driver.controller.nodes[39].async_set_value("39-112-0-999", 1)


def test_the_node_status_and_the_driver_home_id_match_the_capture(driver: FakeDriver) -> None:
    assert driver.controller.home_id == 3538613642
    assert driver.controller.nodes[40].status == NodeStatus.ASLEEP
    assert driver.controller.nodes[40].is_listening is False


def _depth(mapping: object) -> int:
    depth = 0
    while isinstance(mapping, dict):
        depth += 1
        mapping = next(iter(mapping.values()))
    return depth


async def test_two_drivers_do_not_share_association_state() -> None:
    """Fixture state is parsed once and cached, so a shared list would leak between tests."""
    first = build_driver_from_fixture()
    second = build_driver_from_fixture()
    await first.controller.async_add_associations(
        AssociationAddress(first.controller, node_id=36),
        7,
        [AssociationAddress(first.controller, node_id=38)],
    )

    untouched = await second.controller.async_get_associations(
        AssociationAddress(second.controller, node_id=36)
    )

    assert untouched[7] == []
    assert second.controller.write_count == 0


async def test_raise_on_write_also_fails_a_parameter_write(driver: FakeDriver) -> None:
    """One hook for every write, so E13 can be reached from the settings path too."""
    controller = driver.controller
    controller.raise_on_write = RuntimeError("ZW0201: transmit failed")
    node = controller.nodes[39]
    value = next(
        v
        for v in node.get_configuration_values().values()
        if (v.property_, v.property_key) == (35, 4)
    )

    with pytest.raises(RuntimeError, match="ZW0201"):
        await node.async_set_value(value, 1)

    assert value.value == 0, "a write that failed must not have landed"
    assert controller.written_parameters == {}


def test_a_node_status_can_be_moved_without_touching_is_listening(driver: FakeDriver) -> None:
    """Status and is_listening are independent on a real node, so E4 stays reachable."""
    node = driver.controller.nodes[36]
    node.status = NodeStatus.DEAD

    assert node.status == NodeStatus.DEAD
    assert node.is_listening is True
