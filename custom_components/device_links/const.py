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

# Events on the Home Assistant bus (FR-E2). Every payload is plain JSON: automations and
# the recorder both go through it, and a payload carrying an enum or a dataclass fails at
# the moment somebody's automation fires rather than at the moment it was written.
EVENT_JOB_FINISHED: Final = f"{DOMAIN}_job_finished"
EVENT_DRIFT_DETECTED: Final = f"{DOMAIN}_drift_detected"
EVENT_PENDING_WAKEUP: Final = f"{DOMAIN}_pending_wakeup"

# Config entry options. Auto-apply on a profile switch is off unless somebody asks for it
# (FR-E1): a select box is a control people try in order to find out what it does, and
# this one names whole sets of associations across a house.
OPTION_AUTO_APPLY_ON_PROFILE_SWITCH: Final = "auto_apply_on_profile_switch"

# The advanced Z-Wave services write to an association group directly, with no rule and no
# plan behind them (Decision D14). They are absent until somebody turns this on, which is
# what makes them expert tools rather than a shortcut past the plan dialog.
OPTION_ENABLE_RAW_SERVICES: Final = "enable_raw_services"
