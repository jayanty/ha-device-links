"""The coordinator: whose link is whose, and what an unreadable device is allowed to mean.

Two failures are what this file exists to prevent, and both of them are silent.

The first is adopting somebody else's association. The planner removes exactly what
`managed_by` claims, so a coordinator that decides "this looks like something a rule would
make, so it must be ours" deletes an association a user made by hand in Z-Wave JS UI, with
no warning and no undo. Ownership is by recorded fingerprint and nothing else, and
`test_a_link_that_only_looks_like_ours_is_never_adopted` is the test that keeps it that way.

The second is a dropped connection reading as a deletion. If "I got nothing back" became
"the device holds nothing", every link in the house would show as drifted and the next
apply would try to rewrite the entire network.

Everything here runs against the Phase 1B fake driver through the real Z-Wave adapter, so
what is asserted is what that adapter really produces.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace

from homeassistant.core import HomeAssistant
import pytest
from zwave_js_server.model.association import AssociationAddress

from custom_components.device_links.backends.base import (
    BackendDevice,
    LinkCheck,
    LinkResult,
    ObservedDevice,
    SettingResult,
    SettingValue,
)
from custom_components.device_links.backends.zwave import ZWaveBackend
from custom_components.device_links.coordinator import (
    DeviceLinksCoordinator,
    PlanScope,
    RuleState,
)
from custom_components.device_links.models import Backend as BackendId
from custom_components.device_links.models import (
    DeviceCapabilities,
    DeviceHandle,
    Feature,
    Link,
    PlanItem,
    PlanOp,
    Profile,
    Rule,
    RuleSource,
    RuleTarget,
    Template,
)
from custom_components.device_links.storage import DeviceLinksStore, StoredState
from tests.factories import handle, profiles
from tests.fakes.zwave import FakeDriver, build_driver_from_fixture

# Short enough that a test does not wait on it, long enough that a burst really coalesces.
TEST_DEBOUNCE = 0.05


class ControlledBackend:
    """The real Z-Wave adapter, with the two things a fake driver cannot express.

    Every answer still comes from `ZWaveBackend` over the Stage 0 fake, so these tests are
    about what that adapter really produces. What is added here is a backend that has
    stopped answering (the add-on restarted, the WebSocket dropped) and a count of how many
    times it was asked, which is how a debounce is proved.
    """

    def __init__(self, inner: ZWaveBackend) -> None:
        self.inner = inner
        self.available = True
        self.unreadable: set[str] = set()
        self.observed_reads = 0
        self.deep_reads = 0
        self.subscriptions = 0
        self.notify: Callable[[str], None] = lambda identity: None

    def _check(self, identity: str | None = None) -> None:
        if not self.available:
            raise ConnectionError("the Z-Wave JS add-on is not answering")
        if identity is not None and identity in self.unreadable:
            raise ConnectionError(f"{identity} did not answer")

    async def async_devices(self) -> list[BackendDevice]:
        self._check()
        return await self.inner.async_devices()

    async def async_capabilities(self, handle: DeviceHandle) -> DeviceCapabilities:
        self._check(handle.identity)
        return await self.inner.async_capabilities(handle)

    async def async_observed(self, handle: DeviceHandle, deep: bool = False) -> ObservedDevice:
        self._check(handle.identity)
        self.observed_reads += 1
        self.deep_reads += int(deep)
        return await self.inner.async_observed(handle, deep)

    async def async_check_link(self, link: Link) -> LinkCheck:
        return await self.inner.async_check_link(link)

    async def async_add_link(self, link: Link) -> LinkResult:
        return await self.inner.async_add_link(link)

    async def async_remove_link(self, link: Link) -> LinkResult:
        return await self.inner.async_remove_link(link)

    async def async_read_setting(self, handle: DeviceHandle, capability: str) -> SettingValue:
        return await self.inner.async_read_setting(handle, capability)

    async def async_write_setting(
        self, handle: DeviceHandle, capability: str, value: int
    ) -> SettingResult:
        return await self.inner.async_write_setting(handle, capability, value)

    def subscribe(self, callback: Callable[[str], None]) -> Callable[[], None]:
        self.subscriptions += 1
        self.notify = callback
        unsubscribe = self.inner.subscribe(callback)

        def _unsubscribe() -> None:
            self.subscriptions -= 1
            unsubscribe()

        return _unsubscribe

    def wake_instructions(self, handle: DeviceHandle) -> str | None:
        return self.inner.wake_instructions(handle)


@pytest.fixture
def driver() -> FakeDriver:
    return build_driver_from_fixture()


@pytest.fixture
def backend(driver: FakeDriver) -> ControlledBackend:
    """The real adapter, with its own debounce off so the coordinator's is what is tested."""
    return ControlledBackend(ZWaveBackend(driver=driver, profiles=profiles(), debounce_seconds=0))


