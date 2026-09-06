"""Turning what this integration knows into what a client can render.

The WebSocket API and diagnostics both need the same things described the same way, so
they are described once, here. Two properties are what this module is for.

**A plan is grouped by device, and by what kind of work it is.** The panel renders one
section per device with adds, removes, blocked-with-reasons, pending and
unmanaged-with-fingerprints beside each other, and a flat list would make it filter the
same tuple five times and invent the grouping itself. One device is also what a user
decides about, because one device is one radio conversation.

**Nothing crosses that is not JSON.** Not "happens to serialize", but built from strings,
numbers, lists and dicts on purpose: a `StrEnum` survives `json.dumps` and a `Diagnostic`
does not, and the difference shows up at the moment somebody's panel is open rather than
at the moment the code was written. Enums are stringified here and value types are
flattened here, so nothing downstream has to remember to.

Every message that could be shown to a person is a translation key and its placeholders,
never an English sentence: the panel localises it, and a diagnostic that arrived as prose
could not be localised at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback

from .models import Diagnostic, Link, ObservedLink, PlanOp
from .rule_entity import async_upstream_device
from .yaml_io import rule_to_data

if TYPE_CHECKING:
    from . import DeviceLinksConfigEntry
    from .compiler import CompiledRule
    from .models import (
        DeviceCapabilities,
        DeviceHandle,
        Emitter,
        Plan,
        PlanItem,
        Profile,
        Rule,
        SettingWrite,
    )
    from .storage import JobSummary, Snapshot


class Serializer:
    """Describes one moment's worth of state, for one request.

    Built per request rather than kept, because everything it resolves (which rule owns
    what, which Home Assistant device a handle is) changes as the user works. The device
    id lookups are cached for the life of one request only, which is what makes serializing
    a forty-link plan one registry lookup per device rather than one per link.
    """

    def __init__(self, hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> None:
        """Hold the entry this is about and resolve nothing yet."""
        self._hass = hass
        self._entry = entry
        self._coordinator = entry.runtime_data.coordinator
        self._device_ids: dict[str, str | None] = {}
        profile = self._coordinator.active_profile
        self._rule_names = {} if profile is None else {rule.id: rule.name for rule in profile.rules}

    # Devices.

    @callback
    def device_id(self, handle: DeviceHandle) -> str | None:
        """Return the Home Assistant device id for this handle, or None when it has none.

        None is a real answer rather than a failure: a Zigbee or Matter handle cannot be
        resolved to a registry entry yet (see `rule_entity`), and a device the upstream
        integration has removed has no entry at all.
        """
        if handle.identity not in self._device_ids:
            device = async_upstream_device(self._hass, self._entry, handle)
            self._device_ids[handle.identity] = None if device is None else device.id
        return self._device_ids[handle.identity]

    @callback
    def device(self, handle: DeviceHandle) -> dict[str, Any]:
        """Return one device as a list row: what it is, and how much is on it."""
        observed = self._coordinator.observed_for(handle)
        capabilities = self._coordinator.capabilities_for(handle.identity)
        return {
            "identity": handle.identity,
            "device_id": self.device_id(handle),
            "name": handle.name_at_authoring,
            "backend": str(handle.backend),
            "protocol_id": handle.protocol_id,
            "available": self._coordinator.is_available(handle.identity),
            "links": 0 if observed is None else len(observed.links),
            "emitters": 0 if capabilities is None else len(capabilities.emitters),
            "is_long_range": capabilities is not None and capabilities.is_long_range,
        }

    @callback
    def capabilities(self, capabilities: DeviceCapabilities) -> list[dict[str, Any]]:
        """Return one device's controls, with the group each feature is written to."""
        return [self._emitter(emitter) for emitter in capabilities.emitters]

    @staticmethod
    def _emitter(emitter: Emitter) -> dict[str, Any]:
        """Return one control, including why it may need care (`semantics`)."""
        return {
            "emitter_id": emitter.emitter_id,
            "label": emitter.label,
            "group_ids": list(emitter.group_ids),
            "actions": {str(feature): group for feature, group in emitter.actions.items()},
            "capacity": emitter.capacity,
            "supports_endpoint_targets": emitter.supports_endpoint_targets,
            "is_lifeline": emitter.is_lifeline,
            "grouping": emitter.grouping,
            "semantics": emitter.semantics,
        }

    # Links.

    @callback
    def link(self, link: Link | ObservedLink) -> dict[str, Any]:
        """Return one link, desired or observed, in one shape.

        One shape on purpose: the panel shows a link the same way whether it is about to be
        written or was read off a device, and a client that had to switch on which kind it
        was holding would get it wrong exactly once, in the list where both appear.
        `is_system` is false and `managed_by` is None for a link that does not exist yet,
        which is true of it rather than merely absent.
        """
        observed = link if isinstance(link, ObservedLink) else None
        rule_id = link.rule_id
        return {
            "fingerprint": link.fingerprint,
            "backend": str(link.backend),
            "feature": str(link.feature),
            "emitter_id": link.emitter_id,
            "emitter_group": link.emitter_group,
            "source": {
                "identity": link.source.identity,
                "protocol_id": link.source.protocol_id,
                "name": link.source.name_at_authoring,
                "device_id": self.device_id(link.source),
                "endpoint": link.source_endpoint,
            },
            "target": {
                "identity": link.target.handle.identity,
                "protocol_id": link.target.handle.protocol_id,
                "name": link.target.handle.name_at_authoring,
                "device_id": self.device_id(link.target.handle),
                "endpoint": link.target.endpoint,
            },
            "rule_id": rule_id,
            "rule_name": None if rule_id is None else self._rule_names.get(rule_id),
            "is_system": observed is not None and observed.is_system,
            "managed_by": None if observed is None else observed.managed_by,
        }

    # Plans.

    @callback
    def plan(self, plan: Plan) -> dict[str, Any]:
        """Return a plan grouped by device, with one list per kind of work.

        Every device the plan says anything about is here, including one that has only
        unmanaged links on it: "nothing to do here, and these four entries are not mine"
        is a thing the user has to be able to see, and a device that vanished from the list
        because it had no work would read as a device nobody looked at.
        """
        devices: dict[str, dict[str, Any]] = {}
        for item in plan.items:
            self._bucket(devices, item.device_identity)[str(item.op)].append(self.item(item))
        ignored = self._coordinator.state.ignored_unmanaged
        for link in plan.unmanaged:
            entry = self._bucket(devices, link.source.identity)
            entry["unmanaged"].append({**self.link(link), "ignored": link.fingerprint in ignored})
        counts = {str(op): 0 for op in PlanOp}
        for item in plan.items:
            counts[str(item.op)] += 1
        counts["unmanaged"] = len(plan.unmanaged)
        return {
            "token": plan.token,
            "is_empty": plan.is_empty,
            "unchanged_count": plan.unchanged_count,
            "counts": counts,
            "devices": sorted(
                devices.values(), key=lambda entry: (entry["name"], entry["identity"])
            ),
        }

    def _bucket(self, devices: dict[str, dict[str, Any]], identity: str) -> dict[str, Any]:
        """Return the entry one device's work goes into, building it the first time."""
        if identity not in devices:
            handle = self._coordinator.handle_for(identity)
            devices[identity] = {
                "identity": identity,
                "device_id": None if handle is None else self.device_id(handle),
                "name": identity if handle is None else handle.name_at_authoring,
                "backend": None if handle is None else str(handle.backend),
                "available": self._coordinator.is_available(identity),
                **{str(op): [] for op in PlanOp},
                "unmanaged": [],
            }
        return devices[identity]

    @callback
    def item(self, item: PlanItem) -> dict[str, Any]:
        """Return one step of a plan, with the reason it is blocked when it is."""
        return {
            "op": str(item.op),
            "device_identity": item.device_identity,
            "link": None if item.link is None else self.link(item.link),
            "setting": None if item.setting is None else self.setting(item.setting),
            "reason": diagnostic(item.reason),
        }

    @staticmethod
    def setting(setting: SettingWrite) -> dict[str, Any]:
        """Return one device setting a rule asked for, and where it really lives."""
        return {
            "device_identity": setting.device.identity,
            "capability": setting.capability,
            "parameter": setting.parameter,
            "bitmask": setting.bitmask,
            "value": setting.value,
        }

    # Rules and profiles.

    @callback
    def compiled(self, compiled: CompiledRule) -> dict[str, Any]:
        """Return what one rule compiles to, warnings and refusals included.

        A rule that compiles to nothing with an error is the answer to "will this work?",
        so this is a result rather than a failure: the panel shows the reason beside the
        rule the user is still editing.
        """
        return {
            "links": [self.link(link) for link in compiled.links],
            "settings": [self.setting(setting) for setting in compiled.settings],
            "warnings": [diagnostic(warning) for warning in compiled.warnings],
            "errors": [diagnostic(error) for error in compiled.errors],
        }

    @callback
    def rule(self, rule: Rule) -> dict[str, Any]:
        """Return one rule with what it is currently doing, for the rule list."""
        states = self._coordinator.drift_state()
        total, in_sync = self._coordinator.rule_link_counts(rule.id)
        return {
            "rule": rule_to_data(rule),
            "state": str(states[rule.id]) if rule.id in states else "unknown",
            "links_total": total,
            "links_in_sync": in_sync,
        }

    @callback
    def profile(self, profile: Profile, *, active_profile_id: str | None) -> dict[str, Any]:
        """Return one profile as a list row: what it is called and how big it is."""
        return {
            "id": profile.id,
            "name": profile.name,
            "rules": len(profile.rules),
            "enabled_rules": sum(1 for rule in profile.rules if rule.enabled),
            "is_active": profile.id == active_profile_id,
        }

    # History.

    @staticmethod
    def job(job: JobSummary) -> dict[str, Any]:
        """Return one apply as the Activity view shows it afterwards (FR-A2)."""
        return {
            "id": job.id,
            "created_at": job.created_at,
            "scope": job.scope,
            "status": job.status,
            "total": len(job.results),
            "results": [
                {
                    "fingerprint": result.fingerprint,
                    "status": result.status,
                    "reason": result.reason,
                }
                for result in job.results
            ],
        }

    @staticmethod
    def snapshot(snapshot: Snapshot) -> dict[str, Any]:
        """Return one pre-apply snapshot: what it covers, not what is in it.

        The links themselves are deliberately left out of a listing. A snapshot of twenty
        devices is hundreds of entries, and what a person choosing one needs is when it was
        taken and which devices it speaks for.
        """
        return {
            "id": snapshot.id,
            "created_at": snapshot.created_at,
            "reason": snapshot.reason,
            "devices": list(snapshot.devices),
            "links": len(snapshot.links),
        }


@callback
def diagnostic(message: Diagnostic | None) -> dict[str, Any] | None:
    """Return one message as a key and its placeholders, never as a sentence."""
    if message is None:
        return None
    return {
        "translation_key": message.translation_key,
        "placeholders": dict(message.placeholders),
    }
