# Phase 2A: the Zigbee2MQTT backend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second backend behind the same `Backend` protocol, so a Zigbee paddle can control a Zigbee light through the same rules, plans and UI that already work for Z-Wave.

**Architecture:** `backends/zigbee_protocol.py` is pure (parsing `bridge/devices`, building bind payloads). `backends/zigbee2mqtt.py` is the adapter: MQTT subscribe, request and response correlation, managed groups. Core code changes as little as possible; if it needs to change, the abstraction was wrong.

**Tech Stack:** Python 3.14, Home Assistant's `mqtt` integration, the Stage 0 G1 fixture.

---

## The honest position on the write path

**Stage 0 item G2 was never approved, so no Zigbee bind has ever been performed.** Everything about writing here comes from the Zigbee2MQTT documentation, not from observation. That is recorded as assumption **A2** in `docs/open-items.md` and as issue #6.

What this means for how you build:

- The **read** path is proven. `tests/fixtures/g1_bridge.json` is a real capture of the live bridge, and the schema in it is confirmed.
- The **write** path is a model. Build it, test it thoroughly against a fake bridge, and put a comment on every write path naming assumption A2 and issue #6, exactly as the Z-Wave adapter does for sleeping nodes.
- **Do not soften the tests to match the model.** If the model is wrong, the tests should be wrong in the same way and get fixed together when G2 runs.

## What Stage 0 G1 established

From the real bridge, Zigbee2MQTT 2.14.1:

- `bridge/devices` carries per-endpoint `bindings`, `clusters.input` / `clusters.output`, and `configured_reportings`.
- A binding target is `{type: "endpoint", ieee_address, endpoint}` or `{type: "group", id}`.
- Inovelli Blue VZM31-SN: endpoint 1 is the load, **endpoint 2 is the paddle** and emits `genOnOff` and `genLevelCtrl`, endpoint 3 is the config button and emits the same.
- **Every binding on the network today targets the coordinator.** Those are Zigbee2MQTT's own reporting setup and must be classified as system links: offering them for removal would invite a user to delete the thing that makes their devices report at all.
- **No Zigbee groups exist**, so the `dl_` prefix starts clean.
- Exactly one coordinator is reported, so the stale second bridge device the PRD warns about is a Home Assistant registry leftover, not something the bridge knows about.

From the documentation (unproven, assumption A2):

- Bind: `<base>/bridge/request/device/bind` with `{from, from_endpoint, to, to_endpoint, clusters, transaction}`; response on `<base>/bridge/response/device/bind` with `{data: {from, from_endpoint, to, to_endpoint, clusters, failed}, status, error, transaction}`.
- **`status` is `error` only when every cluster failed.** A partial failure reports `ok` with a non-empty `failed` list. Treating `ok` as success is therefore a real bug, and there is a test for it.
- **An on-only binding is impossible**: `genOnOff` carries both on and off. The compiler already knows this; the adapter must not pretend otherwise.
- Unbinding removes the attribute reporting Zigbee2MQTT configured, unless `skip_disable_reporting` is set.
- A sleeping battery source must be awake when the request is made.

## Ground rules

Read `CLAUDE.md`, `docs/stage0-report.md` and `docs/open-items.md` first.

- **Deployment to Jayant's Home Assistant is paused.** Do not deploy, do not touch the instance.
- `zigbee_protocol.py` is a **pure module**: add it to `PURE_MODULES` in `tests/test_manifest.py`.
- **Core code should barely change.** The `Backend` protocol exists so a second backend slots in. If you find yourself editing `compiler.py` or `planner.py` to special-case Zigbee, stop and say so: either the abstraction is wrong or the change belongs in the adapter.
- Never use the em dash. `mypy --strict` clean. Coverage gate 95%.
- Conventional commits ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Register anything unresolved in `docs/open-items.md`**, continuing from T40.

---

### Task 1: Pure Zigbee interpretation

**Files:** create `backends/zigbee_protocol.py`, `tests/test_zigbee_protocol.py`; modify `tests/test_manifest.py`

- [x] Parse `bridge/devices` into handles, capabilities and observed links, driven by the real
      G1 fixture. Cover: every device in the fixture parses; an endpoint with output clusters
      becomes an emitter; `genOnOff` maps to `on_off` and `genLevelCtrl` to both `level_set`
      and `level_hold` (Zigbee does not separate them the way Z-Wave groups do, and the
      compiler must see that honestly rather than being told they are separate emitters);
      a binding whose target is the coordinator is a **system** link; a group target parses
      as a group rather than an endpoint.
- [x] Build bind and unbind payloads. Cover: clusters are always listed explicitly and never
      "all supported"; `from_endpoint` and `to_endpoint` are always present for an endpoint
      target; a group target omits `to_endpoint`; every payload carries a `transaction`.
- [x] Parse a response. Cover: `status: ok` with an empty `failed` is success; **`status: ok`
      with a non-empty `failed` is a partial failure and must not read as success**;
      `status: error` carries the error text.
- [x] Commit: `feat(zigbee): pure parsing of bridge state and bind payloads`

### Task 2: A fake Zigbee2MQTT bridge

**Files:** create `tests/fakes/zigbee.py`, `tests/test_fakes_zigbee.py`

- [x] Build a fake bridge from `tests/fixtures/g1_bridge.json` that holds real state: a bind
      request updates `bridge/devices`, an unbind removes it, and group operations work.
- [x] It must reproduce the documented behaviours that matter: correlation by `transaction`,
      a partial failure (`ok` plus a `failed` list), a total failure (`status: error`), a
      request that never gets a response (so the timeout path is reachable), and a sleeping
      device that refuses.