@pytest.fixture
async def coordinator(
    hass: HomeAssistant, backend: ControlledBackend
) -> AsyncGenerator[DeviceLinksCoordinator]:
    coordinator = DeviceLinksCoordinator(
        hass,
        backends={BackendId.ZWAVE: backend},
        store=DeviceLinksStore(hass),
        refresh_debounce_seconds=TEST_DEBOUNCE,
    )
    await coordinator.async_setup()
    yield coordinator
    await coordinator.async_shutdown()


def rule(
    rule_id: str = "rule-1",
    *,
    target: int = 38,
    emitter: str = "g2",
    enabled: bool = True,
) -> Rule:
    """Return a rule the Bedroom Scene Controller's main button drives one light with."""
    return Rule(
        id=rule_id,
        name=f"Rule {rule_id}",
        template=Template.REMOTE,
        backend=BackendId.ZWAVE,
        source=RuleSource(device=handle(36), endpoint=0, emitter_id=emitter),
        targets=(RuleTarget(device=handle(target), endpoint=None),),
        features=frozenset({Feature.ON_OFF}),
        enabled=enabled,
    )


def with_rules(coordinator: DeviceLinksCoordinator, *rules: Rule) -> None:
    """Make a profile of these rules the active one, as a profile edit would."""
    profile = Profile(id="profile-1", name="Bedroom", rules=rules)
    coordinator.async_update_state(StoredState(profiles=(profile,), active_profile_id=profile.id))


async def apply_by_hand(driver: FakeDriver, *, source: int, group: int, target: int) -> None:
    """Put an association on a device the way somebody using Z-Wave JS UI would.

    Deliberately not through our own write path: this is the association Device Links did
    not create, and the whole point is that nothing about it went through us.
    """
    controller = driver.controller
    await controller.async_add_associations(
        AssociationAddress(controller, node_id=source),
        group,
        [AssociationAddress(controller, node_id=target)],
    )


def links_of(coordinator: DeviceLinksCoordinator, node_id: int = 36) -> tuple:
    device = coordinator.observed_for(handle(node_id))
    assert device is not None
    return device.links


def owned_link(coordinator: DeviceLinksCoordinator, *, group: str, target: int):
    """Return the one observed entry in this group pointing at this node."""
    return next(
        link
        for link in links_of(coordinator)
        if link.emitter_group == group and link.target.handle.identity.endswith(f":{target}")
    )


# Ownership.


