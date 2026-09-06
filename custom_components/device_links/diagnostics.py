"""Diagnostics: everything a report needs, and nothing that identifies a network.

A diagnostics file is the artifact somebody pastes into a public issue tracker, under
their own name, from their own house. So what leaves here is decided by one question: does
this describe the fault, or does it describe the network? Node numbers, group numbers,
capacities, rule ids, device names and job outcomes describe the fault and stay. The
Z-Wave home id, a Zigbee IEEE address, a Matter node id and anything shaped like a DSK
describe the network and go (CLAUDE.md Section 3 rule 8).

**Keyed redaction is not enough here, and that is the whole design of this module.**
`async_redact_data` replaces the value of a named key, and the home id is never a value of
its own: it is a substring of `zwave:3538613642:36`, of every link fingerprint built from
that, and of every snapshot entry. So the payload is built first and then scrubbed by
value, everywhere, at any depth, keys included. The keyed helper is still used for the
config entry's own data and options, where a future secret really would be a value under a
name, and using both is not redundancy: they catch different shapes.

**The secrets are collected from everything the dump can contain, not from what answers
now.** A dump taken while the backend is down is exactly the dump a user sends, and at that
moment the device list may be empty while the stored profiles, the job history and the
snapshots are still full of addresses. So handles are gathered from all of them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .models import Backend as BackendId
from .rule_entity import async_handle_of_device
from .serialize import Serializer

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from homeassistant.helpers.device_registry import DeviceEntry

    from . import DeviceLinksConfigEntry, DeviceLinksRuntimeData
    from .models import DeviceHandle, Rule

# What a redacted value is replaced with. One marker for everything, because a dump that
# distinguished between the kinds of secret it removed would be describing them.
REDACTED: Final = "**REDACTED**"

# Keys whose value would be a secret in itself. Nothing writes one today; they are here
# because the config entry's data and options are the one part of this dump that grows
# without this module being touched.
TO_REDACT: Final = {"home_id", "ieee", "dsk", "network_key", "s2_access_control_key", "token"}

# A Z-Wave DSK is eight groups of five digits. Scrubbed by shape rather than by where it
# was expected: nothing stores one, and a device name or a raw backend error is exactly the
# sort of place one would turn up if it ever did.
_DSK: Final = re.compile(r"\b\d{5}(?:-\d{5}){3,7}\b|\b\d{40}\b")

# A device identity, wherever one is embedded in text: `<backend>:<address>`, which is how
# a job scope and a link fingerprint carry one. The backend names are spelled out rather
# than matched loosely, so this cannot start redacting a timestamp.
_IDENTITY: Final = re.compile(rf"(?:{'|'.join(str(backend) for backend in BackendId)}):[^|,\s\"]+")

# A Z-Wave address, by shape rather than by value: `zwave:<home id>:<node id>` as an
# identity, and the same thing inside a link fingerprint. The values above cover this
# already whenever a handle carrying that home id is still reachable, and this covers the
# case where none is: a job history outlives the profile that made it, and its fingerprints
# carry the home id with nothing left to collect it from.
_ZWAVE_HOME_ID: Final = re.compile(r"(?<=zwave:)\d+(?=:)")


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry
) -> dict[str, Any]:
    """Return everything known about this integration, with the network scrubbed out."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    serializer = Serializer(hass, entry)
    state = coordinator.state
    profile = coordinator.active_profile
    payload: dict[str, Any] = {
        "integration": {
            "entry_id": entry.entry_id,
            "version": runtime.version,
            "deployment": _deployment(runtime),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "backends": [
            {
                "backend": str(info.backend_id),
                "upstream": info.upstream_domain,
                "upstream_version": info.upstream_version,
                "available": coordinator.backend_availability.get(info.backend_id, False),
            }
            for info in runtime.backend_info
        ],
        "coordinator": {
            "devices": len(coordinator.devices),
            "unavailable": sorted(
                identity
                for identity in coordinator.devices
                if not coordinator.is_available(identity)
            ),
            "last_error": None if coordinator.last_error is None else dict(coordinator.last_error),
            "pending_links": sorted(coordinator.pending_link_fingerprints()),
        },
        "active_profile": None
        if profile is None
        else {
            "id": profile.id,
            "name": profile.name,
            "rules": _rule_details(runtime, profile.rules),
        },
        "profiles": [
            serializer.profile(candidate, active_profile_id=state.active_profile_id)
            for candidate in state.profiles
        ],
        "observed": [
            _observed_device(hass, entry, handle)
            for _identity, handle in sorted(coordinator.devices.items())
        ],
        "ignored_unmanaged": sorted(state.ignored_unmanaged),
        "applied_rules": sorted(state.applied_rule_ids),
        "jobs": [serializer.job(job) for job in state.jobs],
        "snapshots": [serializer.snapshot(snapshot) for snapshot in state.snapshots],
    }
    scrubbed: dict[str, Any] = _scrubbed(payload, _secrets(runtime))
    return scrubbed


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return everything known about one device, with the network scrubbed out.

    A device Device Links does not adapt (its own hub, or an upstream device no rule
    names) answers with an empty dump rather than an error: "there is nothing about this
    device" is a useful answer to somebody who opened the page expecting one.
    """
    runtime = entry.runtime_data
    handle = async_handle_of_device(hass, entry, device.id)
    if handle is None:
        return {"device": None, "emitters": [], "links": [], "rules": [], "job_results": []}
    serializer = Serializer(hass, entry)
    coordinator = runtime.coordinator
    capabilities = coordinator.capabilities_for(handle.identity)
    observed = coordinator.observed_for(handle)
    profile = coordinator.active_profile
    rules = [] if profile is None else [rule for rule in profile.rules if _touches(rule, handle)]
    fingerprints = {link.fingerprint for link in (observed.links if observed else ())} | {
        link.fingerprint
        for rule in rules
        if (compiled := coordinator.compiled_for(rule.id)) is not None
        for link in compiled.links
    }
    payload: dict[str, Any] = {
        "device": serializer.device(handle),
        "emitters": [] if capabilities is None else serializer.capabilities(capabilities),
        "links": [] if observed is None else [serializer.link(link) for link in observed.links],
        "settings": {} if observed is None else dict(observed.settings),
        "deep_verified": observed is not None and observed.deep_verified,
        "rules": _rule_details(runtime, rules),
        "job_results": [
            {"job_id": job.id, "created_at": job.created_at, **_result(result)}
            for job in coordinator.state.jobs
            for result in job.results
            if result.fingerprint in fingerprints
        ],
    }
    scrubbed: dict[str, Any] = _scrubbed(payload, _secrets(runtime))
    return scrubbed


def _deployment(runtime: DeviceLinksRuntimeData) -> dict[str, Any] | None:
    """Return what the dev deploy tool recorded, or None on a normal install."""
    deployment = runtime.deployment
    if deployment is None:
        return None
    return {
        "commit": deployment.commit,
        "branch": deployment.branch,
        "deployed_at": deployment.deployed_at,
        "previous_commit": deployment.previous_commit,
        "changed_files": deployment.changed_files,
    }


def _rule_details(runtime: DeviceLinksRuntimeData, rules: Sequence[Rule]) -> list[dict[str, Any]]:
    """Return these rules with what each wants and what is really on the devices.

    The two things every rule is judged against, the drift states and the fingerprints the
    devices are holding, are worked out once for the whole list rather than once per rule:
    both walk every device, and a house with forty rules would otherwise walk them forty
    times to produce one file.
    """
    coordinator = runtime.coordinator
    present = _present_fingerprints(runtime)
    states = coordinator.drift_state()
    return [_rule_detail(runtime, rule, present, states) for rule in rules]


def _rule_detail(
    runtime: DeviceLinksRuntimeData,
    rule: Rule,
    present: set[str],
    states: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one rule with what it wants and what is really on the devices.

    Per link rather than per rule, because "three of four" is the difference between a
    fault in one group and a device that has stopped listening, and a report that only
    said `drift` makes the person reading it ask for this list next.
    """
    compiled = runtime.coordinator.compiled_for(rule.id)
    return {
        "id": rule.id,
        "name": rule.name,
        "template": str(rule.template),
        "backend": str(rule.backend),
        "enabled": rule.enabled,
        "state": str(states.get(rule.id, "unknown")),
        "source": rule.source.device.identity,
        "targets": [target.device.identity for target in rule.targets],
        "warnings": []
        if compiled is None
        else [warn.translation_key for warn in compiled.warnings],
        "errors": [] if compiled is None else [error.translation_key for error in compiled.errors],
        "links": []
        if compiled is None
        else [
            {
                "fingerprint": link.fingerprint,
                "group": link.emitter_group,
                "feature": str(link.feature),
                "target": link.target.handle.identity,
                "desired": rule.enabled,
                "observed": link.fingerprint in present,
            }
            for link in compiled.links
        ],
    }


def _present_fingerprints(runtime: DeviceLinksRuntimeData) -> set[str]:
    """Return the fingerprint of every link every readable device is currently holding."""
    coordinator = runtime.coordinator
    present: set[str] = set()
    for identity, handle in coordinator.devices.items():
        observed = coordinator.observed_for(handle)
        if observed is not None and coordinator.is_available(identity):
            present.update(link.fingerprint for link in observed.links)
    return present


def _observed_device(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, handle: DeviceHandle
) -> dict[str, Any]:
    """Return what one device is holding, as it was last read."""
    coordinator = entry.runtime_data.coordinator
    serializer = Serializer(hass, entry)
    observed = coordinator.observed_for(handle)
    return {
        "identity": handle.identity,
        "name": handle.name_at_authoring,
        "backend": str(handle.backend),
        "available": coordinator.is_available(handle.identity),
        "deep_verified": observed is not None and observed.deep_verified,
        "settings": {} if observed is None else dict(observed.settings),
        "links": [] if observed is None else [serializer.link(link) for link in observed.links],
    }


def _result(result: Any) -> dict[str, Any]:
    """Return one recorded link outcome."""
    return {
        "fingerprint": result.fingerprint,
        "status": result.status,
        "reason": result.reason,
    }


def _touches(rule: Rule, handle: DeviceHandle) -> bool:
    """Say whether this rule is about this device, at either end of it."""
    return handle.identity in {
        rule.source.device.identity,
        *(target.device.identity for target in rule.targets),
    }


# --------------------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------------------


def _secrets(runtime: DeviceLinksRuntimeData) -> list[str]:
    """Return every string that identifies this network, longest first.

    Longest first so that a value which contains another (a home id inside a longer
    address) cannot be half-replaced and leave the rest legible.
    """
    found: set[str] = set()
    for identity in _identities(runtime):
        backend, _, protocol_id = identity.partition(":")
        found.add(protocol_id.partition(":")[0] if backend == BackendId.ZWAVE else protocol_id)
    for handle in _handles(runtime):
        if handle.backend is BackendId.ZWAVE:
            # `<home id>:<node id>`: the home id names the network and the node id names a
            # device on it, and only the first is a secret. Keeping the node number is what
            # makes the rest of the dump worth reading.
            home_id = handle.protocol_id.partition(":")[0]
            if home_id:
                found.add(home_id)
        elif handle.protocol_id:
            # An IEEE address and a Matter node id are the whole address and identify a
            # device globally rather than within a network, so all of it goes.
            found.add(handle.protocol_id)
    return sorted(found - {""}, key=len, reverse=True)


def _identities(runtime: DeviceLinksRuntimeData) -> Iterator[str]:
    """Yield every device identity the dump can carry that no handle accounts for.

    A job summary outlives the rule and the device it was about: its scope names device
    identities and every result carries a fingerprint built from one, and neither is
    reachable from a handle once the profile that made the job is deleted. A snapshot names
    the devices it covers for the same reason it exists, which includes ones that held
    nothing. Read out by shape, so this keeps working for a protocol whose adapter does not
    exist yet: an identity is a backend name and an address, and both halves are known.
    """
    coordinator = runtime.coordinator
    for job in coordinator.state.jobs:
        yield from _IDENTITY.findall(job.scope)
        for result in job.results:
            yield from _IDENTITY.findall(result.fingerprint)
    for snapshot in coordinator.state.snapshots:
        for device in snapshot.devices:
            yield from _IDENTITY.findall(device)


def _handles(runtime: DeviceLinksRuntimeData) -> Iterator[DeviceHandle]:
    """Yield every device handle anything in a dump could carry.

    Not only the devices that answer now: a dump taken while a backend is down still holds
    the stored profiles, the job history and the snapshots, and those are full of
    addresses. Collecting from what answers would redact exactly nothing in the one dump
    that is most likely to be sent.
    """
    coordinator = runtime.coordinator
    for handle in coordinator.devices.values():
        yield handle
        observed = coordinator.observed_for(handle)
        if observed is not None:
            yield from (link.target.handle for link in observed.links)
    for profile in coordinator.state.profiles:
        for rule in profile.rules:
            yield rule.source.device
            yield from (target.device for target in rule.targets)
    for snapshot in coordinator.state.snapshots:
        for link in snapshot.links:
            yield link.source
            yield link.target.handle


def _scrubbed(value: Any, secrets: Sequence[str]) -> Any:
    """Return this payload with every secret replaced, at any depth, keys included.

    Keys as well as values, because an identity is a perfectly natural dictionary key and
    a redaction that only looked at values would publish the whole list of them.
    """
    if isinstance(value, str):
        return _scrubbed_text(value, secrets)
    if isinstance(value, dict):
        return {_scrubbed(key, secrets): _scrubbed(item, secrets) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrubbed(item, secrets) for item in value]
    return value


def _scrubbed_text(value: str, secrets: Sequence[str]) -> str:
    """Return one string with every secret and anything DSK-shaped taken out of it."""
    for secret in secrets:
        value = value.replace(secret, REDACTED)
    return _DSK.sub(REDACTED, _ZWAVE_HOME_ID.sub(REDACTED, value))
