"""The Device Links config entry: what is built at setup and what is taken down at unload.

Everything the integration owns is built here and hung on `entry.runtime_data`: the
backends, the observed-state coordinator and the job runner. Nothing is in `hass.data`.

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
entity can call into a runner that is being shut down; then the runner, which waits for
writes already on the radio; then the coordinator, which drops the backend subscriptions.
Every one of those has a listener or a timer behind it, and a single one left behind fires
after a reload against an object that no longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.loader import async_get_integration

from .backends.base import Backend
from .backends.zwave import ZWaveBackend
from .backends.zwave_accessor import (
    ZWaveAccessorError,
    async_get_driver,
    async_get_server_version,
)
from .const import DOMAIN
from .coordinator import DeviceLinksCoordinator
from .deployment import Deployment, read_deployment
from .executor import JobRunner
from .models import Backend as BackendId
from .profile_db import ProfileDatabase, load_profiles
from .storage import DeviceLinksStore, StorageSchemaError

if TYPE_CHECKING:
    from homeassistant.components.zwave_js.models import ZwaveJSConfigEntry

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "DOMAIN",
    "PLATFORMS",
    "DeviceLinksConfigEntry",
    "DeviceLinksRuntimeData",
    "async_setup_entry",
    "async_unload_entry",
]

# The platforms this integration forwards its entry to. Order is the order they are set
# up in and, reversed, the order they come down in.
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

# Where the curated device profiles live, relative to this package.
PROFILES_DIR_NAME: Final = "profiles_db"


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """What the Health sensor has to say about one backend beyond whether it answered.

    Resolved once at setup rather than asked for on every state write: the upstream
    version cannot change without the upstream integration reloading, which reloads this
    one, and an entity property that reaches into another integration's runtime data on
    every update is a coupling that only shows up under load.
    """

    backend_id: BackendId
    upstream_domain: str
    upstream_version: str | None


@dataclass
class DeviceLinksRuntimeData:
    """Everything the integration keeps for the lifetime of its config entry.

    Quality-scale rule runtime-data: state lives here rather than in `hass.data`, and the
    entry is typed as `DeviceLinksConfigEntry` so mypy checks access to it.
    """

    coordinator: DeviceLinksCoordinator
    runner: JobRunner
    backends: dict[BackendId, Backend]
    backend_info: tuple[BackendInfo, ...]
    version: str | None
    deployment: Deployment | None
    profiles: ProfileDatabase | None = None


type DeviceLinksConfigEntry = ConfigEntry[DeviceLinksRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> bool:
    """Set up Device Links from a config entry."""
    profiles = await hass.async_add_executor_job(_load_profile_database)
    backends, backend_info = _async_build_backends(hass, profiles)
    if not backends:
        raise ConfigEntryNotReady(
            "no protocol integration that Device Links adapts is loaded yet, so there is "
            "nothing to read or write; this is retried rather than failed because "
            "after_dependencies does not order the upstream integration before this one",
            translation_domain=DOMAIN,
            translation_key="no_backend_loaded",
        )

    coordinator = DeviceLinksCoordinator(hass, backends=backends, store=DeviceLinksStore(hass))
    try:
        await coordinator.async_setup()
    except StorageSchemaError as error:
        # E18 wants the integration up and read-only with a Repairs issue rather than
        # silently empty. Read-only mode and that issue are Task 6's; what must not happen
        # meanwhile is coming up with an empty profile list, because the next save would
        # write it over the file that could not be read. Failing with a translated reason
        # leaves the file untouched, which is the half of E18 that cannot be added later.
        raise ConfigEntryError(
            str(error),
            translation_domain=DOMAIN,
            translation_key=error.translation_key or "storage_unreadable",
            translation_placeholders=error.translation_placeholders,
        ) from error

    entry.runtime_data = DeviceLinksRuntimeData(
        coordinator=coordinator,
        runner=JobRunner(coordinator),
        backends=backends,
        backend_info=backend_info,
        version=await _async_version(hass),
        deployment=await hass.async_add_executor_job(read_deployment),
        profiles=profiles,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(
        "Device Links is set up with the %s backend(s)",
        ", ".join(sorted(str(backend_id) for backend_id in backends)),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> bool:
    """Unload a config entry, taking down exactly what setup put up.

    Nothing is torn down until the platforms have gone, because a platform that failed to
    unload still has live entities, and entities holding a runner that has been shut down
    is worse than an entry that stayed loaded.
    """
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime = entry.runtime_data
    await runtime.runner.async_shutdown()
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


def _async_build_backends(
    hass: HomeAssistant, profiles: ProfileDatabase | None
) -> tuple[dict[BackendId, Backend], tuple[BackendInfo, ...]]:
    """Build an adapter for every upstream integration that is loaded and connected.

    Zigbee and Matter have no adapter yet (Phase 2 and Phase 3), so this is Z-Wave only
    today and is written as a loop over what exists rather than as a special case, which
    is what keeps `BACKEND_INTEGRATIONS` the single list of what is adapted.
    """
    backends: dict[BackendId, Backend] = {}
    info: list[BackendInfo] = []
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
        backends[BackendId.ZWAVE] = ZWaveBackend(driver=driver, profiles=profiles)
        info.append(
            BackendInfo(
                backend_id=BackendId.ZWAVE,
                upstream_domain="zwave_js",
                upstream_version=async_get_server_version(typed),
            )
        )
        break
    return backends, tuple(info)


async def _async_version(hass: HomeAssistant) -> str | None:
    """Return the version this integration declares in its manifest."""
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version
    return None if version is None else str(version)
