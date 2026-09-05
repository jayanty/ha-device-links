"""Stage 0 Z3: prove the Z-Wave association write path on the one approved sandbox.

Jayant approved exactly one Z-Wave write target on 2026-09-05, recorded in CLAUDE.md
Section 3: node 36 (Bedroom Scene Controller, Zooz ZEN35), association group 8
("Button 2 - Held"), adding and then removing node 1 (the controller). Group 8 is unused
by the bedroom design and was confirmed empty by the Z2 fixture before this was written.

Every other target is refused before a connection is opened. The refusal is a pure
function so it can be tested on a laptop with no radio anywhere near it.

This opens its own connection to zwave-js-server rather than going through the zwave_js
integration. That is deliberate and is confined to tools/: PRD Decision D19 keeps a
standalone client as a probe, while the integration itself always reuses the zwave_js
driver (Decision D2 (a), see backends/zwave_accessor.py).

Run inside the Home Assistant Core container, which can reach the add-on:

    ssh root@<ha> 'docker exec -i homeassistant python3 -' < tools/probe_zwave_write.py
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# The approved sandbox, and nothing else. Changing these constants is a decision that
# needs Jayant's explicit approval for the specific new target, not a code review.
APPROVED_SOURCE_NODE = 36
APPROVED_GROUP = 8
APPROVED_TARGET_NODE = 1

WS_URL = "ws://a0d7b954-zwavejs2mqtt:3000"


class SandboxViolationError(Exception):
    """Raised when a write outside the approved Stage 0 sandbox is attempted."""


def assert_in_sandbox(source_node: int, group: int, target_node: int) -> None:
    """Refuse any write Jayant has not approved. Called before anything connects."""
    approved = (APPROVED_SOURCE_NODE, APPROVED_GROUP, APPROVED_TARGET_NODE)
    if (source_node, group, target_node) != approved:
        raise SandboxViolationError(
            f"REFUSED: node {source_node} group {group} target {target_node} is outside "
            f"the approved Stage 0 sandbox (node {APPROVED_SOURCE_NODE} group "
            f"{APPROVED_GROUP} target {APPROVED_TARGET_NODE}). Get explicit approval "
            "from Jayant for this specific write before changing these constants."
        )


def assert_group_was_empty(observed: Sequence[dict[str, Any]]) -> None:
    """Refuse to write into a group that someone is already using.

    Z3 is only safe because group 8 is unused. If a real design has since put an entry
    there, restoring the group afterwards would no longer be provably correct.
    """
    if observed:
        raise SandboxViolationError(
            f"REFUSED: node {APPROVED_SOURCE_NODE} group {APPROVED_GROUP} is not empty "
            f"(contains {observed!r}). The sandbox assumed an unused group. Stop and "
            "record this in docs/stage0-report.md instead of writing."
        )


def _normalise(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce driver association addresses to the comparable shape used in fixtures."""
    return sorted(
        ({"node_id": t["nodeId"], "endpoint": t.get("endpoint")} for t in targets),
        key=lambda t: (t["node_id"], t["endpoint"] if t["endpoint"] is not None else -1),
    )


async def main() -> None:  # pragma: no cover - runs only against live hardware
    """Read, add, read, remove, read. Restore is proven, not assumed."""
    # Imported here so the sandbox guards above stay importable, and therefore
    # testable, on a machine that has neither aiohttp nor the Z-Wave library.
    import aiohttp  # noqa: PLC0415
    from zwave_js_server.client import Client  # noqa: PLC0415
    from zwave_js_server.const import CommandClass  # noqa: PLC0415
    from zwave_js_server.model.association import AssociationAddress  # noqa: PLC0415

    assert_in_sandbox(APPROVED_SOURCE_NODE, APPROVED_GROUP, APPROVED_TARGET_NODE)

    result: dict[str, Any] = {"timing_ms": {}}

    async with aiohttp.ClientSession() as session:
        client = Client(WS_URL, session)
        await client.connect()
        listen_ready = asyncio.Event()
        listen_task = asyncio.create_task(client.listen(listen_ready))
        await listen_ready.wait()

        assert client.driver is not None
        controller = client.driver.controller
        node = controller.nodes[APPROVED_SOURCE_NODE]
        # AssociationAddress carries the controller as its first field on
        # zwave-js-server-python 0.73.0, not just a node id.
        source = AssociationAddress(controller, node_id=APPROVED_SOURCE_NODE)
        target = AssociationAddress(controller, node_id=APPROVED_TARGET_NODE)

        result["node"] = {
            "node_id": node.node_id,
            "label": node.device_config.label,
            "status": node.status.value,
            "ready": node.ready,
        }

        async def read_group() -> list[dict[str, Any]]:
            associations = await controller.async_get_associations(source)
            entries = associations.get(APPROVED_GROUP, [])
            return _normalise([{"nodeId": a.node_id, "endpoint": a.endpoint} for a in entries])

        # 1. Read before writing, and refuse if anyone else is using the group.
        result["before"] = await read_group()
        assert_group_was_empty(result["before"])

        # 2. Ask the driver whether this association is even permitted.
        check = await controller.async_check_association(source, APPROVED_GROUP, target)
        result["check_result"] = {"name": check.name, "value": check.value}

        # 3. Add, then read back.
        started = time.monotonic()
        await controller.async_add_associations(
            source, APPROVED_GROUP, [target], wait_for_result=True
        )
        result["timing_ms"]["add"] = round((time.monotonic() - started) * 1000)
        result["after_add_cached"] = await read_group()

        # Does the driver cache reflect the write without an explicit refresh? This is
        # what decides whether FR-B4 deep verify is mandatory after every write.
        started = time.monotonic()
        await node.async_refresh_cc_values(CommandClass.ASSOCIATION)
        result["timing_ms"]["refresh_cc_values"] = round((time.monotonic() - started) * 1000)
        result["after_add_refreshed"] = await read_group()
        result["cache_updated_without_refresh"] = (
            result["after_add_cached"] == result["after_add_refreshed"]
        )

        # 4. Remove, then read back, proving restoration.
        started = time.monotonic()
        await controller.async_remove_associations(
            source, APPROVED_GROUP, [target], wait_for_result=True
        )
        result["timing_ms"]["remove"] = round((time.monotonic() - started) * 1000)
        await node.async_refresh_cc_values(CommandClass.ASSOCIATION)
        result["after_remove"] = await read_group()
        result["restored"] = result["after_remove"] == result["before"]

        # 5. Lifeline must be untouched throughout.
        associations = await controller.async_get_associations(source)
        result["lifeline_after"] = _normalise(
            [{"nodeId": a.node_id, "endpoint": a.endpoint} for a in associations.get(1, [])]
        )

        listen_task.cancel()
        await client.disconnect()

    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
