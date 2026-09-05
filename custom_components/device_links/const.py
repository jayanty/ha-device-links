"""Constants for the Device Links integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "device_links"
INTEGRATION_TITLE: Final = "Device Links"

PANEL_URL_PATH: Final = "device_links"
STATIC_URL_BASE: Final = "/device_links_static"

STORAGE_KEY: Final = "device_links.profiles"
STORAGE_VERSION: Final = 1

# Upstream integrations this one adapts. At least one must be loaded for setup to make
# sense. Order is the order backends are presented in the UI.
BACKEND_INTEGRATIONS: Final = ("zwave_js", "mqtt", "matter")
