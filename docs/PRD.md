# PRD: Device Links for Home Assistant
## Native UI for Z-Wave associations, Zigbee bindings, and Matter bindings, with profiles, verification, drift detection, and automation hooks

| | |
|---|---|
| Status | Draft v1.2 for implementation by Claude Code (v1.1 added Long Range facts, hybrid-leg mechanics, whole-house UI, testing strategy, observability, repository workflow, CLAUDE.md; v1.2 adds the automated GitHub-to-HA dev deployment loop and resolves D3, D6, D20, D21) |
| Date | 2026-09-05 |
| Owner | Jayant |
| Working name | `device_links` (see Decision D1 for naming) |
| Supersedes | `zwave_zigbee_assoc` prototype (services-only integration, mock-tested, never deployed) |
| Target platform | Home Assistant 2026.8+ (validated against 2026.8.3 on HAOS 18.1), distributed via HACS |

---

## 0. How to use this document (read first, Claude Code)

1. Read the whole document before writing code. Section 3 contains facts verified against the live instance and public documentation on 2026-09-05; treat anything marked **ASSUMPTION** as unverified.
2. Do **Stage 0** (Section 13.1) before any Phase 1 code. Stage 0 is validation only. Every Stage 0 item states whether it is read-only or writes to a device. **Do not perform any device write without an explicit go-ahead from Jayant for that specific item.** Read-only probes are pre-approved.
3. Produce a Stage 0 report (`docs/stage0-report.md`) that closes or amends every ASSUMPTION in Section 3 and records real fixtures (JSON dumps) under `tests/fixtures/`.
4. Section 14 is the decision register. Each decision has a default. If Jayant has not answered, proceed with the default and record that you did so in the Stage 0 report.
5. Preserve the engineering discipline that worked in the prototype: protocol logic with zero Home Assistant imports (unit-testable against fakes), read-before-write, verify-after-write, and never deploy a write path that has not been proven against real hardware.
6. Style rule for all generated docs and UI strings: never use the em dash character. Use a plain hyphen or a colon.
7. Section 16 (testing), Section 17 (observability and remote debugging), and Section 18 (repository, releases, CLAUDE.md) are not optional extras: the repository is created in Stage 0 (item R1), every change goes through the workflow in Section 18, and `CLAUDE.md` is written before Phase 1 code so every later session inherits the same rules.
8. Deployment to Jayant's Home Assistant is automated through GitHub (Section 17.5): Claude Code commits and pushes, then triggers a pull on the HA side through the HA MCP server. **Claude never restarts Home Assistant.** When a restart is needed, Claude says so and waits for Jayant.

Glossary (used consistently throughout):

| Term | Meaning |
|---|---|
| Backend | A protocol adapter: `zwave` (Z-Wave JS via the `zwave_js` integration), `zigbee2mqtt` (Zigbee2MQTT over MQTT), `matter` (HA Matter integration / Matter Server). `zha` is a possible future backend. |
| Link | The protocol primitive. One directed edge from a source emitter to a target: a Z-Wave association group entry, a Zigbee binding table entry, or a Matter Binding cluster entry (plus its ACL grant). |
| Emitter | The thing on a source device that sends commands: a Z-Wave association group (for example "Button 1 - Pressed"), a Zigbee endpoint with client clusters (for example Inovelli Blue EP2 "Paddle"), or a Matter endpoint with client clusters and a Binding cluster. |
| Rule | The user-facing unit of intent ("Scene controller button 3 controls Bedside Light L, with dimming"). One rule compiles to one or more links plus optional device settings and optional hybrid legs. |
| Template | A guided rule type (Remote controls light, Virtual 3-way, Scene button, Off-all button, Status feedback, Custom). |
| Profile | A named, versioned set of rules. Exactly one profile is active and represents desired state. |
| Observed state | What the controllers currently report as configured on the devices. |
| Plan | The computed diff between desired state (active profile) and observed state. |
| Apply | Executing a plan, then re-reading and verifying. |
| Drift | Observed state differs from desired state after the last successful apply. |
| Unmanaged link | A link that exists on a device but is not produced by any rule in the active profile. |
| Device handle | The stable identity the integration stores for a device (Section 8.2). Survives renames and area moves; used for device swap. |
| Hybrid leg | A part of a rule that cannot be expressed natively on the radio and is executed by the integration inside Home Assistant (opt-in, clearly labeled). |

---

## 1. Summary

Home Assistant has no first-party UI or API for Z-Wave associations, and the only Zigbee binding UI lives inside Zigbee2MQTT's own frontend. Both exist only as low-level, per-device, add-one-remove-one operations with no notion of intent, no verification, no drift detection, no way to save and re-apply a design, and no way to react to a device swap. Matter bindings are in a similar state: possible through the Matter Server dashboard, but manual and per-attribute.

This project builds a HACS-distributable custom integration with a native-looking sidebar panel that lets a user:

- Read what is currently configured on every Z-Wave, Zigbee, and Matter device (associations, bindings, and the device settings that govern them), and show it in one place.
- Express intent with guided templates ("this switch with no load is a remote for that light, including dimming") and have the integration compile intent into the exact association groups, binding clusters, endpoints, and configuration parameters each device needs.
- Save profiles, apply them, and have the integration transparently add and remove the right links, re-read everything, and prove the result matches.
- Detect drift, handle device swaps by re-mapping every rule that referenced the old device, and expose rule state to automations, including enabling and disabling a rule as a switch.

The design deliberately reuses Home Assistant's existing protocol clients (the `zwave_js`, `mqtt`, and `matter` integrations), adds no network exposure, stores nothing sensitive, is admin-only, and is engineered to meet every rule of the Home Assistant Integration Quality Scale up to Platinum even though custom integrations are not formally scored (Section 11).

## 2. Problem statement, goals, non-goals

### 2.1 Problem

Direct device-to-device control (associations and bindings) is the single most reliable way to make lighting work when the hub is down or slow, and it is the only way to get smooth hold-to-dim from a remote switch. Today, configuring it in a Home Assistant home means hand-driving Z-Wave JS UI's group dialog, Zigbee2MQTT's bind tab, and the Matter dashboard, one entry at a time, with no record of what the desired end state was. When a switch fails and is replaced, every association that referenced it silently disappears and must be rediscovered by memory. Nothing tells you when a device's associations no longer match what you intended.

### 2.2 Goals (measurable)

| # | Goal | Measure |
|---|---|---|
| G1 | A user can configure the full Master Bedroom cluster (6 devices, roughly 20 links plus parameter changes) from templates in under 15 minutes of UI time, without ever typing a group number. | Timed walkthrough against the live network. |
| G2 | Apply is transparent and verified: after Apply, the panel shows every link as `in_sync` based on a fresh read from the devices, not on what was sent. | Acceptance scenarios in Section 15. |
| G3 | Drift caused by an external change (for example Z-Wave JS UI removing an association) is reflected in the panel and in a Home Assistant entity within 30 seconds for listening devices. | Scenario S6. |
| G4 | A device swap (same model or different model) re-maps every rule that referenced the old device and re-applies in one guided flow. | Scenario S7. |
| G5 | Engineering bar: strict typing (mypy strict, zero errors), 95%+ test coverage of the Python package, hassfest and HACS validation passing in CI, every quality-scale rule accounted for in `quality_scale.yaml`. | CI gates. |
| G6 | Safety: the integration never removes a lifeline association, never removes a link it did not create unless the user explicitly selects it, and never writes to a device without a plan the user confirmed (UI) or an explicit service call (automation). | Code review checklist plus tests. |

### 2.3 Non-goals (v1)

- Not a general Z-Wave or Zigbee management tool. No inclusion, exclusion, interviews, firmware updates, or configuration parameter editing beyond the parameters a rule needs. Those stay in Z-Wave JS UI, Zigbee2MQTT, and the HA device page.
- Not a scene or automation engine. Hybrid legs (Section 6.7) exist only to fill specific gaps that the radio cannot express, and are opt-in.
- No ZHA backend in v1 (Jayant runs Zigbee2MQTT). The backend interface is designed so ZHA can be added without touching the core (Section 8).
- No Matter group (multicast) bindings in v1. Matter support is unicast bindings plus the required ACL grants (Phase 3).
- No cloud, no telemetry, no external HTTP calls at runtime.
- Not a replacement for Home Assistant's own Z-Wave JS UI add-on. The integration reads and writes through the same driver; it does not own the radio.

---

## 3. Facts established on 2026-09-05

### 3.1 Live instance (verified via MCP, read-only)

| Item | Value |
|---|---|
| Home Assistant Core | 2026.8.3 on Home Assistant OS 18.1, Supervisor 2026.08.0, Python 3.14.6 |
| Z-Wave JS UI add-on | 7.6.0, slug `a0d7b954_zwavejs2mqtt`, container `app_a0d7b954_zwavejs2mqtt`, zwave-js-server on port 3000 (not reachable from the MCP host; reachable from HA Core and from `docker exec` inside the add-on) |
| Z-Wave controller | Home Assistant Connect ZWA-2 (Nabu Casa), node 1, SDK 8.0.0, RF region 9 = "USA (Long Range)", `supports_long_range: true`, SUC/SIS present. Note: the memory summary calling this a "Zooz ZWA2" is wrong; it is the Nabu Casa ZWA-2. |
| Z-Wave network | 36 nodes, all classic mesh (no node id above 255, so no Long Range nodes yet). All bedroom nodes 35-40 are included **without security** (`highest_security_class = -1`). Node 21 (JY Bath Light) is S2 Authenticated. Nodes 13 ("Ceiling Lights Old", VZW31-SN) and 16 ("House West Lights") are dead. Node 13 has clearly been replaced by node 42 ("Ceiling Lights"), which is a real, already-existing device-swap artifact to use in testing. Node 40 (ZEN37 800LR remote) is battery powered and asleep (`status: 1`). |
| Bedroom cluster | 035 Entrance Lobby Light (Inovelli VZW32-SN fw 2.2.0), 036 Bedroom Scene Controller (Zooz ZEN35 fw 1.40.0), 037 Master Bedroom Lights (VZW32-SN 2.2.0), 038 Bedside Light L (VZW32-SN 2.2.0), 039 Bedside Light R (ZEN35 1.40.0), 040 Master Bedroom Remote (Zooz ZEN37 800LR fw 1.0.0). HA device ids: 035 `d7ac4cd43495577033ae17dbfb2ea29a`, 036 `1f50c99924ffdc3f767cdcdb9f6b6294`, 037 `677156a3a470a6ce83684ee3a90984a2`, 038 `71e78949d3927fcc1d52eae410bdba10`, 039 `ba1b952875560ca94681e8f46a65c66f`, 040 `08eddc2728f76151ae36c499c6608f01`. |
| Other Z-Wave models present | Inovelli VZW31-SN (fw 1.4.0), VZW32-SN (x9), Zooz ZEN04, ZEN15, ZEN16, ZEN20, ZEN30, ZEN32 (fw 2.40.0), ZEN35 (x3), ZEN37 800LR (x3), ZEN75, ZEN78, ZSE50. |
| Zigbee2MQTT add-on | 2.14.1-1. Active bridge IEEE `0x00124b002e1dfd4a`. A stale second "Zigbee2MQTT Bridge" device (IEEE `0x00124b0031dd0be5`, sw 2.8.0) still exists in the device registry: the integration must tolerate multiple or stale bridge devices and must select the base topic explicitly. |
| Zigbee devices | Inovelli Blue VZM31-SN 2-in-1 (x9, fw 2.00-3.04) including "Entrance Inside Lights Aux" (a real aux/remote candidate paired with "Entrance Inside Lights"), Inovelli VZM32-SN mmWave (x6, fw 1.02), Philips Hue string lights (x4), Aqara temperature sensors (x4). |
| Matter Server add-on | 9.2.0 (the matter.js-based server lineage; python-matter-server was archived at 8.1.2). OpenThread Border Router add-on 3.1.2 plus an Apple TV border router. HA Matter integration loaded (config entry `01JM6QFZ3DJ69PHBQND7KFHXD0`). |
| Matter devices | Inovelli White Series 2-1 Switch (x2: "Kitchen Accent Lights", "Entrance Outside Light - OLD"), Aqara Light Switch H2 US, IKEA BILRESA dual button, Eve Energy (x6), IKEA TIMMERFLOTTE and ALPSTUGA sensors, Level Lock+, Aqara U400, Schlage Sense Pro, Shelly EM Mini Gen4 (x3), Nest thermostat. The two Inovelli White switches, the Aqara H2 switch and the BILRESA button are realistic Matter binding sources; Eve Energy and the Inovelli White load endpoints are realistic targets. |
| MCP tooling limits | `ha_manage_radio` (zwave) exposes no association verbs, and direct port 3000 access is not reachable from the MCP host (Ingress only), so association reads and writes for Stage 0 must run from inside HA Core or via `docker exec` into the add-on. The prototype confirmed that HA core registers no `zwave_js/*association*` WebSocket commands; re-confirm on 2026.8 in Stage 0 Z1. `zwave_js/get_config_parameters` works and was used for Section 3.2. |
| HACS | 2.0.5 installed. |

### 3.2 Device configuration facts pulled live (these drive the "device settings" part of rules)

**Zooz ZEN35 (node 39, fw 1.40.0)**, relevant parameters as reported by Z-Wave JS on 2026-09-05:

| Param | Label | Current | Relevance |
|---|---|---|---|
| 19 | Load Control (Smart Bulb Mode): 0 local control disabled, 1 local and Z-Wave enabled, 2 both disabled | **0** | Node 039 currently has local paddle control of its own load disabled. This contradicts the stated intent that the Bedside Light R dimmer button toggles its own load. See Decision D4. |
| 20 | Send Report and Toggle LED on Button Press If Dimmer Disabled | 1 (Disable) | Interacts with 19. |
| 33 | Smart Bulb Mode: Dimming Reporting Behavior: 0 each level / final (Basic Set), 1 final level only for local, 2 each level / final (Multilevel Switch) | 2 | Answers the prototype's open question 2: the report command class sent to group 3/4 targets is selectable. For on/off-only status feedback choose Basic Set (0) or accept Multilevel and let receivers collapse non-zero to "on". |
| 35 (bitmask) | Send Status Change Report: bit 1 Local Control, bit 2 3-Way, bit 4 Z-Wave, bit 8 Timer | all 1 | **This is Zooz's mirroring control.** Bit 4 decides whether hub-initiated changes are forwarded to associated devices. |
| 32 | 3-Way Switch Type | 1 | Not association related, informational. |
| 37 | Scene Control: Remote 3-Way Switch | 0 | Informational. |
| 1-5, 6-10, 11-15 | LED indicator mode / color / brightness per button (dimmer, button 1-4). Modes: on when load off, on when load on, always off, always on. | mode 1 | **All four small-button LEDs reflect the ZEN35's own load only.** There is no parameter that makes a small button's LED follow a remote device. See Section 6.8 and Decision D6. |

ZEN35 association groups (from the prototype, node 036, verified live earlier): group 1 lifeline (max 10), groups 2/3/4 = main dimmer button Pressed (Basic Set) / Held (Multilevel) / Start-Stop (Multilevel); small button N uses groups (3+2N)/(4+2N): button 1 = 5/6, button 2 = 7/8, button 3 = 9/10, button 4 = 11/12. Node 036 group 1 contains only node 1; all other groups were empty. Node 039's groups have **not** been read yet (Stage 0).

**Inovelli VZW32-SN (node 37, fw 2.2.0)**, relevant parameters pulled live:

