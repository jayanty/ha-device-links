"""The services: everything the panel can do, callable from an automation.

Registered in `async_setup` rather than in `async_setup_entry` (quality-scale rule
action-setup), so an automation that calls one validates at load time instead of failing
while the integration is still retrying its setup. A service called before the entry is
loaded says so, translated, which is the state a user can act on.

**Two error types, and the difference is whose fault it is.** Input this integration
cannot act on (an unknown rule, a profile that is not active, YAML that does not parse) is
a `ServiceValidationError`: nothing was attempted and nothing changed. A failure that came
back from a radio or from the job runner is a `HomeAssistantError`: something was
attempted and could not be done. Both carry a translation key, so both are sentences in
the user's own language rather than a traceback in the log (`action-exceptions`,
`exception-translations`).

**`set_rule_enabled` goes through the rate limiter, not through the runner.** This is the
caller an automation loop would actually use, and a rule toggle rewrites an association
table in device NVM, which has a finite write endurance. Reaching the runner directly here
would reintroduce exactly the bypass E35 exists to prevent, for the one caller that can be
run in a loop.

**`import_profile` never writes to a device.** It changes what should be true and hands
back the plan that implies. A file naming devices this network does not have is refused
whole (E38), naming every device and every rule that wants one: an import that quietly
dropped the rules it could not resolve would report success and leave a house half
described, and those are exactly the rules somebody goes looking for later.

**The raw services are not registered unless the option is on** (Decision D14). They write
to an association group directly, with no rule and no plan behind them, so they are expert
tools that are absent until somebody asks for them, and they still refuse to touch a
lifeline when they are present (CLAUDE.md Section 3 rule 4).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .backends.base import LinkResult, LinkResultStatus
from .const import DOMAIN, OPTION_ENABLE_RAW_SERVICES
from .coordinator import PlanScope
from .models import Backend as BackendId
from .models import DeviceHandle, Emitter, Feature, Link, LinkTarget, Plan, Profile
from .rule_entity import async_handle_of_device
from .yaml_io import ProfileFormatError, dump_profile, parse_profile

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from . import DeviceLinksConfigEntry, DeviceLinksRuntimeData
    from .coordinator import DeviceLinksCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_APPLY: Final = "apply"
SERVICE_VERIFY: Final = "verify"
SERVICE_SET_RULE_ENABLED: Final = "set_rule_enabled"
SERVICE_ACTIVATE_PROFILE: Final = "activate_profile"
SERVICE_EXPORT_PROFILE: Final = "export_profile"
SERVICE_IMPORT_PROFILE: Final = "import_profile"

SERVICE_ZWAVE_GET_ASSOCIATIONS: Final = "zwave_get_associations"
SERVICE_ZWAVE_ADD_ASSOCIATION: Final = "zwave_add_association"
SERVICE_ZWAVE_REMOVE_ASSOCIATION: Final = "zwave_remove_association"

ATTR_PROFILE_ID: Final = "profile_id"
ATTR_RULE_IDS: Final = "rule_ids"
ATTR_RULE_ID: Final = "rule_id"
ATTR_ENABLED: Final = "enabled"
ATTR_REMOVE_UNMANAGED: Final = "remove_unmanaged"
ATTR_APPLY: Final = "apply"
ATTR_YAML: Final = "yaml"
ATTR_GROUP: Final = "group"
ATTR_TARGET_DEVICE_ID: Final = "target_device_id"
ATTR_TARGET_ENDPOINT: Final = "target_endpoint"

# The scope fields every service that works on part of the network shares. One definition,
# so `apply` and `verify` cannot drift into meaning different things by the same names.
_SCOPE_FIELDS: Final = {
    vol.Optional(ATTR_PROFILE_ID): cv.string,
    vol.Optional(ATTR_RULE_IDS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
}

APPLY_SCHEMA: Final = vol.Schema(
    {
        **_SCOPE_FIELDS,
        # Fingerprints, not a boolean. CLAUDE.md Section 3 rule 5 makes removing a link
        # nobody here created a per-link decision, and a boolean that meant "remove every
        # unmanaged link" would put a whole-network deletion behind one word in a YAML
        # automation. See docs/open-items.md for the amendment this owes PRD FR-E3.
        vol.Optional(ATTR_REMOVE_UNMANAGED): vol.All(cv.ensure_list, [cv.string]),
    }
)
VERIFY_SCHEMA: Final = vol.Schema(dict(_SCOPE_FIELDS))
SET_RULE_ENABLED_SCHEMA: Final = vol.Schema(
    {vol.Required(ATTR_RULE_ID): cv.string, vol.Required(ATTR_ENABLED): cv.boolean}
)
ACTIVATE_PROFILE_SCHEMA: Final = vol.Schema(
    {vol.Required(ATTR_PROFILE_ID): cv.string, vol.Optional(ATTR_APPLY, default=False): cv.boolean}
)
EXPORT_PROFILE_SCHEMA: Final = vol.Schema({vol.Optional(ATTR_PROFILE_ID): cv.string})
IMPORT_PROFILE_SCHEMA: Final = vol.Schema({vol.Required(ATTR_YAML): cv.string})

GET_ASSOCIATIONS_SCHEMA: Final = vol.Schema({vol.Required(CONF_DEVICE_ID): cv.string})
ASSOCIATION_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(ATTR_GROUP): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required(ATTR_TARGET_DEVICE_ID): cv.string,
        vol.Optional(ATTR_TARGET_ENDPOINT): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)

# Every service and the schema it validates against, which is also what the test comparing
# this module with `services.yaml` walks. One mapping rather than a list of registrations,
# so a service cannot be added in one place and forgotten in the other.
SERVICE_SCHEMAS: Final[Mapping[str, vol.Schema]] = {
    SERVICE_APPLY: APPLY_SCHEMA,
    SERVICE_VERIFY: VERIFY_SCHEMA,
    SERVICE_SET_RULE_ENABLED: SET_RULE_ENABLED_SCHEMA,
    SERVICE_ACTIVATE_PROFILE: ACTIVATE_PROFILE_SCHEMA,
    SERVICE_EXPORT_PROFILE: EXPORT_PROFILE_SCHEMA,
    SERVICE_IMPORT_PROFILE: IMPORT_PROFILE_SCHEMA,
    SERVICE_ZWAVE_GET_ASSOCIATIONS: GET_ASSOCIATIONS_SCHEMA,
    SERVICE_ZWAVE_ADD_ASSOCIATION: ASSOCIATION_SCHEMA,
    SERVICE_ZWAVE_REMOVE_ASSOCIATION: ASSOCIATION_SCHEMA,
}

# What is always there, and what is there only when the option is on (Decision D14).
RAW_SERVICES: Final = (
    SERVICE_ZWAVE_GET_ASSOCIATIONS,
    SERVICE_ZWAVE_ADD_ASSOCIATION,
    SERVICE_ZWAVE_REMOVE_ASSOCIATION,
)
CORE_SERVICES: Final = tuple(service for service in SERVICE_SCHEMAS if service not in RAW_SERVICES)

# What a job that had nothing to do reports, so a caller can tell it from a job that ran.
NOTHING_TO_DO: Final = "nothing_to_do"

# Group 1 is the lifeline on every Z-Wave device ever certified.
LIFELINE_GROUP: Final = "1"

# The order a raw call's feature is chosen in, plainest first. Fixed rather than arbitrary
# so the same call always produces the same fingerprint.
_FEATURE_ORDER: Final = (
    Feature.ON_OFF,
    Feature.LEVEL_SET,
    Feature.LEVEL_HOLD,
    Feature.SCENE,
    Feature.STATUS_REPORT,
    Feature.COLOR,
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services that exist whether or not an entry is loaded."""
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY, _async_apply, APPLY_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_VERIFY, _async_verify, VERIFY_SCHEMA, SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_RULE_ENABLED, _async_set_rule_enabled, SET_RULE_ENABLED_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVATE_PROFILE,
        _async_activate_profile,
        ACTIVATE_PROFILE_SCHEMA,
        SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_PROFILE,
        _async_export_profile,
        EXPORT_PROFILE_SCHEMA,
        SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_PROFILE,
        _async_import_profile,
        IMPORT_PROFILE_SCHEMA,
        SupportsResponse.ONLY,
    )


