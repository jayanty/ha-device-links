"""Config flow coverage. Quality-scale rule config-flow-test-coverage wants 100%."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_links.const import (
    DEFAULT_YAML_MIRROR_PATH,
    DEFAULT_ZIGBEE_BASE_TOPIC,
    DOMAIN,
    INTEGRATION_TITLE,
    OPTION_AUTO_APPLY_ON_PROFILE_SWITCH,
    OPTION_ENABLE_RAW_SERVICES,
    OPTION_HYBRID_LEGS,
    OPTION_MATTER_WRITES,
    OPTION_YAML_MIRROR,
    OPTION_YAML_MIRROR_PATH,
    OPTION_ZIGBEE_BASE_TOPIC,
)


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


async def test_the_options_flow_shows_every_switch_off(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Every switch is off unless somebody asks, and each is off for its own reason.

    Auto-apply writes to a house, the raw services arm expert tools, the mirror writes
    files into a configuration directory, hybrid legs are the one part of this integration
    that stops working when Home Assistant does (FR-H1), and Matter writes are the one
    switch that is off because the code behind it has never met hardware (FR-B7, D11).
    """
    result = await hass.config_entries.options.async_init(device_links_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"]({})
    assert schema == {
        OPTION_AUTO_APPLY_ON_PROFILE_SWITCH: False,
        OPTION_ENABLE_RAW_SERVICES: False,
        OPTION_ZIGBEE_BASE_TOPIC: DEFAULT_ZIGBEE_BASE_TOPIC,
        OPTION_HYBRID_LEGS: False,
        OPTION_MATTER_WRITES: False,
        OPTION_YAML_MIRROR: False,
        OPTION_YAML_MIRROR_PATH: DEFAULT_YAML_MIRROR_PATH,
    }


async def test_the_options_flow_saves_what_was_chosen(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """Saving reloads the entry, which is what makes the raw services appear (D14)."""
    result = await hass.config_entries.options.async_init(device_links_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            OPTION_AUTO_APPLY_ON_PROFILE_SWITCH: True,
            OPTION_ENABLE_RAW_SERVICES: True,
            OPTION_ZIGBEE_BASE_TOPIC: "zigbee2mqtt",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert device_links_entry.options == {
        OPTION_AUTO_APPLY_ON_PROFILE_SWITCH: True,
        OPTION_ENABLE_RAW_SERVICES: True,
        OPTION_ZIGBEE_BASE_TOPIC: "zigbee2mqtt",
        OPTION_HYBRID_LEGS: False,
        OPTION_MATTER_WRITES: False,
        OPTION_YAML_MIRROR: False,
        OPTION_YAML_MIRROR_PATH: DEFAULT_YAML_MIRROR_PATH,
    }
    assert hass.services.has_service(DOMAIN, "zwave_add_association")


async def test_a_second_zigbee2mqtt_instance_is_named_by_its_base_topic(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """E25: the base topic is how a Zigbee2MQTT instance is addressed, so it is a setting."""
    result = await hass.config_entries.options.async_init(device_links_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {OPTION_ZIGBEE_BASE_TOPIC: "  zigbee2mqtt_upstairs/ "}
    )
    await hass.async_block_till_done()

    assert device_links_entry.options[OPTION_ZIGBEE_BASE_TOPIC] == "zigbee2mqtt_upstairs"


async def test_clearing_the_base_topic_puts_the_default_back(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """An empty topic would subscribe to `/bridge/devices`, which nothing publishes on."""
    result = await hass.config_entries.options.async_init(device_links_entry.entry_id)

    await hass.config_entries.options.async_configure(
        result["flow_id"], {OPTION_ZIGBEE_BASE_TOPIC: "   "}
    )
    await hass.async_block_till_done()

    assert device_links_entry.options[OPTION_ZIGBEE_BASE_TOPIC] == DEFAULT_ZIGBEE_BASE_TOPIC


async def test_the_options_flow_keeps_what_was_already_chosen(
    hass: HomeAssistant, device_links_entry: MockConfigEntry
) -> None:
    """A form that forgets the current setting is a form that turns things off by accident."""
    hass.config_entries.async_update_entry(
        device_links_entry, options={OPTION_ENABLE_RAW_SERVICES: True}
    )
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(device_links_entry.entry_id)

    assert result["data_schema"]({}) == {
        OPTION_AUTO_APPLY_ON_PROFILE_SWITCH: False,
        OPTION_ENABLE_RAW_SERVICES: True,
        OPTION_ZIGBEE_BASE_TOPIC: DEFAULT_ZIGBEE_BASE_TOPIC,
        OPTION_HYBRID_LEGS: False,
        OPTION_MATTER_WRITES: False,
        OPTION_YAML_MIRROR: False,
        OPTION_YAML_MIRROR_PATH: DEFAULT_YAML_MIRROR_PATH,
    }
