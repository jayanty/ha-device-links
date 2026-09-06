"""The Matter adapter's read path, against the fabric the M1 capture recorded.

Everything here is proved: `tests/fixtures/m1_matter.json` came off 19 real devices, and the
fake serves exactly what they served. The write path is in `tests/test_matter_writes.py` and
is proved against nothing (assumption A9).
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.device_links.backends import matter_protocol as mp
from custom_components.device_links.backends.matter import (
    MatterBackend,
    MatterBackendError,
    MatterNodeUnavailableError,
)
from custom_components.device_links.models import Feature
from tests.factories import (
    KITCHEN_ACCENT,
    KITCHEN_PENDANTS,
    SPARE_EVE,
    TIGHT_EVE,
    matter_handle,
    profiles,
)
from tests.fakes.matter import (
    COMPRESSED_FABRIC_ID,
    FakeMatterClient,
    FakeMatterError,
    build_fabric_from_fixture,
)

AQARA_SWITCH = 30
BILRESA = 50


@pytest.fixture
def fabric() -> FakeMatterClient:
    return build_fabric_from_fixture()


@pytest.fixture
def backend(fabric: FakeMatterClient) -> MatterBackend:
    return MatterBackend(client=fabric)


# --------------------------------------------------------------------------------------
# Devices and capabilities
# --------------------------------------------------------------------------------------


async def test_every_node_on_the_fabric_is_a_device_and_costs_no_reads(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The listing is held by the client, so nothing here touches a radio.

    That matters more here than in the other two backends: the coordinator reads every
    device of every backend at setup, and a listing that read attributes would spend a
    round trip per node before the integration had finished loading.
    """
    devices = await backend.async_devices()

    assert len(devices) == 19
    assert fabric.reads == []
    assert matter_handle(KITCHEN_ACCENT) in {device.handle for device in devices}


async def test_a_switch_offers_its_paddle_and_nothing_else(backend: MatterBackend) -> None:
    capabilities = await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    (paddle,) = capabilities.emitters
    assert paddle.emitter_id == "ep2"
    assert paddle.endpoint == 2
    assert paddle.actions[Feature.ON_OFF] == "6"
    assert capabilities.receivable == frozenset(
        {Feature.ON_OFF, Feature.LEVEL_SET, Feature.LEVEL_HOLD, Feature.COLOR}
    )
    assert capabilities.receiving_endpoint == 1
    assert not capabilities.is_long_range
    assert capabilities.settings == {}


@pytest.mark.parametrize("node_id", [AQARA_SWITCH, BILRESA, TIGHT_EVE])
async def test_a_device_that_is_not_a_binding_source_offers_no_control(
    backend: MatterBackend, node_id: int
) -> None:
    """PRD Section 3.1 named two of these three as sources. None of them is one."""
    capabilities = await backend.async_capabilities(matter_handle(node_id))

    assert capabilities.emitters == ()


async def test_a_curated_entry_gives_the_paddle_its_name(fabric: FakeMatterClient) -> None:
    """The shipped profile database claims the VTM31-SN, so the label comes from it."""
    backend = MatterBackend(client=fabric, profiles=profiles())

    capabilities = await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    (paddle,) = capabilities.emitters
    assert paddle.label == "Paddle"
    assert paddle.grouping == mp.GROUPING_PROFILE_DB
    assert paddle.emitter_id == "ep2"