- [x] **The fake is a model of an unobserved system.** Say so in its module docstring, name
      assumption A2 and issue #6, and note that when G2 runs, the fake is what gets corrected.
- [x] Commit: `test(zigbee): fake bridge built from the Stage 0 capture`

### Task 3: The adapter, read path

**Files:** create `backends/zigbee2mqtt.py`, `tests/test_zigbee_backend.py`

- [x] Subscribe to `<base>/bridge/devices`, `bridge/groups`, `bridge/info`, `bridge/state`.
      Implement `async_devices`, `async_capabilities`, `async_observed`.
- [x] **Store the IEEE address in the handle and resolve the friendly name at request time**
      (E23). Friendly names are renameable; a handle keyed on one breaks silently when a user
      tidies their names.
- [x] Base topic is configurable and must not be hard-coded, since the identifier format
      embeds it and a second instance uses a different one.
- [x] `bridge/state` going offline marks the backend unavailable, logging once (E26).
- [x] Commit: `feat(zigbee): read devices, capabilities and observed state`

### Task 4: The adapter, write path

**Files:** modify `backends/zigbee2mqtt.py`; create `tests/test_zigbee_writes.py`

- [x] `async_add_link`, `async_remove_link`, `async_check_link`, with request and response
      correlated by `transaction` and a **20** second timeout: the executor's own operation
      timeout is 30 seconds, and two timers of the same length would pick at random between
      "the bridge did not answer this bind" and "a backend did not return".
- [x] **A partial failure is a failure.** A response with `status: ok` and a non-empty
      `failed` must produce a failed `LinkResult` naming the clusters that failed, not a
      success. This is the single most likely way to ship a bug that looks like it works.
- [x] A coordinator binding is refused, the same way a lifeline is on Z-Wave. Same reasoning,
      same defence in depth: the planner will not ask, but a service call could.
- [x] A sleeping source reports `pending_user_action` with the wake instruction rather than a
      failure (E22).
- [x] Every write path carries a comment naming assumption A2 and issue #6.
- [x] Commit: `feat(zigbee): bind and unbind with per-cluster failure reporting`

### Task 5: Managed groups

**Files:** modify `backends/zigbee2mqtt.py`; create `tests/test_zigbee_groups.py`

Decision D5: one-to-many uses a managed Zigbee group rather than many unicast binds, because
unicast to many targets sends commands sequentially and hits binding-table limits.

- [x] A rule with more than one Zigbee target creates a group named `dl_<rule_id>`, keeps its
      membership in sync, binds the source to the group, and deletes it when the rule goes.
- [x] **The adapter refuses to touch any group without the `dl_` prefix.** A user's own groups
      are not ours to modify, and this is the guard that makes the feature safe to ship.
- [x] A managed group that has disappeared is recreated on apply; a foreign group with a
      colliding name is a warning, never a takeover (E24).
- [x] Commit: `feat(zigbee): managed groups for one-to-many rules`

### Task 6: Profile database entries for Inovelli Blue

**Files:** create `profiles_db/inovelli_blue.json`; modify tests

- [x] Entries for VZM31-SN and **VZM32-SN**: paddle on endpoint 2, config button on
      endpoint 3, load on endpoint 1 as a target. Settings adapters for `smart_bulb_mode`,
      `local_protection`, `remote_protection`, `binding_off_to_on_sync_level`.
      **VZM35-SN was not shipped**: no device of that model is on this network, so nothing
      about it could be checked against the capture, and this task's own validation rule is
      the reason not to guess. VZM32-SN is in the capture and took its place.
- [x] **Validate against the G1 fixture** the same way the Z-Wave entries are validated
      against Z2: every endpoint an entry names must exist on the real device, and every
      cluster it claims must be in that endpoint's output list. A curated entry that is
      wrong writes a binding to the wrong place with full confidence.
- [x] VZM32-SN appears in the fixture too. Add it if the capture supports it; if the capture
      does not show its endpoint layout, say so and leave it to the generic path rather than
      inventing one.
- [x] Commit: `feat(zigbee): profile entries for Inovelli Blue, validated against the capture`

### Task 7: End to end, and PRD scenario S8

**Files:** create `tests/test_zigbee_loop.py`

- [x] Scenario **S8**: "Entrance Inside Lights Aux" endpoint 2 controls "Entrance Inside
      Lights" endpoint 1 with on/off and dim. Compile, plan, apply, verify, re-plan empty.
- [x] A one-to-many rule creating a managed group, applied and verified.
- [x] A partial cluster failure surfaces as a failed link with the cluster named, and the
      plan converges on retry.
- [x] **A mixed-backend profile**: one Z-Wave rule and one Zigbee rule in the same profile,
      planned and applied together. This is the test that proves the `Backend` abstraction
      actually held. If it needed core changes to pass, say so prominently.
- [x] Commit: `test(zigbee): scenario S8 and a mixed-backend profile end to end`

---

## Phase 2A exit criteria

- [x] `ZigbeeBackend` satisfies the `Backend` protocol, tested
- [x] Coordinator bindings are system links and cannot be removed
- [x] A partial cluster failure never reads as success
- [x] Groups without the `dl_` prefix are never touched
- [x] Profile entries are validated against the real G1 capture
- [x] A mixed Z-Wave and Zigbee profile plans and applies, with **no special-casing in core**
- [x] Every write path names assumption A2 and issue #6
- [x] All gates pass, CI green, nothing deployed
