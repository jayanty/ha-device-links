"""The admin WebSocket API: everything the panel does, and therefore everything scriptable.

Phase 1E's panel is the only client, so the shape of what is answered here is the shape of
the panel. That cuts both ways: PRD Section 17.2 relies on these commands being callable
through MCP as well, so a remote debugging session can see exactly the plan a user would
see without a browser.

**Every command requires an admin user** (`@websocket_api.require_admin`, E32). After this
phase a WebSocket message can drive the executor into a real write on somebody's house, so
the gate is not a formality and is not applied per command by hand: `_command` is the only
way a handler is registered here, and it applies the gate.

**Errors are translated, always.** Home Assistant turns a `HomeAssistantError` raised in a
handler into an error payload carrying `code`, `message` and, when the exception has one,
`translation_key` with its domain and placeholders. So handlers raise the same exception
types the services raise, and nothing here formats an English sentence.

**An apply runs in a background task, not in the command.** The panel gets the job id at
once and follows the work through `jobs/subscribe`. Awaiting the job inside the command
would tie a write to somebody's Z-Wave mesh to the life of a browser tab: closing the tab
cancels the task, and the executor would (correctly) record a job that stopped halfway
through a house. The id is generated here and handed to the runner so the panel has
something to follow before the first write lands.

**A subscription dies with its connection.** Every listener a subscription registers is
removed by the one callable stored in `connection.subscriptions`, which Home Assistant
calls when the connection closes as well as on an explicit unsubscribe, and a flag makes a
callback already in flight silent from the moment it is dropped. A listener that outlives
its connection survives a reload and is the leak nobody finds.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import replace
import logging
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.decorators import async_response, require_admin
from homeassistant.components.websocket_api.messages import (
    BASE_COMMAND_MESSAGE_SCHEMA,
    event_message,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import voluptuous as vol

from .const import DOMAIN, EVENT_JOB_FINISHED
from .coordinator import PlanScope
from .executor import JobRunningError
from .models import Plan, PlanOp, Profile, Rule, Template
from .rule_entity import async_handle_of_device
from .serialize import Serializer
from .services import NOTHING_TO_DO, refuse_unknown_devices
from .yaml_io import (
    ProfileFormatError,
    devices_to_data,
    dump_profile,
    parse_profile,
    profile_from_data,
    rule_from_data,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.components.websocket_api.connection import ActiveConnection

    from . import DeviceLinksConfigEntry, DeviceLinksRuntimeData
    from .coordinator import DeviceLinksCoordinator
    from .models import DeviceHandle
    from .storage import StoredState

_LOGGER = logging.getLogger(__name__)

type _Handler = Callable[
    [HomeAssistant, "ActiveConnection", dict[str, Any]], Coroutine[Any, Any, None]
]
type _Registered = Callable[[HomeAssistant, "ActiveConnection", dict[str, Any]], None]

# Every command this phase implements, and the schema each validates against. Registered
# from this one mapping so a command cannot exist without a schema or without the admin
# gate, and so a test can assert the whole surface rather than the commands somebody
# remembered to list.
COMMANDS: Final[dict[str, dict[vol.Marker, Any]]] = {}

# PRD Section 8.7 commands this phase deliberately does not implement, with the phase that
# owns each. Named rather than merely absent: a command that is missing by oversight and a
# command that is missing on purpose look identical from the outside, and Phase 1E has to
# be able to tell them apart before it builds a button for one.
DEFERRED_COMMANDS: Final = frozenset(
    {
        # Adopting an unmanaged link means writing a per-link ownership record, which is a
        # storage schema change and therefore a migration (open item T11).
        "unmanaged/adopt",
        # Device swap is Phase 2 (FR-S1 to FR-S4), and there is no second backend to swap
        # between yet.
        "swap/candidates",
        "swap/preview",
        "swap/apply",
        # Rollback re-applies a snapshot as a plan, which is Phase 2 alongside the swap
        # flow that needs it. The snapshots themselves are taken and listed today.
        "snapshots/rollback",
    }
)

# The scope every command that works on part of the network takes, in one place.
_SCOPE: Final[dict[vol.Marker, Any]] = {
    vol.Optional("rule_ids"): [str],
    vol.Optional("device_ids"): [str],
}


def _command(
    command: str, schema: dict[vol.Marker, Any] | None = None
) -> Callable[[_Handler], _Handler]:
    """Register one admin-only command, and remember it for the registration sweep."""

    def _decorate(handler: _Handler) -> _Handler:
        COMMANDS[command] = dict(schema or {})
        handler.__dl_command__ = command  # type: ignore[attr-defined]
        return handler

    return _decorate


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register every command with Home Assistant's WebSocket API.

    Called from `async_setup` rather than from the config entry: WebSocket handlers are
    global and registering them again on a reload would be the same handler twice
    (quality-scale rule config-entry-unloading, which asks for exactly this). A command
    called while no entry is loaded answers with a translated reason, like the services.
    """
    for handler in _HANDLERS:
        command = handler.__dl_command__  # type: ignore[attr-defined]
        async_register_command(
            hass,
            f"{DOMAIN}/{command}",
            _wrapped(handler),
            BASE_COMMAND_MESSAGE_SCHEMA.extend(
                {vol.Required("type"): f"{DOMAIN}/{command}", **COMMANDS[command]}
            ),
        )


