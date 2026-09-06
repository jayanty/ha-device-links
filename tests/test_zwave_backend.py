"""Reading: devices, capabilities and observed state, against the fake driver."""

from __future__ import annotations

import inspect
import logging

import pytest
from zwave_js_server.model.association import AssociationAddress, AssociationGroup

from custom_components.device_links.backends.base import Backend
from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.backends.zwave_accessor import ZWaveAccessorError
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import DeviceHandle, Feature, ZWaveFingerprint
from tests.factories import profiles
from tests.fakes.zwave import build_driver_from_fixture


@pytest.fixture
def backend() -> ZWaveBackend:
    return ZWaveBackend(driver=build_driver_from_fixture(), profiles=None)


@pytest.fixture
def curated() -> ZWaveBackend:
    return ZWaveBackend(driver=build_driver_from_fixture(), profiles=profiles())


async def test_devices_are_discovered_with_stable_handles(backend: ZWaveBackend) -> None:
    devices = await backend.async_devices()
    identities = {device.handle.identity for device in devices}

    assert any(identity.endswith(":36") for identity in identities)
    assert all(identity.startswith("zwave:") for identity in identities)


async def test_a_handle_carries_the_fingerprint_a_profile_is_looked_up_by(
    backend: ZWaveBackend,
) -> None:
    """Without the real fingerprint, every device would fall back to the generic derivation."""
    handle = await _handle_for(backend, 36)

    assert handle.backend is BackendId.ZWAVE
    assert handle.fingerprint == ZWaveFingerprint(
        manufacturer_id=634, product_type=28672, product_id=40984, firmware="1.40.0"
    )
    assert handle.name_at_authoring == "Bedroom Scene Controller"


async def test_capabilities_use_the_curated_profile_when_one_matches(
    curated: ZWaveBackend,
) -> None:
    """The Inovelli paddle must come back as one control, not three groups."""
    capabilities = await curated.async_capabilities(await _handle_for(curated, 37))
    paddle = next(e for e in capabilities.emitters if e.emitter_id == "paddle")

    assert paddle.actions[Feature.ON_OFF] == "2"
    assert paddle.actions[Feature.LEVEL_HOLD] == "4"


async def test_capabilities_carry_the_settings_the_profile_knows_about(
    curated: ZWaveBackend,
) -> None:
    """The compiler reads a setting write off these, so an empty map compiles nothing."""
    capabilities = await curated.async_capabilities(await _handle_for(curated, 37))

    assert capabilities.settings["mirror_hub_commands"].parameter == 59


async def test_capabilities_fall_back_when_no_profile_matches(backend: ZWaveBackend) -> None:
    """An unknown model still gets usable links, just per-group emitters."""
    capabilities = await backend.async_capabilities(await _handle_for(backend, 37))

    assert all(emitter.grouping == "per_group" for emitter in capabilities.emitters)
    assert capabilities.settings == {}


async def test_the_lifeline_never_appears_as_an_emitter(backend: ZWaveBackend) -> None:
    capabilities = await backend.async_capabilities(await _handle_for(backend, 36))

    assert all(not emitter.is_lifeline for emitter in capabilities.emitters)


async def test_a_long_range_node_is_reported_as_such(backend: ZWaveBackend) -> None:
    """D13: LR nodes cannot participate in associations, and the UI must say so."""
    capabilities = await backend.async_capabilities(await _handle_for(backend, 36))

    assert capabilities.is_long_range is False


async def test_a_node_that_joined_over_long_range_is_reported_as_such() -> None:
    """The protocol is what the driver reports, and it is authoritative when present."""
    driver = build_driver_from_fixture()
    driver.controller.add_long_range_node(41)
    backend = ZWaveBackend(driver=driver, profiles=None)

    capabilities = await backend.async_capabilities(await _handle_for(backend, 41))

    assert capabilities.is_long_range is True


async def test_a_node_id_in_the_long_range_range_is_reported_as_such() -> None:
    """CLAUDE.md Section 10: the id alone settles it, even if the protocol is not reported."""
    driver = build_driver_from_fixture()
    node = driver.controller.add_long_range_node(300)
    node.protocol = None
    backend = ZWaveBackend(driver=driver, profiles=None)

    capabilities = await backend.async_capabilities(await _handle_for(backend, 300))

    assert capabilities.is_long_range is True


