"""Config flow coverage. Quality-scale rule config-flow-test-coverage wants 100%."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_links.const import DOMAIN, INTEGRATION_TITLE


@pytest.mark.parametrize("backend", ["zwave_js", "mqtt", "matter"])
async def test_user_flow_creates_entry_for_each_backend(hass: HomeAssistant, backend: str) -> None:
    """Any one loaded backend integration is enough to set Device Links up."""
    hass.config.components.add(backend)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == INTEGRATION_TITLE
    assert result["data"] == {}


async def test_user_flow_aborts_without_a_backend(hass: HomeAssistant) -> None:
    """Without Z-Wave JS, MQTT, or Matter there is nothing to manage."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_backend"


async def test_only_one_instance_is_allowed(hass: HomeAssistant) -> None:
    """Rule unique-config-entry: a second setup attempt aborts."""
    hass.config.components.add("zwave_js")
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