def _wrapped(handler: _Handler) -> _Registered:
    """Return the handler with the admin gate and the async response wrapper on it."""
    return require_admin(async_response(handler))


# --------------------------------------------------------------------------------------
# What every handler starts with
# --------------------------------------------------------------------------------------


def _runtime(hass: HomeAssistant) -> tuple[DeviceLinksConfigEntry, DeviceLinksRuntimeData]:
    """Return the loaded entry and its runtime, or say there is none to act on."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(
            "Device Links has no loaded config entry, so there is nothing to act on",
            translation_domain=DOMAIN,
            translation_key="not_loaded",
        )
    entry: DeviceLinksConfigEntry = entries[0]
    return entry, entry.runtime_data


def _scope(hass: HomeAssistant, entry: DeviceLinksConfigEntry, msg: Mapping[str, Any]) -> PlanScope:
    """Turn a message's scope into a plan scope, refusing anything that names nothing."""
    coordinator = entry.runtime_data.coordinator
    profile = coordinator.active_profile
    known = {rule.id for rule in profile.rules} if profile is not None else set()
    for rule_id in msg.get("rule_ids", []):
        if rule_id not in known:
            raise _unknown_rule(rule_id)
    identities = {
        _handle_of_device(hass, entry, device_id).identity
        for device_id in msg.get("device_ids", [])
    }
    return PlanScope(
        rule_ids=frozenset(msg.get("rule_ids", [])), device_identities=frozenset(identities)
    )


