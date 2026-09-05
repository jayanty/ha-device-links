"""Stage 0 Z8: how hybrid leg kind (c) drives a scene-controller button LED.

Decision D6 asks whether a Zooz ZEN35 small-button LED can be driven to follow a remote
light, and if so by which mechanism. There are two candidates and this probe measures
both on the same button:

1. The LED-mode configuration parameter (node 36 parameter 3, "LED Indicator (Button 2)").
   Configuration writes land in device NVM, so they carry flash-wear cost and need the
   write hygiene described in FR-H2.
2. Indicator CC (0x87) value 68 property 2, "Button 2 indication". Indicator sets do not
   touch NVM, which is why the PRD prefers this path when it exists.

Approved by Jayant on 2026-09-05 as Stage 0 item Z8, scoped to node 36 button 2 only.
Both writes record the value first and restore it afterwards.

Run inside the Home Assistant Core container:

    ssh root@<ha> 'docker exec -i homeassistant python3 -' < tools/probe_zwave_led.py
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

# The approved sandbox for Z8, and nothing else. Button 2 on node 36 is unassigned in
# the bedroom design (Decision D15), which is why it is the safe button to disturb.
APPROVED_NODE = 36
APPROVED_LED_PARAMETER = 3
APPROVED_INDICATOR_ID = 68
INDICATOR_PROPERTY_KEY = 2

# Command class ids, named so the probe reads as intent rather than magic numbers.
CC_CONFIGURATION = 112
CC_INDICATOR = 135

# ZEN35 LED mode 3 is "Always on", which makes the write observable on the device.
LED_MODE_ALWAYS_ON = 3

WS_URL = "ws://a0d7b954-zwavejs2mqtt:3000"


class SandboxViolationError(Exception):
    """Raised when a write outside the approved Stage 0 sandbox is attempted.

    Deliberately defined per probe rather than shared from probe_common. Probe scripts
    are piped straight into a container as a single file:

        ssh root@<ha> 'docker exec -i homeassistant python3 -' < tools/<probe>.py

    so nothing else in tools/ is importable at runtime. A shared import would make the
    guard unrunnable exactly where it is needed. The cost is that the two probes raise
    unrelated classes, which is harmless because each runs standalone; the tests import
    each module's own class rather than assuming they are interchangeable.
    """


def assert_led_target_in_sandbox(node_id: int, parameter: int) -> None:
    """Refuse a configuration write to anything but node 36 parameter 3."""
    if (node_id, parameter) != (APPROVED_NODE, APPROVED_LED_PARAMETER):
        raise SandboxViolationError(
            f"REFUSED: node {node_id} parameter {parameter} is outside the approved Z8 "
            f"sandbox (node {APPROVED_NODE} parameter {APPROVED_LED_PARAMETER}). "
            "Parameter writes land in device NVM; get Jayant's approval for the specific "
            "target before changing these constants."
        )


def assert_indicator_target_in_sandbox(node_id: int, indicator_id: int) -> None:
    """Refuse an Indicator CC write to anything but node 36 button 2."""
    if (node_id, indicator_id) != (APPROVED_NODE, APPROVED_INDICATOR_ID):
        raise SandboxViolationError(
            f"REFUSED: node {node_id} indicator {indicator_id} is outside the approved Z8 "
            f"sandbox (node {APPROVED_NODE} indicator {APPROVED_INDICATOR_ID})."
        )


async def _measure_parameter_path(node: Any, find_value: Any, result: dict[str, Any]) -> None:
    """Write the LED-mode configuration parameter and restore the recorded value.

    Configuration writes land in device NVM, which is the cost this path carries.
    """
    param = find_value(CC_CONFIGURATION, APPROVED_LED_PARAMETER)
    result["param_before"] = param.value
    result["param_metadata"] = {
        "label": param.metadata.label,
        "states": param.metadata.states,
        "writeable": param.metadata.writeable,
    }

    started = time.monotonic()
    await node.async_set_value(param, LED_MODE_ALWAYS_ON, wait_for_result=True)
    result["timing_ms"]["param_write"] = round((time.monotonic() - started) * 1000)
    await asyncio.sleep(1)
    result["param_after_write"] = find_value(CC_CONFIGURATION, APPROVED_LED_PARAMETER).value

    started = time.monotonic()
    await node.async_set_value(param, result["param_before"], wait_for_result=True)
    result["timing_ms"]["param_restore"] = round((time.monotonic() - started) * 1000)
    await asyncio.sleep(1)
    result["param_after_restore"] = find_value(CC_CONFIGURATION, APPROVED_LED_PARAMETER).value
    result["param_restored"] = result["param_after_restore"] == result["param_before"]


async def _measure_indicator_path(node: Any, find_value: Any, result: dict[str, Any]) -> None:
    """Set the per-button Indicator CC value and restore it. Does not touch NVM."""
    indicators = [
        {
            "indicator_id": value.property_,
            "property_key": value.property_key,
            "label": value.metadata.label,
            "writeable": value.metadata.writeable,
            "value": value.value,
        }
        for value in node.values.values()
        if value.command_class == CC_INDICATOR and value.metadata.writeable
    ]
    result["indicator_cc_supported"] = bool(indicators)
    result["indicator_ids"] = sorted(
        (i for i in indicators if isinstance(i["indicator_id"], int)),
        key=lambda i: i["indicator_id"],
    )

    indicator = find_value(CC_INDICATOR, APPROVED_INDICATOR_ID, INDICATOR_PROPERTY_KEY)
    result["indicator_before"] = indicator.value

    started = time.monotonic()
    await node.async_set_value(indicator, True, wait_for_result=True)
    result["timing_ms"]["indicator_write"] = round((time.monotonic() - started) * 1000)
    await asyncio.sleep(1)
    result["indicator_after_write"] = find_value(
        CC_INDICATOR, APPROVED_INDICATOR_ID, INDICATOR_PROPERTY_KEY
    ).value

    started = time.monotonic()
    await node.async_set_value(indicator, result["indicator_before"], wait_for_result=True)
    result["timing_ms"]["indicator_restore"] = round((time.monotonic() - started) * 1000)
    await asyncio.sleep(1)
    result["indicator_after_restore"] = find_value(
        CC_INDICATOR, APPROVED_INDICATOR_ID, INDICATOR_PROPERTY_KEY
    ).value
    result["indicator_restored"] = result["indicator_after_restore"] == result["indicator_before"]


async def main() -> None:  # pragma: no cover - runs only against live hardware
    """Measure both LED paths on button 2, restoring each recorded value."""
    # Imported here so the sandbox guards stay importable, and testable, on a machine
    # with neither aiohttp nor the Z-Wave library.
    import aiohttp  # noqa: PLC0415
    from zwave_js_server.client import Client  # noqa: PLC0415

    assert_led_target_in_sandbox(APPROVED_NODE, APPROVED_LED_PARAMETER)
    assert_indicator_target_in_sandbox(APPROVED_NODE, APPROVED_INDICATOR_ID)

    result: dict[str, Any] = {"timing_ms": {}}

    async with aiohttp.ClientSession() as session:
        client = Client(WS_URL, session)
        await client.connect()
        listen_ready = asyncio.Event()
        listen_task = asyncio.create_task(client.listen(listen_ready))
        await listen_ready.wait()

        assert client.driver is not None
        node = client.driver.controller.nodes[APPROVED_NODE]

        def find_value(command_class: int, prop: Any, property_key: Any = None) -> Any:
            for value in node.values.values():
                if (
                    value.command_class == command_class
                    and value.property_ == prop
                    and value.property_key == property_key
                ):
                    return value
            raise LookupError(f"no value for cc {command_class} property {prop}")

        await _measure_parameter_path(node, find_value, result)
        await _measure_indicator_path(node, find_value, result)

        listen_task.cancel()
        await client.disconnect()

    print(json.dumps(result, indent=1, sort_keys=True, default=str))


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
