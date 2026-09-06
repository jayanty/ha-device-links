"""The Device Links config entry: what is built at setup and what is taken down at unload.

Everything the integration owns is built here and hung on `entry.runtime_data`: the
backends, the observed-state coordinator, the job runner, and the rate limiter that
stands between every caller and a rule toggle. Nothing is in `hass.data`.

**A backend whose upstream integration has not loaded yet is not a failure.** The
manifest lists `zwave_js`, `mqtt` and `matter` in `after_dependencies`, which asks Home
Assistant to load them first *if they are going to load at all* and does not order them
otherwise. On a slow start our entry can therefore be set up while the `zwave_js` entry is
still connecting, and its `runtime_data` does not exist yet. That is `ConfigEntryNotReady`
and nothing else: the situation is temporary, Home Assistant retries with a backoff, and
the alternative (setting up with no backends and coming up empty) produces an integration
that looks loaded, reports every device unavailable, and never recovers without a manual
reload.

The same answer covers the case where the user removed Z-Wave JS entirely, which is not
temporary. It surfaces as "Retrying setup" rather than as silence, which is the honest
description of an integration that adapts protocol integrations and has none to adapt.
The config flow already refuses to create an entry in that state, so reaching it means
something was removed after setup, and Task 6's Repairs issue (E1) is what turns the retry
into an explanation.

**Unload is the mirror of setup, in reverse order.** The platforms come down first, so no
entity can call into a runner that is being shut down; then the rate limiter's timers, so
no deferred toggle starts a job during teardown; then the runner, which waits for writes
already on the radio; then the event bridge, so the job the runner just interrupted is
still announced (the Activity view is the only record of a job that wrote and stopped);
and last the coordinator, which drops the backend subscriptions. Every one of those has a
listener or a timer behind it, and a single one left behind fires after a reload against
an object that no longer exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .backends.base import Backend
from .backends.matter import MatterBackend
from .backends.matter_client import (
    MatterAccessorError,
    async_get_client,
    async_matter_is_available,
)
from .backends.mqtt_client import HomeAssistantMqttClient, async_mqtt_is_available
from .backends.zigbee2mqtt import ZigbeeBackend
from .backends.zwave import ZWaveBackend
from .backends.zwave_accessor import (
    ZWaveAccessorError,
    async_get_driver,
    async_get_server_version,
)
from .const import (
    DEFAULT_ZIGBEE_BASE_TOPIC,
    DOMAIN,
    OPTION_HYBRID_LEGS,
    OPTION_MATTER_WRITES,
    OPTION_ZIGBEE_BASE_TOPIC,
)
from .coordinator import DeviceLinksCoordinator
from .deployment import Deployment, read_deployment
from .events import DeviceLinksEventBridge
from .executor import JobRunner
from .hybrid import HybridLegs
from .models import Backend as BackendId
from .models import Plan
from .panel import async_register_panel, async_unregister_panel
from .profile_db import ProfileDatabase, load_profiles
from .repairs import async_clear_issues, async_raise_storage_issue, async_setup_repairs
from .rule_toggle import RuleToggleLimiter
from .services import (
    async_setup_raw_services,
    async_setup_services,
    async_unload_raw_services,
)
from .storage import DeviceLinksStore, StorageSchemaError
from .websocket import async_register_commands
from .yaml_mirror import MirrorSettings, YamlMirror

if TYPE_CHECKING:
    from homeassistant.components.matter.helpers import MatterConfigEntry
    from homeassistant.components.zwave_js.models import ZwaveJSConfigEntry

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "CONFIG_SCHEMA",
    "DOMAIN",
    "PLATFORMS",
    "DeviceLinksConfigEntry",
    "DeviceLinksRuntimeData",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]

# Set up through the UI only, so YAML under our domain is a mistake rather than a config.
CONFIG_SCHEMA: Final = cv.config_entry_only_config_schema(DOMAIN)

# The platforms this integration forwards its entry to. Order is the order they are set
# up in and, reversed, the order they come down in.
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Where the curated device profiles live, relative to this package.
PROFILES_DIR_NAME: Final = "profiles_db"


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """What the Health sensor has to say about one backend beyond whether it answered.

    `read_version` is a reader rather than a string because the two protocols differ in
    whether the answer can change under us. A `zwave_js` server version cannot: it is read
    off that integration's config entry, and it cannot change without that entry reloading,
    which reloads this one. So Z-Wave passes a fixed answer, and an entity property never
    reaches into another integration's runtime data on every state write.

    Zigbee2MQTT is an add-on rather than an integration, so upgrading it republishes
    `bridge/info` and reloads nothing of ours: a version snapshotted at setup would be quoted
    in an issue report months after it stopped being true. So Zigbee passes its adapter's own
    accessor, which reads a field the adapter already holds.
    """

    backend_id: BackendId
    upstream_domain: str
    read_version: Callable[[], str | None]

    @property
    def upstream_version(self) -> str | None:
        """Return the upstream system's version as it reads now."""
        return self.read_version()


