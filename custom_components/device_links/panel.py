"""Serving the panel bundle and putting the panel in the sidebar.

Two decisions are worth setting out, because they look like they contradict each other and
do not.

**The version is in the static URL.** The bundle is served from
`/device_links_static/<cache key>/device-links-panel.js`, and the cache key is the
integration's own version. A HACS update therefore changes the URL, so no browser, proxy or
service worker anywhere in the path can answer with the previous bundle: the previous
bundle lives at a URL nothing asks for any more. That is the release case, and it is the
one where a stale bundle is silent and long lived.

**Cache headers are off.** Within one version the URL does not move, which is exactly the
dev loop: `tools/ha_deploy.py` pulls a frontend-only change, reports `browser_reload` and
does not ask for a restart, because nothing Python changed. Serving with
`cache_headers=False` means aiohttp sends `Last-Modified` and an `ETag` and no
`Cache-Control`, so a hard refresh fetches the new bytes and a normal reload revalidates
rather than being told the file is good for a year. The cost is a conditional request per
page load for a 40 kB file on a LAN, which is not a cost.

A dev deploy that *did* restart Home Assistant gets the stronger guarantee anyway: the
cache key picks up the deployed commit from `.deployed`, so the URL moves for that deploy
too. What is deliberately not attempted is making a frontend-only deploy move the URL,
because nothing re-registers anything without a restart and a URL that claimed to have
moved when it had not would be worse than one that plainly did not.

**Static paths cannot be unregistered.** aiohttp's router has no removal, so the path is
registered at most once per URL for the life of the process and the set of URLs already
claimed is remembered in `hass.data`. That is genuinely global rather than per entry, like
the WebSocket command registration, which is why it is not on `runtime_data`. The panel
itself is per entry and is removed on unload.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components import frontend, panel_custom

# `StaticPathConfig` is re-exported from `http.server` with a `noqa` rather than through
# `__all__`, so a strict checker calls it a private import. It is the supported public
# name (every core integration that serves a file uses it), and reaching into
# `http.server` to satisfy the checker would be the genuinely private import.
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined]
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, INTEGRATION_TITLE, PANEL_URL_PATH, STATIC_URL_BASE

if TYPE_CHECKING:
    from . import DeviceLinksConfigEntry
    from .deployment import Deployment

# Where the built bundle is committed, relative to this package, and what it is called.
# Both are spelled in `frontend/vite.config.ts` as well; `tests/test_panel.py` asserts the
# file this names exists, so the two cannot drift apart unnoticed.
BUNDLE_DIR_NAME: Final = "frontend"
BUNDLE_FILE_NAME: Final = "device-links-panel.js"

# The custom element `frontend/src/panel.ts` defines.
PANEL_ELEMENT: Final = "device-links-panel"

PANEL_ICON: Final = "mdi:link-variant"

# The cache key goes into a URL path, and both halves of it are read off disk: the version
# from the manifest and the commit from `.deployed`. Anything outside this set is dropped
# rather than escaped, because there is no legitimate value that needs escaping.
_SAFE_KEY: Final = re.compile(r"[^A-Za-z0-9._-]")

# How much of a commit hash is enough to tell two deploys apart without a URL nobody can
# read. Twelve hex characters is what `git log --abbrev-commit` settles on for a large
# repository, and collisions at this length are not a class of bug that matters here: the
# worst case is a browser reusing a bundle from a different commit of the same version,
# which is exactly what the situation is without the commit at all.
_COMMIT_LENGTH: Final = 12

# Static URLs already claimed in this process. See the module docstring: a route cannot be
# removed, so this is what keeps a reload from registering a duplicate.
STATIC_PATHS_KEY: HassKey[set[str]] = HassKey(f"{DOMAIN}_static_paths")


@callback
def cache_key(version: str | None, deployment: Deployment | None) -> str:
    """Return the path segment that names the code being served.

    The version alone for a normal install, which is what makes an update a different URL.
    The version and the deployed commit for a dev deploy, which is what makes two deploys
    of the same version different URLs when one of them restarted Home Assistant.
    """
    key = _safe_segment(version, "dev")
    commit = None if deployment is None else deployment.commit
    if commit:
        short = _safe_segment(commit, "")[:_COMMIT_LENGTH]
        if short:
            key = f"{key}-{short}"
    return key


def _safe_segment(value: str | None, fallback: str) -> str:
    """Return one URL path segment that cannot be anything but a name.

    Both inputs come off disk (the manifest, and `.deployed` as the deploy tool wrote it),
    so neither is attacker supplied in any ordinary sense. This is still the one place a
    value from a file becomes part of a route, and a segment of dots is the difference
    between naming a directory and naming its parent. Unsafe characters are dropped rather
    than escaped because no legitimate version or commit contains one.
    """
    cleaned = _SAFE_KEY.sub("", value or "")
    if not cleaned or set(cleaned) <= {"."}:
        return fallback
    return cleaned


@callback
def bundle_directory() -> Path:
    """Return the directory the committed bundle lives in."""
    return Path(__file__).parent / BUNDLE_DIR_NAME


async def async_register_panel(hass: HomeAssistant, entry: DeviceLinksConfigEntry) -> None:
    """Serve the bundle and put Device Links in the sidebar, for admins only.

    Called from `async_setup_entry`. Registering the panel again over one that is already
    there is a replacement rather than an error, because Home Assistant refuses to
    overwrite a panel url path and a half-completed setup could leave one behind.
    """
    runtime = entry.runtime_data
    key = cache_key(runtime.version, runtime.deployment)
    url_base = f"{STATIC_URL_BASE}/{key}"
    claimed = hass.data.setdefault(STATIC_PATHS_KEY, set())
    if url_base not in claimed:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(url_base, str(bundle_directory()), cache_headers=False)]
        )
        claimed.add(url_base)

    module_url = f"{url_base}/{BUNDLE_FILE_NAME}"
    config: dict[str, Any] = {
        # What the panel compares against the version its bundle was built from (E33).
        "version": runtime.version,
        "cache_key": key,
        "bundle_url": module_url,
        # Whether the rule editor may offer the HA-executed opt-ins at all (FR-H1). It is
        # here rather than in a command because it cannot change without the config entry
        # reloading, which re-registers this panel with the new answer, and because a
        # checkbox the backend would refuse is worse than no checkbox.
        "hybrid_legs": runtime.coordinator.hybrid_allowed,
    }
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        sidebar_title=INTEGRATION_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=module_url,
        embed_iframe=False,
        require_admin=True,
        config=config,
    )


@callback
def async_unregister_panel(hass: HomeAssistant) -> None:
    """Take the panel out of the sidebar.

    The static path stays: aiohttp cannot remove a route, and leaving it serving a file
    nobody imports costs nothing. `STATIC_PATHS_KEY` remembers it so the next setup does
    not try to register it a second time, which would raise.
    """
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)


__all__ = [
    "BUNDLE_DIR_NAME",
    "BUNDLE_FILE_NAME",
    "PANEL_ELEMENT",
    "STATIC_PATHS_KEY",
    "async_register_panel",
    "async_unregister_panel",
    "bundle_directory",
    "cache_key",
]