@callback
def async_setup_raw_services(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> None:
    """Register the expert tools, if this entry's option asks for them (Decision D14).

    Per entry rather than in `async_setup`, because the option lives on the entry and the
    point of the decision is that these do not exist until somebody turns them on. An
    entry update listener reloads the entry, so the switch takes effect without a restart.
    """
    if not entry.options.get(OPTION_ENABLE_RAW_SERVICES, False):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_ZWAVE_GET_ASSOCIATIONS,
        _async_zwave_get_associations,
        GET_ASSOCIATIONS_SCHEMA,
        SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ZWAVE_ADD_ASSOCIATION,
        _async_zwave_add_association,
        ASSOCIATION_SCHEMA,
        SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ZWAVE_REMOVE_ASSOCIATION,
        _async_zwave_remove_association,
        ASSOCIATION_SCHEMA,
        SupportsResponse.OPTIONAL,
    )
    _LOGGER.info(
        "the raw Z-Wave association services are registered because the option asking for "
        "them is on; they write to a group directly, with no rule and no plan behind them"
    )


@callback
def async_unload_raw_services(hass: HomeAssistant) -> None:
    """Take the expert tools away with the entry that asked for them."""
    for service in RAW_SERVICES:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


# --------------------------------------------------------------------------------------
# What every handler starts with
# --------------------------------------------------------------------------------------


