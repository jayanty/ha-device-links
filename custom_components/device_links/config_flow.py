"""Config flow for Device Links, and the two options that are off until somebody asks.

Single instance, no user input beyond confirmation. Setup is refused when none of the
upstream protocol integrations is loaded, so the user gets a translated reason instead of
an integration that silently does nothing (quality-scale rule test-before-configure).

Both options are off by default and both are off for the same reason: each turns a
deliberate act into an automatic one. Auto-apply makes a select box rewrite associations
across a house (FR-E1), and the raw services write to an association group with no rule
and no plan behind them (Decision D14). An option that exists only in code is one nobody
can turn on, which is why this flow exists at all; saving reloads the entry, which is what
makes the raw services appear and disappear without a restart.

Auto-apply is deliberately about the Active profile select and nothing else. Decision D18
says the plan dialog is always shown, so the panel and the WebSocket command it calls open
a plan whatever this is set to; the select is the one surface with nowhere to show one, and
this option is the answer for somebody who wants it to act anyway.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    BACKEND_INTEGRATIONS,
    DEFAULT_ZIGBEE_BASE_TOPIC,
    DOMAIN,
    INTEGRATION_TITLE,
    OPTION_AUTO_APPLY_ON_PROFILE_SWITCH,
    OPTION_ENABLE_RAW_SERVICES,
    OPTION_ZIGBEE_BASE_TOPIC,
)


class DeviceLinksConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the single-instance setup flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm setup, once, after checking that a backend is available."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if not self._async_loaded_backends():
            return self.async_abort(reason="no_backend")

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title=INTEGRATION_TITLE, data={})

    def _async_loaded_backends(self) -> list[str]:
        """Return the upstream protocol integrations that are currently loaded."""
        return [domain for domain in BACKEND_INTEGRATIONS if domain in self.hass.config.components]

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DeviceLinksOptionsFlow:
        """Return the options flow for this entry."""
        return DeviceLinksOptionsFlow()


class DeviceLinksOptionsFlow(OptionsFlow):
    """The two things a user can turn on, and the one thing they may have to say."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options, and save exactly what was chosen.

        The Zigbee base topic is not a switch and is not off by default: it is how a
        Zigbee2MQTT instance is addressed, so it always has a value, and the value is
        Zigbee2MQTT's own default. Somebody who changed theirs, or who runs a second
        instance, is the only person who ever has to touch it (E25).
        """
        if user_input is not None:
            return self.async_create_entry(data=_cleaned(user_input))
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        OPTION_AUTO_APPLY_ON_PROFILE_SWITCH,
                        default=options.get(OPTION_AUTO_APPLY_ON_PROFILE_SWITCH, False),
                    ): cv.boolean,
                    vol.Optional(
                        OPTION_ENABLE_RAW_SERVICES,
                        default=options.get(OPTION_ENABLE_RAW_SERVICES, False),
                    ): cv.boolean,
                    vol.Optional(
                        OPTION_ZIGBEE_BASE_TOPIC,
                        default=options.get(OPTION_ZIGBEE_BASE_TOPIC, DEFAULT_ZIGBEE_BASE_TOPIC),
                    ): cv.string,
                }
            ),
        )


def _cleaned(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return the submitted options with the base topic tidied, or dropped when emptied.

    A topic with stray spaces or a trailing slash is a topic nothing is published on, and
    the failure it produces is silence: every retained payload lands on a filter nobody
    subscribed to and the bridge reads as absent. Cleared to nothing means "use the
    default", which is what the field shows, rather than "subscribe to `/bridge/devices`".
    """
    base = str(user_input.get(OPTION_ZIGBEE_BASE_TOPIC, "")).strip().strip("/")
    return {
        **user_input,
        OPTION_ZIGBEE_BASE_TOPIC: base or DEFAULT_ZIGBEE_BASE_TOPIC,
    }
