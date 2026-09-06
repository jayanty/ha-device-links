"""The sidebar panel: what is registered, what comes off again, and what the panel is told.

Three things are worth proving here and none of them are visible from the browser until
somebody has already been surprised by them.

**A reload must not leave two panels or a second static route.** Home Assistant removes a
panel by url path, so a second registration silently replaces the first and a reload that
forgot to remove leaves the previous config behind. aiohttp, meanwhile, cannot remove a
route at all, so the static path has to be registered exactly once per url for the life of
the process, which is a different lifetime from the config entry's.

**The URL a browser fetches has to change when the code does.** The version is in the path
so a released update cannot be served from cache, and cache headers are off so a dev deploy
that only changed the frontend is picked up by a hard refresh without a restart.

**The panel is told the backend's version.** That is the whole of the E33 handshake: the
bundle knows what it was built from, the backend says what it is, and a difference means
the page has been open across an update and wants reloading.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from homeassistant.components.frontend import DATA_PANELS
from homeassistant.components.http import HomeAssistantHTTP
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_links import panel as panel_module
from custom_components.device_links.const import DOMAIN, PANEL_URL_PATH, STATIC_URL_BASE
from custom_components.device_links.deployment import Deployment

if TYPE_CHECKING:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "device_links"
BUNDLE = COMPONENT / panel_module.BUNDLE_DIR_NAME / panel_module.BUNDLE_FILE_NAME
MANIFEST_VERSION = json.loads((COMPONENT / "manifest.json").read_text())["version"]


def registered_panel(hass: HomeAssistant) -> Any:
    """Return the panel object Home Assistant is holding for us, or None."""
    return hass.data.get(DATA_PANELS, {}).get(PANEL_URL_PATH)


def panel_config(hass: HomeAssistant) -> dict[str, Any]:
    """Return the config the frontend hands to the panel element."""
    config = registered_panel(hass).config
    assert config is not None
    return config


def static_paths(hass: HomeAssistant) -> set[str]:
    """Return the static url bases this integration has claimed in this process."""
    return hass.data.get(panel_module.STATIC_PATHS_KEY, set())


# --------------------------------------------------------------------------------------
# What setup puts up
# --------------------------------------------------------------------------------------


async def test_setup_registers_an_admin_only_panel(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """The panel is ours, it is not an iframe, and only an admin sees it."""
    panel = registered_panel(hass)
    assert panel is not None
    assert panel.require_admin is True
    assert panel.sidebar_title == "Device Links"
    assert panel.component_name == "custom"
    custom = panel_config(hass)["_panel_custom"]
    assert custom["name"] == panel_module.PANEL_ELEMENT
    assert custom["embed_iframe"] is False
    assert custom["trust_external"] is False


async def test_the_module_url_carries_the_version_and_points_at_the_committed_bundle(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A browser cannot serve a stale bundle after an update, because the URL moved."""
    module_url = panel_config(hass)["_panel_custom"]["module_url"]
    assert module_url.startswith(f"{STATIC_URL_BASE}/{MANIFEST_VERSION}")
    assert module_url.endswith(f"/{panel_module.BUNDLE_FILE_NAME}")
    assert BUNDLE.is_file(), "the built bundle must be committed alongside the source"


async def test_the_static_path_is_the_bundle_directory_without_cache_headers(
    hass: HomeAssistant, zwave_js_devices: dict[int, Any], hass_storage: dict[str, Any]
) -> None:
    """Serving without cache headers is what makes a frontend-only deploy a hard refresh."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: PLC0415

    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, title="Device Links")
    entry.add_to_hass(hass)
    with patch.object(HomeAssistantHTTP, "async_register_static_paths", AsyncMock()) as register:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # The frontend component registers its own static paths through the same method, so
    # this picks out ours rather than asserting a call count that is not about us.
    ours = [
        config
        for call in register.await_args_list
        for config in call.args[0]
        if config.url_path.startswith(STATIC_URL_BASE)
    ]
    assert len(ours) == 1
    assert ours[0].url_path == f"{STATIC_URL_BASE}/{MANIFEST_VERSION}"
    assert ours[0].path == str(COMPONENT / panel_module.BUNDLE_DIR_NAME)
    assert ours[0].cache_headers is False


async def test_the_panel_is_told_the_backend_version(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """E33: the panel compares this with the version its bundle was built from."""
    config = panel_config(hass)
    assert config["version"] == MANIFEST_VERSION
    assert config["cache_key"] == MANIFEST_VERSION
    assert config["bundle_url"] == config["_panel_custom"]["module_url"]


# --------------------------------------------------------------------------------------
# What unload takes down
# --------------------------------------------------------------------------------------


async def test_unload_removes_the_panel(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Nothing of ours is left in the sidebar once the entry is gone."""
    assert registered_panel(hass) is not None
    assert await hass.config_entries.async_unload(device_links_entry.entry_id)
    await hass.async_block_till_done()
    assert registered_panel(hass) is None


