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

from .coordinator import RuleState
from .models import Diagnostic, HybridLeg, Link, ObservedLink, PlanOp
from .rule_entity import async_upstream_device
from .yaml_io import rule_to_data

if TYPE_CHECKING:
    from collections.abc import Mapping

    from . import DeviceLinksConfigEntry
    from .compiler import CompiledRule
    from .loops import Loop
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
    from .swap import EmitterMapping, Replacement, RuleRewrite, SwapProposal


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
        # What every rule is judged against, worked out on first use and then kept for the
        # rest of this request: it walks every device, and a profile listing is every rule.
        # Lazily rather than here, so that constructing a serializer costs nothing and a
        # caller that builds one before it changes something still gets the change.
        self._drift: Mapping[str, RuleState] | None = None

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
        """Return one device as a list row: what it is, and how much is on it.

        `receiving_endpoint` is here rather than only on the device detail because it is
        what the rule editor needs while a target is being ticked, and the targets step
        holds the device list and nothing else. Reading a detail per candidate would be one
        command per device to fill in a number the list already knows (open item T50).
        """
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
            "receiving_endpoint": None if capabilities is None else capabilities.receiving_endpoint,
        }

    @callback
    def capabilities(self, capabilities: DeviceCapabilities) -> list[dict[str, Any]]:
        """Return one device's controls, with the group each feature is written to."""
        return [self._emitter(emitter) for emitter in capabilities.emitters]

    @staticmethod
    def _emitter(emitter: Emitter) -> dict[str, Any]:
        """Return one control, including why it may need care (`semantics`).

        `endpoint` is where the control drives from, and the rule editor puts it straight
        on the rule it saves: a rule's source endpoint is not something a client can guess,
        because it is 0 on the Z-Wave root and 2 on an Inovelli Blue paddle (open item T50).
        """
        return {
            "emitter_id": emitter.emitter_id,
            "label": emitter.label,
            "endpoint": emitter.endpoint,
            "group_ids": list(emitter.group_ids),
            "actions": {str(feature): group for feature, group in emitter.actions.items()},
            "capacity": emitter.capacity,
            "supports_endpoint_targets": emitter.supports_endpoint_targets,
            "is_lifeline": emitter.is_lifeline,
            "grouping": emitter.grouping,
            "semantics": emitter.semantics,
            # What a hybrid leg on this control would need. The rule editor reads them to
            # decide which of the three checkboxes it may offer at all, so that a user is
            # never shown an opt-in the compiler will refuse (PRD Section 6.7).
            "scene_id": emitter.scene_id,
            "indicator_id": emitter.indicator_id,
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
            "hybrid_legs": [self.hybrid_leg(leg) for leg in compiled.hybrid_legs],
            "warnings": [diagnostic(warning) for warning in compiled.warnings],
            "errors": [diagnostic(error) for error in compiled.errors],
        }

    @callback
    def hybrid_leg(self, leg: HybridLeg) -> dict[str, Any]:
        """Return one HA-executed leg, said as what it is rather than as a link.

        A separate shape from `link` on purpose, and the reason is the product's honesty
        rather than the data: a leg is not written to a device, it is a listener inside
        Home Assistant, and rendering one in the same list as the association entries would
        blur exactly the boundary Decision D3 says has to stay visible. Every screen that
        shows one of these labels it HA-executed, and it can only do that if the payload
        never let it be mistaken for a device write in the first place.
        """
        return {
            "identity": leg.identity,
            "kind": str(leg.kind),
            "rule_id": leg.rule_id,
            "feature": str(leg.feature),
            "emitter_id": leg.emitter_id,
            "source": {
                "identity": leg.source.identity,
                "name": leg.source.name_at_authoring,
                "device_id": self.device_id(leg.source),
            },
            "target": {
                "identity": leg.target.handle.identity,
                "name": leg.target.handle.name_at_authoring,
                "device_id": self.device_id(leg.target.handle),
                "endpoint": leg.target.endpoint,
            },
            "scene_id": leg.scene_id,
            "indicator_id": leg.indicator_id,
        }

    @callback
    def rule(self, rule: Rule) -> dict[str, Any]:
        """Return one rule with what it is currently doing, for the rule list."""
        states = self._drift_state()
        total, in_sync = self._coordinator.rule_link_counts(rule.id)
        return {
            "rule": rule_to_data(rule),
            "state": str(states[rule.id]) if rule.id in states else "unknown",
            "links_total": total,
            "links_in_sync": in_sync,
        }

    def _drift_state(self) -> Mapping[str, RuleState]:
        """Return what every rule of the active profile is doing, asked once per request."""
        if self._drift is None:
            self._drift = self._coordinator.drift_state()
        return self._drift

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

    # Loops (FR-R7).

    @callback
    def loop(self, loop: Loop) -> dict[str, Any]:
        """Return one loop as the devices on it and the rules that join them.

        The rules are what makes this something a user can do anything about: "these three
        devices form a loop" is a fact about a house, and "and it is the Virtual 3-way rule
        that closes it" is a rule they can go and open.
        """
        return {
            "devices": [
                {
                    "identity": device.identity,
                    "name": device.name_at_authoring,
                    "device_id": self.device_id(device),
                }
                for device in loop.devices
            ],
            "rule_ids": list(loop.rule_ids),
            "rule_names": list(loop.rule_names),
        }

    # Swaps.

    @callback
    def replacement(self, replacement: Replacement) -> dict[str, Any]:
        """Return one device that looks replaced, with what could take over from it."""
        return {
            "old": self.device(replacement.old),
            "changed_in_place": replacement.changed_in_place,
            "rule_ids": list(replacement.rule_ids),
            "candidates": [self.device(handle) for handle in replacement.candidates],
        }

    @callback
    def proposal(self, proposal: SwapProposal) -> dict[str, Any]:
        """Return everything one swap would do, before any of it is done.

        The whole of it, every rule before and after: a swap rewrites a user's entire
        configuration in one move, and a summary would be asking them to confirm a count.
        `is_lossy` and `is_applicable` are computed rather than left to the client, because
        the same two answers gate `swap/apply` and a client deriving its own could offer a
        button the backend will refuse.
        """
        return {
            "old": self.device(proposal.old),
            "new": self.device(proposal.new),
            "same_model": proposal.same_model,
            "is_lossy": proposal.is_lossy,
            "is_applicable": proposal.is_applicable,
            "unmapped": list(proposal.unmapped),
            "errors": [diagnostic(error) for error in proposal.errors],
            "mappings": [self._mapping(mapping) for mapping in proposal.mappings],
            "rewrites": [self._rewrite(rewrite) for rewrite in proposal.rewrites],
        }

    @staticmethod
    def _mapping(mapping: EmitterMapping) -> dict[str, Any]:
        """Return one control on the old device and what would take over from it."""
        return {
            "old_emitter_id": mapping.old_emitter_id,
            "new_emitter_id": mapping.new_emitter_id,
            "new_label": mapping.new_label,
            "new_endpoint": mapping.new_endpoint,
            "basis": str(mapping.basis),
            "features_needed": [str(feature) for feature in mapping.features_needed],
            "features_carried": [str(feature) for feature in mapping.features_carried],
        }

    @callback
    def _rewrite(self, rewrite: RuleRewrite) -> dict[str, Any]:
        """Return one rule as it stands and as the swap would leave it."""
        return {
            "rule_id": rewrite.rule_id,
            "name": rewrite.before.name,
            "before": rule_to_data(rewrite.before),
            "after": rule_to_data(rewrite.after),
            "is_lossy": rewrite.is_lossy,
            "losses": [diagnostic(loss) for loss in rewrite.losses],
            "notes": [diagnostic(note) for note in rewrite.notes],
            "errors": [diagnostic(error) for error in rewrite.errors],
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
