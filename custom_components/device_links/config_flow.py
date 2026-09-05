"""Config flow for Device Links.

Single instance, no user input beyond confirmation. Setup is refused when none of the
upstream protocol integrations is loaded, so the user gets a translated reason instead of
an integration that silently does nothing (quality-scale rule test-before-configure).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import BACKEND_INTEGRATIONS, DOMAIN, INTEGRATION_TITLE


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