| Param | Label | Current | Relevance |
|---|---|---|---|
| 59 bit 1 | Send Local Commands to Associated Devices | 1 | Local paddle events go to association groups (default on). |
| 59 bit 2 | Forward Z-Wave Commands to Associated Devices | 0 | **This is Inovelli's mirroring control** (default off). Inovelli's own guidance for a virtual 3-way is to enable it on exactly one side to avoid loops. |
| 22 | Switch Type: 0 single pole, 1 multi-way with aux | 0 | Informational for aux-wired setups. |
| 52 | Smart Bulb Mode | 0 | Relevant when a switch is used purely as a remote with a smart bulb behind it. |
| 123 | Aux Switch Scenes | 0 | Informational. |
| 130-134 | Group 7 enable, levels 1-3, LED color | 0 | Group 7 is a special "cycle levels" association group on this model. |
| 158 | Dimmer Mode (dimmer / on-off) | 0 | Affects which commands make sense. |

Inovelli VZW32-SN association groups (public manual, to be confirmed live in Stage 0): 1 lifeline; 2 Basic Set (paddle on/off); 3 Switch Multilevel Set (release sends level so targets stay in sync, single press up sends 0xFF); 4 Multilevel Start/Stop Level Change (hold to dim); 5 and 6 double-tap / triple-tap Basic Set; 7 special "cycle levels" Basic Set group gated by parameter 130.

**Inovelli Blue VZM31-SN / VZM35-SN (Zigbee)**, public documentation: endpoint 1 is the load, **endpoint 2 is the paddle's OnOff/LevelCtrl client endpoint used as the binding source**, endpoint 3 is the config button (firmware 2.17+ on VZM31-SN, requires parameter 130 set to cycle or multi-tap). Devices also expose `smartBulbMode`, `localProtection`, `remoteProtection`, and `bindingOffToOnSyncLevel`.

### 3.3 Protocol and platform facts (public documentation)

**Z-Wave JS driver association API** (source: `zwave-js/zwave-js` docs, `docs/api/controller.md`, master):

```
getAssociationGroups(source: AssociationAddress): ReadonlyMap<number, AssociationGroup>
getAllAssociationGroups(nodeId): ReadonlyMap<endpoint, ReadonlyMap<groupId, AssociationGroup>>
getAssociations(source): ReadonlyMap<groupId, readonly AssociationAddress[]>
getAllAssociations(nodeId): Map<AssociationAddress, Map<groupId, AssociationAddress[]>>
checkAssociation(source, group, destination): AssociationCheckResult   // replaced isAssociationAllowed in zwave-js v13
addAssociations(source, group, destinations[], options?: { force?: boolean }): Promise<void>
removeAssociations(source, group, destinations[]): Promise<void>
removeNodeFromAllAssociations(nodeId): Promise<void>

interface AssociationGroup { maxNodes; isLifeline; multiChannel; label; profile?; issuedCommands?: Map<CommandClasses, number[]> }
interface AssociationAddress { nodeId; endpoint? }     // endpoint absent = node association, endpoint present = endpoint association
enum AssociationCheckResult { OK, Forbidden_DestinationIsLongRange, Forbidden_SourceIsLongRange, Forbidden_SelfAssociation,
  Forbidden_SecurityClassMismatch, Forbidden_DestinationSecurityClassNotGranted, Forbidden_NoSupportedCCs }
```

Important documented caveats: association methods only work **after the node interview**; a target endpoint of 0 is treated as a root-endpoint association which some devices do not like as a lifeline; `getAssociations` returns the driver's cached view of the device. **Z-Wave Long Range nodes cannot participate in associations at all** (source or destination). The bedroom nodes are all classic, but the ZWA-2 supports LR and Jayant has considered enabling it: any device intended to use associations must be included as classic, and the integration must refuse LR nodes with a clear message.