def _handle_of_device(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, device_id: str
) -> DeviceHandle:
    """Return the device handle behind a Home Assistant device id, or refuse.

    Devices are named by registry id rather than by protocol address (PRD Section 10): a
    node id is something a caller could invent, and a device id is something they picked.
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


def _unknown_rule(rule_id: str) -> ServiceValidationError:
    """Return the refusal for a rule id the active profile does not carry."""
    return ServiceValidationError(
        f"no rule of the active profile has the id {rule_id}",
        translation_domain=DOMAIN,
        translation_key="unknown_rule",
        translation_placeholders={"rule": rule_id},
    )


def _profile(coordinator: DeviceLinksCoordinator, profile_id: str) -> Profile:
    """Return the stored profile with this id, or say there is none."""
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


def _active(coordinator: DeviceLinksCoordinator) -> Profile:
    """Return the active profile, or say that nothing is active."""
    profile = coordinator.active_profile
    if profile is None:
        raise ServiceValidationError(
            "no profile is active",
            translation_domain=DOMAIN,
            translation_key="no_active_profile",
        )
    return profile


def _read_profile(coordinator: DeviceLinksCoordinator, payload: Mapping[str, Any]) -> Profile:
    """Return the profile this payload describes, resolved against the real network.

    The devices are the ones this integration can see, never the ones the payload
    describes: a client that could describe its own devices could author a rule about a
    node that does not exist, and the first anybody would hear of it is an apply that
    plans nothing (E38).
    """
    data = {**payload, "devices": devices_to_data(coordinator.devices.values())}
    try:
        return profile_from_data(data)
    except ProfileFormatError as error:
        raise _invalid_profile(error) from error


def _read_rule(coordinator: DeviceLinksCoordinator, payload: Mapping[str, Any]) -> Rule:
    """Return the rule this payload describes, resolved against the real network."""
    try:
        return rule_from_data(payload, coordinator.devices)
    except ProfileFormatError as error:
        raise _invalid_profile(error) from error


def _invalid_profile(error: ProfileFormatError) -> ServiceValidationError:
    """Return the refusal for a profile or rule that cannot be read as one."""
    return ServiceValidationError(
        str(error),
        translation_domain=DOMAIN,
        translation_key="profile_invalid",
        translation_placeholders={"error": str(error)},
    )


def _stored_with(state: StoredState, profile: Profile) -> tuple[Profile, ...]:
    """Return the stored profiles with this one added or replaced."""
    if any(candidate.id == profile.id for candidate in state.profiles):
        return tuple(
            profile if candidate.id == profile.id else candidate for candidate in state.profiles
        )
    return (*state.profiles, profile)


# --------------------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------------------


@_command("profiles/list")
async def _profiles_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the stored profiles and say which one is in force."""
    _entry, runtime = _runtime(hass)
    serializer = Serializer(hass, _entry)
    state = runtime.coordinator.state
    connection.send_result(
        msg["id"],
        {
            "active_profile_id": state.active_profile_id,
            "profiles": [
                serializer.profile(profile, active_profile_id=state.active_profile_id)
                for profile in state.profiles
            ],
        },
    )