@dataclass
class DeviceLinksRuntimeData:
    """Everything the integration keeps for the lifetime of its config entry.

    Quality-scale rule runtime-data: state lives here rather than in `hass.data`, and the
    entry is typed as `DeviceLinksConfigEntry` so mypy checks access to it.
    """

    coordinator: DeviceLinksCoordinator
    runner: JobRunner
    toggles: RuleToggleLimiter
    events: DeviceLinksEventBridge
    hybrid: HybridLegs
    backends: dict[BackendId, Backend]
    backend_info: tuple[BackendInfo, ...]
    version: str | None
    deployment: Deployment | None
    profiles: ProfileDatabase | None = None

    # The plan a profile switch opened and nobody has applied yet. Held rather than
    # applied, because FR-E1 makes activating a profile a decision about what should be
    # true and applying it a separate, deliberate act. Phase 1E's panel serves it.
    pending_plan: Plan | None = None


type DeviceLinksConfigEntry = ConfigEntry[DeviceLinksRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services and the WebSocket commands, entry or no entry.

    Quality-scale rule action-setup. An automation calling `device_links.apply` validates
    when it is loaded rather than failing while this integration is still retrying its
    setup, and a call that arrives with no entry loaded is answered with a translated
    reason instead of "service not found". The WebSocket commands are registered here for
    the other half of the same reason: they are global rather than per entry, so a reload
    must not register a second copy of each (`config-entry-unloading`).
    """
    async_setup_services(hass)
    async_register_commands(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> bool:
    """Set up Device Links from a config entry."""
    profiles = await hass.async_add_executor_job(_load_profile_database)
    backends, backend_info, teardown = await _async_build_backends(hass, entry, profiles)
    # Registered before the first thing that can fail, so an adapter holding subscriptions
    # of its own (the Zigbee one holds four on the broker) is taken down whichever way this
    # setup ends. Home Assistant runs these for a setup that raised as well as for a normal
    # unload, which is the only reason they can be registered this early.
    for stop in teardown:
        entry.async_on_unload(stop)
    if not backends:
        raise ConfigEntryNotReady(
            "no protocol integration that Device Links adapts is loaded yet, so there is "
            "nothing to read or write; this is retried rather than failed because "
            "after_dependencies does not order the upstream integration before this one",
            translation_domain=DOMAIN,
            translation_key="no_backend_loaded",
        )

    hybrid_allowed = bool(entry.options.get(OPTION_HYBRID_LEGS, False))
    coordinator = DeviceLinksCoordinator(
        hass,
        backends=backends,
        store=DeviceLinksStore(hass),
        hybrid_allowed=hybrid_allowed,
    )
    try:
        await coordinator.async_setup()
    except StorageSchemaError as error:
        # E18 wants the integration up and read-only with a Repairs issue rather than
        # silently empty. The Repairs half is here; read-only mode is open item T23. What
        # must not happen meanwhile is coming up with an empty profile list, because the
        # next save would write it over the file that could not be read. Failing with a
        # translated reason leaves the file untouched, which is the half of E18 that
        # cannot be added later.
        async_raise_storage_issue(hass, error)
        raise ConfigEntryError(
            str(error),
            translation_domain=DOMAIN,
            translation_key=error.translation_key or "storage_unreadable",
            translation_placeholders=error.translation_placeholders,
        ) from error

    events = DeviceLinksEventBridge(hass, entry, coordinator)
    runner = JobRunner(coordinator, on_finished=events.async_job_finished)
    hybrid = HybridLegs(hass, entry, coordinator, allowed=hybrid_allowed)
    mirror = YamlMirror(hass, coordinator, MirrorSettings.from_options(entry.options))
    try:
        entry.runtime_data = DeviceLinksRuntimeData(
            coordinator=coordinator,
            runner=runner,
            toggles=RuleToggleLimiter(hass, coordinator, runner),
            events=events,
            hybrid=hybrid,
            backends=backends,
            backend_info=backend_info,
            version=await _async_version(hass),
            deployment=await hass.async_add_executor_job(read_deployment),
            profiles=profiles,
        )
        events.async_setup()
        # After `runtime_data`, because a leg resolves devices through it, and before the
        # platforms, so a rule's status sensor has counters to read from the first write.
        hybrid.async_setup()
        # Before the platforms, and after `runtime_data`, because it registers a
        # coordinator listener and writes the first files from inside `async_setup`.
        mirror.async_setup(entry)
        async_setup_raw_services(hass, entry)
        # Before the platforms, so that a platform that will not load takes the panel down
        # with it through the handler below rather than leaving a sidebar entry pointing at
        # an integration that failed to set up.
        await async_register_panel(hass, entry)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        # `async_setup_entry` already subscribed to every backend, and Home Assistant does
        # not call `async_unload_entry` for an entry that failed to set up. Without this,
        # a platform that would not load leaves those subscriptions and the debounced
        # refresh timer running for the life of the process, and a later reload adds a
        # second set on top of them.
        hybrid.async_shutdown()
        events.async_shutdown()
        async_unload_raw_services(hass)
        async_unregister_panel(hass)
        await coordinator.async_shutdown()
        raise
    # An option that needs a restart to take effect is an option nobody turns on, and the
    # one this listens for decides whether services that write to a group directly exist
    # at all (Decision D14).
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Raises what should be raised and, just as importantly, withdraws what should not be:
    # the storage issue a previous failed setup left behind is gone by the end of this.
    async_setup_repairs(hass, entry)
    _LOGGER.info(
        "Device Links is set up with the %s backend(s)",
        ", ".join(sorted(str(backend_id) for backend_id in backends)),
    )
    return True


async def _async_options_updated(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> None:
    """Reload the entry, because its options decide what is built and what is registered."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> bool:
    """Unload a config entry, taking down exactly what setup put up.

    Nothing is torn down until the platforms have gone, because a platform that failed to
    unload still has live entities, and entities holding a runner that has been shut down
    is worse than an entry that stayed loaded.
    """
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime = entry.runtime_data
    async_clear_issues(hass)
    async_unregister_panel(hass)
    async_unload_raw_services(hass)
    runtime.toggles.async_shutdown()
    # Before the runner, for the same reason the platforms come down before everything: a
    # leg that outlives its entry fires against a house whose owner thought they had turned
    # it off, and it would survive a reload as a second copy of itself.
    runtime.hybrid.async_shutdown()
    await runtime.runner.async_shutdown()
    runtime.events.async_shutdown()
    await runtime.coordinator.async_shutdown()
    return True


def _load_profile_database() -> ProfileDatabase | None:
    """Read the shipped curated profiles. Blocking, so it runs in the executor.

    A database that cannot be read is not a reason to refuse to set up: every model then
    falls back to per-group emitters, which is cruder but correct, and an integration that
    will not start because a curated file is malformed helps nobody.
    """
    directory = Path(__file__).parent / PROFILES_DIR_NAME
    try:
        return load_profiles(
            {
                path.name: path.read_text()
                for path in sorted(directory.glob("*.json"))
                if path.name != "schema.json"
            }
        )
    except (OSError, ValueError):
        _LOGGER.warning(
            "the curated profile database in %s could not be read, so devices fall back "
            "to the association groups they report for themselves",
            directory,
            exc_info=True,
        )
        return None


async def _async_build_backends(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, profiles: ProfileDatabase | None
) -> tuple[dict[BackendId, Backend], tuple[BackendInfo, ...], tuple[Callable[[], None], ...]]:
    """Build an adapter for every upstream integration that is loaded and answering.

    One protocol per section, each of which adds nothing when its upstream integration is
    absent, and none of which is an error: a Z-Wave-only house, a Zigbee-only house and a
    Matter-only house are all ordinary, and Device Links adapts what is there.

    **The Matter backend is built whatever the Matter writes option says.** The option is
    about writing (FR-B7, Decision D11), and reading is proven: leaving the backend out when
    it is off would hide every Matter device from the panel rather than protect anything, and
    would mean that turning the option on changed what a user could see as well as what they
    could do. What the option reaches is the adapter's own refusal, which answers every write
    with a translated reason naming the option.

    The third return value is what has to be taken down again. The Z-Wave adapter borrows a
    driver somebody else owns and has nothing to release, and so does the Matter one; the
    Zigbee one holds four MQTT subscriptions of its own, and a subscription that outlives a
    config entry unload fires against a dead entry and survives a reload.
    """
    backends: dict[BackendId, Backend] = {}
    info: list[BackendInfo] = []
    teardown: list[Callable[[], None]] = []
    for built in (
        _build_zwave(hass, profiles),
        await _async_build_zigbee(hass, entry, profiles),
        _build_matter(hass, entry, profiles),
    ):
        if built is None:
            continue
        backends[built.info.backend_id] = built.backend
        info.append(built.info)
        if built.stop is not None:
            teardown.append(built.stop)
    return backends, tuple(info), tuple(teardown)


@dataclass(frozen=True, slots=True)
class _BuiltBackend:
    """One adapter, what is said about it, and what has to be called to take it down."""

    backend: Backend
    info: BackendInfo
    stop: Callable[[], None] | None = None


def _build_zwave(hass: HomeAssistant, profiles: ProfileDatabase | None) -> _BuiltBackend | None:
    """Adapt the first loaded `zwave_js` entry whose client has a driver.

    The first and only the first: `BackendId` is one key per protocol, so a second Z-Wave
    network cannot be represented without keying the map on the config entry too. Nobody on
    this network has two, and a second one is ignored rather than misread. Open item T22.

    Nothing to stop: the driver belongs to `zwave_js`, and the only subscription the adapter
    takes is the one the coordinator takes and drops.
    """
    for zwave_js_entry in hass.config_entries.async_entries("zwave_js"):
        if zwave_js_entry.state is not ConfigEntryState.LOADED:
            continue
        typed = cast("ZwaveJSConfigEntry", zwave_js_entry)
        try:
            driver = async_get_driver(typed)
        except ZWaveAccessorError:
            _LOGGER.debug(
                "the zwave_js entry %s is loaded but its client has no driver yet",
                zwave_js_entry.entry_id,
            )
            continue
        return _BuiltBackend(
            backend=ZWaveBackend(driver=driver, profiles=profiles),
            info=BackendInfo(
                backend_id=BackendId.ZWAVE,
                upstream_domain="zwave_js",
                read_version=_fixed(async_get_server_version(typed)),
            ),
        )
    return None


async def _async_build_zigbee(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, profiles: ProfileDatabase | None
) -> _BuiltBackend | None:
    """Adapt the Zigbee2MQTT instance on the configured base topic, if one answers.

    Two absences, told apart because they mean different things to whoever reads the log.
    **No `mqtt` integration** is silent: there is no broker, so there is no Zigbee2MQTT, and
    saying so on every start of a Z-Wave house would be noise. **A broker with nothing on
    this base topic** is said once at warning level: MQTT is set up, and either Zigbee2MQTT
    is not running or its base topic is not the one configured, and both are things the
    person reading can act on (E25).

    Neither is a failure. A bridge that comes up after this is not picked up until the entry
    reloads, which is what changing the base topic in the options already does; open item T52.
    """
    if not async_mqtt_is_available(hass):
        _LOGGER.debug("the mqtt integration is not loaded, so no Zigbee2MQTT is adapted")
        return None
    base_topic = (
        str(entry.options.get(OPTION_ZIGBEE_BASE_TOPIC, DEFAULT_ZIGBEE_BASE_TOPIC)).strip("/")
        or DEFAULT_ZIGBEE_BASE_TOPIC
    )
    backend = ZigbeeBackend(
        client=HomeAssistantMqttClient(hass), base_topic=base_topic, profiles=profiles
    )
    try:
        await backend.async_start()
    # `mqtt` being a loaded component does not mean its broker is connected, and an MQTT
    # client refuses a subscription by raising whatever its broker raised. Caught broadly
    # for that reason: a broker that will not answer must cost the Zigbee half of a house,
    # not the whole integration, and the Z-Wave half of a mixed house least of all.
    # `async_start` has dropped its own subscriptions on the way out either way, so there is
    # nothing here to tear down and nothing to register.
    except Exception as error:
        _LOGGER.warning(
            "no Zigbee2MQTT bridge answered on the base topic %r, so Zigbee links are not "
            "available: %s. Set the base topic in the Device Links options if this instance "
            "publishes somewhere else, then reload the integration",
            base_topic,
            error,
        )
        return None
    return _BuiltBackend(
        backend=backend,
        info=BackendInfo(
            backend_id=BackendId.ZIGBEE2MQTT,
            upstream_domain="mqtt",
            read_version=backend.bridge_version,
        ),
        stop=backend.async_stop,
    )


def _build_matter(
    hass: HomeAssistant, entry: DeviceLinksConfigEntry, profiles: ProfileDatabase | None
) -> _BuiltBackend | None:
    """Adapt the first loaded `matter` entry whose client is connected.

    The first and only the first, for the reason `_build_zwave` gives: `BackendId` is one key
    per protocol. The `matter` integration itself assumes one fabric (its own `get_matter`
    helper takes the first loaded entry and says so), so this is not a limitation of ours.

    Nothing to stop: the client belongs to `matter`, and the only subscription the adapter
    takes is the one the coordinator takes and drops.

    Absence is silent and a client that is not connected yet is a debug line, neither of them
    an error: a house with no Matter fabric is an ordinary house, and this integration
    explicitly supports Z-Wave-only and Zigbee-only installs.
    """
    if not async_matter_is_available(hass):
        _LOGGER.debug("the matter integration is not loaded, so no Matter fabric is adapted")
        return None
    for matter_entry in hass.config_entries.async_entries("matter"):
        if matter_entry.state is not ConfigEntryState.LOADED:
            continue
        typed = cast("MatterConfigEntry", matter_entry)
        try:
            client = async_get_client(typed)
        except MatterAccessorError:
            _LOGGER.debug(
                "the matter entry %s is loaded but its client is not connected yet",
                matter_entry.entry_id,
            )
            continue
        backend = MatterBackend(
            client=client,
            profiles=profiles,
            # FR-B7 and Decision D11. Read either way, write only when somebody has said so.
            writes_enabled=bool(entry.options.get(OPTION_MATTER_WRITES, False)),
        )
        return _BuiltBackend(
            backend=backend,
            info=BackendInfo(
                backend_id=BackendId.MATTER,
                upstream_domain="matter",
                # Read live rather than snapshotted, for the reason the Zigbee bridge version
                # is: the Matter server is an add-on, so upgrading it reconnects the client
                # and reloads nothing of ours.
                read_version=backend.server_version,
            ),
        )
    return None


def _fixed(version: str | None) -> Callable[[], str | None]:
    """Return a reader for a version that cannot change while this entry is loaded."""
    return lambda: version


async def _async_version(hass: HomeAssistant) -> str | None:
    """Return the version this integration declares in its manifest."""
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version
    return None if version is None else str(version)