**zwave-js-server wire protocol**: every driver controller method is exposed with a `controller.` prefix and snake_case (`controller.get_association_groups`, `controller.get_associations`, `controller.add_associations`, `controller.remove_associations`, `controller.remove_node_from_all_associations`, `controller.get_all_association_groups`, `controller.get_all_associations`, and the check method). Params are flat (`nodeId`, `endpoint`, `groupId`, `associations: [{nodeId, endpoint}]`). Read path was proven live in the prototype; write path is still unproven (Stage 0 item Z3). `zwave-js-server-python` (the library HA's `zwave_js` integration uses) wraps these as `controller.async_get_association_groups(AssociationAddress)`, `async_get_associations`, `async_add_associations`, `async_remove_associations`, `async_remove_node_from_all_associations`, and a check method whose exact name in the installed version must be confirmed in Stage 0 (`async_is_association_allowed` in older versions; expect `async_check_association` after the driver rename). **ASSUMPTION A1**: the installed `zwave-js-server-python` exposes a check method and `wait_for_result` style handling for sleeping nodes.

**Home Assistant `zwave_js` integration internals**: the driver object is reachable from a custom integration through the `zwave_js` config entry's `runtime_data` and through helper functions in `homeassistant.components.zwave_js.helpers` (for example resolving a HA device id to a `Node`). **ASSUMPTION A2**: exact helper names and the `runtime_data` shape on 2026.8 (Stage 0 item Z1). Coupling to these internals is a deliberate trade-off (Decision D2).

**Zigbee2MQTT binding API** (source: zigbee2mqtt.io, Binding and MQTT Topics guides, current as of 2026-08-22):

- Request `zigbee2mqtt/bridge/request/device/bind` and `.../unbind` with payload `{"from": SOURCE, "to": TARGET, "clusters": [...], "from_endpoint": ..., "to_endpoint": ..., "skip_disable_reporting": bool, "transaction": ...}`. SOURCE and TARGET are friendly names of devices or groups (a group must be referenced by friendly name, not id). Response on `zigbee2mqtt/bridge/response/device/bind` with `{"data": {"from", "from_endpoint", "to", "to_endpoint", "clusters": [...], "failed": [...]}, "status": "ok"|"error", "error": "...", "transaction": ...}`. Status is `error` only when all clusters fail.
- Bindable clusters: `genScenes`, `genOnOff`, `genLevelCtrl`, `lightingColorCtrl`, `closuresWindowCovering`. Binding is per cluster, so **an on-only binding is impossible in Zigbee** (genOnOff carries both on and off).
- Binding a source to many targets is idiomatically done by putting targets in a Zigbee group and binding to the group (`bridge/request/group/members/add`). Some remotes only support group bindings.
- Zigbee2MQTT configures attribute reporting on the target when a binding is created and removes it on unbind (unless `skip_disable_reporting`). Sleeping battery sources must be woken right before the request or the bind fails.
- `zigbee2mqtt/bridge/request/device/binds/clear` with `{"target": DEVICE, "ieee_list": [...]}` clears bindings selectively and resyncs Zigbee2MQTT's cached binding table.
- **ASSUMPTION A3**: the retained `zigbee2mqtt/bridge/devices` message lists per-device `endpoints.<id>.bindings[] = {cluster, target: {type: "endpoint", ieee_address, endpoint} | {type: "group", id}}` plus `clusters.input/output` and `configured_reportings`. This is the read path for observed Zigbee state and must be confirmed against 2.14.1 (Stage 0 item G1).

**Matter bindings**: Matter defines the Binding cluster (0x001E) whose single attribute `Binding` (0x0000) is a list of `TargetStruct {node, group, endpoint, cluster, fabricIndex}` written on the **source** endpoint; the **target** node must additionally carry an Access Control (0x001F) entry granting the source node Operate privilege. Prior art exists: the HACS integration `cedricziel/ha-matter-binding-helper` (MIT, v0.35.0, June 2026) implements list/create/delete bindings through the official Matter server with a custom panel, and the matter.js-based Matter Server dashboard supports binding and ACL writes (its changelog notes writes now report device-side rejections, and that the Python client's `write_attribute()` serializes struct values keyed by TLV tag). Community reports show the classic failure mode: "ACL write partially failed: 1 entries rejected" (ACL capacity or malformed entries). **ASSUMPTION A4**: the HA `matter` integration exposes a client with `read_attribute`/`write_attribute` usable from a custom integration on 2026.8 (Stage 0 item M1).

**Home Assistant platform facts**:

- Custom panels: `homeassistant.components.panel_custom.async_register_panel(hass, webcomponent_name=..., frontend_url_path=..., sidebar_title=..., sidebar_icon=..., module_url=..., embed_iframe=False, require_admin=True)`; static files via `await hass.http.async_register_static_paths([StaticPathConfig(url, path, cache_headers)])` (the sync `register_static_path` was removed in 2025.7). Manifest `dependencies` must include `http`, `frontend`, `panel_custom`, `websocket_api`. WebSocket commands are registered with `websocket_api.async_register_command` and decorated with `@websocket_api.websocket_command({...})`, `@websocket_api.require_admin`, `@websocket_api.async_response`.
- Integration Quality Scale (developers.home-assistant.io, rules page updated 2025-05-21, index updated 2026-06-17): rule list reproduced in Section 11. The scale formally applies to core integrations; custom integrations sit in the "Custom" special tier and are not scored. We still implement every rule and ship `quality_scale.yaml`.
- HACS publishing requirements (hacs.xyz): one integration per repository under `custom_components/<domain>/`, `manifest.json` with at least `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version`; `hacs.json` in the repo root with at least `name`; brand assets (`brand/icon.png` in the repo, plus a `custom_integrations/<domain>/` entry in `home-assistant/brands` for the integrations page); GitHub releases preferred; the repository needs a description and topics; CI with `hacs/action` and `home-assistant/actions/hassfest`.

### 3.4 Z-Wave Long Range: clarification for this network

Jayant asked whether his many LR-capable ("800LR") devices are simply not running in LR mode, and whether they could switch to LR on their own. Facts:

- LR-capable devices are dual-protocol. **The protocol is fixed at inclusion time.** Classic inclusion, or SmartStart with protocol = Z-Wave Classic (the zwave-js default for a provisioning entry), produces a classic node (ids 2-232). Only SmartStart with protocol = Long Range produces an LR node (ids 256-4000). Nothing changes the protocol afterwards: not firmware updates, not route rebuilds, not the controller's RF region setting, not a controller migration. Moving a device to LR requires exclusion or factory reset followed by re-inclusion with LR explicitly selected.
- All 36 nodes on this network have ids 1-42, so they are classic nodes with the LR radio capability dormant. The controller's RF region "USA (Long Range)" only means the controller *can* include LR nodes; it does not affect existing nodes.
- LR nodes talk only to the controller (star topology): they cannot be association sources or targets and they do not repeat for neighbors. Practical rule for this house: when including new devices through SmartStart in Z-Wave JS UI, pick "Z-Wave Classic" for every switch, dimmer, scene controller, and remote that should participate in associations or act as a repeater; reserve LR for far-away, battery sensors that only report to the hub. The same applies when using "replace failed node" for a swap.
- Integration behavior: each Z-Wave device handle records the node's protocol (Stage 0 item Z2 records the exact field, expected `node.protocol` with `Protocols.ZWaveLongRange`, with node id >= 256 as the fallback check). LR nodes show an "LR: no associations" badge, cannot be picked as source or target, and a Repairs issue is raised if a device referenced by a rule turns out to be LR (for example after a replace-failed-node done as LR).

---

## 4. Users and use cases

### 4.1 Personas

- **Owner-integrator (Jayant)**: technically deep, git-tracked config, local-first, wants intent-level configuration with full transparency into what is written to each device, and a durable record that survives device failures.
- **Advanced HACS user**: comfortable with Z-Wave JS UI but tired of hand-managing groups; wants templates, verification, and drift alerts; may run ZHA or Zigbee2MQTT; may have mixed security classes and battery remotes.
- **Automation author**: wants to react to link state (drift, pending) and to enable or disable specific links from automations (for example disable the "remote controls porch light" rule while guests are staying).
- **Contributor**: wants to add a device profile (parameter mapping for a new switch) without touching Python core logic.

### 4.2 Primary use cases (all must be expressible in the UI)

| ID | Use case | Notes and constraints discovered |
|---|---|---|
| UC1 | **Remote / aux switch controls a load switch, with dimming.** A switch wired without a load (Jayant has several, Z-Wave and Zigbee) acts as a remote for another switch's load: single tap on/off, hold to dim, release to stop, and the remote's LED bar stays in sync. | Z-Wave: source groups 2 (Basic Set), 3 (Multilevel Set), 4 (Start/Stop) on Inovelli; Zooz main button groups 2/3/4. LED sync on a no-load remote works via a status link from the load device's report group back to the remote's root endpoint (a received Basic Set updates the remote's internal level and LED bar, harmless because there is no load). Zigbee: bind source EP2 genOnOff + genLevelCtrl to target EP1; Zigbee2MQTT sets up reporting on the target. Optional device settings: Inovelli param 52 (smart bulb mode) when a bulb is behind the remote; Zooz param 19. |
| UC2 | **Virtual 3-way / mirrored pair.** Two load-bearing switches control the same light from both places, both directions. | Two control links (A to B, B to A) plus mirroring on exactly one side (Inovelli param 59 bit 2, or Zooz param 35 bit 4 semantics). Loop analysis must warn when hub-forwarding is enabled on both ends of a mutual link. |
| UC3 | **Scene button controls one or several lights.** Zooz ZEN35/ZEN32 small buttons, Inovelli double/triple-tap groups, Inovelli Blue config button (EP3), ZEN37 remote buttons. | Zooz small button N maps to a Pressed/Held group pair; the rule's `dim` feature adds the Held group. Battery remotes (ZEN37) queue writes until wake-up. |
| UC4 | **"Off all" button.** One button turns off every light in the room, including lights controlled by other switches, and possibly including the source device's own load. | Group capacity (maxNodes) must be checked; a device cannot be a member of its own group (`Forbidden_SelfAssociation`), so "own load" needs a hybrid leg or a device-specific parameter. |
| UC5 | **Status feedback.** A scene controller's LED reflects the actual state of a remote load regardless of who changed it. | Works natively only when the receiving device has no load of its own (UC1 pattern) or when the device has a documented parameter or Indicator CC path. Zooz small-button LEDs cannot follow a remote device via associations (Section 3.2). |
| UC6 | **One-way vs two-way.** Some rules are deliberately one-way (button drives light, light does not drive button). | Direction is an explicit rule property; default one-way. |
| UC7 | **On-only propagation.** "When primary light turns on, also turn on the secondary light; do not propagate off." | Not expressible natively in Z-Wave associations, Zigbee bindings, or Matter bindings (a group or cluster carries both on and off). Offered only as a hybrid leg, clearly labeled, opt-in (Decision D3). |
| UC8 | **One-to-many and many-to-one.** One button controls five lights; five switches control one light. | One-to-many: multiple targets in one Z-Wave group (bounded by maxNodes), a managed Zigbee group, or multiple Matter binding entries. Many-to-one: multiple rules; the UI provides a target-centric view so the user can see everything that controls a given light. |
| UC9 | **Read and edit what exists.** Open a device, see its current associations/bindings with human labels, tweak one entry, apply, verify. | Observed-state view with adopt/ignore/remove for unmanaged entries. |
| UC10 | **Profiles.** Save the whole design, re-apply after a controller rebuild, or verify that the devices still match. | Single active profile as desired state; export/import YAML for git. |
| UC11 | **Device swap.** A failed switch is replaced (same model, or a different brand). Every rule that referenced it is re-pointed and re-applied. | Node 13 to node 42 already happened on this network. Matching by fingerprint (manufacturer/product ids) enables automatic group re-mapping for same-model swaps; different models go through an emitter-mapping wizard. |
| UC12 | **Automation hooks.** Enable or disable a rule from an automation; trigger on drift; apply or verify from a script. | Rule switch entities, status sensors, events, services. Radio writes on every toggle: rate-limited and documented. |
| UC13 | **Matter over Thread bindings.** Bind the Aqara H2 switch or an Inovelli White switch to an Eve Energy outlet or another Inovelli White load. | Unicast binding entries on the source plus ACL grants on the target; Phase 3. |

---

## 5. Concept model

```
Template --compiles--> Rule --compiles--> Links (1..n) --apply--> device association group / binding table / Matter Binding + ACL
                         |
                         +--> Device settings (config params the rule needs, e.g. Zooz P35, Inovelli P59, P52)
                         +--> Hybrid legs (HA-executed, opt-in, only where the radio cannot express the intent)

Profile  = named, versioned set of Rules + device handles + managed Zigbee groups   (exactly one Active profile = desired state)
Observed = per-device state read from the backends (Z-Wave driver cache, Zigbee2MQTT bridge/devices, Matter attributes)
Plan     = diff(compile(active profile), observed) -> adds, removes, setting writes, blocked (with reason), pending (sleeping), unmanaged
Apply    = execute plan per device sequentially -> re-read -> verify -> record snapshot + job log -> update entities
Drift    = any managed link or setting whose observed value differs from desired after last successful apply
```

Rules are the unit of intent and of enable/disable. Links are derived, never edited directly by the user (except through the "Custom" template, which is a one-link rule with raw group/cluster selection for experts).

### 5.1 Capability model (how the compiler avoids per-device hardcoding)

Every backend produces a normalized `DeviceCapabilities` object for a device:

- **Emitters**: list of `{emitter_id, label, kind: button|paddle|report|special, actions: {on_off, level_set, level_hold, scene, cover, color}, capacity, supports_endpoint_targets, endpoint}`. Z-Wave derives these from Association Group Info (label, `profile` such as `Control: Key01`, `issuedCommands` such as Basic Set 0x20/0x01, Multilevel Switch Set 0x26/0x01, Start/Stop Level Change 0x26/0x04+0x05, Scene Activation 0x2B) and the driver's device config labels. Zigbee derives them from output (client) clusters per endpoint. Matter derives them from the Descriptor cluster `ClientList` per endpoint plus the presence of a Binding cluster server.
- **Receivers**: what the device can accept (Z-Wave: supported CCs per endpoint; Zigbee: input clusters per endpoint; Matter: server clusters per endpoint). Used to validate that a link can do anything (`Forbidden_NoSupportedCCs` equivalent for Zigbee and Matter).
- **Settings adapters**: named capabilities (`mirror_hub_commands`, `send_local_to_associations`, `smart_bulb_mode`, `local_control`, `report_command_class`, `remote_source_endpoint`) mapped to concrete parameters by a **device profile database** (JSON files keyed by backend + manufacturer/product ids or Zigbee model, contributor-friendly, validated by schema). The database ships with Zooz ZEN3x/ZEN7x and Inovelli 500/700/800-series and Blue-series entries first; unknown devices still work for links but show "settings not available for this model".
- **Fingerprint**: `{backend, manufacturer_id, product_type, product_id, firmware}` (Z-Wave), `{model, manufacturer, firmware}` (Zigbee), `{vendor_id, product_id, software_version}` (Matter). Used for swap matching and for profile database lookup.

### 5.2 Rule feature vocabulary

A rule declares **features**, and the compiler picks emitters and clusters:

| Feature | Z-Wave (per source emitter) | Zigbee | Matter |
|---|---|---|---|
| `on_off` | group issuing Basic Set or Binary Switch Set | `genOnOff` | OnOff (0x0006) client |
| `level_hold` (hold to dim) | group issuing Multilevel Switch Start/Stop Level Change | `genLevelCtrl` (Move/Stop) | LevelControl (0x0008) client |
| `level_set` (keep level in sync on release) | group issuing Multilevel Switch Set | `genLevelCtrl` | LevelControl |
| `scene` | group issuing Scene Activation / Central Scene forward | `genScenes` | not in v1 |
| `color` | not supported natively | `lightingColorCtrl` | not in v1 |
| `status_report` (source reports its state to targets) | group flagged as state/report group (Inovelli group 2 on local change; Zooz group 2 with param 35) | reporting configured by Zigbee2MQTT automatically | subscription based, not a binding |

Selecting `on_off + level_hold + level_set` on an Inovelli VZW32-SN paddle compiles to three links (groups 2, 3, 4) to the same target. Selecting `on_off + level_hold` on Zooz small button 3 compiles to groups 9 and 10.

---

## 6. Functional requirements

Priorities: **P0** must ship in the first usable release (Phase 1 for Z-Wave, Phase 2 for Zigbee); **P1** high-value follow-ups; **P2** design-for-later. Each requirement has acceptance criteria (AC).

### 6.1 Backends and observed state

**FR-B1 (P0)** Z-Wave backend reads, for every ready node, all association groups for all endpoints (labels, maxNodes, isLifeline, multiChannel, profile, issued commands) and all current associations, using the `zwave_js` integration's existing driver connection. AC: a device with 12 groups renders 12 labeled emitters; lifeline is marked read-only.

**FR-B2 (P0)** Z-Wave backend writes associations with the driver's check method first; any non-OK check result blocks the link with the enum reason translated to a user message. AC: attempting to add a target to its own group yields "A device cannot control itself over the radio" and no write happens.

**FR-B3 (P0)** Observed state refreshes on backend events (Z-Wave value-updated events for Association CC 0x85 and Multi Channel Association CC 0x8E values, node ready, node removed; Zigbee2MQTT retained `bridge/devices` updates; Matter attribute subscriptions) with a 2 s debounce, and on demand. Polling is off by default; an optional periodic verify (1 h / 6 h / 24 h) is configurable. AC: G3.

**FR-B4 (P0)** "Deep verify" for Z-Wave refreshes the Association and Multi Channel Association CC values from the device before reading (driver `refreshCCValues` equivalent; exact command confirmed in Stage 0), and is used automatically after every apply for listening nodes. AC: after an external change made with a secondary controller (simulated in tests), deep verify shows the true state.

**FR-B5 (P0, Phase 2)** Zigbee2MQTT backend reads bindings and cluster capabilities from the retained `bridge/devices` message and writes with `bridge/request/device/bind|unbind` correlated by `transaction`. Bindings whose target is the coordinator are auto-classified as "system" and never shown as unmanaged. Base topic is configurable; multiple Zigbee2MQTT instances are supported as separate backend instances. AC: bind, unbind, and read round trip on a real pair with per-cluster results surfaced.

**FR-B6 (P0, Phase 2)** Zigbee groups: when a rule has more than one Zigbee target, the backend creates and manages a Zigbee2MQTT group named `dl_<rule_id>` (friendly name shown as `Device Links: <rule name>`), keeps membership in sync, binds the source to the group, and deletes the group when the rule is deleted (unless the user opts to keep it). Groups the integration did not create are never modified. Configurable (Decision D5).

**FR-B7 (P1, Phase 3)** Matter backend reads Binding attributes on every endpoint that has a Binding cluster and ACLs on every node; writes bindings as a merged list (never dropping entries it does not manage) and ACL entries as merged lists that never touch the controller's Administer entry, respecting the device's reported ACL and binding capacities. All Matter writes are behind an options flag defaulting to off until Stage 0 validation passes on the live devices.

**FR-B8 (P2)** ZHA backend using ZHA's WebSocket binding commands. Backend interface must not assume MQTT.

### 6.2 Rules and templates

**FR-R1 (P0)** Templates: Remote controls light (UC1), Virtual 3-way (UC2), Scene button (UC3), Off-all (UC4), Status feedback (UC5), Custom (single raw link). Each template is a guided editor that collects source device, emitter (labeled), targets (one or many, with endpoint selection when the target is multi-channel), features, direction, and device-setting choices. AC: the bedroom cluster in Section 15 is expressible with templates only.

**FR-R2 (P0)** Compilation is pure and deterministic: `compile(rule, capabilities) -> CompiledRule {links[], settings[], hybrid_legs[], warnings[], errors[]}`. Warnings cover capacity, security class, Long Range, self-target, loop risk, missing settings adapter, multi-channel downgrade. Errors block saving only when the rule cannot produce any link.

**FR-R3 (P0)** Direction: `one_way` (default) or `two_way`. Two-way compiles the reverse control links and offers mirroring on exactly one side, defaulting to the load-bearing device (the one the hub commands).

**FR-R4 (P0)** Mirroring option `mirror_hub_commands: true|false|leave` per rule side, implemented through the settings adapter (Zooz P35 bit 4, Inovelli 800-series P59 bit 2, Inovelli Gen2 P12 bitmask, others via profile DB). `leave` never writes the parameter. AC: enabling mirror on an Inovelli VZW32-SN plans a write of parameter 59 bit 2 = 1 and verifies it after apply.

**FR-R5 (P0)** Rules can be enabled or disabled. Disabled rules are excluded from desired state, so their links are planned for removal. Enabling re-adds them. Toggle is available from the panel, the rule switch entity, and a service.

**FR-R6 (P1)** Rule validation surfaces group capacity as "n of maxNodes used" including unmanaged entries, and refuses to plan an add into a full group with a suggestion (remove an unmanaged entry, or use a Zigbee group).

**FR-R7 (P1)** Loop analysis: build the directed graph of control links plus mirror settings; flag cycles where every node on the cycle forwards received commands. AC: a two-way rule with mirror on both sides shows a loop warning before save.

### 6.3 Profiles

**FR-P1 (P0)** Profiles are stored in `.storage/device_links.profiles` via HA `Store` with schema version and migrations. Exactly one profile is active. Create, rename, duplicate, delete, activate.

**FR-P2 (P0)** Export a profile to YAML and import from YAML (file upload in the panel plus services). Optional automatic YAML mirror to `<config>/device_links/profiles/<slug>.yaml` on every change, so the user's git tracking sees the change (Decision D8). Import never writes to devices by itself; it only updates desired state and shows the plan.

**FR-P3 (P0)** Snapshots: before every apply, the observed state of every device touched by the plan is saved as a snapshot (last 20 retained). Rollback re-applies a snapshot's links (managed ones) as a plan the user confirms.

**FR-P4 (P1)** Profile diff view: compare two profiles or a profile against a snapshot, rule by rule and link by link.

### 6.4 Plan, apply, verify, drift

**FR-A1 (P0)** Plan is always computed from a fresh observed read and shown before apply: per device, a list of adds, removes, setting writes, blocked items with reasons, and pending items (sleeping devices). Unmanaged links are listed separately and are **not** removed unless the user ticks "also remove unmanaged links" (per link or all). Lifeline entries are never planned for removal.

**FR-A2 (P0)** Apply runs as a job: sequential per device, at most 2 devices concurrently overall (configurable), each operation with timeout and bounded retry (2 attempts, exponential backoff), per-link results (`applied`, `already_present`, `pending_wakeup`, `failed: <reason>`), cancel support (stops scheduling new operations), progress streamed to the panel over a WebSocket subscription, and a persisted job summary. HA restart marks an in-flight job as `interrupted`; re-running apply is safe because the plan is recomputed.

**FR-A3 (P0)** Optimistic concurrency: the plan carries a token derived from the observed state it was computed from; if observed state for a device changed between plan and apply (for example Z-Wave JS UI edited the same group), that device's operations are skipped with `stale_plan` and the user is asked to re-plan.

**FR-A4 (P0)** Verify after apply: re-read (deep verify for Z-Wave listening nodes), compare, and record per-link `verified_at`. Links that were sent but not confirmed are `unverified` and reported. Sleeping-node links stay `pending_wakeup` until the node wakes and the read confirms; the integration subscribes to wake-up and value-updated events to close them, and raises a Repairs issue if pending for more than 24 h.

**FR-A5 (P0)** Drift: any managed link or setting that differs from desired after the last successful apply flips the rule status to `drift`, updates profile-level entities, fires `device_links_drift_detected`, and (configurable) opens a Repairs issue that links to the plan. Ignoring a specific unmanaged link is persisted so it never re-flags.

**FR-A6 (P1)** Apply scope: whole profile, selected rules, or a single device. Services accept the same scopes.

### 6.5 Device swap

**FR-S1 (P0)** Every device reference in a rule is a device handle: `{backend, protocol_id, ha_device_id, fingerprint, name_at_authoring}`. Renames and area moves never break rules.

**FR-S2 (P0)** Swap flow: choose the missing or old device, choose the replacement. Same fingerprint: emitters map 1:1 automatically. Different fingerprint: a mapping step shows old emitters with their labels and asks the user to pick the equivalent emitter on the new device (pre-filled by matching AGI profile such as `Control: Key02` or by action set). The result rewrites all rules (as source and as target), plans removal of stale links on the old device if it is still reachable (or uses `removeNodeFromAllAssociations` semantics when the old node is gone), plans the new links, and applies on confirmation.

**FR-S3 (P1)** Replacement detection: when a device referenced by rules disappears from the registry or is reported dead, and a new device with the same fingerprint appears, a Repairs issue offers the swap flow pre-filled. Z-Wave "replace failed node" (same node id, possibly different fingerprint) is detected by fingerprint change on an existing handle.

### 6.6 Automation surface

**FR-E1 (P0)** Entities (all `has_entity_name`, unique ids, translations, icons):

| Entity | Attached to | Category | Default | Notes |
|---|---|---|---|---|
| `switch` "Link: <rule name>" | the rule's source device (attached to the existing `zwave_js`/`mqtt`/`matter` device entry via matching identifiers) | config | enabled | On = rule enabled and applied; Off = links removed. Toggle triggers plan+apply for that rule only. Rate-limited: at most one toggle per rule per 30 s is executed; extra toggles are coalesced to the latest requested state. Attributes: `status`, `links_total`, `links_in_sync`, `last_applied`, `last_verified`, `profile`. |
| `sensor` "<rule> status" | source device | diagnostic | disabled by default | enum: `in_sync`, `drift`, `pending`, `applying`, `blocked`, `disabled`, `unknown`. |
| `binary_sensor` "Drift" (device_class `problem`) | integration hub device "Device Links" | diagnostic | enabled | on when any managed link or setting in the active profile is drifted. |
| `sensor` "Active profile status" | hub | diagnostic | enabled | enum as above, aggregated. |
| `sensor` "Pending links" | hub | diagnostic | disabled by default | count of `pending_wakeup`. |
| `sensor` "Health" | hub | diagnostic | enabled | `ok`, `degraded`, `error`; attributes: `version` (manifest), `commit` and `deployed_at` (from the `.deployed` file written by the dev deploy tool, Section 17.5), backend states and upstream versions, last error, job counters, hybrid-leg counters, event subscription liveness. This is the single entity Claude reads first when debugging remotely (Section 17). |
| `select` "Active profile" | hub | config | enabled | switching activates the profile and opens a plan; does **not** auto-apply unless the option "auto-apply on profile switch" is on. |
| `button` "Apply active profile", `button` "Verify" | hub | config | enabled | |

**FR-E2 (P0)** Events on the HA bus: `device_links_job_finished {job_id, scope, results summary}`, `device_links_drift_detected {profile_id, rule_ids}`, `device_links_pending_wakeup {rule_id, device_id}`.

**FR-E3 (P0)** Services (registered in `async_setup`, documented in `services.yaml`, raising `ServiceValidationError`/`HomeAssistantError` with translated messages): `device_links.apply` (profile_id?, rule_ids?, device_id?, remove_unmanaged: bool=false, deep_verify: bool=true), `device_links.verify` (same scope), `device_links.set_rule_enabled` (rule_id, enabled), `device_links.activate_profile` (profile_id, apply: bool=false), `device_links.export_profile` (profile_id) with response, `device_links.import_profile` (yaml) with response. Advanced services gated by an option (default off): `device_links.zwave_get_associations`, `device_links.zwave_add_association`, `device_links.zwave_remove_association`, `device_links.zigbee_bind`, `device_links.zigbee_unbind`. These are the prototype's services, kept for scripting and debugging.

**FR-E4 (P2)** Integration-provided triggers and conditions (HA trigger/condition platforms) such as "drift detected for rule". Until then, events and entity states cover the need.

### 6.7 Hybrid legs (HA-executed): what they are and how they work

**Why they exist.** A rule compiles into "legs". Native legs are written into the devices (association group entries, binding table entries, configuration parameters) and keep working when Home Assistant is off. Some intents contain one piece that no radio can express:

- (a) **On-only or off-only propagation** (UC7): an association group or a bound cluster always carries both on and off.
- (b) **A device acting on its own load from one of its scene buttons** (UC4, Bedside Light R's "off all" including itself): a node cannot be a member of its own association group (`Forbidden_SelfAssociation`).
- (c) **Scene-controller small-button LEDs following a remote light** (UC5): a Zooz ZEN32/ZEN35 interprets any incoming Basic Set or Multilevel Set as "control my load"; it has no per-button endpoints, so there is nothing an association can address to light up button 3. The button LEDs are only reachable through the LED-mode configuration parameters (2-5, 7-10, 12-15) or, if the firmware supports it, the Indicator CC.

For those pieces the integration itself becomes the missing wire. It subscribes to information Home Assistant already receives over the lifeline (Central Scene notifications for button presses, state reports from the light that changed, whether the change came from a paddle, an association, or HA) and issues the one Home Assistant command that completes the intent. This is exactly what a user would otherwise write as an automation, with four differences: it is created, versioned, enabled, disabled, exported, and verified together with the rest of the rule; it does not appear in the user's automation list (it is registered in-process by the integration, the way device triggers and integration listeners are); it is labeled "HA-executed" on every screen so the local-first boundary stays honest; and its firing statistics are visible.

**Behind the scenes for the user.** In the rule editor the user only sees a checkbox such as "Also turn off this device's own load" or "Keep button LEDs in sync with the light". If the checkbox needs a hybrid leg, the editor says so inline ("This part runs in Home Assistant; the rest is device-to-device") and the plan lists it under "HA-executed" instead of under device writes. Nothing else changes for the user.

**FR-H1 (P1, Decision D3)** Hybrid legs are limited to kinds (a), (b), (c). They are disabled globally by default (options flag), and each leg is opt-in per rule.

**FR-H2 (P1)** Mechanics:
- Registration: on profile activation and on Home Assistant start, for every enabled rule with hybrid legs, the integration registers listeners: `async_track_state_change_event` on the tracked light/switch entity for (a) and (c); the `zwave_js_value_notification` bus event filtered by device id and scene id for Z-Wave button presses for (b); the Zigbee2MQTT `action` event entity or MQTT `action` topic for Zigbee buttons; Matter switch events for Matter buttons. Listeners are removed on rule disable, profile switch, and entry unload.
- Execution: one Home Assistant service call per firing (`light.turn_off`, `light.turn_on`, `zwave_js.set_config_parameter`, or an Indicator CC set through `zwave_js.invoke_cc_api`), with a 10 s timeout, one retry, debounce of 500 ms, and de-duplication so a burst of identical events produces one command.
- Write hygiene for (c): the LED parameter is written only when the desired value differs from the last value written (cached per device and button), never more than once per second per device, and the original parameter value is recorded before the first write so disabling the leg restores it. Indicator CC is preferred over parameters when Stage 0 shows per-LED indicator ids, because indicator sets do not touch device NVM.
- Status: the rule's status sensor exposes `hybrid_legs`, `hybrid_fired`, `hybrid_errors`, `hybrid_last_fired`; the Health sensor aggregates them; an error rate above a threshold raises a Repairs issue.
- Failure mode: when Home Assistant is down or restarting, only the hybrid piece stops working; native legs keep working. Docs state this plainly.

**FR-H3 (P1)** "Listening to association traffic" is not needed and is not the default. The controller only sees node-to-node association commands if node 1 is itself a member of the group (it then receives a Basic Set that HA surfaces as a `zwave_js_value_notification` with command class 32). Central Scene notifications over the lifeline already report every button press on Zooz and Inovelli devices, and the target's lifeline reports already tell HA the resulting state. For the rare device without Central Scene, an advanced per-rule option "add controller to this group" is available; it consumes one slot of the group's capacity and is shown as a system entry.

**Not recommended alternative (documented for completeness).** Case (b) could be faked natively by two hops: 039 button 2 to 037 via association, and 037's state-report group back to 039's root endpoint, so 039's load follows 037. That couples 039's load to 037 permanently (every change of 037 drags 039 along), which is not the intent, so the template does not offer it.

### 6.8 Status feedback specifics

**FR-F1 (P0)** The Status feedback template only offers native links when the receiving emitter can safely receive them: a no-load remote (root endpoint receives Basic Set / Multilevel Set and updates its LED), or a device whose profile DB entry declares a status-capable receiver. For a load-bearing device the template warns that a received Basic Set will switch its load, and offers the hybrid LED leg instead when hybrid legs are enabled.

**FR-F2 (P0)** Report command class selection: when the source is a Zooz device with parameter 33 (or an equivalent adapter), the template lets the user choose Basic Set (binary) vs Multilevel Switch (level) reporting and plans the parameter write.

### 6.9 Unmanaged links

**FR-U1 (P0)** Observed links not produced by the active profile are shown as unmanaged with actions: **Adopt** (creates a Custom rule that reproduces the link exactly, so it becomes managed), **Ignore** (persisted, never flagged), **Remove** (planned removal on next apply, requires confirmation). Lifeline and coordinator bindings are system links and are neither unmanaged nor removable.

### 6.10 Settings and configuration (config flow / options)

**FR-C1 (P0)** Config flow: single instance (`unique-config-entry`), no user input required beyond confirmation; setup fails with a translated reason if none of `zwave_js`, `mqtt`, or `matter` is loaded (`test-before-setup`). Options (also reachable via reconfigure): backends enabled (Z-Wave, Zigbee2MQTT, Matter), Zigbee2MQTT base topic(s) (auto-detected from the retained `bridge/info` when possible), periodic verify interval (off, 1 h, 6 h, 24 h), deep verify after apply (on), auto-apply on profile switch (off), hybrid legs allowed (off), Zigbee group management (on), YAML mirror (off, path), advanced raw services (off), drift creates Repairs issue (on), max concurrent devices during apply (2), Matter writes enabled (off until validated).

---

## 7. UI specification (native Home Assistant look and feel)

### 7.1 Placement and shell

- A sidebar panel "Device Links" (icon `mdi:link-variant`), admin only (`require_admin=True`), registered by the integration at setup (no `configuration.yaml`). The panel is a Lit + TypeScript custom element bundled to a single ES module served from the integration directory under `/device_links_static/<version>/device-links-panel.js` (version in the path for cache busting). No CDN imports; everything is bundled.
- The panel uses Home Assistant's own web components so it inherits theme, dark mode, typography, and dialog behavior: `ha-top-app-bar-fixed` with `ha-menu-button` (gives the hamburger on narrow screens for free), `ha-tabs`/`ha-tab-group` (whichever exists on the running version, detected at runtime), `ha-card`, `ha-data-table`, `ha-dialog`, `ha-form` with selectors (`device`, `entity`, `select`, `boolean`, `number`, `text`), `ha-alert`, `ha-button`, `ha-icon-button`, `ha-switch`, `ha-select`, `ha-list-item`, `ha-expansion-panel`, `ha-chip-set` / `ha-assist-chip`, `ha-spinner`, `ha-markdown`, `ha-svg-icon` with `@mdi/js` icons. These components are lazily defined by the frontend; the panel must force-load them using the card-helpers technique (`window.loadCardHelpers()` then creating a throwaway `entities` card, then `customElements.whenDefined(...)`) and degrade gracefully (plain `mwc-*` or native elements) when a component is missing. Reference implementations of this pattern: Alarmo (nielsfaber), HACS frontend.
- Layout: two-pane on wide screens (list left, detail right), stacked with full-screen dialogs on narrow screens (`ha-dialog` handles this). All actions reachable by keyboard; every icon-only button has a label/tooltip.
- Text is localized through the panel's own translation bundle keyed by `hass.language` with English fallback; backend errors arrive already translated (`exception-translations`).

### 7.2 Screens

**Overview tab**
- Status header: active profile name, chips for `In sync n`, `Drift n`, `Pending n`, `Blocked n`, last verified time. Buttons: `Verify`, `Plan and apply`, overflow menu (Export, Snapshots, Settings).
- "Needs attention" list: drift, pending wake-up (with the device's wake instruction from the profile DB when known), blocked rules, replacement candidates. Each row links to the fix.
- Recent activity: last 5 jobs.

**Rules tab (primary working surface)**
- `ha-data-table` with columns: Rule, Source (device name plus emitter label, for example "Bedroom Scene Controller · Button 3 - Pressed/Held"), Targets (chips, "+2" overflow), Features (icons: power, dim, sync, mirror, two-way, hybrid), Backend, Status chip, Enabled toggle. Search, filter by backend/area/status/template, group by source device or by area. Row click opens the rule editor. Multi-select for enable/disable/delete/apply-selected.
- Empty state: "No rules yet" with template cards.

**Rule editor (dialog or side panel)** - a stepper:
1. Template cards with one-line descriptions and a small diagram.
2. Source: device picker (`device` selector filtered to backends enabled and to devices that have at least one emitter), then emitter picker listing labeled emitters with their capabilities as icons and capacity ("2 of 5 used").
3. Targets: multi device picker; when a target is multi-channel show an endpoint picker with labels; when more than one Zigbee target is chosen show the group notice.
4. Behavior: feature toggles available for the chosen emitter (greyed with a reason when unsupported), direction, mirroring (with the exact parameter it will set shown inline, for example "Sets Inovelli parameter 59: Forward Z-Wave commands = Enabled on Master Bedroom Lights"), report command class where applicable, status feedback back-link option, hybrid legs section (only when enabled globally, always with the "HA-executed" badge).
5. Review: the compiled links and settings as they will exist on each device, plus warnings and errors from the compiler. Buttons: `Save`, `Save and apply`.

**Devices tab (observed state)**
- Left: device list (name, area, backend, status dot, counts of managed/unmanaged links). Right: device detail with two sections: **Outgoing** (each emitter: label, capacity, entries with target names, managed by which rule or "Unmanaged" with Adopt/Ignore/Remove) and **Incoming** (who controls this device, derived from all observed state). Device settings section shows the association-relevant parameters with current and desired values. Buttons: `Refresh`, `Deep verify`, `Replace device...`.

**Profiles tab**
- Profile list with active marker, rule count, last applied/verified, actions: Activate, Duplicate, Rename, Export, Delete. Import button. Snapshot list with Rollback. Diff viewer (P1).

**Activity tab**
- Job list with scope, started/finished, result counts; job detail with per-link rows and raw backend error text under an expander (useful for issue reports).

**Plan and apply dialog** (used everywhere apply happens)
- Grouped by device: Add (n), Remove (n), Settings (n), Blocked (n, with reason), Pending (n, sleeping devices, with wake instructions), Unmanaged (n, unchecked checkboxes "also remove"). Summary line and a confirm button labeled with the count ("Apply 14 changes"). Progress replaces the list during the job; result stays until dismissed.

### 7.3 Device page touchpoints

- Rule switch and status entities appear on the source device's own HA device page because they are attached to that device entry (Section 6.6). This is the "native" way to surface per-device state without a custom device panel hook.
- Deep link support: `/device_links?device=<ha_device_id>` opens the Devices tab on that device, and `/device_links?rule=<id>` opens the editor. Repairs issues and notifications use these links.

### 7.4 Lovelace card (P2)

A small `device-links-card` (separate HACS plugin or bundled resource) showing a rule or profile status with an apply/verify button, for dashboards. Not required for v1; the entities already allow tile and entity cards.

### 7.5 Scaling to a whole house: how the UI brings many devices into place

The bedroom cluster is one of many. With 36 Z-Wave, 25 Zigbee, and 19 Matter devices the panel must make "who controls what" fast to build and fast to audit. Requirements, with priorities:

**FR-W1 (P0) Areas, floors, and labels everywhere.** Every table and every device picker supports grouping and filtering by floor, area, HA label, backend, manufacturer/model, and device role. Devices are displayed as "Name · Area · Model" with role and status badges. Area and floor come from the HA registries and update live.

**FR-W2 (P0) Area view.** A per-area page (also reachable from the Rules tab by grouping) that shows, side by side, the area's controllers (each with its emitters and their current targets) and the area's loads (each with its incoming sources, including sources from other areas). One click on an emitter starts a template with the source pre-filled; one click on a load starts a template with the target pre-filled.

**FR-W3 (P0) Device roles.** Each device gets a role: `remote` (no load, or smart-bulb mode), `load_switch`, `scene_controller`, `sensor`, `bulb_or_outlet`, `other`. Roles are derived from capabilities and fingerprints (for example a Zooz ZEN37 is a remote, a device whose only emitters are report groups is a load) and can be overridden by the user (the override is stored with the device handle). Roles order the pickers (the Remote template lists remotes and scene controllers first) and drive suggestions.

**FR-W4 (P0) Adopt all.** A bootstrap action scans observed state across all backends and offers to adopt every non-system link into the active profile as Custom rules, grouped by source device with editable names, so an existing house becomes fully managed in one pass. Adopt never writes to devices.

**FR-W5 (P1) Room matrix wizard.** Choose an area, a floor, or a label set. The wizard renders a matrix: rows are emitters (every button and paddle of every controller in scope), columns are loads in scope plus an "add load from elsewhere" column; each cell is a chip picker for features (on/off, dim, sync, status, two-way). Saving generates one rule per non-empty row, with capacity and loop warnings computed live in the matrix. A "same pattern as area X" action clones a matrix with a device-mapping step.

**FR-W6 (P1) Target sets.** Named, reusable target lists referenced by rules ("All bedroom lights"). Membership can be explicit, or dynamic by area + domain or by label. Dynamic membership changes surface as plan diffs, never as silent writes, and capacity checks run per source group.

**FR-W7 (P1) Working efficiently.** Default rule names generated from source and targets, tags, saved filters, multi-select bulk actions (enable, disable, apply, delete, retag), keyboard navigation, recently used devices in pickers, and a global search across rules, devices, and emitters.

**FR-W8 (P2) Suggestions ("Discover").** Heuristics produce ranked draft rules: name suffixes such as "Aux", "Remote", "Controller" paired with a load in the same area (this network already has "Entrance Inside Lights Aux" next to "Entrance Inside Lights"); scene controllers in an area with lights in that area; sensors that have Basic Set groups next to lights; Zigbee remotes and bulbs sharing an area. The user accepts or dismisses each draft; accepted drafts become rules with `origin: suggestion`.

**FR-W9 (P2) Graph view.** A per-area or per-floor graph of devices and links with direction and feature icons, capacity and conflict highlighting, and click-through to rules.

**FR-W10 (P2) Integration-applied labels (opt-in).** The integration can maintain HA labels such as `Device Links: managed` and `Device Links: drift` on devices so users can build dashboards and automations with label targets.

---

## 8. Architecture

### 8.1 Package layout

```
custom_components/device_links/
  __init__.py            setup/unload, panel registration, service registration (in async_setup), platforms
  manifest.json          domain, name, version, codeowners, documentation, issue_tracker, dependencies:
                         ["http","frontend","panel_custom","websocket_api"], after_dependencies:
                         ["zwave_js","mqtt","matter"], iot_class: local_push, integration_type: service
  const.py
  config_flow.py         single-instance config flow + options flow + reconfigure
  coordinator.py         DeviceLinksCoordinator: observed-state cache, event subscriptions, drift evaluation
  models.py              dataclasses: DeviceHandle, Emitter, Capabilities, Rule, Profile, Link, Plan, Job (no HA imports)
  compiler.py            rules -> compiled links/settings/hybrid legs (pure, no HA imports)
  planner.py             desired vs observed -> Plan (pure)
  executor.py            job runner, retries, concurrency, snapshots, verification
  storage.py             HA Store wrapper, schema versions, migrations, YAML mirror
  yaml_io.py             profile export/import schema and validation
  backends/
    base.py              Backend protocol (Python Protocol class), capability/observed models, errors
    zwave.py             thin adapter over zwave-js-server-python objects obtained from the zwave_js entry
    zwave_protocol.py    pure helpers: AGI/issued-command interpretation, check-result mapping (no HA imports)
    zigbee2mqtt.py       MQTT adapter (subscribe bridge/devices, request/response correlation)
    zigbee_protocol.py   pure helpers: bridge/devices parsing, bind payload building (no HA imports)
    matter.py            Phase 3 adapter
    matter_protocol.py   pure: Binding/ACL merge logic (no HA imports)
  profiles_db/           JSON device profiles (settings adapters, emitter labels, wake instructions), schema.json
  hybrid.py              hybrid leg listeners (Phase 2)
  websocket.py           panel API (admin only)
  services.py, services.yaml
  entity.py, switch.py, sensor.py, binary_sensor.py, button.py, select.py
  diagnostics.py, repairs.py
  strings.json, translations/en.json, icons.json, quality_scale.yaml
  frontend/              built panel bundle (committed per release) + translations
frontend/                TypeScript/Lit sources, vite build, vitest unit tests
tests/                   pytest with pytest-homeassistant-custom-component; fixtures from real dumps
docs/                    user docs (README sections), stage0-report.md, architecture notes
hacs.json, README.md, CHANGELOG.md, LICENSE (MIT), brand/icon.png, .github/workflows/
```

Pure modules (`models.py`, `compiler.py`, `planner.py`, `*_protocol.py`) must not import Home Assistant, so they can be tested without the HA harness and reused by a standalone probe script (the prototype's `probe_zwave.py` pattern).

### 8.2 Data model

```yaml
DeviceHandle:
  backend: zwave | zigbee2mqtt | matter
  protocol_id: "homeid:nodeid" | "0x<ieee>" | "<fabric>:<nodeid>"
  ha_device_id: string          # may go stale; protocol_id is authoritative
  fingerprint: { manufacturer_id, product_type, product_id, firmware } | { model, manufacturer, firmware } | { vendor_id, product_id, sw }
  name_at_authoring: string

Rule:
  id: uuid
  name: string
  enabled: bool
  template: remote | virtual_3way | scene_button | off_all | status_feedback | custom
  backend: zwave | zigbee2mqtt | matter
  source: { device: DeviceHandle, endpoint: int|null, emitter_id: string }   # zwave: "g<groupId>", zigbee: "ep<n>", matter: "ep<n>"
  targets: [ { device: DeviceHandle, endpoint: int|null } ]                  # or { zigbee_group: managed }
  features: { on_off: bool, level_hold: bool, level_set: bool, scene: bool, color: bool }
  direction: one_way | two_way
  mirror: { source: true|false|leave, target: true|false|leave }
  report_cc: basic | multilevel | leave          # only where an adapter exists
  device_settings_extra: [ { device: DeviceHandle, capability: string, value } ]
  hybrid_legs: [ { kind: on_only | self_target | led_status, params } ]
  tags: [string]
  notes: string
  created_at, updated_at

Profile:
  id, name, description, version (int, bumped on every save), rules: [Rule], managed_zigbee_groups: [ {rule_id, group_id, friendly_name} ],
  created_at, updated_at

Storage root (.storage/device_links.profiles, Store version 1):
  active_profile_id, profiles: [Profile], ignored_unmanaged: [link fingerprint], snapshots: [ {id, created_at, reason, observed: {...}} ], jobs: [summaries, last 50]

Link (derived):
  backend, source(handle, endpoint, emitter_id), target(handle, endpoint) | group, action_set, rule_id | null, fingerprint (stable string)

ObservedLink: same shape with managed_by resolved and system: bool

Plan:
  token (hash of observed inputs), items: [ {device, op: add|remove|set_param|create_group|group_add|group_remove, link|setting, reason, status: ready|blocked|pending|stale} ], unmanaged: [ObservedLink], hybrid: [...]
```

### 8.3 Backend protocol (Python `Protocol`)

```python
class Backend(Protocol):
    id: str                       # "zwave", "zigbee2mqtt", "matter"
    async def async_devices(self) -> list[BackendDevice]                      # handles + fingerprints + ha device ids
    async def async_capabilities(self, handle) -> DeviceCapabilities           # emitters, receivers, settings adapters
    async def async_observed(self, handle, deep: bool = False) -> ObservedDevice  # links + relevant settings
    async def async_check_link(self, link) -> LinkCheck                        # ok | blocked(reason)
    async def async_add_link(self, link) -> LinkResult                         # applied | already_present | pending_wakeup | failed
    async def async_remove_link(self, link) -> LinkResult
    async def async_read_setting(self, handle, capability) -> SettingValue
    async def async_write_setting(self, handle, capability, value) -> SettingResult
    def subscribe(self, callback) -> CALLBACK_TYPE                             # observed-state change notifications
    def wake_instructions(self, handle) -> str | None
```

Backends are instantiated only for enabled options and only when their upstream integration is loaded; they register a listener for the upstream config entry's state so the coordinator can mark everything `unavailable` when Z-Wave JS UI restarts or MQTT drops, logging once on loss and once on recovery (`log-when-unavailable`).

### 8.4 Z-Wave adapter notes

- Obtain the driver from the `zwave_js` config entry (`runtime_data`), never by opening a second WebSocket (Decision D2). Keep the prototype's standalone raw client only under `tools/` for probing.
- Node lookups go through `zwave_js` helpers (device id to node) so device-registry mapping matches HA's own.
- Wire semantics: `AssociationAddress(node_id, endpoint=None)` for node associations; supply `endpoint` only when the group supports multi-channel **and** the target is an endpoint other than root; otherwise downgrade with a warning.
- Sleeping nodes: run add/remove as a background task with a long timeout; report `pending_wakeup` immediately; close on `wake up` / value-updated events; expose the device's wake instruction from the profile DB (ZEN37: press any button).
- Parameter writes go through the node's configuration values (`async_set_value` on the config value id), read back after write.
- Value-updated subscriptions for CC 0x85/0x8E and 0x70 (configuration) keep observed state fresh without polling.

### 8.5 Zigbee2MQTT adapter notes

- Subscribe to `<base>/bridge/devices` (retained), `<base>/bridge/groups`, `<base>/bridge/info`, and `<base>/bridge/response/device/bind|unbind`, `.../group/members/add|remove`, `.../device/binds/clear`. Correlate by `transaction` (uuid) with a 30 s timeout.
- Store IEEE addresses in handles; resolve to the **current** friendly name at request time (friendly names can be renamed).
- Bind payloads always specify `clusters` explicitly (never "all supported"), `from_endpoint`, and `to_endpoint` when the target is a device.
- Managed groups use a reserved prefix; the adapter refuses to touch groups without the prefix.

### 8.6 Matter adapter notes (Phase 3)

- Use the HA `matter` integration's client. Read `Descriptor.ClientList` per endpoint to derive emitters and `Binding.Binding` (endpoint/30/0) for observed links; read `AccessControl.ACL` (0/31/0) and capacity attributes (`SubjectsPerAccessControlEntry`, `TargetsPerAccessControlEntry`, `AccessControlEntriesPerFabric`) on targets.
- Writes: Binding list = existing entries not managed by us + desired managed entries; ACL = existing entries + one Operate/CASE entry per source subject (merge subjects into an existing managed entry when capacity is tight); never modify entries whose privilege is Administer. Serialize struct fields by TLV tag as the current server expects (Stage 0 item M2).

### 8.7 WebSocket API (admin only, all `device_links/...`)

```
profiles/list, profiles/get, profiles/create, profiles/update, profiles/delete, profiles/activate, profiles/duplicate,
profiles/export, profiles/import
rules/validate (returns CompiledRule with warnings), rules/upsert, rules/delete, rules/set_enabled
devices/list (backend, capabilities summary, counts), devices/get (capabilities + observed + settings), devices/refresh (deep: bool)
templates/list
plan (scope) -> Plan
apply (plan_token, scope, remove_unmanaged: [fingerprints]) -> job_id
jobs/list, jobs/get, jobs/cancel, jobs/subscribe (streaming progress)
verify (scope)
unmanaged/adopt, unmanaged/ignore, unmanaged/remove
swap/candidates, swap/preview (old_handle, new_device_id, mapping?) -> rewritten rules + plan, swap/apply
snapshots/list, snapshots/rollback
```

All commands validate input with voluptuous, resolve devices through the device registry, and translate backend exceptions into `{code, message, translation_key}` errors.

---

## 9. Error and edge-condition catalog

Every row must have a test. "User sees" text is a translation key, not literal copy.

| # | Condition | Detection | Behavior | User sees |
|---|---|---|---|---|
| E1 | `zwave_js`, `mqtt`, or `matter` integration not loaded / config entry failed | setup and entry-state listener | backend disabled; rules for that backend `unknown`; entities `unavailable`; log once | Repairs: "Z-Wave backend unavailable" with link to the upstream entry |
| E2 | Z-Wave JS UI add-on restarting mid-apply | driver disconnected event / command exceptions | job stops scheduling, marks remaining `interrupted`, snapshot retained | Job result with retry button |
| E3 | Node not ready / interview incomplete | `node.ready` false | device listed as "not ready"; plan blocked for that device | "Interview not complete; re-interview in Z-Wave JS UI" |
| E4 | Node dead | node status | plan blocked; drift not evaluated (state unknown, not drift) | "Device unreachable" |
| E5 | Node asleep (battery) | node status / wake-up CC | writes queued; link `pending_wakeup`; closes on wake | wake instruction from profile DB; Repairs after 24 h |
| E6 | Group full (`maxNodes` reached counting unmanaged entries) | planner | add blocked | "Group 'Button 2 - Pressed' is full (5 of 5). Remove an unmanaged entry or use a group target." |
| E7 | Self association | check result | blocked; suggest hybrid leg when enabled | "A device cannot control itself over the radio" |
| E8 | Long Range source or target | check result / node id > 255 | blocked | "Long Range devices cannot use associations. Re-include as classic Z-Wave." |
| E9 | Security class mismatch / destination class not granted | check result | blocked | explains both classes and suggests re-inclusion with matching security |
| E10 | No supported CCs at destination | check result | blocked | "Target cannot act on the commands this button sends" |
| E11 | Multi-channel target on a group without multi-channel support | compiler | downgrade to node association with warning, or block if the user explicitly required the endpoint | warning in review step |
| E12 | Duplicate link already present | planner | `already_present`, no write | shown as unchanged |
| E13 | Command timeout | executor | retry 2x with backoff, then `failed` | error text plus raw backend error under expander |
| E14 | Verify mismatch after write (sent but not present on re-read) | verifier | link `unverified`; rule `drift`; suggest deep verify / re-apply | |
| E15 | Observed state changed between plan and apply (external edit) | plan token mismatch | that device's ops `stale_plan`, others proceed | "Plan is out of date for X; re-plan" |
| E16 | Two applies started concurrently (UI + automation) | job lock per profile | second call rejected with `job_running` | |
| E17 | HA restart during apply | job persistence | job `interrupted`; no auto-resume | banner on Overview |
| E18 | Storage load or migration failure | Store | integration loads read-only; apply disabled | Repairs with instructions and backup location |
| E19 | Rule references a device no longer in the registry / on the network | coordinator | rule `blocked: device_missing`; swap flow offered | Repairs "Device missing for 3 rules" |
| E20 | Device replaced with same node id but different fingerprint (replace failed node) | fingerprint change on handle | rule `blocked: device_changed`; swap flow pre-filled | |
| E21 | Controller replaced (new home id) | protocol_id prefix mismatch for all Z-Wave handles | global re-map wizard; nothing applied automatically | Repairs "Z-Wave network changed" |
| E22 | Zigbee source sleeping (battery remote) | bind response error | prompt to wake and retry; link `pending_user_action` | wake instruction |
| E23 | Zigbee friendly name changed | IEEE lookup | transparent | none |
| E24 | Zigbee group missing or renamed outside the integration | `bridge/groups` | recreate on apply if managed; warn if foreign | |
| E25 | Multiple Zigbee2MQTT instances or stale bridge device in registry | options / discovery | backend instance per base topic; stale bridge devices ignored | options hint |
| E26 | Zigbee2MQTT restart | `bridge/state` offline | backend unavailable; retained `bridge/devices` re-read on online | log once |
| E27 | Matter ACL write rejected (capacity, malformed) | write result | link `failed`, no partial state left: binding entry is written only after ACL succeeds | "Target rejected the access grant (n of m entries used)" |
| E28 | Matter binding table full | capacity attribute | blocked | |
| E29 | Matter node offline / sleepy (ICD) | subscription state | `pending`; retried on reachability | |
| E30 | Loop risk (mutual links with forwarding on both ends) | loop analysis | warning (not blocked) | "Mirroring on both sides can cause command loops" |
| E31 | Profile DB has no entry for a model | capability lookup | links still work; settings adapters absent; rule warns | "Settings not available for this model; contribute a profile" |
| E32 | User is not admin | WS `require_admin` | rejected | HA standard unauthorized error |
| E33 | Frontend bundle version mismatch with backend (after update without reload) | version handshake on panel load | banner asking to reload | |
| E34 | Non-secure source, S2 target (or vice versa) in the same room, common after mixed inclusions | check result | same as E9 | |
| E35 | Excessive toggling of a rule switch from automations | rate limiter | coalesced to latest state; logged at debug | attribute `rate_limited: true` |
| E36 | Large networks (200+ nodes) | design | lazy loading per device; observed cache; no full-network reads at startup | |
| E37 | Config entry unload / reload | `async_unload_entry` | subscriptions removed, panel unregistered, jobs cancelled cleanly | |
| E38 | Import YAML with unknown devices or schema version | yaml_io | import rejected with a per-line error list; nothing changed | |

---

## 10. Security and privacy

- **No new network surface.** The integration reuses existing clients: the `zwave_js` driver connection, the `mqtt` integration's broker session (respecting its credentials and TLS), and the `matter` client. It opens no listening ports and no outbound connections. The zwave-js-server protocol has no authentication; not opening a second connection also means not creating a second unauthenticated client path.
- **Admin only.** The panel and every WebSocket command require an admin user. Services follow HA's normal permission model; when called from automations they run as system. Advanced raw services (direct group/cluster writes) are off by default and clearly documented as expert tools.
- **Explicit writes only.** The UI never writes without a confirmed plan. Services write only what their explicit arguments scope. Removal of unmanaged links requires per-link opt-in. Lifeline associations and coordinator bindings are hard-protected in code (not just in UI).
- **Least privilege on Matter.** ACL entries granted are Operate on the specific cluster and endpoint when the device supports targeted entries; never Administer; never touching existing entries not created by the integration.
- **Input validation** with voluptuous on every WS command and service; device references resolved through HA registries; node ids, IEEE addresses and Matter node ids accepted from clients only in the gated raw services.
- **Storage hygiene.** No credentials, keys, or DSKs are stored. Diagnostics redact IEEE addresses, home id, and Matter node ids (`async_redact_data`). Snapshots contain protocol ids only.
- **Frontend supply chain.** Bundled dependencies pinned via lockfile, no runtime CDN loads, CSP-friendly (no inline scripts), Dependabot enabled, build reproducible in CI, the built bundle committed with a version header and a checksum listed in the release notes.
- **Rate limiting and radio hygiene.** Per-device serialization, bounded global concurrency, bounded retries, coalesced toggles. Association and binding tables live in device flash; the docs state that rule switches are for occasional changes, not per-minute toggling.
- **Recoverability.** Pre-apply snapshots, rollback, YAML export, and a documented manual recovery path (Z-Wave JS UI groups dialog) in the troubleshooting docs.
- **Dependency transparency.** No new Python requirements beyond what HA already ships (`zwave-js-server-python`, `paho`/`aiomqtt` via `mqtt`, Matter client via `matter`). If a helper library is ever added it must be on PyPI, open source, built from source, async, and accept an injected websession where relevant.

---

## 11. Engineering standards and quality-scale mapping

The Home Assistant Integration Quality Scale applies formally only to core integrations; custom integrations are shown as "Custom" and are not scored. This project implements every rule anyway, ships `quality_scale.yaml`, and treats the rule list as its engineering checklist so it would be eligible for a core submission without redesign.

| Rule | Tier | How this project satisfies it |
|---|---|---|
| action-setup | Bronze | services registered in `async_setup`, validate that the config entry is loaded, raise `ServiceValidationError` otherwise |
| appropriate-polling | Bronze | event-driven; optional periodic verify with a user-chosen interval, default off |
| brands | Bronze | `brand/icon.png` in repo plus PR to `home-assistant/brands` `custom_integrations/device_links` |
| common-modules | Bronze | `coordinator.py`, `entity.py`, `models.py`, `backends/base.py` |
| config-flow, config-flow-test-coverage | Bronze | UI-only setup with `strings.json`/translations, 100% flow coverage including options and reconfigure |
| dependency-transparency | Bronze | no extra requirements (Section 10) |
| docs-actions, docs-triggers, docs-conditions | Bronze | README documents every service with examples; triggers/conditions marked exempt until FR-E4 |
| docs-high-level-description, docs-installation-instructions, docs-removal-instructions | Bronze | README sections; removal explains that links stay on devices and how to remove them first |
| entity-event-setup | Bronze | subscriptions in `async_added_to_hass`, removed in `async_will_remove_from_hass` |
| entity-unique-id, has-entity-name | Bronze | unique ids `<entry_id>_<rule_id>_switch` etc.; `_attr_has_entity_name = True` with translation keys |
| runtime-data | Bronze | typed `DeviceLinksConfigEntry = ConfigEntry[DeviceLinksRuntimeData]` |
| test-before-configure, test-before-setup | Bronze | flow and setup verify at least one backend integration is loaded; raise `ConfigEntryNotReady` when upstream entries are still loading |
| unique-config-entry | Bronze | single instance via `_abort_if_unique_id_configured` |
| action-exceptions | Silver | `ServiceValidationError` for bad input, `HomeAssistantError` for backend failures, translated |
| config-entry-unloading | Silver | full unload: listeners, panel, jobs, WS commands stay registered (idempotent) |
| docs-configuration-parameters, docs-installation-parameters | Silver | README options table |
| entity-unavailable | Silver | entities unavailable when their backend is unavailable |
| integration-owner | Silver | `codeowners` in manifest |
| log-when-unavailable | Silver | one log line on backend loss and one on recovery |
| parallel-updates | Silver | `PARALLEL_UPDATES = 0` on platforms (entities are push-updated) |
| reauthentication-flow | Silver | exempt: no credentials of its own (documented in `quality_scale.yaml`) |
| test-coverage | Silver | 95%+ line coverage enforced in CI (`--cov-fail-under=95`) |
| devices | Gold | hub device "Device Links" plus rule entities attached to existing devices |
| diagnostics | Gold | config, options, profile summary, observed state, job history, redacted |
| discovery, discovery-update-info | Gold | exempt (no discoverable hardware; the integration is set up from existing integrations) |
| docs-data-update, docs-examples, docs-known-limitations, docs-supported-devices, docs-supported-functions, docs-troubleshooting, docs-use-cases | Gold | README sections; known limitations include on-only impossibility, Long Range, self association, Zooz small-button LEDs, Zigbee reporting caveats |
| dynamic-devices | Gold | new devices appear via backend subscriptions without reload |
| entity-category, entity-device-class | Gold | categories per Section 6.6; `problem` device class for drift |
| entity-disabled-by-default | Gold | per-rule status sensors and pending counter disabled by default |
| entity-translations, exception-translations, icon-translations | Gold | `translations/en.json`, `icons.json` with state icons |
| reconfiguration-flow | Gold | reconfigure step mirrors options |
| repair-issues | Gold | issues listed in Section 9 (E1, E5, E18, E19, E21) |
| stale-devices | Gold | rule entities removed when the referenced device is removed; hub device removal supported via `async_remove_config_entry_device` |
| async-dependency | Platinum | all backends async; no blocking I/O in the event loop (file I/O via `hass.async_add_executor_job`) |
| inject-websession | Platinum | exempt: no HTTP client dependency |
| strict-typing | Platinum | `mypy --strict` on the package, `py.typed`, typed `runtime_data`, no `Any` leaks in public signatures |

Additional standards (testing is detailed in Section 16):

- Python 3.13+ (HA 2026.8 runs 3.14), Ruff (lint + format) with HA's ruleset, `pre-commit`.
- Tests: pure-module tests without HA; HA integration tests with `pytest-homeassistant-custom-component` using fixtures captured in Stage 0 (node dumps, `bridge/devices` payloads, Matter attribute reads); property-based tests (Hypothesis) for the planner (plan then apply on a fake backend always converges, is idempotent, never removes lifelines); frontend unit tests with vitest for compile/plan rendering logic.
- CI: hassfest, HACS action, pytest+coverage, mypy, ruff, frontend build and test, release workflow that builds the bundle, tags, attaches a zip (`zip_release: true` in `hacs.json`), and refuses to release if `manifest.json` version differs from the tag.
- Conventional commits, CHANGELOG, semantic versions, `2026.9.0` style calendar versioning is acceptable but keep it consistent with HACS version comparison.
- Logging: `_LOGGER` per module, debug logs include job ids and link fingerprints, never raw payloads above debug.

---

## 12. HACS packaging

- Repository: public GitHub, description and topics (`home-assistant`, `hacs`, `zwave`, `zigbee`, `matter`, `associations`, `bindings`).
- `hacs.json`: `{"name": "Device Links", "render_readme": true, "homeassistant": "2026.8.0", "zip_release": true, "filename": "device_links.zip"}`.
- `manifest.json` keys: `domain`, `name`, `version`, `codeowners`, `documentation`, `issue_tracker`, `dependencies`, `after_dependencies`, `iot_class`, `integration_type`, `config_flow: true`, `quality_scale` omitted (custom).
- Brand assets: `brand/icon.png` (256x256) and `brand/logo.png`; PR to `home-assistant/brands`.
- Releases: GitHub release per version with changelog; HACS shows the last 5.
- Install/remove docs, "how to migrate from the `zwave_zigbee_assoc` prototype" note (delete the old custom component; nothing on devices changes).

---

## 13. Delivery plan

### 13.1 Stage 0: validation (no product code; probes, fixtures, and a report)

Deliverable: `docs/stage0-report.md` plus fixtures under `tests/fixtures/`. Each item lists its write policy. **Read-only items are pre-approved. Every WRITE item requires Jayant's explicit approval for that item before execution, and must be preceded by a read of the exact group/binding it touches and followed by a read that proves the state was restored.**

| ID | Item | Write? | Acceptance |
|---|---|---|---|
| Z1 | On HA 2026.8.3, confirm how a custom integration reaches the Z-Wave driver (Decision D2, resolved as (a)); deliver an automated test with the HA test harness that patches a fake `zwave_js` entry and asserts the accessor works, so upstream refactors break CI instead of users: the `zwave_js` config entry `runtime_data` shape, the helper to resolve HA device id to `Node`, and the installed `zwave-js-server-python` version and method names for association groups, associations, check, add, remove, remove-node-from-all, and CC value refresh. Record exact import paths and signatures. | no | report section with code snippets that run in the HA container (`hass` REPL via `homeassistant.components.python_script` is not acceptable; use a throwaway custom component or `docker exec` into HA core with a small script) |
| Z2 | Dump `getAllAssociationGroups` and `getAllAssociations` for nodes 35, 36, 37, 38, 39, 40, 29 (ZEN32), 30 (ZEN35 hallway), 42 (VZW32-SN swap target) and 21 (S2 node). Record labels, maxNodes, isLifeline, multiChannel, AGI profile and issuedCommands availability. Record each node's protocol field (classic vs Long Range) for Section 3.4. Record each node's supported CC list (specifically Association 0x85, Multi Channel Association 0x8E, AGI 0x59, Indicator 0x87, Central Scene 0x5B). | no | fixtures saved; group maps for VZW32-SN, ZEN35, ZEN37, ZEN32 documented; any node without AGI noted |
| Z3 | Prove the write path: add node 1 to an unused, non-lifeline group on node 36 (candidate: group 8, "Button 2 - Held", which the bedroom design leaves unused), read back, remove, read back. Confirm whether the driver cache updates synchronously, and find the exact refresh command for CC 0x85/0x8E (deep verify). Measure round-trip time. | **WRITE** | before/after reads identical to the pre-test state; timing recorded |
| Z4 | Sleeping node behavior on node 40 (ZEN37 800LR): issue an add to an unused group, observe whether the library call blocks until wake-up or returns immediately, wake the remote (Jayant presses a button), confirm the write lands, remove it, confirm. Identify the events (`wake up`, value updated) usable to close `pending_wakeup`. | **WRITE** | state restored; behavior documented |
| Z5 | Confirm that when an association is changed in Z-Wave JS UI (Jayant edits node 36 group 8 by hand), the driver emits a value-updated event that a custom integration can subscribe to, and what the value id looks like (CC 0x85, property `nodeIds`, propertyKey = group id is the expectation). | no (Jayant's manual edit) | event captured; if no event, drift detection must fall back to periodic verify and the report must say so |
| Z6 | Read (not write) configuration parameters through the driver value API for ZEN35 param 35 bits (property 35, property keys 1/2/4/8) and VZW32-SN param 59 bits (property keys 1/2), and confirm the value ids for writes. Also read ZEN35 params 19, 20, 33. | no | value ids recorded for the settings adapters |
| Z7 | Determine the Basic Set semantics of Zooz ZEN35/ZEN32 small-button "Pressed" groups: does a press alternate ON/OFF, always send ON, or depend on LED state or a parameter? This decides how "Off-all" is compiled. Use the manual first; confirm with a Z-Wave JS UI log capture while Jayant presses a button that has node 1 temporarily in its group (reuse the Z3 window). | reuse Z3 | documented per model |
| G1 | Zigbee2MQTT 2.14.1: capture the retained `zigbee2mqtt/bridge/devices`, `bridge/groups`, and `bridge/info` payloads; confirm the per-endpoint `bindings`, `clusters.input/output`, and `configured_reportings` schema; identify the coordinator IEEE; confirm VZM31-SN EP2/EP3 output clusters; confirm which base topic the active bridge uses and that the stale 2.8.0 bridge device is a registry leftover. | no | fixtures saved |
| G2 | Bind/unbind round trip on a pair Jayant approves. Candidate: "Entrance Inside Lights Aux" EP2 to "Entrance Inside Lights" EP1, `genOnOff` only, then unbind (unless Jayant wants it kept). Capture response payloads and the time until `bridge/devices` reflects the change. | **WRITE** | responses captured; state restored or explicitly kept |
| M1 | Matter: confirm how a custom integration reaches the HA `matter` client on 2026.8.3 and which read/write attribute APIs exist against Matter Server 9.2.0. Read Descriptor `ClientList` and Binding attributes for the two Inovelli White switches, the Aqara H2 switch and the BILRESA button; read ACL and ACL capacity attributes on one Eve Energy. | no | fixtures saved; feasibility verdict for Phase 3 |
| P1 | Panel spike: register a hello-world panel from a throwaway integration using `panel_custom.async_register_panel` and `async_register_static_paths`; force-load `ha-data-table`, `ha-form`, `ha-dialog` via card helpers; call one admin WS command; verify in desktop browser and in the HA companion app. | no | screenshots; list of HA components confirmed loadable on 2026.8.3 |
| P2 | Entity attachment spike: a switch entity whose `DeviceInfo.identifiers` matches an existing `zwave_js` device; confirm it shows on that device page and is removed on unload without touching the upstream device. Record identifier formats for `zwave_js`, Zigbee2MQTT (`mqtt`), and `matter` devices. | no | documented |
| Z8 | Hybrid LED path check on node 36 (Bedroom Scene Controller): write the LED mode parameter for an unused button (param 3, button 2: set 3 = always on, read back, restore to the recorded value), measure latency; then check whether the Indicator CC (0x87) exposes per-button indicator ids and whether an indicator set lights the same LED. Decides the implementation of hybrid leg kind (c). | **WRITE** | parameter restored; latency and Indicator CC verdict recorded |
| R1 | Create the GitHub repository and push the skeleton (Section 18.1): with `gh` if authenticated, otherwise print the manual steps and stop until Jayant completes them. Add description, topics, labels, issue templates, Dependabot, branch protection. | no (GitHub only) | repository exists, CI runs |
| R2 | Bootstrap the automated dev deployment loop (Section 17.5): install `tools/ha_deploy.py` on the HA host, add the `shell_command` entries, have Jayant restart HA once, then run one full round trip (push a trivial change to `dev`, trigger the deploy through MCP, confirm the JSON response, confirm the `.deployed` file, confirm the health sensor reports the commit after Jayant restarts). Also test `rollback` and `status`. | no device writes (HA config only) | round trip and rollback proven; documented in `docs/dev-deploy.md` |
| D1 | Repository skeleton with CI (hassfest, HACS action, pytest, mypy strict, ruff, frontend build) passing on an empty integration, plus `CLAUDE.md` (Section 18.4). | no | green CI |

Stage 0 exit criteria: all read-only items complete; R1 and D1 complete; Z3 complete (write path proven) or an explicit decision to postpone; assumptions A1-A4 closed or amended; fixtures committed; `docs/stage0-report.md` merged.

### 13.2 Phase 1: Z-Wave end to end (P0 for Z-Wave)

Models, compiler, planner, executor, storage, Z-Wave backend, profile DB entries for Zooz ZEN3x and Inovelli 800-series, panel (Overview, Rules with templates, Devices, Profiles basic, Activity, Plan/Apply dialog), entities, events, services, diagnostics, basic Repairs (E1, E5, E19), docs, tests. Exit: scenarios S1-S6 and S9-S10 pass on the live network.

### 13.3 Phase 2: Zigbee, swap, hybrid, hardening

Zigbee2MQTT backend with managed groups, device swap flow and detection, hybrid legs (opt-in), snapshots and rollback, YAML mirror, profile diff, loop analysis, full Repairs set, profile DB for Inovelli Blue and common IKEA/Hue devices. Exit: S7 and S8 pass.

### 13.4 Phase 3: Matter and polish

Matter backend behind the options flag (unicast bindings plus ACL), Lovelace card, optional graph view of links, ZHA backend design note, contributor guide for the profile DB, HACS default-repository submission.

---

## 14. Decision register (answers needed from Jayant; defaults apply if unanswered)

| ID | Decision | Options | Default / recommendation | Why it matters |
|---|---|---|---|---|
| D1 | Integration name and domain | `device_links` / "Device Links"; alternatives: `direct_control`, `bindings_manager`, keep `zwave_zigbee_assoc` | **RESOLVED 2026-09-05: `device_links`** | Scope now spans three protocols; the old name will be wrong in HACS search and in translations. |
| D2 | How to reach the Z-Wave driver | (a) reuse the `zwave_js` integration's driver via `runtime_data` and helpers; (b) open an independent WebSocket to zwave-js-server as the prototype did | **RESOLVED 2026-09-05: (a)**, isolated in one adapter module with a version-guarded accessor and an automated accessor test (Stage 0 Z1); keep the raw client only as a `tools/` probe | (a) avoids a second unauthenticated client, gives the node models, device config labels, events, and HA device mapping for free, and matches how other HACS Z-Wave add-ons work. The cost is coupling to internals that can change between HA versions, mitigated by Stage 0 Z1, tests against pinned HA versions, and a fast-fail Repairs issue when the accessor breaks. |
| D3 | Hybrid (HA-executed) legs (explained in Section 6.7) | in scope opt-in; out of scope | **RESOLVED 2026-09-05: in scope, Phase 2, per-rule opt-in, global option off by default** | On-only propagation, self-target "off all", and Zooz small-button LED sync cannot be done on the radio; without hybrid legs those intents simply cannot be represented, and they conflict with the local-first goal, so they must be explicit and labeled. |
| D4 | Node 039 (Bedside Light R) parameter 19 currently disables local control | (a) intentional (smart bulb behind it); (b) should be 1 so the paddle drives its load | **RESOLVED 2026-09-05: temporary state, ignore; the integration never touches parameter 19 unless a rule selects it** | The stated intent for 039 assumes the paddle controls its own load. The integration will never change parameter 19 unless the user selects it in a rule. |
| D5 | Managed Zigbee groups for one-to-many | on with `dl_` prefix; off (multiple unicast binds) | **on** | Group binding is the idiomatic and more reliable Zigbee pattern; unicast to many targets sends commands sequentially and hits binding-table limits. |
| D6 | Status feedback for Zooz scene-controller small-button LEDs | hybrid via Indicator CC (if Z2 shows 0x87 support) or LED-mode parameters; skip | **RESOLVED 2026-09-05: hybrid leg kind (c), opt-in; Indicator CC when Stage 0 Z8 confirms it, otherwise LED-mode parameters with write hygiene** | The ZEN35 LED parameters only track the device's own load; no native path exists. |
| D7 | What the rule `switch` entity does | (a) physically remove/add links (universal); (b) toggle a device parameter where available (Inovelli P59, Zooz P35) | **RESOLVED 2026-09-05: (a)**, rate-limited, documented as not for frequent toggling | (a) works for every backend and is verifiable by reading the device; (b) is model-specific and only affects hub-forwarding, not local control. |
| D8 | YAML mirror | off; on with path `<config>/device_links/` | **off by default; Jayant enables it** | Matches the `nrg` pattern (`.storage` authoritative, YAML mirror for git). |
| D9 | Unmanaged link default | report only; auto-remove | **report only** | Never destroy what the integration did not create without a click. |
| D10 | Profile semantics | single active profile = desired state; multiple simultaneously active layered profiles | **single active** | Layering needs conflict resolution rules; tags plus apply-scope cover "partial" needs. |
| D11 | Matter scope | unicast bindings plus ACL behind a flag; none | **Phase 3 behind a flag** | Real candidates exist on the network (Inovelli White, Aqara H2, BILRESA, Eve Energy) and prior art proves feasibility, but ACL writes are security-relevant and the server changed lineage in 2026. |
| D12 | ZHA backend | v1; later | **later** | No ZHA in use; keep the interface backend-neutral. |
| D13 | Z-Wave Long Range | refuse LR nodes with a message | **refuse** | Protocol limitation; if Jayant enables LR inclusion, devices meant for associations must stay classic. |
| D14 | Advanced raw services | keep, gated by option | **keep, off by default** | Useful for scripting and debugging; risky as defaults. |
| D15 | Bedroom design confirmations from the prototype: 036 small button 2 left unassigned; 039 small button 2 "off all" includes its own load (needs hybrid); which devices get status feedback | needs answer | defaults: button 2 unassigned; off-all excludes own load unless hybrid enabled; status feedback native only for the no-load controller 036 | Drives scenario S3-S5. |
| D16 | Frontend stack | Lit + TypeScript + vite, HA components at runtime; React starter kit | **Lit + TS** | Matches HA's own frontend and the reference panels (Alarmo, HACS). |
| D17 | License | MIT; Apache-2.0 | **MIT** | Compatible with the MIT prior art that may be consulted (never copied without attribution). |
| D18 | Apply on save | always require the plan dialog; auto-apply on save | **plan dialog always; "Save and apply" opens it pre-confirmed** | Goal G6. |
| D19 | Existing prototype code | reuse `zwave_client.py` and tests as probes; discard | **reuse as `tools/probe_zwave.py` and as reference for test shapes; no production use** | The mock-tested client stays valuable for Stage 0 and for a fallback if D2(a) ever breaks. |
| D20 | GitHub repository owner and name | Jayant's user or org; name `ha-device-links` | **RESOLVED 2026-09-05: `ha-device-links` under Jayant's GitHub user** | Needed for `manifest.json` `documentation`/`issue_tracker` URLs and HACS. |
| D21 | Development install path on Jayant's HA | (a) HACS custom repository releases only; (b) branch-tracked install for fast iteration, HACS for releases | **RESOLVED 2026-09-05: (b) until Jayant is comfortable releasing through HACS, fully automated: Claude Code on Jayant's computer commits and pushes to GitHub, then triggers an HA-side pull from GitHub through the HA MCP server; HA restarts stay manual (Section 17.5)** | Fast fix-and-verify loops early; clean upgrade path later. |
| D22 | Remote debugging access for Claude | MCP read/write tools plus the Claude Terminal add-on; MCP only | **MCP plus the Claude Terminal add-on for log tailing, probe scripts, and hotfix deployment; device writes still require per-item approval** | Section 17. |

---

## 15. Acceptance scenarios (run on the live network after Phase 1/2)

| ID | Scenario | Pass criteria |
|---|---|---|
| S1 | Read: open Devices, select Bedroom Scene Controller (036) | 12 emitters with the labels Z-Wave JS knows, lifeline marked system and not editable, group 1 shows node 1 (controller), capacity shown per group |
| S2 | Remote template: "036 main button controls Master Bedroom Lights (037)" with on/off, hold-to-dim, level sync, status feedback back to 036 | plan shows adds for 036 groups 2,3,4 to 037 and 037 report group to 036, no parameter writes unless selected; apply completes; verify marks all `in_sync`; `switch.bedroom_scene_controller_link_...` exists on the 036 device page and is on |
| S3 | Scene buttons on 036: button 1 to 035, button 3 to 038, button 4 to 039, with dim | plan shows Pressed/Held pairs (5/6, 9/10, 11/12); apply and verify pass; button 2 remains empty (D15) |
| S4 | Off-all on 039 small button 2 to 035, 037, 038 (and own load via hybrid if D3/D15 say so) | capacity checked; self-target correctly blocked natively with the hybrid suggestion; applied links verified |
| S5 | ZEN37 remote (040): button 1 to 039, button 2 off-all | links show `pending_wakeup` with the wake instruction; after Jayant presses a button, links become `in_sync` without further user action |
| S6 | Drift: Jayant removes one association in Z-Wave JS UI | rule shows `drift` and `binary_sensor` Drift turns on within 30 s; Repairs issue appears; "Plan and apply" restores it; drift clears |
| S7 | Swap: import a profile referencing dead node 13 ("Ceiling Lights Old") and swap it to node 42 ("Ceiling Lights") | wizard maps emitters automatically (same model), rewrites the rules, plans links on 42, marks the old device's links as unreachable, applies and verifies |
| S8 | Zigbee: "Entrance Inside Lights Aux" EP2 controls "Entrance Inside Lights" EP1 with on/off and dim | bind response per cluster shown; `bridge/devices` confirms bindings; reporting configured; rule `in_sync` |
| S9 | Automation: toggle the S2 rule switch off then on from a script | links removed, then re-added and verified; a burst of 5 toggles in 10 s results in one coalesced final apply |
| S10 | Profile export/import/rollback | export YAML, delete a rule, import, plan shows exactly the re-add; rollback to the pre-apply snapshot restores the previous links |
| S11 | Safety: attempt to remove node 1 from any lifeline via raw service and via crafted WS call | refused in both paths with a translated error |
| S12 | Unload/reload the config entry during idle and during an apply | idle: clean; during apply: job `interrupted`, no exceptions in the log, panel re-registers |

---

## 16. Testing strategy (regressions are the enemy)

Tests are part of every phase's definition of done; a feature without tests is not done. Levels:

1. **Unit tests, pure modules (no Home Assistant imports)**: `models`, `compiler`, `planner`, `yaml_io`, `zwave_protocol`, `zigbee_protocol`, `matter_protocol`, profile DB schema validation. Target 100% line coverage for these modules. Property-based tests with Hypothesis on a `FakeBackend`: for any profile and any starting observed state, plan then apply converges to desired state, a second plan is empty (idempotence), lifeline and coordinator entries are never removed, group capacity is never exceeded, unmanaged links are never removed unless selected.
2. **Backend contract tests**: each adapter runs against recorded fixtures from Stage 0 (node dumps, `bridge/devices` payloads, Matter attribute reads) through fake clients that mimic the upstream libraries (fake `Node`/`Controller` objects for `zwave-js-server-python`, HA's `async_fire_mqtt_message` helper for MQTT, a fake Matter client). Fixtures are refreshed whenever upstream versions change and the diff is reviewed.
3. **Home Assistant integration tests** (`pytest-homeassistant-custom-component`): config flow, options, reconfigure (100%); setup, unload, reload; entity creation, attachment to upstream devices, availability transitions; services with valid and invalid input (`ServiceValidationError` paths); WebSocket commands via `hass_ws_client` including admin gating; Repairs issues; diagnostics redaction; bus events; rate limiting of rule switches; job lifecycle including cancel and restart-interrupted; storage migrations from every previous schema version.
4. **System scenario tests**: scenarios S1-S12 encoded as data files and executed against in-process simulators (`FakeZWaveNetwork` with sleeping nodes, capacity, security classes, external edits and driver restarts; `FakeZigbee2MQTT`; `FakeMatterFabric`). The same scenario files drive the live runner.
5. **Live tests (opt-in, never in CI)**: `pytest -m live` reads a token and URL from environment variables and talks to Jayant's HA through the integration's own WebSocket API. The read-only suite can run anytime and asserts that observed reads still match the shape of the fixtures. The write suite is restricted to a designated sandbox (node 36 group 8 and the Zigbee pair approved in Stage 0 G2), snapshots before, restores after, and fails if the post-state differs from the pre-state.
6. **Frontend**: vitest unit tests for view models (plan rendering, compiler warnings, filtering, matrix generation) and Playwright smoke tests against a mocked `hass` object for the main flows (create rule from template, plan and apply dialog, swap wizard, adopt all).
7. **Regression policy**: every bug fix adds a test named after the issue (`test_issue_<n>_<slug>`), first failing then passing; CI blocks merge when coverage drops below the gate; a nightly workflow runs the suite against Home Assistant `dev` and the current beta (allowed to fail, but it opens an issue automatically when it does).
8. **Gates**: Python coverage >= 95% (`--cov-fail-under=95`), pure modules 100%, `mypy --strict`, `ruff check` and `ruff format --check`, hassfest, HACS validation, frontend build and tests, and a check that the committed frontend bundle matches a fresh build.

## 17. Observability and remote debugging by Claude

Goal: during the first weeks in use, Claude (through the Home Assistant MCP server used in this session, and through the Claude Terminal add-on already installed on Jayant's HA) can see what the integration is doing, diagnose a problem from a single conversation, ship a fix, and verify it, without Jayant hand-collecting logs.

### 17.1 What the integration exposes

- **Diagnostics** (`diagnostics.py`, config-entry level and device level, redacted with `async_redact_data` for home id, IEEE addresses, Matter node ids, DSKs): integration version and manifest; options; backend status with upstream versions (HA core, zwave-js-server schema and driver version, Zigbee2MQTT version from `bridge/info`, Matter server version); active profile summary with every rule, its compiled links, desired vs observed per link, status and timestamps; observed-state cache per device; the last 50 jobs with per-link results and raw backend error text; the last 200 log records from an in-memory ring-buffer log handler for the integration's logger namespace; event-subscription liveness (last event time per backend); hybrid-leg counters; storage schema version; timing metrics (p50/p95 per backend operation). Readable via the HA UI download and via MCP (`ha_get_integration(entry_id=..., include_diagnostics=True, diagnostics_fields=[...])`).
- **Health sensor** (`sensor.device_links_health`, Section 6.6): one cheap entity whose state and attributes summarize everything above; the first thing Claude reads.
- **Logging**: logger namespace `custom_components.device_links.<module>`; INFO for lifecycle and job summaries, DEBUG for wire-level payloads (never above DEBUG); runtime level changes through the standard `logger.set_level` service (Claude can enable DEBUG via MCP, then read `ha_get_logs(source="system"|"error_log", search="device_links")`).
- **Repairs issues and bus events** as the primary "something needs attention" signals (Section 9), both readable via MCP.
- **Debug bundle service** `device_links.export_debug_bundle` (`redact: bool = true`, response contains the path): writes `<config>/device_links/debug/<timestamp>.json` containing the unredacted diagnostics when `redact` is false, for local inspection through the terminal add-on only. Bundles are never sent anywhere.
- **Self-check (opt-in option)**: a daily verify plus health summary event `device_links_health_report`, so a review needs one event or one sensor read rather than logs.

### 17.2 Remote debugging playbook (documented in `docs/remote-debugging.md` and summarized in `CLAUDE.md`)

1. Read `sensor.device_links_health` and Repairs (`ha_get_state`, `ha_get_system_health(include="repairs")`).
2. Pull diagnostics through `ha_get_integration(..., include_diagnostics=True)` with `diagnostics_fields` to stay within context limits; page large lists with `diagnostics_data_path` and `diagnostics_data_limit`.
3. If needed, raise the log level with `logger.set_level`, reproduce with `device_links.verify` (read-only) or a scoped `device_links.apply` (only with Jayant's approval, since it writes to devices), then read logs.
4. One-shot WebSocket commands from the panel API are also callable through `ha_call_service(ws_command="device_links/plan", data={...})`, so Claude can see exactly the plan a user would see.
5. With the Claude Terminal add-on (or SSH add-on): `ha core logs`, inspect `/config/.storage/device_links.profiles`, run `tools/probe_zwave.py` inside the Z-Wave JS UI container via `docker exec` (the prototype's proven method), and deploy a fix branch to `/config/custom_components/device_links` (Decision D21), then `ha core restart`.
6. Close the loop: turn the diagnostics into a fixture, write the regression test, fix, release, and verify on the live system through the same MCP reads.

### 17.3 Privacy and safety

Everything stays local. No telemetry, no outbound calls. Debug bundles live in the config directory and are listed in the docs so users know what they contain. Device writes during debugging follow the same approval rule as Stage 0.

### 17.4 Deployment paths on Jayant's HA

- **Iteration (until Jayant opts into HACS releases)**: the `dev` branch on GitHub is the source of truth; `custom_components/device_links` on the HA host is a pull-deployed copy of that branch (Section 17.5). The built frontend bundle is committed, so no build step runs on the HA host.
- **Releases**: HACS custom repository pointing at the GitHub repo; tagged releases with the zip asset; HACS "show beta versions" for pre-releases. Switching is documented (remove the pull-deployed directory, install from HACS; `.storage` data is unchanged).

### 17.5 Automated dev deployment: GitHub to Home Assistant, triggered by Claude Code

**Requirement (Decision D21).** Claude Code runs on Jayant's computer, writes code, commits, and pushes to GitHub. The new code must then show up on Jayant's HA instance **through GitHub** (HA pulls from GitHub; nothing is copied directly from the laptop), so Jayant can test the integration and its fixes. Any HA restart is left to Jayant.

**Design: pull-based deploy tool on the HA host, triggered over MCP.**

1. `tools/ha_deploy.py` (in the repository, stdlib only: `urllib`, `zipfile`, `json`, `shutil`, `hashlib`, `compileall`) is installed once at `/config/tools/ha_deploy.py` (Stage 0 item R2). It runs inside the HA Core container through the `shell_command` integration, which is the one supported way to run a script from a service call without add-ons:

   ```yaml
   # configuration.yaml (git-tracked, one-time)
   shell_command:
     deploy_device_links: "python3 /config/tools/ha_deploy.py deploy --repo <owner>/ha-device-links --branch dev --domain device_links"
     deploy_device_links_ref: "python3 /config/tools/ha_deploy.py deploy --repo <owner>/ha-device-links --ref {{ ref }} --domain device_links"
     rollback_device_links: "python3 /config/tools/ha_deploy.py rollback --domain device_links"
     device_links_deploy_status: "python3 /config/tools/ha_deploy.py status --domain device_links"
   ```

2. `deploy` does, in order, and aborts leaving everything untouched on any failure:
   - Resolve the branch head through `https://api.github.com/repos/<owner>/<repo>/commits/<branch>` (or use `--ref <sha>`), download the immutable archive `https://codeload.github.com/<owner>/<repo>/zip/<sha>`, and verify the archive's top-level directory and the presence of `custom_components/<domain>/manifest.json` with the expected `domain`.
   - Extract to `/config/custom_components/.<domain>.new`, run `python3 -m compileall -q` on it (catches syntax errors before anything is swapped), and compute a file-hash diff against the currently deployed directory.
   - Back up the current directory to `/config/<domain>/backups/<timestamp>-<oldsha>/` (keep the last 5), then swap atomically (rename current away, rename new into place).
   - Write `/config/custom_components/<domain>/.deployed` as JSON: `{"commit", "branch", "deployed_at", "previous_commit", "changed_files"}`. The integration reads this file at startup and exposes `commit` and `deployed_at` on the Health sensor and in diagnostics.
   - Print one JSON object to stdout: `{"ok": true, "commit", "previous_commit", "changed_files": [...], "restart_required": bool, "browser_reload": bool}`. `restart_required` is true when any file outside `frontend/` changed (Python modules only reload on HA restart); `browser_reload` is true when frontend files changed (the panel serves them from disk with `cache_headers=False` in dev builds, so a hard refresh picks them up without a restart).
   - Never restarts Home Assistant, never reloads the config entry, never touches `.storage`.
   - `rollback` restores the newest backup with the same swap and JSON output; `status` prints the current `.deployed` content.
   - Security: HTTPS only, repository pinned by the command line, no credentials required for the public repository (if the repo is ever private, the token is passed from `secrets.yaml` through the shell command's environment, never stored in the script), nothing executed from the archive, only the `custom_components/<domain>` subtree is extracted.

3. **Trigger from Claude Code** through the same HA MCP server used in this session (`ha_call_service(domain="shell_command", service="deploy_device_links", return_response=True)`); the JSON summary comes back as the service response. `shell_command` returns stdout, stderr, and the return code, so failures are visible to Claude immediately. The Claude Terminal add-on remains a fallback for the rare case where the shell command itself is broken.

4. **The loop Claude Code follows (also in `CLAUDE.md`):**
   1. `scripts/test` and `scripts/lint` pass locally (unit, contract, HA integration, frontend).
   2. Commit with a conventional message on `dev` (or a feature branch merged into `dev`), push. CI runs on GitHub in parallel; `main` stays protected and only receives merges from `dev` when CI is green.
   3. Trigger `shell_command.deploy_device_links` over MCP, parse the JSON, and report the commit and the list of changed files to Jayant.
   4. If `restart_required`, create a persistent notification through MCP ("Device Links <sha> deployed; restart Home Assistant to load it") and **stop; do not call `ha_restart`**. If only `browser_reload`, say so.
   5. After Jayant restarts, poll `sensor.device_links_health` until its `commit` attribute equals the pushed SHA and the state is `ok`; then run the read-only live suite (`pytest -m live`) from Jayant's computer against HA, and read the Health sensor and Repairs once more.
   6. If the deploy is bad, trigger `shell_command.rollback_device_links`, tell Jayant a restart is needed, and open a regression test.

5. **Later, HACS path (Decision D21 (a)):** once releases exist, the HACS update entity for the repository is installable through MCP (`ha_manage_updates(action="install", entity_ids=[...])`) with the same "restart is manual" rule. The deploy tool and its `shell_command` entries are removed at that point and the directory is reinstalled from HACS.

## 18. Repository, releases, maintenance, and CLAUDE.md

### 18.1 Repository creation (Stage 0 item R1)

Automatic path (preferred): check `gh auth status`. If authenticated, run, from the skeleton directory:

```
gh repo create <owner>/ha-device-links --public --source=. --push \
  --description "Home Assistant integration for Z-Wave associations, Zigbee bindings and Matter bindings: templates, profiles, verification, drift detection"
gh repo edit --add-topic home-assistant --add-topic hacs --add-topic home-assistant-integration --add-topic zwave --add-topic zigbee --add-topic matter --add-topic associations --add-topic bindings
gh label create bug --color d73a4a ; gh label create needs-diagnostics --color fbca04 ; gh label create device-profile --color 0e8a16 ; gh label create backend:zwave ; gh label create backend:zigbee ; gh label create backend:matter ; gh label create regression
```

Then enable Dependabot (`.github/dependabot.yml` for `pip`, `npm`, `github-actions`, weekly), branch protection on `main` (require CI status checks, no force push), and Issues with templates. Manual path: if `gh` is missing or not authenticated, print the exact manual steps (create the repository in the GitHub UI with the same name, description, and topics; `git remote add origin ...`; `git push -u origin main`; enable Actions; add branch protection) and stop until Jayant confirms.

### 18.2 Repository contents

Everything in Section 8.1 plus: `.github/workflows/ci.yml` (lint, type check, tests, coverage, hassfest, HACS validation, frontend build check), `nightly.yml` (HA dev/beta), `release.yml` (tag-triggered), `.github/ISSUE_TEMPLATE/bug_report.yml` (asks for the diagnostics download and versions), `feature_request.yml`, `device_profile_request.yml`, `PULL_REQUEST_TEMPLATE.md` (checklist: tests added, docs updated, CHANGELOG updated, quality_scale.yaml reviewed), `CODEOWNERS`, `CONTRIBUTING.md` (including how to add a profile DB entry), `SECURITY.md`, `LICENSE` (MIT), `CHANGELOG.md` (Keep a Changelog), `CLAUDE.md`.

### 18.3 Versioning, releases, and the maintenance loop

- SemVer; `manifest.json` `version` is the source of truth; the release workflow refuses a tag that does not match it.
- Release flow: bump version and CHANGELOG in a PR, merge, tag `vX.Y.Z`, workflow builds the frontend, zips `custom_components/device_links` to `device_links.zip`, publishes the GitHub release with notes from the CHANGELOG. Pre-releases use `vX.Y.Z-beta.N`.
- Every change: branch, PR, green CI, merge. Bug fixes carry a regression test and a CHANGELOG line. Docs, `services.yaml`, translations, and `quality_scale.yaml` are updated in the same PR as the behavior change.
- When Home Assistant, zwave-js-server, Zigbee2MQTT, or the Matter Server change versions on Jayant's system, re-run the read-only Stage 0 probes, refresh fixtures, and update `docs/stage0-report.md`.
- Issue triage labels and a monthly compatibility check against the latest HA release are part of the routine. HACS default-repository submission happens after the first stable release and the brands PR.

### 18.4 CLAUDE.md (written in Stage 0, kept current)

`CLAUDE.md` at the repository root must contain:

1. **Purpose and status**: one paragraph, link to this PRD (`docs/PRD.md`) and to `docs/stage0-report.md`.
2. **Architecture invariants**: pure modules never import Home Assistant; backends implement `Backend`; storage schema changes require a migration and a test; the frontend bundle is committed and must match a fresh build; no new Python requirements without a decision-register entry.
3. **Safety rules**: never write to a device without explicit approval for that specific write; the only pre-approved write sandbox is node 36 group 8 and the Stage 0 G2 Zigbee pair, with restore after; read before write, verify after write; lifeline, coordinator, and Administer ACL entries are untouchable; never remove unmanaged links by default; never use `force` on `addAssociations`.
4. **Commands**: `scripts/setup`, `scripts/test` (unit, integration, `-m live` explanation), `scripts/lint`, `npm run build`, `npm run test`, release steps, and the deploy loop of Section 17.5 (`shell_command.deploy_device_links`, `rollback_device_links`, `device_links_deploy_status`) with the rule that Home Assistant restarts are Jayant's to perform: never call `ha_restart`, never call `homeassistant.restart`, never reload the entry as a substitute.
5. **Working with Jayant's Home Assistant**: which MCP tools to use for what (Section 17.2), the Claude Terminal add-on workflow, the `docker exec` probe pattern for zwave-js-server, where storage and debug bundles live, and that credentials never go into the repository.
6. **Coding standards**: `mypy --strict`, ruff, translations for every user-facing string, exception translations, no em dash anywhere, conventional commits, tests for every change.
7. **Decision register pointer** and the list of open decisions with their defaults.
8. **Debugging playbook** summary and the regression-test naming rule.
9. **Known gotchas**: Long Range nodes, sleeping nodes and `pending_wakeup`, Zigbee2MQTT friendly-name renames (store IEEE), Zigbee reporting removal on unbind, Matter TLV-tag serialization and ACL capacity, HA frontend component lazy loading in the panel.
10. **When in doubt, ask**: a short list of things that always require a question to Jayant (any device write outside the sandbox, any storage schema change that cannot be migrated, any change to what counts as a system link, anything that would restart Home Assistant or an add-on).

## Appendix A: device notes captured for the profile database (seed entries)

| Device (backend) | Emitters (label: id) | Settings adapters | Wake instruction |
|---|---|---|---|
| Zooz ZEN35 (zwave, fw 1.40) | Main button Pressed: g2 (Basic Set), Held: g3 (Multilevel), Start/Stop: g4; Button N Pressed: g(3+2N), Held: g(4+2N); Lifeline g1 (max 10) | `mirror_hub_commands` = param 35 bit 4; `send_local_to_associations` = param 35 bit 1; `report_command_class` = param 33 (0 Basic, 2 Multilevel); `local_control` = param 19; LED modes params 1-5 (own load only) | mains |
| Zooz ZEN32 (zwave) | same layout as ZEN35 minus dimming groups (confirm in Z2) | expected same family; confirm | mains |
| Zooz ZEN37 800LR (zwave, battery) | confirm in Z2 (expected Basic/Multilevel pair per large button) | none expected | press any button to wake |
| Inovelli VZW32-SN / VZW31-SN (zwave, fw 2.2 / 1.4) | Paddle on/off: g2 (Basic Set), level sync: g3 (Multilevel Set), hold: g4 (Start/Stop), double-tap: g5, triple-tap: g6, cycle levels: g7 (param 130) | `send_local_to_associations` = param 59 bit 1; `mirror_hub_commands` = param 59 bit 2; `smart_bulb_mode` = param 52; `switch_type` = param 22 (informational); `dimmer_mode` = param 158 | mains |
| Inovelli LZW31-SN Gen2 (zwave) | g2 Basic Set, g3 Multilevel, g4 Start/Stop (confirm) | `association_behavior` = param 12 bitmask (1 local, 2 3-way, 4 Z-Wave hub, 8 timer) | mains |
| Inovelli VZM31-SN / VZM35-SN (zigbee2mqtt) | Paddle: EP2 (genOnOff, genLevelCtrl); Config button: EP3 (fw 2.17+, requires param 130 cycle/multi-tap); Load: EP1 (target) | `smart_bulb_mode`, `local_protection`, `remote_protection`, `binding_off_to_on_sync_level` via `/set` | mains |
| Inovelli VZM32-SN (zigbee2mqtt) | confirm EP layout in G1 | as above | mains |
| Inovelli White VTM31-SN (matter) | confirm ClientList per endpoint in M1 | none | mains |
| Aqara Light Switch H2 US, IKEA BILRESA (matter) | confirm in M1 | none | BILRESA: press a button to wake |

## Appendix B: wire-level cheat sheet (for probes and tests)

```
zwave-js-server (via zwave-js-server-python or raw WS):
  controller.get_association_groups   {nodeId, endpoint}
  controller.get_all_association_groups {nodeId}
  controller.get_associations         {nodeId, endpoint}
  controller.get_all_associations     {nodeId}
  controller.check_association        {nodeId, endpoint?, group, association: {nodeId, endpoint?}}   (name per Stage 0 Z1)
  controller.add_associations         {nodeId, endpoint?, groupId, associations: [{nodeId, endpoint?}]}
  controller.remove_associations      {nodeId, endpoint?, groupId, associations: [{nodeId, endpoint?}]}
  controller.remove_node_from_all_associations {nodeId}
  node.refresh_cc_values              {nodeId, commandClass: 0x85 | 0x8E}   (confirm in Z3)
  errors: {type: result, success: false, errorCode, message, zwaveErrorCode?, zwaveErrorMessage?}

Zigbee2MQTT:
  read : retained <base>/bridge/devices, <base>/bridge/groups, <base>/bridge/info, <base>/bridge/state
  bind : <base>/bridge/request/device/bind   {from, from_endpoint, to, to_endpoint, clusters: [...], transaction}
  unbind: <base>/bridge/request/device/unbind {same, skip_disable_reporting?}
  clear: <base>/bridge/request/device/binds/clear {target, ieee_list?}
  groups: <base>/bridge/request/group/add {friendly_name}, .../group/remove, .../group/members/add {group, device}, .../group/members/remove
  responses on <base>/bridge/response/<same path> {data, status: ok|error, error?, transaction}

Matter (via HA matter client):
  read  Descriptor.ClientList  (endpoint/29/2), Binding.Binding (endpoint/30/0), AccessControl.ACL (0/31/0) and capacity attrs
  write Binding.Binding list of {node, endpoint, cluster} on source; AccessControl.ACL merged list on target
```

## Appendix C: references consulted (2026-09-05)

- Z-Wave JS controller API, associations section and `AssociationCheckResult`: github.com/zwave-js/zwave-js/blob/master/docs/api/controller.md
- Z-Wave JS changelog: `isAssociationAllowed` replaced by `checkAssociation` (v13): github.com/zwave-js/zwave-js/blob/master/CHANGELOG.md
- zwave-js-server README (controller command naming): github.com/zwave-js/zwave-js-server
- zwave-js-server-python (HA's client library): github.com/home-assistant-libs/zwave-js-server-python
- Zigbee2MQTT Binding guide, Groups guide, MQTT topics: zigbee2mqtt.io/guide/usage/binding.html, groups.html, mqtt_topics_and_messages.html
- Inovelli: VZW32-SN manual (association groups), Blue-series binding endpoints (EP2 paddle, EP3 config button), Z-Wave JS UI association how-to (enable mirroring on one side): help.inovelli.com
- Matter binding prior art: github.com/cedricziel/ha-matter-binding-helper; python-matter-server issue #815; matterjs-server CHANGELOG (binding/ACL dashboard writes, TLV-tag serialization)
- Home Assistant Integration Quality Scale index and rules: developers.home-assistant.io/docs/core/integration-quality-scale/ and /rules
- Custom panel registration from an integration (community guide, Jan 2026) and `async_register_static_paths` developer blog (June 2024)
- HACS publishing requirements: hacs.xyz/docs/publish/integration/ and /publish/include/
