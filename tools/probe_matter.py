"""Stage 0 M1: Matter binding and ACL feasibility. Read-only.

Closes PRD assumption A4: whether a custom integration can read and write Matter
attributes on Home Assistant 2026.8.3, and whether this network actually has devices
worth binding in Phase 3.

Reads only. It calls read_attribute and never write_attribute, so no Binding list and no
ACL entry is modified. Matter ACL writes are security relevant and stay behind the
options flag that defaults to off (Decision D11, FR-B7).

Run inside the Home Assistant Core container:

    ssh root@<ha> 'docker exec -i homeassistant python3 -' < tools/probe_matter.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

CONFIG_ENTRIES = "/config/.storage/core.config_entries"

# Matter cluster and attribute ids used as attribute paths "<endpoint>/<cluster>/<attr>".
DESCRIPTOR_CLUSTER = 29
DESCRIPTOR_CLIENT_LIST = 2
DESCRIPTOR_SERVER_LIST = 1
BINDING_CLUSTER = 30
BINDING_ATTRIBUTE = 0
ACCESS_CONTROL_CLUSTER = 31
ACL_ATTRIBUTE = 0
ACL_SUBJECTS_PER_ENTRY = 2
ACL_TARGETS_PER_ENTRY = 3
ACL_ENTRIES_PER_FABRIC = 4


def _matter_url() -> str:
    """Read the Matter server URL from Home Assistant's own config entry."""
    with Path(CONFIG_ENTRIES).open() as handle:
        entries = json.load(handle)["data"]["entries"]
    for entry in entries:
        if entry["domain"] == "matter":
            return str(entry["data"]["url"])
    raise LookupError("no matter config entry found")


async def _read(client: Any, node_id: int, path: str) -> Any:
    """Read one attribute and unwrap it, returning an error record rather than raising.

    read_attribute returns a dict keyed by the attribute path, for example
    {"2/29/2": [3, 6, 8]}, not the bare value. Treating the dict as the value silently
    turns every list-shaped result into "not a list", which reads as "this device has no
    client clusters" rather than as an error. Unwrap here, once.
    """
    try:
        response = await client.read_attribute(node_id, path)
    except Exception as err:  # a probe records failures, it does not crash
        return {"error": f"{type(err).__name__}: {err}"}

    if isinstance(response, dict) and len(response) == 1 and path in response:
        return response[path]
    return response


async def main() -> None:  # pragma: no cover - runs only against a live Matter fabric
    """Record the client API surface, per-endpoint client clusters, bindings, and ACLs."""
    import aiohttp  # noqa: PLC0415
    from matter_server.client.client import MatterClient  # noqa: PLC0415

    result: dict[str, Any] = {
        "read_attribute_available": hasattr(MatterClient, "read_attribute"),
        "write_attribute_available": hasattr(MatterClient, "write_attribute"),
        "accessor_notes": (
            "Home Assistant 2026.8.3 requires matter-python-client 1.3.0, which installs "
            "the matter_server package. The distribution was renamed from "
            "python-matter-server, so PRD Appendix C's references to that project and its "
            "8.1.2 archive point at the old lineage. A custom integration reaches the "
            "client through the matter config entry's runtime_data, the same pattern as "
            "the Z-Wave accessor. This probe connects to the server directly instead, "
            "which is allowed for tools/ only."
        ),
        "devices": [],
    }

    async with aiohttp.ClientSession() as session:
        client = MatterClient(_matter_url(), session)
        await client.connect()
        listen_ready = asyncio.Event()
        listen_task = asyncio.create_task(client.start_listening(listen_ready))
        await listen_ready.wait()

        result["server_info"] = {
            "sdk_version": getattr(client.server_info, "sdk_version", None),
            "schema_version": getattr(client.server_info, "schema_version", None),
        }

        for node in client.get_nodes():
            record: dict[str, Any] = {
                "node_id": node.node_id,
                "available": node.available,
                "name": node.name,
                "vendor": node.device_info.vendorName if node.device_info else None,
                "product": node.device_info.productName if node.device_info else None,
                "endpoints": {},
                "client_clusters": {},
                "bindings": {},
            }

            for endpoint in node.endpoints.values():
                endpoint_id = endpoint.endpoint_id
                clients = await _read(
                    client,
                    node.node_id,
                    f"{endpoint_id}/{DESCRIPTOR_CLUSTER}/{DESCRIPTOR_CLIENT_LIST}",
                )
                servers = await _read(
                    client,
                    node.node_id,
                    f"{endpoint_id}/{DESCRIPTOR_CLUSTER}/{DESCRIPTOR_SERVER_LIST}",
                )
                record["endpoints"][str(endpoint_id)] = {
                    "client_list": clients,
                    "server_list": servers,
                }
                if isinstance(clients, list) and clients:
                    record["client_clusters"][str(endpoint_id)] = clients
                if isinstance(servers, list) and BINDING_CLUSTER in servers:
                    record["bindings"][str(endpoint_id)] = await _read(
                        client,
                        node.node_id,
                        f"{endpoint_id}/{BINDING_CLUSTER}/{BINDING_ATTRIBUTE}",
                    )

            record["acl"] = await _read(
                client, node.node_id, f"0/{ACCESS_CONTROL_CLUSTER}/{ACL_ATTRIBUTE}"
            )
            record["acl_capacity"] = {
                "subjects_per_entry": await _read(
                    client, node.node_id, f"0/{ACCESS_CONTROL_CLUSTER}/{ACL_SUBJECTS_PER_ENTRY}"
                ),
                "targets_per_entry": await _read(
                    client, node.node_id, f"0/{ACCESS_CONTROL_CLUSTER}/{ACL_TARGETS_PER_ENTRY}"
                ),
                "entries_per_fabric": await _read(
                    client, node.node_id, f"0/{ACCESS_CONTROL_CLUSTER}/{ACL_ENTRIES_PER_FABRIC}"
                ),
            }
            result["devices"].append(record)

        listen_task.cancel()
        await client.disconnect()

    print(json.dumps(result, default=str))


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