async def test_a_link_a_rule_compiled_is_owned_by_that_rule(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    with_rules(coordinator, rule("rule-1"))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()

    assert owned_link(coordinator, group="2", target=38).managed_by == "rule-1"


async def test_a_link_that_only_looks_like_ours_is_never_adopted(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """Ownership is by recorded fingerprint. It is never inferred from shape.

    On the device, these two entries are the same kind of thing: the same source node, the
    same association group, the same feature, both pointing at a dimmer. One of them is
    what rule-1 compiles to. The other is an association somebody made by hand in Z-Wave JS
    UI, possibly years ago, and no rule in the profile produced its fingerprint.

    A lookup that matched on anything less than the whole fingerprint (the group, or the
    group and the feature, or "does some rule use this control") would adopt the second
    one, and the next apply would delete it with no warning and no undo. If you are here
    because this test failed after you optimised the ownership lookup: the optimisation is
    wrong, not the test.
    """
    with_rules(coordinator, rule("rule-1", target=38))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await apply_by_hand(driver, source=36, group=2, target=35)
    await coordinator.async_refresh()

    assert owned_link(coordinator, group="2", target=38).managed_by == "rule-1"
    assert owned_link(coordinator, group="2", target=35).managed_by is None

    plan = await coordinator.async_plan()
    removed = [item.link for item in plan.items if item.op is PlanOp.REMOVE]

    assert removed == []
    assert [entry.target.handle.identity for entry in plan.unmanaged] == [handle(35).identity]


async def test_a_system_link_is_never_owned_even_if_a_rule_claims_its_fingerprint(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """Belt and braces over the planner's own guard: a lifeline is never ours, ever.

    Group 2 of this node is reported as a lifeline here, which no real ZEN35 does, so that
    a rule really does compile a link whose fingerprint is a system link's. Nothing about
    that may make it removable.
    """
    groups = driver.controller._groups[36][0]
    groups[2] = replace(groups[2], is_lifeline=True)
    with_rules(coordinator, rule("rule-1", target=38))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()

    entry = owned_link(coordinator, group="2", target=38)

    assert entry.is_system
    assert entry.managed_by is None


async def test_disabling_a_rule_leaves_its_links_owned_so_they_can_be_removed(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """The subtle one. FR-R5: disabling is not deleting, and it must not orphan links.

    A disabled rule's links are no longer wanted, so they are planned for removal, and only
    an owned link is ever removed. If disabling made them unmanaged, the integration would
    report them forever and never clean them up: the user would have to go and delete by
    hand exactly what they asked the integration to take off.
    """
    with_rules(coordinator, rule("rule-1"))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()

    with_rules(coordinator, rule("rule-1", enabled=False))

    assert owned_link(coordinator, group="2", target=38).managed_by == "rule-1"

    plan = await coordinator.async_plan()

    assert [item.op for item in plan.items] == [PlanOp.REMOVE]
    assert plan.items[0].link is not None
    assert plan.items[0].link.target.handle.identity == handle(38).identity


async def test_deleting_a_rule_makes_its_links_unmanaged_so_they_are_only_reported(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """The user's intent is gone, so the link is somebody's leftover, not ours to remove.

    The other half of the disable case, and the reason ownership follows the profile rather
    than a rule's history: a rule that no longer exists claims nothing.
    """
    with_rules(coordinator, rule("rule-1"))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()

    with_rules(coordinator, rule("rule-2", emitter="g5", target=35))

    assert owned_link(coordinator, group="2", target=38).managed_by is None

    plan = await coordinator.async_plan()

    assert not [item for item in plan.items if item.op is PlanOp.REMOVE]
    assert len(plan.unmanaged) == 1


async def test_ownership_is_resolved_again_when_the_profile_changes(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """Changing the profile is when ownership changes, and no device is re-read for it."""
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()
    reads = coordinator_reads(coordinator)

    assert owned_link(coordinator, group="2", target=38).managed_by is None

    with_rules(coordinator, rule("rule-1"))

    assert owned_link(coordinator, group="2", target=38).managed_by == "rule-1"
    assert coordinator_reads(coordinator) == reads


def coordinator_reads(coordinator: DeviceLinksCoordinator) -> int:
    backend = coordinator.backend_for(handle(36))
    assert isinstance(backend, ControlledBackend)
    return backend.observed_reads


# Availability.


async def test_a_backend_going_unavailable_never_looks_like_mass_deletion(
    coordinator: DeviceLinksCoordinator, backend: ControlledBackend, driver: FakeDriver
) -> None:
    """E1. The Z-Wave JS add-on restarting must not read as "somebody deleted everything".

    The cache is kept and the devices are marked unavailable. If the coordinator answered
    with an empty device instead, every managed link would look removed, every rule would
    show drift, and the next apply would try to rewrite the whole network.
    """
    with_rules(coordinator, rule("rule-1"))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()
    before = links_of(coordinator)

    backend.available = False
    await coordinator.async_refresh()

    assert links_of(coordinator) == before
    assert not coordinator.is_available(handle(36).identity)

    plan = await coordinator.async_plan()

    assert plan.items == ()
    assert plan.unmanaged == ()


async def test_a_device_that_cannot_be_read_is_unknown_rather_than_drifted(
    coordinator: DeviceLinksCoordinator, backend: ControlledBackend, driver: FakeDriver
) -> None:
    """E4: state unknown is not the same as state wrong, and only one of them is a fault."""
    with_rules(coordinator, rule("rule-1"))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()
    coordinator.async_note_applied(["rule-1"])

    backend.unreadable.add(handle(36).identity)
    await coordinator.async_refresh()

    assert coordinator.drift_state() == {"rule-1": RuleState.UNKNOWN}


async def test_a_backend_that_comes_back_is_read_again_before_it_is_believed(
    coordinator: DeviceLinksCoordinator, backend: ControlledBackend, driver: FakeDriver
) -> None:
    """A cache from before an outage is of unknown age, so recovery is a read, not a thaw."""
    with_rules(coordinator, rule("rule-1"))
    await coordinator.async_refresh()
    backend.available = False
    await coordinator.async_refresh()

    await apply_by_hand(driver, source=36, group=2, target=38)
    backend.available = True
    await coordinator.async_refresh()

    assert coordinator.is_available(handle(36).identity)
    assert owned_link(coordinator, group="2", target=38).managed_by == "rule-1"


# Subscriptions and drift.


async def test_a_burst_of_backend_events_is_one_refresh(
    hass: HomeAssistant, coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """FR-B3: one refresh emits an event per group, and each one is not worth a re-read."""
    reads = coordinator_reads(coordinator)

    for _ in range(3):
        driver.controller.emit_association_changed(36, group=2)
    await asyncio.sleep(TEST_DEBOUNCE * 3)
    await hass.async_block_till_done()

    assert coordinator_reads(coordinator) == reads + 1


async def test_an_event_refreshes_only_the_device_it_is_about(
    hass: HomeAssistant, coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """One device changing is one radio conversation, not a sweep of the whole network."""
    await apply_by_hand(driver, source=36, group=2, target=38)
    driver.controller.emit_association_changed(36, group=2)
    await asyncio.sleep(TEST_DEBOUNCE * 3)
    await hass.async_block_till_done()

    assert len(links_of(coordinator)) == 2


async def test_shutdown_stops_the_subscriptions(
    coordinator: DeviceLinksCoordinator, backend: ControlledBackend, driver: FakeDriver
) -> None:
    """A listener that outlives the config entry fires at a coordinator that is gone."""
    assert backend.subscriptions == 1

    await coordinator.async_shutdown()
    reads = coordinator_reads(coordinator)
    driver.controller.emit_association_changed(36, group=2)
    await asyncio.sleep(TEST_DEBOUNCE * 3)

    assert backend.subscriptions == 0
    assert coordinator_reads(coordinator) == reads


async def test_drift_is_reported_only_after_a_successful_apply(
    coordinator: DeviceLinksCoordinator,
) -> None:
    """A rule that was never applied is pending. Nothing has drifted from anything yet."""
    with_rules(coordinator, rule("rule-1"))

    assert coordinator.drift_state() == {"rule-1": RuleState.PENDING}

    coordinator.async_note_applied(["rule-1"])

    assert coordinator.drift_state() == {"rule-1": RuleState.DRIFT}


async def test_a_rule_whose_links_are_all_present_is_in_sync(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    with_rules(coordinator, rule("rule-1"))
    await apply_by_hand(driver, source=36, group=2, target=38)
    await coordinator.async_refresh()
    coordinator.async_note_applied(["rule-1"])

    assert coordinator.drift_state() == {"rule-1": RuleState.IN_SYNC}


async def test_a_disabled_rule_reports_as_disabled(
    coordinator: DeviceLinksCoordinator,
) -> None:
    with_rules(coordinator, rule("rule-1", enabled=False))

    assert coordinator.drift_state() == {"rule-1": RuleState.DISABLED}


async def test_a_rule_naming_a_device_this_network_does_not_have_is_unknown(
    coordinator: DeviceLinksCoordinator,
) -> None:
    """A rule that has outlived its hardware is unknown, not in sync and not drifted."""
    missing = replace(handle(38), protocol_id="3538613642:200")
    with_rules(
        coordinator, replace(rule("rule-1"), targets=(RuleTarget(device=missing, endpoint=None),))
    )

    assert coordinator.drift_state() == {"rule-1": RuleState.UNKNOWN}


async def test_there_is_no_drift_state_without_an_active_profile(
    coordinator: DeviceLinksCoordinator,
) -> None:
    assert coordinator.active_profile is None
    assert coordinator.drift_state() == {}


# Planning.


async def test_a_plan_covers_every_device_by_default(
    coordinator: DeviceLinksCoordinator,
) -> None:
    with_rules(coordinator, rule("rule-1", target=38), rule("rule-2", emitter="g5", target=35))
    plan = await coordinator.async_plan()

    assert [item.op for item in plan.items] == [PlanOp.ADD, PlanOp.ADD]


async def test_a_rule_scoped_plan_touches_only_that_rule_s_devices(
    coordinator: DeviceLinksCoordinator,
) -> None:
    """A scoped apply must not become a whole-network apply by accident."""
    with_rules(coordinator, rule("rule-1", target=38), rule("rule-2", emitter="g5", target=35))
    plan = await coordinator.async_plan(PlanScope(rule_ids=frozenset({"rule-1"})))

    assert len(plan.items) == 1
    assert plan.items[0].link is not None
    assert plan.items[0].link.target.handle.identity == handle(38).identity


async def test_a_device_scoped_plan_leaves_other_devices_alone(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    with_rules(coordinator, rule("rule-1", target=38))
    await apply_by_hand(driver, source=36, group=2, target=35)
    await coordinator.async_refresh()

    plan = await coordinator.async_plan(
        PlanScope(device_identities=frozenset({handle(37).identity}))
    )

    assert plan.items == ()
    assert plan.unmanaged == ()


async def test_an_unmanaged_link_is_removed_only_when_it_is_selected(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """D9: report by default, remove only what the user picked out by fingerprint."""
    await apply_by_hand(driver, source=36, group=2, target=35)
    await coordinator.async_refresh()
    foreign = owned_link(coordinator, group="2", target=35)

    plan = await coordinator.async_plan(remove_unmanaged=frozenset({foreign.fingerprint}))

    assert [item.op for item in plan.items] == [PlanOp.REMOVE]


async def test_the_active_profile_is_the_one_the_store_had(
    hass: HomeAssistant, backend: ControlledBackend
) -> None:
    """A profile survives a restart: setup finds it, and its links are owned again."""
    profile = Profile(id="profile-1", name="Bedroom", rules=(rule("rule-1"),))
    store = DeviceLinksStore(hass)
    await store.async_save(StoredState(profiles=(profile,), active_profile_id="profile-1"))

    coordinator = DeviceLinksCoordinator(
        hass, backends={BackendId.ZWAVE: backend}, store=DeviceLinksStore(hass)
    )
    await coordinator.async_setup()

    assert coordinator.active_profile == profile
    assert coordinator.state.active_profile_id == "profile-1"
    await coordinator.async_shutdown()


async def test_the_observed_state_of_an_unknown_device_is_nothing_at_all(
    coordinator: DeviceLinksCoordinator,
) -> None:
    """Answering with an empty device would be indistinguishable from a device with none."""
    unknown = replace(handle(38), protocol_id="3538613642:200")

    assert coordinator.observed_for(unknown) is None
    assert not coordinator.is_available(unknown.identity)


async def test_refreshing_one_device_reads_only_that_device(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """What the executor does after writing to a node: re-read that node, not the mesh."""
    reads = coordinator_reads(coordinator)
    await apply_by_hand(driver, source=36, group=2, target=38)

    await coordinator.async_refresh(handle(36))

    assert coordinator_reads(coordinator) == reads + 1
    assert len(links_of(coordinator)) == 2


async def test_a_device_whose_backend_is_not_loaded_is_left_alone(
    coordinator: DeviceLinksCoordinator,
) -> None:
    """Zigbee arrives in Phase 2. Until then a Zigbee handle is not an error, just unknown."""
    zigbee = replace(handle(38), backend=BackendId.ZIGBEE2MQTT)

    await coordinator.async_refresh(zigbee)

    assert coordinator.observed_for(zigbee) is None
    assert coordinator.backend_for(zigbee) is None


async def test_noting_the_same_rule_applied_twice_changes_nothing(
    coordinator: DeviceLinksCoordinator,
) -> None:
    """An apply per minute must not be a storage write per minute."""
    with_rules(coordinator, rule("rule-1"))
    coordinator.async_note_applied(["rule-1"])
    before = coordinator.state

    coordinator.async_note_applied(["rule-1"])

    assert coordinator.state is before


async def test_a_scoped_plan_still_removes_an_unmanaged_link_the_user_selected(
    coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """The selection is the user's own decision about one link, not a rule's work."""
    with_rules(coordinator, rule("rule-1"))
    await apply_by_hand(driver, source=36, group=2, target=35)
    await coordinator.async_refresh()
    foreign = owned_link(coordinator, group="2", target=35)

    plan = await coordinator.async_plan(
        PlanScope(rule_ids=frozenset({"rule-1"})),
        remove_unmanaged=frozenset({foreign.fingerprint}),
    )

    assert sorted(item.op for item in plan.items) == [PlanOp.ADD, PlanOp.REMOVE]


async def test_an_event_about_a_device_that_was_never_listed_is_ignored(
    hass: HomeAssistant, coordinator: DeviceLinksCoordinator, backend: ControlledBackend
) -> None:
    """A node included after setup is not one we hold a handle for, and must not crash us."""
    reads = coordinator_reads(coordinator)

    backend.notify("zwave:3538613642:200")
    await asyncio.sleep(TEST_DEBOUNCE * 3)
    await hass.async_block_till_done()

    assert coordinator_reads(coordinator) == reads


async def test_shutting_down_cancels_a_refresh_that_was_about_to_happen(
    hass: HomeAssistant, coordinator: DeviceLinksCoordinator, driver: FakeDriver
) -> None:
    """An unload during the debounce window must not read a backend on the way out."""
    reads = coordinator_reads(coordinator)
    driver.controller.emit_association_changed(36, group=2)

    await coordinator.async_shutdown()
    await asyncio.sleep(TEST_DEBOUNCE * 3)
    await hass.async_block_till_done()

    assert coordinator_reads(coordinator) == reads


def test_a_plan_item_that_is_not_about_a_link_survives_a_rule_scope() -> None:
    """Nothing produces a setting write yet (open item T2), so this pins what will happen.

    A `set_param` item is about a device rather than about one link, so there is no owner
    to compare against the scope. Dropping it silently would make a scoped apply skip the
    device setting a rule asked for, which is the kind of omission nobody notices until the
    hold-to-dim they configured does nothing.
    """
    item = PlanItem(op=PlanOp.SET_PARAM, device_identity=handle(36).identity)

    assert DeviceLinksCoordinator._is_wanted(item, frozenset({"rule-1"}), frozenset())


async def test_a_rule_that_compiles_to_nothing_is_blocked_rather_than_in_sync(
    coordinator: DeviceLinksCoordinator,
) -> None:
    """A rule whose every leg was refused has nothing to be in sync with.

    This one is a trap: with no links wanted, "is every wanted link present?" is vacuously
    true, and the rule would report in_sync while doing nothing at all. The user would see
    a healthy rule and a light that never responds.
    """
    with_rules(coordinator, rule("rule-1", emitter="g99"))

    assert coordinator.drift_state() == {"rule-1": RuleState.BLOCKED}


async def test_a_deep_refresh_asks_the_device_rather_than_the_driver_cache(
    coordinator: DeviceLinksCoordinator, backend: ControlledBackend
) -> None:
    """What the executor does after an apply: a verify that reads the cache proves nothing."""
    await coordinator.async_refresh(handle(36), deep=True)

    assert backend.deep_reads == 1