@_command("profiles/get", {vol.Required("profile_id"): str})
async def _profiles_get(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return one profile with each of its rules and what that rule is doing."""
    entry, runtime = _runtime(hass)
    profile = _profile(runtime.coordinator, msg["profile_id"])
    serializer = Serializer(hass, entry)
    connection.send_result(
        msg["id"],
        {
            "profile": serializer.profile(
                profile, active_profile_id=runtime.coordinator.state.active_profile_id
            ),
            "rules": [serializer.rule(rule) for rule in profile.rules],
        },
    )


@_command("profiles/create", {vol.Required("profile"): dict})
async def _profiles_create(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store a new profile, and refuse to overwrite one that exists."""
    entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    profile = _read_profile(coordinator, msg["profile"])
    if any(candidate.id == profile.id for candidate in coordinator.state.profiles):
        raise ServiceValidationError(
            f"a profile with the id {profile.id} already exists",
            translation_domain=DOMAIN,
            translation_key="profile_exists",
            translation_placeholders={"profile": profile.id},
        )
    coordinator.async_update_state(
        replace(coordinator.state, profiles=(*coordinator.state.profiles, profile))
    )
    connection.send_result(msg["id"], _saved(hass, entry, profile))


@_command("profiles/update", {vol.Required("profile"): dict})
async def _profiles_update(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Replace one stored profile with what the client sent, writing to no device."""
    entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    profile = _read_profile(coordinator, msg["profile"])
    _profile(coordinator, profile.id)
    coordinator.async_update_state(
        replace(coordinator.state, profiles=_stored_with(coordinator.state, profile))
    )
    connection.send_result(msg["id"], _saved(hass, entry, profile))


@_command("profiles/delete", {vol.Required("profile_id"): str})
async def _profiles_delete(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete one profile, leaving whatever it wrote on the devices.

    Deleting the active profile leaves nothing active, and the links its rules made become
    unmanaged: they are reported rather than removed (Decision D9), because the intent
    behind them is gone and quietly deleting associations on the strength of a profile
    that no longer exists is the one thing worse than leaving them.
    """
    _entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    profile = _profile(coordinator, msg["profile_id"])
    state = coordinator.state
    coordinator.async_update_state(
        replace(
            state,
            profiles=tuple(candidate for candidate in state.profiles if candidate.id != profile.id),
            active_profile_id=(
                None if state.active_profile_id == profile.id else state.active_profile_id
            ),
        )
    )
    connection.send_result(msg["id"], {"profile_id": profile.id, "deleted": True})


@_command("profiles/activate", {vol.Required("profile_id"): str})
async def _profiles_activate(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Make one profile the active one and open a plan, without writing (FR-E1)."""
    entry, runtime = _runtime(hass)
    _profile(runtime.coordinator, msg["profile_id"])
    runtime.coordinator.async_activate_profile(msg["profile_id"])
    plan = await runtime.coordinator.async_plan()
    runtime.pending_plan = plan
    connection.send_result(
        msg["id"],
        {"profile_id": msg["profile_id"], "plan": Serializer(hass, entry).plan(plan)},
    )


@_command("profiles/duplicate", {vol.Required("profile_id"): str, vol.Optional("name"): str})
async def _profiles_duplicate(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Copy one profile under a new id, so a user can experiment without losing what works."""
    entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    original = _profile(coordinator, msg["profile_id"])
    copy = Profile(
        id=uuid4().hex,
        name=msg.get("name", f"{original.name} copy"),
        rules=original.rules,
    )
    coordinator.async_update_state(
        replace(coordinator.state, profiles=(*coordinator.state.profiles, copy))
    )
    connection.send_result(msg["id"], _saved(hass, entry, copy))


@_command("profiles/export", {vol.Optional("profile_id"): str})
async def _profiles_export(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return one profile as the YAML a user keeps in version control (FR-P2)."""
    _entry, runtime = _runtime(hass)
    profile = (
        _active(runtime.coordinator)
        if "profile_id" not in msg
        else _profile(runtime.coordinator, msg["profile_id"])
    )
    connection.send_result(
        msg["id"],
        {"profile_id": profile.id, "name": profile.name, "yaml": dump_profile(profile)},
    )


@_command("profiles/import", {vol.Required("yaml"): str})
async def _profiles_import(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store the profile this YAML describes, and write to no device (E38)."""
    entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    try:
        profile = parse_profile(msg["yaml"])
    except ProfileFormatError as error:
        raise _invalid_profile(error) from error
    # The file's own device handles are kept, rather than re-resolved against the network
    # the way a profile the panel sends is. A file records what each device was when it was
    # exported, fingerprint included, and that record is what a later release compares
    # against to notice that a node id now answers as a different model (E20). Re-resolving
    # would quietly adopt whatever is at that address today and lose the difference.
    refuse_unknown_devices(coordinator, profile)
    coordinator.async_update_state(
        replace(coordinator.state, profiles=_stored_with(coordinator.state, profile))
    )
    is_active = coordinator.state.active_profile_id == profile.id
    result = _saved(hass, entry, profile)
    if is_active:
        runtime.pending_plan = await coordinator.async_plan()
        result["plan"] = Serializer(hass, entry).plan(runtime.pending_plan)
    connection.send_result(msg["id"], {**result, "is_active": is_active})


def _saved(hass: HomeAssistant, entry: DeviceLinksConfigEntry, profile: Profile) -> dict[str, Any]:
    """Return what every profile write answers with: the profile as it is now stored."""
    coordinator = entry.runtime_data.coordinator
    return {
        "profile": Serializer(hass, entry).profile(
            profile, active_profile_id=coordinator.state.active_profile_id
        )
    }


# --------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------


@_command("rules/validate", {vol.Required("rule"): dict})
async def _rules_validate(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Compile a rule against the devices as they are now, and store nothing.

    What the rule editor asks on every keystroke worth asking about, so it is deliberately
    read-only and deliberately answers with warnings and errors rather than raising: a rule
    the compiler refuses is the answer to "will this work?", and an error reply would leave
    the panel with a failure where it wanted a reason.
    """
    entry, runtime = _runtime(hass)
    rule = _read_rule(runtime.coordinator, msg["rule"])
    compiled = runtime.coordinator.compile_rule(rule)
    connection.send_result(msg["id"], Serializer(hass, entry).compiled(compiled))


@_command("rules/upsert", {vol.Optional("profile_id"): str, vol.Required("rule"): dict})
async def _rules_upsert(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add or replace one rule of a profile. Nothing is written to a device."""
    entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    profile = (
        _active(coordinator)
        if "profile_id" not in msg
        else _profile(coordinator, msg["profile_id"])
    )
    rule = _read_rule(coordinator, msg["rule"])
    rules = (
        tuple(rule if existing.id == rule.id else existing for existing in profile.rules)
        if any(existing.id == rule.id for existing in profile.rules)
        else (*profile.rules, rule)
    )
    updated = replace(profile, rules=rules)
    coordinator.async_update_state(
        replace(coordinator.state, profiles=_stored_with(coordinator.state, updated))
    )
    connection.send_result(msg["id"], Serializer(hass, entry).rule(rule))


@_command("rules/delete", {vol.Optional("profile_id"): str, vol.Required("rule_id"): str})
async def _rules_delete(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete one rule from a profile, leaving what it wrote on the devices.

    Its links become unmanaged, which is Decision D9: the intent is gone, so they are
    reported rather than removed. Disabling a rule is what removes its links (FR-R5), and
    the two are different acts on purpose.
    """
    _entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    profile = (
        _active(coordinator)
        if "profile_id" not in msg
        else _profile(coordinator, msg["profile_id"])
    )
    rule_id: str = msg["rule_id"]
    if not any(rule.id == rule_id for rule in profile.rules):
        raise _unknown_rule(rule_id)
    updated = replace(profile, rules=tuple(rule for rule in profile.rules if rule.id != rule_id))
    coordinator.async_update_state(
        replace(coordinator.state, profiles=_stored_with(coordinator.state, updated))
    )
    connection.send_result(msg["id"], {"rule_id": rule_id, "deleted": True})


@_command("rules/set_enabled", {vol.Required("rule_id"): str, vol.Required("enabled"): bool})
async def _rules_set_enabled(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Enable or disable one rule, through the shared rate limiter (E35).

    The panel is a caller like any other here. A rule toggle rewrites an association table
    in device NVM, which has a finite write endurance, and a surface that reached the
    runner directly would be the bypass the limiter exists to prevent.
    """
    _entry, runtime = _runtime(hass)
    rule_id: str = msg["rule_id"]
    profile = runtime.coordinator.active_profile
    if profile is None or not any(rule.id == rule_id for rule in profile.rules):
        raise _unknown_rule(rule_id)
    await runtime.toggles.async_request(rule_id, enabled=msg["enabled"])
    connection.send_result(
        msg["id"],
        {
            "rule_id": rule_id,
            "enabled": runtime.coordinator.is_rule_enabled(rule_id, default=msg["enabled"]),
            "rate_limited": runtime.toggles.is_rate_limited(rule_id),
        },
    )


# --------------------------------------------------------------------------------------
# Devices and templates
# --------------------------------------------------------------------------------------


@_command("devices/list")
async def _devices_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List every device every loaded backend can see."""
    entry, runtime = _runtime(hass)
    serializer = Serializer(hass, entry)
    connection.send_result(
        msg["id"],
        {
            "devices": [
                serializer.device(handle)
                for _identity, handle in sorted(runtime.coordinator.devices.items())
            ]
        },
    )


@_command("devices/get", {vol.Required("device_id"): str})
async def _devices_get(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return one device: what it can do, what is on it, and how it is set."""
    entry, _runtime_data = _runtime(hass)
    handle = _handle_of_device(hass, entry, msg["device_id"])
    connection.send_result(msg["id"], _device_detail(hass, entry, handle))


@_command("devices/refresh", {vol.Required("device_id"): str, vol.Optional("deep"): bool})
async def _devices_refresh(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Re-read one device and return it. `deep` asks the device rather than the cache."""
    entry, runtime = _runtime(hass)
    handle = _handle_of_device(hass, entry, msg["device_id"])
    await runtime.coordinator.async_refresh(handle, deep=msg.get("deep", False))
    connection.send_result(msg["id"], _device_detail(hass, entry, handle))


def _device_detail(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, handle: DeviceHandle
) -> dict[str, Any]:
    """Return everything known about one device, as the device page shows it."""
    coordinator = entry.runtime_data.coordinator
    serializer = Serializer(hass, entry)
    capabilities = coordinator.capabilities_for(handle.identity)
    observed = coordinator.observed_for(handle)
    return {
        "device": serializer.device(handle),
        "emitters": [] if capabilities is None else serializer.capabilities(capabilities),
        "links": [] if observed is None else [serializer.link(link) for link in observed.links],
        "settings": {} if observed is None else dict(observed.settings),
        "deep_verified": observed is not None and observed.deep_verified,
    }


@_command("templates/list")
async def _templates_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the intents a rule can be authored with.

    Names and descriptions are not here: each template's are translation keys in
    `strings.json`, so the panel localises them rather than showing whatever English this
    file happened to carry.
    """
    connection.send_result(
        msg["id"],
        {"templates": [{"id": str(template)} for template in Template]},
    )


# --------------------------------------------------------------------------------------
# Plan, apply, verify
# --------------------------------------------------------------------------------------


@_command("plan", {**_SCOPE, vol.Optional("remove_unmanaged"): [str]})
async def _plan(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Return what applying this scope would do, without doing any of it."""
    entry, runtime = _runtime(hass)
    plan = await runtime.coordinator.async_plan(
        _scope(hass, entry, msg), remove_unmanaged=frozenset(msg.get("remove_unmanaged", []))
    )
    connection.send_result(msg["id"], Serializer(hass, entry).plan(plan))


@_command(
    "apply",
    {**_SCOPE, vol.Required("plan_token"): str, vol.Optional("remove_unmanaged"): [str]},
)
async def _apply(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Apply the plan this token names, in a task that outlives the connection."""
    entry, runtime = _runtime(hass)
    # Asked before the plan is rebuilt, because a job that is running is the answer
    # whatever the plan says: re-planning mid-job compares against a network that is being
    # written to, and would report the second caller's plan as stale when what is really
    # true is that the first one has not finished (E16).
    if runtime.runner.progress is not None:
        raise JobRunningError(
            "an apply is already running, so this one was refused rather than queued "
            "behind a plan that will be out of date by the time it runs",
            translation_domain=DOMAIN,
            translation_key="job_running",
        )
    scope = _scope(hass, entry, msg)
    remove_unmanaged = frozenset(msg.get("remove_unmanaged", []))
    plan = await runtime.coordinator.async_plan(scope, remove_unmanaged=remove_unmanaged)
    _check_token(plan, msg["plan_token"])
    if plan.is_empty:
        connection.send_result(msg["id"], {"job_id": None, "status": NOTHING_TO_DO})
        return
    job_id = uuid4().hex
    entry.async_create_background_task(
        hass,
        _run_job(runtime, plan, scope, remove_unmanaged, job_id),
        name=f"{DOMAIN} apply {job_id}",
    )
    connection.send_result(msg["id"], {"job_id": job_id, "status": "running"})


async def _run_job(
    runtime: DeviceLinksRuntimeData,
    plan: Plan,
    scope: PlanScope,
    remove_unmanaged: frozenset[str],
    job_id: str,
) -> None:
    """Run one apply outside the connection that asked for it.

    The runner's own refusals are caught rather than left to become an unhandled task
    exception. They are close to unreachable from here: the task is started eagerly, so
    the runner has taken its job lock before this command returns, and the caller was
    already refused if one was running. Close to unreachable is not unreachable, and a
    write to somebody's house is not the place to find out.
    """
    try:
        await runtime.runner.async_apply(
            plan, scope=scope, remove_unmanaged=remove_unmanaged, job_id=job_id
        )
    except HomeAssistantError:
        _LOGGER.warning("job %s was refused by the runner after it was accepted", job_id)


def _check_token(plan: Plan, token: str) -> None:
    """Refuse a plan token that no longer describes what would happen (FR-A3).

    The token is computed from the plan's inputs, so a mismatch means the network or the
    profile moved between the plan the user looked at and the apply they pressed. Refusing
    is the whole point: the alternative is applying work nobody has seen.
    """
    if plan.token != token:
        # Deliberately not the executor's `stale_plan`, which is about one link on one
        # device and says which. This is about the whole plan, and filling that message's
        # placeholders with empty strings to reuse it would print a sentence with holes
        # where the device names should be.
        raise ServiceValidationError(
            "this plan was built against a state that has since changed, so it was not "
            "applied; plan again and look at what it says now",
            translation_domain=DOMAIN,
            translation_key="plan_out_of_date",
        )


@_command("verify", _SCOPE)
async def _verify(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Re-read the devices in scope from the devices themselves. Never writes."""
    entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    scope = _scope(hass, entry, msg)
    identities = sorted(coordinator.identities_in_scope(scope))
    for identity in identities:
        handle = coordinator.handle_for(identity)
        if handle is not None:
            await coordinator.async_refresh(handle, deep=True)
    states = coordinator.drift_state()
    if scope.rule_ids:
        states = {rule_id: state for rule_id, state in states.items() if rule_id in scope.rule_ids}
    connection.send_result(
        msg["id"],
        {
            "devices": len(identities),
            "rules": {rule_id: str(state) for rule_id, state in sorted(states.items())},
        },
    )


# --------------------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------------------


@_command("jobs/list")
async def _jobs_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the applies this integration remembers, newest last (FR-A2)."""
    entry, runtime = _runtime(hass)
    serializer = Serializer(hass, entry)
    connection.send_result(
        msg["id"],
        {
            "jobs": [serializer.job(job) for job in runtime.coordinator.state.jobs],
            "running": _progress(runtime),
        },
    )


@_command("jobs/get", {vol.Required("job_id"): str})
async def _jobs_get(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Return one apply in full, link by link."""
    entry, runtime = _runtime(hass)
    job = next((job for job in runtime.coordinator.state.jobs if job.id == msg["job_id"]), None)
    if job is None:
        raise ServiceValidationError(
            f"no job with the id {msg['job_id']} is in the history",
            translation_domain=DOMAIN,
            translation_key="unknown_job",
            translation_placeholders={"job": msg["job_id"]},
        )
    connection.send_result(msg["id"], Serializer(hass, entry).job(job))


@_command("jobs/cancel")
async def _jobs_cancel(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stop the running job from starting anything else.

    What is already in flight finishes and is reported with its real outcome: a radio
    write that has been sent cannot be un-sent, and reporting it as cancelled would tell
    the user nothing reached a device when something did.
    """
    _entry, runtime = _runtime(hass)
    running = runtime.runner.progress is not None
    if running:
        runtime.runner.async_cancel()
    connection.send_result(msg["id"], {"cancelled": running})


@_command("jobs/subscribe")
async def _jobs_subscribe(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stream a running job's progress, and the summary of every job that finishes.

    Two sources, one unsubscribe. Progress comes from the coordinator, which every device
    a job touches updates, and the finished summary comes from the bus event the runner
    fires for every job whatever started it (FR-E2), so a job somebody started from a
    service call or a button streams here too.

    `live` is what makes an already-dispatched callback silent: removing a listener does
    not recall a callback that is already on its way, and sending into a closed connection
    is the error nobody can act on.
    """
    _entry, runtime = _runtime(hass)
    subscription_id = msg["id"]
    state: dict[str, Any] = {"live": True, "last": None}

    @callback
    def _send(payload: dict[str, Any]) -> None:
        if state["live"]:
            connection.send_message(event_message(subscription_id, payload))

    @callback
    def _on_update() -> None:
        progress = _progress(runtime)
        if progress != state["last"]:
            state["last"] = progress
            _send({"type": "progress", "job": progress})

    @callback
    def _on_finished(event: Any) -> None:
        data = dict(event.data)
        _send({"type": "finished", "job": {"id": data.pop("job_id"), **data}})

    remove_updates = runtime.coordinator.async_add_listener(_on_update)
    remove_event = hass.bus.async_listen(EVENT_JOB_FINISHED, _on_finished)

    @callback
    def _unsubscribe() -> None:
        state["live"] = False
        remove_updates()
        remove_event()

    connection.subscriptions[subscription_id] = _unsubscribe
    connection.send_result(subscription_id)
    _send({"type": "progress", "job": _progress(runtime)})


def _progress(runtime: DeviceLinksRuntimeData) -> dict[str, Any] | None:
    """Return where the running job has got to, or None when none is running."""
    progress = runtime.runner.progress
    if progress is None:
        return None
    return {
        "id": progress.id,
        "total": progress.total,
        "completed": progress.completed,
        "devices_in_flight": list(progress.devices_in_flight),
    }


# --------------------------------------------------------------------------------------
# Unmanaged links and snapshots
# --------------------------------------------------------------------------------------


@_command(
    "unmanaged/ignore",
    {vol.Required("fingerprints"): [str], vol.Required("ignored"): bool},
)
async def _unmanaged_ignore(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Remember that the user does not care about these links, or forget it (FR-A5)."""
    _entry, runtime = _runtime(hass)
    coordinator = runtime.coordinator
    fingerprints = frozenset(msg["fingerprints"])
    ignored = (
        coordinator.state.ignored_unmanaged | fingerprints
        if msg["ignored"]
        else coordinator.state.ignored_unmanaged - fingerprints
    )
    coordinator.async_update_state(replace(coordinator.state, ignored_unmanaged=ignored))
    connection.send_result(msg["id"], {"ignored": sorted(ignored)})


@_command("unmanaged/remove", {vol.Required("fingerprints"): [str]})
async def _unmanaged_remove(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Take these links off their devices, and nothing else.

    Per link, by fingerprint, because that is the whole of the opt-in CLAUDE.md Section 3
    rule 5 requires: this is somebody else's association, made by hand, and taking it off
    is not something they can undo from here. The plan is built with exactly these
    fingerprints selected, so nothing else can come along with them.

    Awaited rather than run in the background, unlike `apply`: this is a handful of
    entries the user ticked in a dialog and is waiting for an answer about, and the answer
    is what they pressed the button to find out. `apply` can be a whole house.
    """
    _entry, runtime = _runtime(hass)
    fingerprints = frozenset(msg["fingerprints"])
    plan = await runtime.coordinator.async_plan(remove_unmanaged=fingerprints)
    selected = replace(
        plan,
        items=tuple(
            item
            for item in plan.items
            # Removals only. A fingerprint identifies a link rather than a direction, so a
            # client that sent the fingerprint of something the plan wants to *add* would
            # otherwise have this write it, which is a write nobody asked this command for.
            if item.op is PlanOp.REMOVE
            and item.link is not None
            and item.link.fingerprint in fingerprints
        ),
    )
    if selected.is_empty:
        connection.send_result(msg["id"], {"job_id": None, "status": NOTHING_TO_DO})
        return
    report = await runtime.runner.async_apply(selected, remove_unmanaged=fingerprints)
    connection.send_result(msg["id"], {"job_id": report.id, "status": str(report.status)})


@_command("snapshots/list")
async def _snapshots_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the pre-apply snapshots that are still kept (FR-P3)."""
    entry, runtime = _runtime(hass)
    serializer = Serializer(hass, entry)
    connection.send_result(
        msg["id"],
        {
            "snapshots": [
                serializer.snapshot(snapshot)
                for snapshot in reversed(runtime.coordinator.state.snapshots)
            ]
        },
    )


# Every handler, in the order they are defined above. Built once here rather than
# collected by scanning the module, so a handler that is written and never registered is
# a missing line rather than something that depends on how a decorator was spelled.
_HANDLERS: Final[tuple[_Handler, ...]] = (
    _profiles_list,
    _profiles_get,
    _profiles_create,
    _profiles_update,
    _profiles_delete,
    _profiles_activate,
    _profiles_duplicate,
    _profiles_export,
    _profiles_import,
    _rules_validate,
    _rules_upsert,
    _rules_delete,
    _rules_set_enabled,
    _devices_list,
    _devices_get,
    _devices_refresh,
    _templates_list,
    _plan,
    _apply,
    _verify,
    _jobs_list,
    _jobs_get,
    _jobs_cancel,
    _jobs_subscribe,
    _unmanaged_ignore,
    _unmanaged_remove,
    _snapshots_list,
)

__all__ = ["COMMANDS", "DEFERRED_COMMANDS", "async_register_commands"]
