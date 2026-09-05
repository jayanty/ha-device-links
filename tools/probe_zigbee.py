"""Stage 0 G1: capture the retained Zigbee2MQTT bridge topics.

Read-only by construction. It subscribes to four retained bridge topics and publishes
nothing: no `bridge/request/...` topic is ever written, so no bind, unbind, or group
change can result from running this.

Broker credentials are read from Home Assistant's own MQTT config entry inside the
container and are never printed, so they do not reach a transcript or a fixture.

Run inside the Home Assistant Core container:

    ssh root@<ha> 'docker exec -i homeassistant python3 -' < tools/probe_zigbee.py
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

CONFIG_ENTRIES = "/config/.storage/core.config_entries"
BASE_TOPIC = "zigbee2mqtt"
TOPICS = (
    f"{BASE_TOPIC}/bridge/devices",
    f"{BASE_TOPIC}/bridge/groups",
    f"{BASE_TOPIC}/bridge/info",
    f"{BASE_TOPIC}/bridge/state",
)
RETAINED_WAIT_SECONDS = 20


def _mqtt_credentials() -> dict[str, Any]:
    """Read broker settings from Home Assistant's MQTT config entry.

    Returned in full because the client needs them; the caller must never print them.
    """
    with Path(CONFIG_ENTRIES).open() as handle:
        entries = json.load(handle)["data"]["entries"]
    for entry in entries:
        if entry["domain"] == "mqtt":
            return entry["data"]
    raise LookupError("no mqtt config entry found")


async def main() -> None:  # pragma: no cover - runs only against a live broker
    """Collect each retained topic once, then print them as one JSON document."""
    import aiomqtt  # noqa: PLC0415

    credentials = _mqtt_credentials()
    collected: dict[str, Any] = dict.fromkeys(TOPICS)

    async with aiomqtt.Client(
        hostname=credentials["broker"],
        port=int(credentials["port"]),
        username=credentials.get("username"),
        password=credentials.get("password"),
    ) as client:
        for topic in TOPICS:
            await client.subscribe(topic)

        async def collect() -> None:
            async for message in client.messages:
                topic = str(message.topic)
                if topic in collected and collected[topic] is None:
                    try:
                        collected[topic] = json.loads(message.payload)
                    except (ValueError, TypeError):
                        collected[topic] = message.payload.decode(errors="replace")
                if all(value is not None for value in collected.values()):
                    return

        # A missing retained topic is a finding, not a crash: it is reported in
        # missing_topics so the report can say which one did not arrive.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(collect(), timeout=RETAINED_WAIT_SECONDS)

    missing = [topic for topic, value in collected.items() if value is None]
    print(
        json.dumps(
            {
                "base_topic": BASE_TOPIC,
                "missing_topics": missing,
                **{topic.rsplit("/", 1)[-1]: value for topic, value in collected.items()},
            },
            default=str,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