async def test_a_node_this_network_does_not_have_is_refused_by_name(
    backend: ZWaveBackend,
) -> None:
    """A silent empty answer for a missing node would read as a device with nothing on it."""
    missing = DeviceHandle(
        backend=BackendId.ZWAVE,
        protocol_id="3538613642:250",
        ha_device_id="",
        fingerprint=ZWaveFingerprint(0, 0, 0, ""),
        name_at_authoring="Gone",
    )

    with pytest.raises(ZWaveAccessorError, match="250"):
        await backend.async_capabilities(missing)


async def test_observed_state_reads_the_three_level_association_shape(
    backend: ZWaveBackend,
) -> None:
    """The bug Stage 0 hit: reading at the wrong depth returns plausible empties."""
    observed = await backend.async_observed(await _handle_for(backend, 36))

    lifelines = [link for link in observed.links if link.is_system]
    assert lifelines, "the lifeline was not read; check the nesting depth"
    assert lifelines[0].target.handle.protocol_id.endswith(":1")


async def test_an_association_dump_for_the_wrong_node_is_refused(
    backend: ZWaveBackend,
) -> None:
    """Stage 0 asserted the node key rather than trusting position. So does this."""

    async def _someone_elses_node(node: object) -> dict[int, dict[int, dict[int, list[object]]]]:
        return {99: {0: {1: []}}}

    backend._driver.controller.async_get_all_associations = _someone_elses_node  # type: ignore[method-assign]

    with pytest.raises(ZWaveAccessorError, match="36"):
        await backend.async_observed(await _handle_for(backend, 36))


async def test_the_lifeline_is_classified_as_a_system_link(backend: ZWaveBackend) -> None:
    """This is what stops it ever being offered for removal."""
    observed = await backend.async_observed(await _handle_for(backend, 36))

    for link in observed.links:
        if link.emitter_group == "1":
            assert link.is_system is True


async def test_non_lifeline_links_are_not_system_links() -> None:
    driver = build_driver_from_fixture()
    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=36),
        7,
        [AssociationAddress(controller, node_id=38)],
    )
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle_for(backend, 36))
    added = next(link for link in observed.links if link.emitter_group == "7")

    assert added.is_system is False
    assert added.managed_by is None, "ownership is resolved by the coordinator, not here"


async def test_an_observed_link_carries_the_feature_its_group_actually_issues() -> None:
    """The fingerprint carries the feature, so a wrong one never matches a desired link."""
    driver = build_driver_from_fixture()
    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=36),
        8,  # Button 2 - Held, Multilevel Switch Start/Stop
        [AssociationAddress(controller, node_id=38)],
    )
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle_for(backend, 36))
    held = next(link for link in observed.links if link.emitter_group == "8")

    assert held.feature is Feature.LEVEL_HOLD
    assert held.target.handle.name_at_authoring == "Bedside Light L"


async def test_a_target_the_driver_does_not_list_still_gets_a_handle(
    backend: ZWaveBackend,
) -> None:
    """The controller is node 1 and is not in the node list, but the lifeline points at it."""
    observed = await backend.async_observed(await _handle_for(backend, 36))
    lifeline = next(link for link in observed.links if link.emitter_group == "1")

    assert lifeline.target.handle.name_at_authoring == "Node 1"
    assert lifeline.feature is Feature.STATUS_REPORT


async def test_observed_state_carries_the_settings_the_profile_knows_about(
    curated: ZWaveBackend,
) -> None:
    """A setting that is already right must be visible, so nothing plans a write for it."""
    observed = await curated.async_observed(await _handle_for(curated, 37))

    assert observed.settings["mirror_hub_commands"] == 0


async def test_observed_state_of_a_model_with_no_profile_has_no_settings(
    backend: ZWaveBackend,
) -> None:
    observed = await backend.async_observed(await _handle_for(backend, 37))

    assert observed.settings == {}


