// Stage 0 Z2 and Z6: read-only dump of Z-Wave association topology and config values.
//
// Runs inside the Z-Wave JS UI add-on container, where zwave-js-server listens on
// 127.0.0.1:3000. Read-only by construction: the only commands it sends are
// start_listening and the controller.get_* association reads. It never sends
// add_associations, remove_associations, or set_value.
//
// Usage:
//   ssh root@<ha> 'docker exec -i app_a0d7b954_zwavejs2mqtt node -' < tools/probe_zwave_ws.js

const NODES = [21, 29, 30, 35, 36, 37, 38, 39, 40, 42];
const CONFIG_PARAM_NODES = [36, 37, 39];
const WS_URL = "ws://127.0.0.1:3000";

// Command classes we care about for capability detection (PRD Stage 0 Z2).
const CC_OF_INTEREST = {
  85: "Association",
  142: "Multi Channel Association",
  89: "Association Group Information",
  135: "Indicator",
  91: "Central Scene",
  112: "Configuration",
};

const pending = new Map();
let counter = 0;
let ws;

function send(command, extra = {}) {
  const messageId = `m${++counter}`;
  return new Promise((resolve, reject) => {
    pending.set(messageId, { resolve, reject });
    ws.send(JSON.stringify({ command, messageId, ...extra }));
    setTimeout(() => {
      if (pending.has(messageId)) {
        pending.delete(messageId);
        reject(new Error(`timeout waiting for ${command}`));
      }
    }, 30000);
  });
}

function fail(err) {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
}

async function main() {
  ws = new WebSocket(WS_URL);

  const versionInfo = await new Promise((resolve, reject) => {
    ws.addEventListener("error", reject);
    ws.addEventListener("message", function first(ev) {
      ws.removeEventListener("message", first);
      resolve(JSON.parse(ev.data));
    });
  });

  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type !== "result" || !pending.has(msg.messageId)) return;
    const { resolve, reject } = pending.get(msg.messageId);
    pending.delete(msg.messageId);
    if (msg.success) resolve(msg.result);
    else reject(new Error(`${msg.errorCode || "error"}: ${msg.message || JSON.stringify(msg)}`));
  });

  await send("set_api_schema", { schemaVersion: versionInfo.maxSchemaVersion });
  const state = await send("start_listening");

  const byId = new Map(state.state.nodes.map((n) => [n.nodeId, n]));
  const out = [];

  for (const nodeId of NODES) {
    const node = byId.get(nodeId);
    if (!node) {
      out.push({ node_id: nodeId, present: false });
      continue;
    }

    const supported = {};
    for (const endpoint of node.endpoints || []) {
      const ccs = (endpoint.commandClasses || [])
        .filter((cc) => CC_OF_INTEREST[cc.id])
        .map((cc) => ({ id: cc.id, name: CC_OF_INTEREST[cc.id], version: cc.version }));
      supported[String(endpoint.index)] = ccs;
    }

    const record = {
      node_id: nodeId,
      present: true,
      ready: node.ready,
      status: node.status,
      protocol: node.protocol ?? null,
      is_listening: node.isListening,
      highest_security_class: node.highestSecurityClass ?? null,
      fingerprint: {
        manufacturer_id: node.manufacturerId ?? null,
        product_type: node.productType ?? null,
        product_id: node.productId ?? null,
        firmware_version: node.firmwareVersion ?? null,
      },
      manufacturer: node.deviceConfig?.manufacturer ?? null,
      label: node.deviceConfig?.label ?? null,
      name: node.name ?? null,
      endpoint_indices: (node.endpoints || []).map((e) => e.index),
      supported_command_classes: supported,
      association_groups: {},
      associations: {},
    };

    try {
      const groups = await send("controller.get_all_association_groups", { nodeId });
      // Wire shape: { groups: { <endpoint>: { <groupId>: AssociationGroup } } }.
      // Note this is NOT the same depth as get_all_associations below, which nests
      // one level deeper under the node id. Verified live on zwave-js 15.28.0 /
      // zwave-js-server 3.10.1, schema 50 (Stage 0 Z2).
      for (const [endpoint, groupMap] of Object.entries(groups.groups)) {
        record.association_groups[endpoint] = {};
        for (const [groupId, g] of Object.entries(groupMap)) {
          record.association_groups[endpoint][groupId] = {
            label: g.label,
            max_nodes: g.maxNodes,
            is_lifeline: g.isLifeline,
            multi_channel: g.multiChannel,
            profile: g.profile ?? null,
            issued_commands: g.issuedCommands ?? null,
          };
        }
      }
    } catch (err) {
      record.association_groups_error = String(err.message || err);
    }

    try {
      const assoc = await send("controller.get_all_associations", { nodeId });
      // Wire shape: { associations: { <nodeId>: { <endpoint>: { <groupId>: [addr] } } } }.
      // One level deeper than get_all_association_groups. Reading it at the wrong
      // depth yields plausible-looking empty groups rather than an error, so assert
      // the node key is the one we asked for instead of trusting position.
      const perNode = assoc.associations[String(nodeId)];
      if (perNode === undefined) {
        throw new Error(
          `get_all_associations did not key its result by node id ${nodeId}; ` +
            `got keys ${JSON.stringify(Object.keys(assoc.associations))}`
        );
      }
      for (const [endpoint, groupMap] of Object.entries(perNode)) {
        record.associations[endpoint] = {};
        for (const [groupId, targets] of Object.entries(groupMap)) {
          if (!Array.isArray(targets)) {
            throw new Error(
              `expected an array of associations at endpoint ${endpoint} group ${groupId}`
            );
          }
          record.associations[endpoint][groupId] = targets.map((t) => ({
            node_id: t.nodeId,
            endpoint: t.endpoint ?? null,
          }));
        }
      }
    } catch (err) {
      record.associations_error = String(err.message || err);
    }

    if (CONFIG_PARAM_NODES.includes(nodeId)) {
      record.config_values = (node.values || [])
        .filter((v) => v.commandClass === 112)
        .map((v) => ({
          node_id: nodeId,
          endpoint: v.endpoint ?? 0,
          property: v.property,
          property_key: v.propertyKey ?? null,
          value: v.value ?? null,
          metadata: {
            label: v.metadata?.label ?? null,
            min: v.metadata?.min ?? null,
            max: v.metadata?.max ?? null,
            states: v.metadata?.states ?? null,
            writeable: v.metadata?.writeable ?? null,
          },
        }));
    }

    out.push(record);
  }

  const payload = JSON.stringify({
    server: {
      driver_version: versionInfo.driverVersion,
      server_version: versionInfo.serverVersion,
      schema_version: versionInfo.maxSchemaVersion,
      home_id: versionInfo.homeId ?? null,
    },
    nodes: out,
  });

  ws.close();
  // process.exit does not flush an async stdout pipe, which silently truncates the
  // payload at the 64 KB pipe buffer. Exit only once the write has drained.
  process.stdout.write(payload, () => process.exit(0));
}

main().catch(fail);
