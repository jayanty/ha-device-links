"""Attaching an entity to a device somebody else created, without creating another one.

FR-E1 puts each rule's switch and status sensor on the **source device's existing Home
Assistant device entry**, so per-rule state appears on the device page the user already
knows rather than on a page they have to go and find.

**How attachment works on Home Assistant 2026.8.** Device registry identifiers are unique
*per config entry* since the composite-device split: two integrations describing the same
physical device each hold their own device record carrying the same identifiers, and
`async_get_device` resolves them to one device for anything that looks a device up. So
attaching means registering our own record with the identifiers `zwave_js` already
registered, and never means adding ourselves to somebody else's record.

The failure mode is the reason this is its own module, because it does not raise.
`async_get_or_create` creates a record for whatever identifiers it is handed, so an
identifier one character out from what `zwave_js` registered is not an error: it makes a
record that groups with nothing, the user gets a second, empty device beside their switch,
and there is nothing in the log to explain it.

So nothing here ever spells an identifier out into a `DeviceInfo`. Every attachment starts
with a registry lookup and copies the identifiers back verbatim from the entry that was
found, which makes a near miss structurally impossible rather than merely unlikely. A rule
whose device is not in the registry gets no entity at all, and the tracker below removes
the entities and our own now-empty record when an upstream device goes away, which is
`stale-devices`.

**No identifier format is written down here.** Each adapter answers
`Backend.registry_identifier` for its own devices, because the part of an identifier that
is not the protocol address is knowledge only the adapter has: a Zigbee2MQTT identifier
embeds the MQTT base topic that instance is configured with, and a Matter one the
compressed fabric id. Deriving Z-Wave's here and calling every other protocol
"not attachable" was open item T57, and what it cost was not attachment: it was that
`Serializer.device_id` had no answer for a Zigbee device, so no Zigbee device could be
opened, refreshed or chosen as a rule's source anywhere in the panel.

A backend that is not loaded, and a handle its adapter says has no upstream record (a
managed Zigbee group is an address rather than a device), both come back as None, which
means the same thing to every caller: there is no Home Assistant device to point at.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import RuleState
from .entity import DeviceLinksEntity

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import DeviceLinksConfigEntry
    from .models import DeviceHandle, Rule


@callback
def async_upstream_device(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, handle: DeviceHandle
) -> dr.DeviceEntry | None:
    """Return the upstream integration's device record for this handle, if it has one.

    Our own record is deliberately not accepted as an answer. Records sharing identifiers
    are resolved to one device, so once the upstream integration removes its record ours
    is the only match left, and treating that as "the device is still there" would keep a
    rule entity alive on a device that no longer exists.
    """
    identifier = _upstream_identifier(entry, handle)
    if identifier is None:
        return None
    device = dr.async_get(hass).async_get_device(identifiers={identifier})
    if device is None or device.primary_config_entry == entry.entry_id:
        return None
    return device


@callback
def async_handle_of_device(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, device_id: str
) -> DeviceHandle | None:
    """Return the device handle behind a Home Assistant device id, if we know one.

    The inverse of `async_upstream_device`, and deliberately built on it rather than on a
    second derivation: a service and a WebSocket command take a device id because that is
    what a user can see and pick, and the answer has to be the same device the rule
    entities attached to. Deriving the identifier the other way round would be a second
    place for the near miss this module exists to prevent.

    Linear over the devices this integration has listed, which is tens on a large house
    and is asked once per service call.
    """
    for handle in entry.runtime_data.coordinator.devices.values():
        device = async_upstream_device(hass, entry, handle)
        if device is not None and device.id == device_id:
            return handle
    return None


def _upstream_identifier(
    entry: DeviceLinksConfigEntry, handle: DeviceHandle
) -> tuple[str, str] | None:
    """Return the registry identifier this handle's device carries upstream, if it has one.

    Asked of the adapter that speaks the device's protocol, never derived here: see the
    module docstring, and `Backend.registry_identifier` for why the adapter is the only
    layer that can answer. A protocol with no loaded backend has no answer, which is the
    same None a device with no upstream record gets.
    """
    backend = entry.runtime_data.coordinator.backend_for(handle)
    return None if backend is None else backend.registry_identifier(handle)


class RuleEntityFactory(Protocol):
    """Builds one entity for one rule, given the device it is to be attached to."""

    def __call__(
        self, entry: DeviceLinksConfigEntry, rule: Rule, device: dr.DeviceEntry
    ) -> RuleEntity:
        """Return the entity for this rule."""


@dataclass(frozen=True, slots=True)
class RuleEntityKind:
    """One sort of per-rule entity: what builds it, and how it is addressed.

    `platform` and `key_prefix` together are how an entity is found in the entity registry
    without holding the object, which is what removal needs: a status sensor is disabled by
    default, so it has a registry entry and no object at all.
    """

    platform: str
    key_prefix: str
    factory: RuleEntityFactory


class RuleEntity(DeviceLinksEntity):
    """One rule's entity, living on that rule's source device rather than on the hub.

    Availability follows the rule's own devices rather than the integration's: a rule
    whose source or target cannot be read is `unknown` in the coordinator, and `unknown`
    is not a switch position. Home Assistant already has a state for "we cannot say", and
    claiming either position instead would be a claim about somebody's house that nothing
    supports (quality-scale rule entity-unavailable).
    """

    def __init__(
        self,
        entry: DeviceLinksConfigEntry,
        rule: Rule,
        device: dr.DeviceEntry,
        *,
        key_prefix: str,
    ) -> None:
        """Attach to the device that was found in the registry, and to no other."""
        super().__init__(entry, f"{key_prefix}_{rule.id}")
        self.rule = rule
        # The identifiers come from the registry entry itself, so the only way to reach
        # this line with a wrong one is for the registry to have been wrong first. The
        # name is copied for the same reason a name is on any device record: it is what
        # Home Assistant builds this entity's own name from, and a record with none would
        # give the user a switch called "Link: ..." with nothing saying which switch.
        self._attr_device_info = DeviceInfo(identifiers=set(device.identifiers), name=device.name)
        self._attr_translation_placeholders = {"rule": rule.name}

    @property
    def rule_state(self) -> RuleState:
        """Return what this rule's links are doing, as the coordinator sees them."""
        return self.coordinator.drift_state().get(self.rule.id, RuleState.UNKNOWN)

    @property
    def available(self) -> bool:
        """Say whether every device this rule names can be read right now."""
        return super().available and all(
            self.coordinator.is_available(identity) for identity in self._device_identities
        )

    @property
    def _device_identities(self) -> Iterable[str]:
        """Return the identity of every device this rule touches."""
        yield self.rule.source.device.identity
        for target in self.rule.targets:
            yield target.device.identity


