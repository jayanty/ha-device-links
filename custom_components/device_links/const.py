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

# Which Zigbee2MQTT to adapt (E25). Never hardcoded: the base topic is how a Zigbee2MQTT
# instance is addressed, every request and every retained topic hangs off it, and a second
# instance on the same broker uses a different one. The default is Zigbee2MQTT's own, so a
# single-instance house never has to open the options at all.
OPTION_ZIGBEE_BASE_TOPIC: Final = "zigbee_base_topic"
DEFAULT_ZIGBEE_BASE_TOPIC: Final = "zigbee2mqtt"

# The YAML mirror (Decision D8, FR-P2). Off by default, because it writes files into
# somebody's configuration directory and a feature that does that without being asked is a
# feature that surprises people. On, every profile change writes the same YAML
# `profiles/export` answers with, so a user who keeps `/config` in git sees their rules
# change in a diff rather than inside `.storage`.
OPTION_YAML_MIRROR: Final = "yaml_mirror"

# Where the mirror writes, relative to the configuration directory and never outside it.
# PRD Section 6.3's own path. Relative on purpose: an absolute one would let a setting in a
# UI form point a writer, and a pruner, at any directory Home Assistant can reach.
OPTION_YAML_MIRROR_PATH: Final = "yaml_mirror_path"
DEFAULT_YAML_MIRROR_PATH: Final = "device_links/profiles"