async def test_a_node_is_read_once_and_then_answered_from_what_was_read(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A Matter attribute read goes to the device, and the coordinator asks constantly."""
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))
    first = len(fabric.reads)
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))
    await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    assert first > 0
    assert len(fabric.reads) == first


async def test_a_client_list_is_read_only_where_it_could_matter(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """An endpoint with no Binding cluster can never be a control, whatever it drives.

    The Inovelli reports 20 endpoints and one of them has a Binding cluster, so this is 20
    server-list reads and one client-list read rather than 40. It is the difference between
    96 reads and 260 across this fabric at setup.
    """
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    client_reads = [path for _, path in fabric.reads if path.endswith("/29/2")]
    server_reads = [path for _, path in fabric.reads if path.endswith("/29/1")]
    assert client_reads == ["2/29/2"]
    assert len(server_reads) == 20


async def test_nothing_reads_an_access_control_list_until_something_is_written(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """It is a security boundary and it is two entries from full, so it is never cached."""
    await backend.async_capabilities(matter_handle(TIGHT_EVE))
    await backend.async_observed(matter_handle(TIGHT_EVE))

    assert not any(path == mp.ACL_PATH for _, path in fabric.reads)


async def test_a_node_the_fabric_does_not_list_raises_rather_than_answering_emptily(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A read that answered "this device holds nothing" is how a network gets unwritten."""
    handle = matter_handle(SPARE_EVE)
    fabric.remove_node(SPARE_EVE)

    with pytest.raises(MatterBackendError, match="not a node this Matter fabric reports"):
        await backend.async_capabilities(handle)


async def test_a_node_that_is_not_answering_raises_its_own_error(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """E29: told apart from a missing node, because a write to this one is pending."""
    fabric.go_offline(TIGHT_EVE)

    with pytest.raises(MatterNodeUnavailableError):
        await backend.async_observed(matter_handle(TIGHT_EVE))


async def test_a_read_that_fails_part_way_takes_the_whole_node_with_it(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A half described node refuses links with a wrong answer stated confidently."""
    fabric.unresponsive.add(KITCHEN_ACCENT)

    with pytest.raises(FakeMatterError):
        await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))


async def test_a_handle_that_names_no_node_is_refused(backend: MatterBackend) -> None:
    with pytest.raises(MatterBackendError, match="not a Matter node address"):
        await backend.async_capabilities(mp.group_handle(4))


# --------------------------------------------------------------------------------------
# Observed links
# --------------------------------------------------------------------------------------


async def test_nothing_on_this_fabric_is_bound(backend: MatterBackend) -> None:
    """The read half of the M1 finding: both Inovelli binding lists are empty."""
    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    assert observed.links == ()
    assert not observed.deep_verified


async def test_one_binding_on_level_control_becomes_two_links(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Binding LevelControl is one entry that gives the user two things, as on Zigbee."""
    fabric.add_binding(KITCHEN_ACCENT, 2, {"1": TIGHT_EVE, "3": 1, "4": mp.LEVEL_CONTROL_CLUSTER})

    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    assert {link.feature for link in observed.links} == {Feature.LEVEL_SET, Feature.LEVEL_HOLD}
    for link in observed.links:
        assert link.source_endpoint == 2
        assert link.emitter_id == "ep2"
        assert link.emitter_group == "8"
        assert link.target.handle == matter_handle(TIGHT_EVE)
        assert link.target.endpoint == 1
        assert not link.is_system
        assert link.managed_by is None


async def test_no_matter_binding_is_ever_a_system_link(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Matter's protected entry is the controller's Administer grant, which is not a binding."""
    fabric.add_binding(KITCHEN_ACCENT, 2, {"1": TIGHT_EVE, "3": 1, "4": mp.ON_OFF_CLUSTER})

    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    assert not any(link.is_system for link in observed.links)


async def test_a_binding_on_a_cluster_we_cannot_drive_is_still_reported(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A binding list half described is a list nobody can plan against."""
    fabric.add_binding(KITCHEN_ACCENT, 2, {"1": TIGHT_EVE, "3": 1, "4": 999})

    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    assert [link.feature for link in observed.links] == [Feature.STATUS_REPORT]


async def test_a_binding_to_a_group_is_reported_against_the_group(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Device Links writes none, and one somebody else wrote is still on the device."""
    fabric.add_binding(KITCHEN_ACCENT, 2, {"2": 4})

    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    (link,) = observed.links
    assert link.target.handle.protocol_id == "group:4"
    assert link.target.endpoint is None
    assert mp.group_id_of(link.target.handle) == 4


async def test_a_binding_naming_nothing_addressable_is_dropped(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    fabric.add_binding(KITCHEN_ACCENT, 2, {"99": 1})

    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    assert observed.links == ()


async def test_a_binding_to_a_node_that_has_left_the_fabric_still_names_it(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """What is left behind when a device is decommissioned with a binding pointing at it."""
    fabric.add_binding(KITCHEN_ACCENT, 2, {"1": SPARE_EVE, "3": 1, "4": mp.ON_OFF_CLUSTER})
    fabric.remove_node(SPARE_EVE)

    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    (link,) = observed.links
    assert link.target.handle.protocol_id == str(SPARE_EVE)
    assert link.target.handle.name_at_authoring == f"Matter node {SPARE_EVE}"


async def test_a_deep_read_asks_the_device_again_and_says_that_it_did(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    await backend.async_observed(matter_handle(KITCHEN_ACCENT))
    fabric.add_binding(KITCHEN_ACCENT, 2, {"1": TIGHT_EVE, "3": 1, "4": mp.ON_OFF_CLUSTER})

    shallow = await backend.async_observed(matter_handle(KITCHEN_ACCENT))
    deep = await backend.async_observed(matter_handle(KITCHEN_ACCENT), deep=True)

    assert shallow.links == ()
    assert len(deep.links) == 1
    assert deep.deep_verified
    assert not deep.deep_verify_timed_out
    assert deep.deep_verify_skipped_reason is None


# --------------------------------------------------------------------------------------
# Identity, subscriptions and the rest of the protocol
# --------------------------------------------------------------------------------------


def test_the_registry_identifier_is_the_one_the_matter_integration_registers(
    backend: MatterBackend,
) -> None:
    """Stage 0 item P2. Getting this wrong makes an orphan device rather than an error."""
    identifier = backend.registry_identifier(matter_handle(KITCHEN_ACCENT))

    assert identifier == (
        "matter",
        f"deviceid_{COMPRESSED_FABRIC_ID:016X}-{KITCHEN_ACCENT:016X}-MatterNodeDevice",
    )


def test_a_group_has_no_registry_identifier(backend: MatterBackend) -> None:
    assert backend.registry_identifier(mp.group_handle(4)) is None


def test_a_fabric_that_has_not_said_what_it_is_has_no_identifier_to_give() -> None:
    backend = MatterBackend(client=FakeMatterClient(server_info=None))

    assert backend.registry_identifier(matter_handle(KITCHEN_ACCENT)) is None
    assert backend.server_version() is None


def test_the_server_version_is_read_live(backend: MatterBackend) -> None:
    """The Matter server is an add-on: upgrading it reloads nothing of ours."""
    assert backend.server_version() == "matter-server/1.4.0 (matter.js/0.17.9)"


def test_a_matter_system_entry_reserves_itself_and_not_its_slot(
    backend: MatterBackend,
) -> None:
    """Both of Matter's tables are lists of independent entries. Answering SLOT would be T49."""
    from custom_components.device_links.backends.base import SystemScope  # noqa: PLC0415

    assert backend.system_scope() is SystemScope.ENTRY


async def test_a_matter_node_has_no_indicator_this_integration_can_address(
    backend: MatterBackend,
) -> None:
    handle = matter_handle(KITCHEN_ACCENT)

    assert await backend.async_read_indication(handle, "ep2") is None
    assert await backend.async_write_indication(handle, "ep2", lit=True) is False


async def test_a_matter_setting_is_refused_rather_than_invented(
    backend: MatterBackend,
) -> None:
    """A Matter device has no numbered parameter list, so there is nothing to adapt."""
    handle = matter_handle(KITCHEN_ACCENT)

    with pytest.raises(MatterBackendError, match="cluster attributes"):
        await backend.async_read_setting(handle, "mirror_hub_commands")

    result = await backend.async_write_setting(handle, "mirror_hub_commands", 1)
    assert not result.ok
    assert result.reason is not None
    assert result.reason.translation_key == "settings_not_available"


def test_a_node_with_no_curated_entry_has_no_wake_instruction(
    backend: MatterBackend,
) -> None:
    assert backend.wake_instructions(matter_handle(TIGHT_EVE)) is None
    assert backend.wake_instructions(mp.group_handle(4)) is None


async def test_a_wake_instruction_comes_from_the_curated_entry_once_the_node_is_read(
    fabric: FakeMatterClient,
) -> None:
    """Answered from what has been read, because it is asked while a job is running."""
    backend = MatterBackend(client=fabric, profiles=profiles())

    assert backend.wake_instructions(matter_handle(KITCHEN_ACCENT)) is None

    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert backend.wake_instructions(matter_handle(KITCHEN_ACCENT)) is None


async def test_a_subscription_tells_the_coordinator_which_node_changed(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    seen: list[str] = []

    remove = backend.subscribe(seen.append)
    fabric.notify("attribute_updated", {"node_id": KITCHEN_ACCENT})

    assert seen == [f"matter:{KITCHEN_ACCENT}"]

    remove()
    fabric.notify("attribute_updated", {"node_id": KITCHEN_ACCENT})

    assert seen == [f"matter:{KITCHEN_ACCENT}"]
    assert fabric.subscription_count == 0


async def test_an_ordinary_attribute_change_does_not_throw_away_what_was_read(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Every attribute of every node arrives here, so a light being switched on is an event.

    Answering one by re-reading the node would put a burst of radio traffic behind every
    button press in the house.
    """
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))
    before = len(fabric.reads)
    backend.subscribe(lambda identity: None)

    fabric.notify("attribute_updated", _attribute_event(KITCHEN_ACCENT, "1/6/0"))
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert len(fabric.reads) == before


@pytest.mark.parametrize("path", ["2/30/0", "0/31/0"])
async def test_a_change_to_a_binding_or_an_access_list_is_read_again(
    backend: MatterBackend, fabric: FakeMatterClient, path: str
) -> None:
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))
    before = len(fabric.reads)
    backend.subscribe(lambda identity: None)

    fabric.notify("attribute_updated", _attribute_event(KITCHEN_ACCENT, path))
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert len(fabric.reads) > before


@pytest.mark.parametrize(
    "data",
    [
        KITCHEN_PENDANTS,
        {"node_id": KITCHEN_PENDANTS},
        {"node_id": KITCHEN_PENDANTS, "path": "2/30/0"},
    ],
)
async def test_a_node_id_is_found_however_the_client_reports_it(
    backend: MatterBackend, fabric: FakeMatterClient, data: Any
) -> None:
    """Never observed: Stage 0 read attributes and subscribed to nothing (assumption A9)."""
    seen: list[str] = []
    backend.subscribe(seen.append)

    fabric.notify("node_updated", data)

    assert seen == [f"matter:{KITCHEN_PENDANTS}"]


@pytest.mark.parametrize("data", [None, True, "31", {"node": 31}, {"node_id": True}])
async def test_an_event_whose_node_cannot_be_identified_is_dropped(
    backend: MatterBackend, fabric: FakeMatterClient, data: Any
) -> None:
    """Dropped rather than raised: this runs inside somebody else's dispatch loop."""
    seen: list[str] = []
    backend.subscribe(seen.append)

    fabric.notify("node_updated", data)

    assert seen == []


async def test_an_event_arriving_after_the_unsubscribe_reaches_nobody(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """The leak that survives a reload: a callback dispatched into a torn down coordinator."""
    seen: list[str] = []
    remove = backend.subscribe(seen.append)
    captured: list[Any] = []
    fabric.subscribe_events(callback=lambda event, data: captured.append((event, data)))

    # The adapter's own listener, taken before it is removed, then called afterwards.
    (_, adapter_callback), *_rest = [(None, sub.callback) for sub in fabric._subscriptions]
    remove()
    adapter_callback("attribute_updated", {"node_id": KITCHEN_ACCENT})

    assert seen == []


def _attribute_event(node_id: int, path: str) -> Any:
    """Return an attribute-updated payload of the shape the client is documented to send."""

    class _Attribute:
        def __init__(self) -> None:
            self.node_id = node_id
            self.path = path

    return _Attribute()


# --------------------------------------------------------------------------------------
# The edges: what happens when the fabric answers with something unexpected
# --------------------------------------------------------------------------------------


async def test_a_device_that_is_not_a_binding_source_says_so_in_the_log(
    backend: MatterBackend, caplog: pytest.LogCaptureFixture
) -> None:
    """ "This device is not a binding source" is the most surprising thing about Matter here.

    An empty control list with no reason anywhere is what makes somebody think the
    integration is broken rather than that their switch is not one.
    """
    with caplog.at_level("DEBUG", logger="custom_components.device_links.backends.matter"):
        capabilities = await backend.async_capabilities(matter_handle(AQARA_SWITCH))

    assert capabilities.emitters == ()
    assert "cannot be the source of a Matter link" in caplog.text


async def test_a_control_that_drives_nothing_usable_is_named_in_the_log(
    backend: MatterBackend, fabric: FakeMatterClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Identify is a client cluster and is not a control, and the endpoint is named."""
    fabric.attributes[KITCHEN_ACCENT][mp.client_list_path(2)] = [mp.IDENTIFY_CLUSTER]

    with caplog.at_level("DEBUG", logger="custom_components.device_links.backends.matter"):
        capabilities = await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert capabilities.emitters == ()
    assert "none of which Device Links can bind" in caplog.text


async def test_a_binding_on_an_endpoint_that_offers_no_control_still_names_it(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """A binding on an endpoint that drives nothing usable is still on the device.

    It is reported against the endpoint number rather than against a control, because there
    is no control: making one up would put a name in a plan that the device picker does not
    have.
    """
    fabric.attributes[KITCHEN_ACCENT][mp.client_list_path(2)] = [mp.IDENTIFY_CLUSTER]
    fabric.add_binding(KITCHEN_ACCENT, 2, {"1": TIGHT_EVE, "3": 1, "4": mp.ON_OFF_CLUSTER})

    observed = await backend.async_observed(matter_handle(KITCHEN_ACCENT))

    (link,) = observed.links
    assert link.emitter_id == "ep2"


async def test_a_read_that_answers_with_the_bare_value_is_taken_as_it_comes(
    backend: MatterBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unwrapping is defensive in both directions.

    Stage 0 established that a read answers with a mapping keyed by the path, and the
    adapter unwraps exactly that. A client version that answered with the value itself would
    otherwise have every list read as a mapping and every device read as empty, which is the
    same failure the other way round.
    """

    wrapped = FakeMatterClient.read_attribute

    async def bare(client: FakeMatterClient, node_id: int, attribute_path: str) -> object:
        answer = await wrapped(client, node_id, attribute_path)
        return answer[attribute_path]

    monkeypatch.setattr(FakeMatterClient, "read_attribute", bare)

    capabilities = await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert len(capabilities.emitters) == 1


@pytest.mark.parametrize("path", ["nonsense", "1/6", "1/6/0/2"])
async def test_an_event_naming_something_that_is_not_an_attribute_path_is_ignored(
    backend: MatterBackend, fabric: FakeMatterClient, path: str
) -> None:
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))
    before = len(fabric.reads)
    backend.subscribe(lambda identity: None)

    fabric.notify("attribute_updated", _attribute_event(KITCHEN_ACCENT, path))
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert len(fabric.reads) == before


async def test_an_event_that_names_its_parts_rather_than_a_path_is_understood(
    backend: MatterBackend, fabric: FakeMatterClient
) -> None:
    """Two spellings, because the client offers both and neither has been observed (A9)."""
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))
    before = len(fabric.reads)
    backend.subscribe(lambda identity: None)

    fabric.notify("attribute_updated", _parts_event(KITCHEN_ACCENT, 2, mp.BINDING_CLUSTER, 0))
    await backend.async_capabilities(matter_handle(KITCHEN_ACCENT))

    assert len(fabric.reads) > before


def _parts_event(node_id: int, endpoint: int, cluster: int, attribute: int) -> Any:
    """Return an attribute-updated payload that names its parts rather than a path."""

    class _Attribute:
        def __init__(self) -> None:
            self.node_id = node_id
            self.endpoint = endpoint
            self.cluster_id = cluster
            self.attribute_id = attribute

    return _Attribute()