@callback
def async_track_rule_entities(
    hass: HomeAssistant,
    entry: DeviceLinksConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    kind: RuleEntityKind,
) -> None:
    """Keep one entity per attachable rule of the active profile, and only that.

    Rules are authored while the integration is running, so this cannot be a listing taken
    once at setup. It runs again on every coordinator update, which is when a rule is
    added, removed, renamed or has its profile switched under it, and on every device
    registry removal, which is when a rule's device stops existing.

    Removal goes through the entity registry rather than through the entity object, and
    that is not a detail: a status sensor is disabled by default, so it has a registry
    entry and no entity object at all, and asking an object that was never added to remove
    itself would do nothing while looking like it had worked.
    """
    coordinator = entry.runtime_data.coordinator
    created: set[str] = set()

    @callback
    def _sync() -> None:
        registry = er.async_get(hass)
        profile = coordinator.active_profile
        attachable: dict[str, tuple[Rule, dr.DeviceEntry]] = {}
        for rule in profile.rules if profile is not None else ():
            device = async_upstream_device(hass, entry, rule.source.device)
            if device is not None:
                attachable[rule.id] = (rule, device)

        for rule_id in sorted(created - set(attachable)):
            created.discard(rule_id)
            entity_id = registry.async_get_entity_id(
                kind.platform, DOMAIN, f"{entry.entry_id}_{kind.key_prefix}_{rule_id}"
            )
            if entity_id is not None:
                registry.async_remove(entity_id)

        added = [
            kind.factory(entry, rule, device)
            for rule_id, (rule, device) in sorted(attachable.items())
            if rule_id not in created
        ]
        created.update(attachable)
        if added:
            async_add_entities(added)
        _prune_our_empty_devices(hass, entry)

    @callback
    def _on_device_removed(event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        """Re-check attachment when a device disappears (quality-scale rule stale-devices).

        Only removals, because every addition of ours is itself a device registry event
        and reacting to those would have this call itself for as long as it kept working.
        """
        if event.data["action"] == "remove":
            _sync()

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))
    entry.async_on_unload(
        hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _on_device_removed)
    )


@callback
def _prune_our_empty_devices(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> None:
    """Drop our own device record for a device that has gone (`stale-devices`).

    Our record is the one carrying the upstream identifiers so the two group into one
    device page. When the upstream record goes, ours is what would be left standing: a
    device page for a switch that is no longer on the network, holding nothing. The hub is
    skipped by its own identifier, because it is ours by definition and outlives every
    device.
    """
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if any(domain == DOMAIN for domain, _ in device.identifiers):
            continue
        if not er.async_entries_for_device(entities, device.id, include_disabled_entities=True):
            devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