async def _handle_for(backend: ZWaveBackend, node_id: int) -> DeviceHandle:
    devices = await backend.async_devices()
    return next(d.handle for d in devices if d.handle.protocol_id.endswith(f":{node_id}"))


async def test_a_group_that_issues_nothing_usable_is_reported_and_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A group nobody can use is a control the UI must not offer, and a fact worth logging."""
    driver = build_driver_from_fixture()
    groups = driver.controller._groups[36][0]
    groups[7] = AssociationGroup(
        max_nodes=groups[7].max_nodes,
        is_lifeline=False,
        multi_channel=False,
        label="Button 2 - Pressed (Basic Set)",
        profile=None,
        issued_commands={},
    )
    backend = ZWaveBackend(driver=driver, profiles=None)

    with caplog.at_level(logging.DEBUG, logger="custom_components.device_links.backends.zwave"):
        capabilities = await backend.async_capabilities(await _handle_for(backend, 36))

    assert all("7" not in emitter.group_ids for emitter in capabilities.emitters)
    assert "association group 7" in caplog.text


async def test_an_entry_in_a_group_the_device_does_not_report_is_still_observed() -> None:
    """Dropping it would hide an association that is really on the device."""
    driver = build_driver_from_fixture()
    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=36),
        7,
        [AssociationAddress(controller, node_id=38)],
    )
    del controller._groups[36][0][7]
    backend = ZWaveBackend(driver=driver, profiles=None)

    observed = await backend.async_observed(await _handle_for(backend, 36))
    orphan = next(link for link in observed.links if link.emitter_group == "7")

    assert orphan.feature is Feature.STATUS_REPORT, "an unknown group controls nothing we know"
    assert orphan.is_system is False


async def test_a_setting_the_device_has_not_reported_is_left_out_of_observed_state(
    curated: ZWaveBackend,
) -> None:
    """Absent is not zero. Reporting it as zero would let a plan skip a write it needs."""
    node = curated._driver.controller.nodes[37]
    node.values = {
        value_id: value
        for value_id, value in node.values.items()
        if (int(value.property_), value.property_key) != (59, 2)
    }

    observed = await curated.async_observed(await _handle_for(curated, 37))

    assert "mirror_hub_commands" not in observed.settings
    assert observed.settings["smart_bulb_mode"] == 0


def test_the_zwave_backend_satisfies_the_backend_protocol() -> None:
    """Phase 1B exit criterion. Core code holds a `Backend` and must never know which one."""
    assert isinstance(ZWaveBackend(driver=build_driver_from_fixture(), profiles=None), Backend)


@pytest.mark.parametrize(
    "name",
    sorted(name for name in vars(Backend) if not name.startswith("_")),
)
def test_every_backend_method_is_implemented_with_the_agreed_parameters(name: str) -> None:
    """`isinstance` only checks that the names exist, and a renamed argument breaks a caller.

    Core code calls these positionally and by keyword (`async_observed(handle, deep=True)`),
    so the parameter names are part of the contract the protocol states.
    """
    expected = inspect.signature(getattr(Backend, name))
    actual = inspect.signature(getattr(ZWaveBackend, name))

    assert list(actual.parameters) == list(expected.parameters), f"{name} took a different shape"


async def test_the_group_dump_is_converted_into_the_shape_the_pure_module_reads(
    backend: ZWaveBackend,
) -> None:
    """The one shape conversion in this adapter, and everything downstream depends on it.

    The library reports integer group ids and a dataclass per group; `zwave_protocol` is
    written against string ids and a TypedDict so it can be handed the JSON fixtures
    directly. Getting this wrong makes every group look unknown, which is silent.
    """
    groups = await backend._groups(backend._driver.controller.nodes[37])

    assert set(groups) == {0}, "the outer key stays the endpoint"
    assert set(groups[0]) == {"1", "2", "3", "4", "5", "6", "7"}
    assert groups[0]["1"]["is_lifeline"] is True
    assert groups[0]["2"] == {
        "is_lifeline": False,
        "issued_commands": {32: [1]},
        "label": "Basic Set",
        "max_nodes": 10,
        "multi_channel": True,
        "profile": 8193,
    }