async def test_a_reload_leaves_exactly_one_panel_and_one_static_path(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """The reload case, which is the one that produces duplicates when it is wrong.

    The static path matters more than the panel here: aiohttp raises on a duplicate route
    and there is no way to remove one, so a second registration would make a reload fail
    outright rather than merely leave something behind.
    """
    with patch.object(HomeAssistantHTTP, "async_register_static_paths", AsyncMock()) as register:
        await hass.config_entries.async_reload(device_links_entry.entry_id)
        await hass.async_block_till_done()
    assert device_links_entry.state is ConfigEntryState.LOADED

    panels = [key for key in hass.data.get(DATA_PANELS, {}) if key == PANEL_URL_PATH]
    assert panels == [PANEL_URL_PATH]
    ours = [
        config
        for call in register.await_args_list
        for config in call.args[0]
        if config.url_path.startswith(STATIC_URL_BASE)
    ]
    assert ours == [], "a reload must not register the static path a second time"
    assert static_paths(hass) == {f"{STATIC_URL_BASE}/{MANIFEST_VERSION}"}


async def test_registering_over_an_existing_panel_replaces_it_rather_than_raising(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Home Assistant raises on a duplicate url path, so registration removes first."""
    await panel_module.async_register_panel(hass, device_links_entry)
    assert registered_panel(hass) is not None


# --------------------------------------------------------------------------------------
# The cache key
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "deployment", "expected"),
    [
        ("0.1.0", None, "0.1.0"),
        (
            "0.1.0",
            Deployment(
                commit="abc123def4567890",
                branch="dev",
                deployed_at="2026-09-05T00:00:00Z",
                previous_commit=None,
                changed_files=3,
            ),
            "0.1.0-abc123def456",
        ),
        (None, None, "dev"),
    ],
)
def test_the_cache_key_names_the_code_that_is_running(
    version: str | None, deployment: Deployment | None, expected: str
) -> None:
    """A released install is named by its version, a dev deploy also by its commit.

    The commit is what makes the two dev deploys of one version different URLs, so a
    deploy that did restart Home Assistant cannot be answered from cache. A deploy that
    did not restart keeps the same URL on purpose: nothing re-registered it, and the hard
    refresh the deploy tool asks for is what picks the new bytes up.
    """
    assert panel_module.cache_key(version, deployment) == expected


def test_the_cache_key_cannot_carry_anything_that_is_not_a_url_path_segment() -> None:
    """It goes straight into a URL, and the values behind it come off disk."""
    deployment = Deployment(
        commit="../../etc/passwd",
        branch=None,
        deployed_at=None,
        previous_commit=None,
        changed_files=0,
    )
    key = panel_module.cache_key("1.0.0/../..", deployment)
    assert "/" not in key
    assert "\\" not in key
    assert key.strip(".") != "", "a segment of nothing but dots would name a directory"
    assert panel_module.cache_key("..", None) == "dev"
    assert panel_module.cache_key("", None) == "dev"
    assert panel_module.cache_key("1.0.0", Deployment("///", None, None, None, 0)) == "1.0.0"


# --------------------------------------------------------------------------------------
# The bundle itself
# --------------------------------------------------------------------------------------


def test_the_bundle_is_one_file_and_imports_nothing_from_a_network() -> None:
    """The premise of a local-first integration is that it works with no internet.

    One import from a CDN defeats that silently, because it works on the machine of
    whoever added it. Checked on the built artefact rather than on the source, because the
    source is not what a user runs.
    """
    text = BUNDLE.read_text()
    assert "http://" not in text
    assert "https://" not in text
    for marker in ("import(", "import ", "from "):
        assert f'{marker}"//' not in text
    assert list(BUNDLE.parent.glob("*.js")) == [BUNDLE], "the bundle must be a single module"