def _runtime(hass: HomeAssistant) -> tuple[DeviceLinksConfigEntry, DeviceLinksRuntimeData]:
    """Return the loaded entry and its runtime, or say that there is none (`action-setup`)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            "Device Links has no loaded config entry, so there is nothing to act on",
            translation_domain=DOMAIN,
            translation_key="not_loaded",
        )
    entry: DeviceLinksConfigEntry = entries[0]
    return entry, entry.runtime_data


def _validated_scope(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, call: ServiceCall
) -> PlanScope:
    """Turn a call's scope fields into a plan scope, refusing anything that names nothing.

    Everything is checked before anything is planned, so a call that names one rule that
    exists and one that does not changes nothing at all. Silently ignoring the unknown
    half would apply half of what an automation asked for and report success.
    """
    coordinator = entry.runtime_data.coordinator
    profile = coordinator.active_profile
    profile_id = call.data.get(ATTR_PROFILE_ID)
    if profile_id is not None:
        _known_profile(coordinator, profile_id)
        if profile is None or profile.id != profile_id:
            raise ServiceValidationError(
                f"profile {profile_id} is not the active one",
                translation_domain=DOMAIN,
                translation_key="profile_not_active",
                translation_placeholders={"profile": profile_id},
            )
    rule_ids = call.data.get(ATTR_RULE_IDS, [])
    known = {rule.id for rule in profile.rules} if profile is not None else set()
    for rule_id in rule_ids:
        if rule_id not in known:
            raise _unknown_rule(rule_id)
    identities = {
        _handle_of_device(hass, entry, device_id).identity
        for device_id in call.data.get(CONF_DEVICE_ID, [])
    }
    return PlanScope(rule_ids=frozenset(rule_ids), device_identities=frozenset(identities))


def _known_profile(coordinator: DeviceLinksCoordinator, profile_id: str) -> Profile:
    """Return the stored profile with this id, or say that there is none."""
    profile = next(
        (candidate for candidate in coordinator.state.profiles if candidate.id == profile_id),
        None,
    )
    if profile is None:
        raise ServiceValidationError(
            f"no stored profile has the id {profile_id}",
            translation_domain=DOMAIN,
            translation_key="unknown_profile",
            translation_placeholders={"profile": profile_id},
        )
    return profile


def _unknown_rule(rule_id: str) -> ServiceValidationError:
    """Return the refusal for a rule id no rule of the active profile carries."""
    return ServiceValidationError(
        f"no rule of the active profile has the id {rule_id}",
        translation_domain=DOMAIN,
        translation_key="unknown_rule",
        translation_placeholders={"rule": rule_id},
    )


def _handle_of_device(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, device_id: str
) -> DeviceHandle:
    """Return the device handle behind a Home Assistant device id, or refuse.

    Resolved through the device registry rather than taken from the caller as a node id,
    which is PRD Section 10: a service takes a reference the user can see in the UI, and
    protocol addresses are accepted only by the gated raw services, and even there only
    after this lookup has turned them into a device this integration already knows.
    """
    handle = async_handle_of_device(hass, entry, device_id)
    if handle is None:
        raise ServiceValidationError(
            f"no device Device Links can see has the Home Assistant device id {device_id}",
            translation_domain=DOMAIN,
            translation_key="unknown_device",
            translation_placeholders={"device": device_id},
        )
    return handle


# --------------------------------------------------------------------------------------
# apply and verify
# --------------------------------------------------------------------------------------


async def _async_apply(call: ServiceCall) -> ServiceResponse:
    """Make the devices in scope match the active profile."""
    entry, runtime = _runtime(call.hass)
    scope = _validated_scope(call.hass, entry, call)
    remove_unmanaged = frozenset(call.data.get(ATTR_REMOVE_UNMANAGED, []))
    plan = await runtime.coordinator.async_plan(scope, remove_unmanaged=remove_unmanaged)
    if plan.is_empty:
        _LOGGER.info("apply was called with nothing to do: the devices already match")
        return {"job_id": None, "status": NOTHING_TO_DO, "results": {}}
    report = await runtime.runner.async_apply(plan, scope=scope, remove_unmanaged=remove_unmanaged)
    return {
        "job_id": report.id,
        "status": str(report.status),
        "results": dict(Counter(str(result.outcome) for result in report.results)),
    }


async def _async_verify(call: ServiceCall) -> ServiceResponse:
    """Re-read the devices in scope from the devices themselves, and write nothing."""
    entry, runtime = _runtime(call.hass)
    scope = _validated_scope(call.hass, entry, call)
    coordinator = runtime.coordinator
    identities = sorted(coordinator.identities_in_scope(scope))
    for identity in identities:
        handle = coordinator.handle_for(identity)
        if handle is not None:
            await coordinator.async_refresh(handle, deep=True)
    states = coordinator.drift_state()
    if scope.rule_ids:
        states = {rule_id: state for rule_id, state in states.items() if rule_id in scope.rule_ids}
    return {
        "devices": len(identities),
        "rules": {rule_id: str(state) for rule_id, state in sorted(states.items())},
    }


# --------------------------------------------------------------------------------------
# Rules and profiles
# --------------------------------------------------------------------------------------


async def _async_set_rule_enabled(call: ServiceCall) -> None:
    """Enable or disable one rule, subject to the shared rate limit (E35)."""
    _entry, runtime = _runtime(call.hass)
    rule_id: str = call.data[ATTR_RULE_ID]
    profile = runtime.coordinator.active_profile
    if profile is None or not any(rule.id == rule_id for rule in profile.rules):
        raise _unknown_rule(rule_id)
    await runtime.toggles.async_request(rule_id, enabled=call.data[ATTR_ENABLED])


async def _async_activate_profile(call: ServiceCall) -> ServiceResponse:
    """Make one profile the active one, and apply it only when asked to (FR-E1)."""
    _entry, runtime = _runtime(call.hass)
    profile_id: str = call.data[ATTR_PROFILE_ID]
    _known_profile(runtime.coordinator, profile_id)
    runtime.coordinator.async_activate_profile(profile_id)
    plan = await runtime.coordinator.async_plan()
    runtime.pending_plan = plan
    job_id: str | None = None
    if call.data[ATTR_APPLY] and not plan.is_empty:
        job_id = (await runtime.runner.async_apply(plan)).id
    return {"profile_id": profile_id, "job_id": job_id, "plan": _plan_summary(plan)}


async def _async_export_profile(call: ServiceCall) -> ServiceResponse:
    """Return one profile as the YAML text a user keeps in version control (FR-P2)."""
    _entry, runtime = _runtime(call.hass)
    profile_id = call.data.get(ATTR_PROFILE_ID)
    if profile_id is None:
        profile = runtime.coordinator.active_profile
        if profile is None:
            raise ServiceValidationError(
                "no profile is active, so there is nothing to export",
                translation_domain=DOMAIN,
                translation_key="no_active_profile",
            )
    else:
        profile = _known_profile(runtime.coordinator, profile_id)
    return {"profile_id": profile.id, "name": profile.name, "yaml": dump_profile(profile)}


async def _async_import_profile(call: ServiceCall) -> ServiceResponse:
    """Store the profile this YAML describes, and write to nothing (FR-P2, E38)."""
    _entry, runtime = _runtime(call.hass)
    coordinator = runtime.coordinator
    try:
        profile = parse_profile(call.data[ATTR_YAML])
    except ProfileFormatError as error:
        raise ServiceValidationError(
            f"this profile could not be read: {error}",
            translation_domain=DOMAIN,
            translation_key="profile_invalid",
            translation_placeholders={"error": str(error)},
        ) from error
    _refuse_unknown_devices(coordinator, profile)

    stored = coordinator.state.profiles
    profiles = (
        tuple(profile if candidate.id == profile.id else candidate for candidate in stored)
        if any(candidate.id == profile.id for candidate in stored)
        else (*stored, profile)
    )
    coordinator.async_update_state(replace(coordinator.state, profiles=profiles))
    is_active = coordinator.state.active_profile_id == profile.id
    plan = await coordinator.async_plan() if is_active else None
    if plan is not None:
        runtime.pending_plan = plan
    _LOGGER.info(
        "profile %s was imported with %s rule(s); nothing has been written to a device",
        profile.id,
        len(profile.rules),
    )
    return {
        "profile_id": profile.id,
        "name": profile.name,
        "rules": len(profile.rules),
        "is_active": is_active,
        "plan": None if plan is None else _plan_summary(plan),
    }


def _refuse_unknown_devices(coordinator: DeviceLinksCoordinator, profile: Profile) -> None:
    """Refuse an import naming devices this network does not have (E38).

    Whole, not partially. The rules that could not be resolved are the ones somebody would
    go looking for later, so an import that kept the rest would report success about a
    profile that no longer says what the file says.
    """
    missing: dict[str, set[str]] = {}
    for rule in profile.rules:
        for handle in (rule.source.device, *(target.device for target in rule.targets)):
            if coordinator.handle_for(handle.identity) is None:
                missing.setdefault(handle.identity, set()).add(rule.id)
    if not missing:
        return
    rules = sorted({rule_id for rule_ids in missing.values() for rule_id in rule_ids})
    raise ServiceValidationError(
        f"this profile names devices that are not on this network: {sorted(missing)}",
        translation_domain=DOMAIN,
        translation_key="import_unknown_devices",
        translation_placeholders={
            "devices": ", ".join(sorted(missing)),
            "rules": ", ".join(rules),
        },
    )


def _plan_summary(plan: Plan) -> dict[str, Any]:
    """Return the counts a caller needs to decide whether to apply this plan."""
    counts = Counter(str(item.op) for item in plan.items)
    return {
        "token": plan.token,
        "adds": counts.get("add", 0),
        "removes": counts.get("remove", 0),
        "blocked": counts.get("blocked", 0),
        "unchanged": plan.unchanged_count,
        "unmanaged": len(plan.unmanaged),
    }


# --------------------------------------------------------------------------------------
# The raw services (Decision D14)
# --------------------------------------------------------------------------------------


async def _async_zwave_get_associations(call: ServiceCall) -> ServiceResponse:
    """Return every association group of one device and what is in it, reading nothing new."""
    entry, runtime = _runtime(call.hass)
    handle = _zwave_handle(call.hass, entry, call.data[CONF_DEVICE_ID])
    coordinator = runtime.coordinator
    observed = coordinator.observed_for(handle)
    capabilities = coordinator.capabilities_for(handle.identity)
    groups: dict[str, dict[str, Any]] = {}
    if capabilities is not None:
        for emitter in capabilities.emitters:
            for group_id in emitter.group_ids:
                groups[group_id] = {
                    "group": group_id,
                    "label": emitter.label,
                    "capacity": emitter.capacity,
                    "is_lifeline": emitter.is_lifeline,
                    "entries": [],
                }
    for link in observed.links if observed is not None else ():
        group = groups.setdefault(
            link.emitter_group,
            {
                "group": link.emitter_group,
                "label": None,
                "capacity": None,
                "is_lifeline": link.is_system,
                "entries": [],
            },
        )
        group["is_lifeline"] = group["is_lifeline"] or link.is_system
        group["entries"].append(
            {
                "node_id": _node_id_of(link.target.handle),
                "endpoint": link.target.endpoint,
                "name": link.target.handle.name_at_authoring,
                "managed_by": link.managed_by,
            }
        )
    return {
        "device": handle.identity,
        "name": handle.name_at_authoring,
        "available": coordinator.is_available(handle.identity),
        "groups": [groups[key] for key in sorted(groups, key=int)],
    }


async def _async_zwave_add_association(call: ServiceCall) -> ServiceResponse:
    """Add one association entry directly, with no rule and no plan behind it."""
    return await _async_raw_write(call, adding=True)


async def _async_zwave_remove_association(call: ServiceCall) -> ServiceResponse:
    """Remove one association entry directly, with no rule and no plan behind it."""
    return await _async_raw_write(call, adding=False)


async def _async_raw_write(call: ServiceCall, *, adding: bool) -> ServiceResponse:
    """Write one association entry, after the refusals that are never negotiable."""
    entry, runtime = _runtime(call.hass)
    hass = call.hass
    source = _zwave_handle(hass, entry, call.data[CONF_DEVICE_ID])
    target = _zwave_handle(hass, entry, call.data[ATTR_TARGET_DEVICE_ID])
    group = str(call.data[ATTR_GROUP])
    link = _raw_link(
        runtime.coordinator, source, target, group, call.data.get(ATTR_TARGET_ENDPOINT)
    )
    backend = runtime.coordinator.backend_for(source)
    if backend is None:
        raise HomeAssistantError(
            "the Z-Wave backend is not loaded, so nothing can be written",
            translation_domain=DOMAIN,
            translation_key="backend_not_loaded",
            translation_placeholders={
                "backend": str(BackendId.ZWAVE),
                "device": source.name_at_authoring,
                "target": target.name_at_authoring,
                "group": group,
            },
        )
    result = await (backend.async_add_link(link) if adding else backend.async_remove_link(link))
    _raise_for(result, link)
    await runtime.coordinator.async_refresh(source)
    _LOGGER.info(
        "raw association %s: %s group %s %s %s",
        "add" if adding else "remove",
        source.identity,
        group,
        "->" if adding else "-x",
        target.identity,
    )
    return {"status": str(result.status), "fingerprint": link.fingerprint}


def _zwave_handle(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, device_id: str
) -> DeviceHandle:
    """Return a Z-Wave device handle for this device id, and refuse anything else."""
    handle = _handle_of_device(hass, entry, device_id)
    if handle.backend is not BackendId.ZWAVE:
        raise ServiceValidationError(
            f"{handle.identity} is not a Z-Wave device",
            translation_domain=DOMAIN,
            translation_key="not_a_zwave_device",
            translation_placeholders={"device": handle.name_at_authoring},
        )
    return handle


def _raw_link(
    coordinator: DeviceLinksCoordinator,
    source: DeviceHandle,
    target: DeviceHandle,
    group: str,
    endpoint: int | None,
) -> Link:
    """Return the link one raw call is about, refusing the groups that are never writable.

    The lifeline is refused here as well as in the adapter, deliberately: this is the one
    caller that names a group number directly, so it is the one place a typo can aim at
    group 1, and the guard that only exists further down is a guard that has to be reached
    to work (CLAUDE.md Section 3 rule 4).

    A group no control of the device claims is refused too. The feature a link carries is
    what the group issues, so a group this integration cannot describe is one it cannot
    write a meaningful entry into, and inventing a feature for it would put a link in the
    observed model that says something the device does not do. Deliberately not the
    planner's `unknown_group`, which is about a group the device does not report at all:
    the two are different situations and a shared message could only describe both by
    describing neither.
    """
    capabilities = coordinator.capabilities_for(source.identity)
    emitters = () if capabilities is None else capabilities.emitters
    observed = coordinator.observed_for(source)
    system = any(
        link.is_system
        for link in (observed.links if observed is not None else ())
        if link.emitter_group == group
    )
    if (
        system
        or group == LIFELINE_GROUP
        or any(emitter.is_lifeline for emitter in emitters if group in emitter.group_ids)
    ):
        raise ServiceValidationError(
            f"group {group} of {source.identity} is the lifeline",
            translation_domain=DOMAIN,
            translation_key="lifeline_is_protected",
            translation_placeholders={
                "device": source.name_at_authoring,
                "target": target.name_at_authoring,
                "group": group,
            },
        )
    feature = _feature_of_group(emitters, group)
    if feature is None:
        raise ServiceValidationError(
            f"no control of {source.identity} uses association group {group}",
            translation_domain=DOMAIN,
            translation_key="group_not_offered",
            translation_placeholders={
                "device": source.name_at_authoring,
                "group": group,
                "groups": ", ".join(
                    sorted(
                        {group_id for emitter in emitters for group_id in emitter.group_ids},
                        key=int,
                    )
                ),
            },
        )
    try:
        return Link(
            backend=BackendId.ZWAVE,
            source=source,
            source_endpoint=0,
            emitter_id=f"g{group}",
            emitter_group=group,
            target=LinkTarget(handle=target, endpoint=endpoint),
            feature=feature,
        )
    except ValueError as error:
        # A device cannot be in its own association group (CLAUDE.md Section 10). The link
        # type refuses to exist, which is the right place for it, and this turns that into
        # something a caller can read.
        raise ServiceValidationError(
            str(error),
            translation_domain=DOMAIN,
            translation_key="self_association",
            translation_placeholders={
                "device": source.name_at_authoring,
                "target": target.name_at_authoring,
                "group": group,
            },
        ) from error


def _feature_of_group(emitters: Iterable[Emitter], group: str) -> Feature | None:
    """Return a feature this group carries, preferring the plainest one.

    On/off first, because a group that carries it is a group whose entries mean "this
    control switches that device", which is what a raw caller almost always wants. The
    order is fixed rather than arbitrary so the same call always produces the same
    fingerprint.
    """
    carried = {
        feature
        for emitter in emitters
        if group in emitter.group_ids
        for feature, group_id in emitter.actions.items()
        if group_id == group
    }
    return next((feature for feature in _FEATURE_ORDER if feature in carried), None)


def _raise_for(result: LinkResult, link: Link) -> None:
    """Turn a refusal or a failure from the radio into a translated error.

    A refusal always carries its reason (`LinkResult` refuses to be built without one), so
    the fallback below is for a backend that got that wrong. It still says which write
    failed, because a translated message with a hole where the device name should be is
    the one thing worse than an untranslated one.
    """
    if result.status not in {LinkResultStatus.BLOCKED, LinkResultStatus.FAILED}:
        return
    reason = result.reason
    raise HomeAssistantError(
        f"the device did not accept this: {result.raw_error or result.status}",
        translation_domain=DOMAIN,
        translation_key="link_write_failed" if reason is None else reason.translation_key,
        translation_placeholders=dict(reason.placeholders)
        if reason is not None
        else {
            "device": link.source.name_at_authoring,
            "target": link.target.handle.name_at_authoring,
            "group": link.emitter_group,
        },
    )


def _node_id_of(handle: DeviceHandle) -> int | None:
    """Return the node id in a Z-Wave protocol address, for the raw read's answer."""
    _home_id, _separator, node_id = handle.protocol_id.partition(":")
    return int(node_id) if node_id.isdigit() else None


__all__ = [
    "CORE_SERVICES",
    "RAW_SERVICES",
    "SERVICE_SCHEMAS",
    "async_setup_raw_services",
    "async_setup_services",
    "async_unload_raw_services",
]
