# Phase 1D: the Home Assistant surface

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose everything Phases 1A to 1C built to Home Assistant: entities, services, events, diagnostics, Repairs, and the admin WebSocket API the panel will call.

**Architecture:** Thin platforms over the coordinator and the job runner. No new decisions live here. Entities read coordinator state and push updates; services validate input and delegate; the WebSocket API is the same surface the panel uses, so anything the panel can do is scriptable.

**Tech Stack:** Python 3.14, Home Assistant entity platforms, `websocket_api`, `voluptuous`, `pytest-homeassistant-custom-component`.

---

## This is the first phase whose code can write to real hardware

Everything before this was reachable only from tests. After 1D, a service call or a WebSocket
command can drive the executor into a real Z-Wave write.

That changes two things:

1. **Admin gating is not a formality.** Every WebSocket command requires an admin user
   (`@websocket_api.require_admin`). The raw services that write directly to groups are off
   unless the user turns them on, and are documented as expert tools.
2. **No live apply during development.** Nothing in this phase may run an apply against
   Jayant's network. Tests use the fakes. Live validation happens later, deliberately, with
   his approval.

## Ground rules

Read `CLAUDE.md`, `docs/stage0-report.md` and `docs/open-items.md` first.

- **Never restart Home Assistant.** Deploy, notify, stop.
- **No test may touch the live network.** Use the Phase 1B fakes.
- Every user-facing string is a translation key with an entry in `strings.json` and
  `translations/en.json`. This phase closes open item **S5**.
- Never use the em dash. `mypy --strict` clean. Coverage gate 95%; repo is at 100%.
- Conventional commits ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Ruff formats Python blocks inside Markdown; run `ruff format` on any `.md` you touch.
- **Register anything unresolved in `docs/open-items.md`**, continuing from T20.

## Quality-scale rules this phase must satisfy

From PRD Section 11, these are the ones that bite here, and each needs a test:

`entity-unique-id`, `has-entity-name`, `entity-event-setup` (subscribe in
`async_added_to_hass`, unsubscribe in `async_will_remove_from_hass`), `entity-category`,
`entity-device-class`, `entity-disabled-by-default`, `entity-translations`,
`exception-translations`, `icon-translations`, `parallel-updates`, `action-setup`
(services registered in `async_setup`, not `async_setup_entry`), `action-exceptions`,
`config-entry-unloading`, `entity-unavailable`, `log-when-unavailable`, `devices`,
`diagnostics`, `repair-issues`, `stale-devices`.

---

## File structure

| File | Responsibility |
|---|---|
| `entity.py` | Base entity: hub device info, availability, coordinator subscription. |
| `sensor.py`, `binary_sensor.py`, `switch.py`, `select.py`, `button.py` | The platforms. |
| `services.py`, `services.yaml` | Service registration, validation, delegation. |
| `websocket.py` | The admin API the panel calls. |
| `diagnostics.py` | Redacted config-entry and device diagnostics. |
| `repairs.py` | Repairs issues for E1, E5, E19. |
| `strings.json`, `translations/en.json`, `icons.json` | Every user-facing string and icon. |

---

### Task 1: Entity base, the hub device, and the health sensor

**Files:** create `entity.py`, `sensor.py`, `binary_sensor.py`; modify `__init__.py`, `const.py`; tests alongside

The Health sensor is the single entity Claude reads first when debugging remotely (PRD 17.1),
so it earns its complexity.

- [x] **Step 1: Write the failing tests.** Cover:
  - A hub device named "Device Links" is created, with `entry_type` service.
  - `sensor.device_links_health` exists, is enabled by default, and its state is one of
    `ok`, `degraded`, `error`.
  - Its attributes include `version` from the manifest, `commit` and `deployed_at` read from
    the `.deployed` file the deploy tool writes, backend states with upstream versions, job
    counters, and the last error.
  - **A missing `.deployed` file is not an error.** A HACS install has none, and the health
    sensor must still report `ok`. This matters: the file only exists on a dev deployment.
  - `binary_sensor` "Drift" has device class `problem`, is enabled by default, and turns on
    when any managed link in the active profile is drifted.
  - A `sensor` "Active profile status" aggregates rule states.
  - A `sensor` "Pending links" counts `pending_wakeup` and is **disabled by default**.
  - Entities are unavailable when every backend is unavailable, and available otherwise.
  - Backend loss logs once and recovery logs once, not per update (`log-when-unavailable`).
  - `PARALLEL_UPDATES = 0` on every platform, since entities are push-updated.
  - Every entity has a unique id derived from the entry id, and `_attr_has_entity_name`.

- [x] **Step 2: Run, confirm failure. Step 3: Implement. Step 4: Confirm. Step 5: Commit.**

```bash
git commit -m "feat(ha): hub device, health sensor and drift binary sensor"
```

---

### Task 2: Rule entities, attached to the user's own devices

**Files:** modify `switch.py`, `sensor.py`; create tests

FR-E1 attaches each rule's switch and status sensor to the **source device's existing Home
Assistant device entry**, so per-rule state appears on the device page the user already
knows. Phase 1B's P2 capture pinned the identifier formats; open item T13 records that the
adapter leaves `ha_device_id` empty and this layer resolves it from the registry.

**The failure mode to avoid:** a near-miss identifier does not error, it silently creates a
second, orphaned device. Test that the entity lands on the existing device, not a new one.

- [x] **Step 1: Write the failing tests.** Cover:
  - A rule switch is created per rule in the active profile, attached to the **existing**
    `zwave_js` device entry, asserted by counting devices before and after.
  - Turning the switch off disables the rule and plans removal of its links; turning it on
    re-enables. Assert against the coordinator's state, not just the entity.
  - **Toggling is rate limited**: at most one toggle per rule per 30 seconds is executed, and
    a burst coalesces to the latest requested state (E35, FR-E1). Assert that five toggles in
    ten seconds produce one apply with the final state, and that the attribute
    `rate_limited` reports it. Do this without real sleeps.
  - A per-rule status sensor exists, is **disabled by default**, and its state is one of
    `in_sync`, `drift`, `pending`, `applying`, `blocked`, `disabled`, `unknown`.
  - When a rule's source device is removed from the registry, its entities are removed
    (`stale-devices`).
  - Unloading the config entry removes every entity and leaves the upstream device entry
    untouched. **This closes the unload half of Stage 0 item P2**; say so in the test
    docstring and update `docs/open-items.md` R2.

- [x] **Steps 2 to 5** as above.

```bash
git commit -m "feat(ha): rule switches and status sensors on the source device"
```

---

### Task 3: Profile select, buttons, and events

**Files:** create `select.py`, `button.py`; modify `const.py`; tests

- [x] **Step 1: Write the failing tests.** Cover:
  - A `select` "Active profile" lists profiles and switching activates one.
  - **Switching a profile does not auto-apply** unless the option is on. It opens a plan.
    Assert no write occurs. This is FR-E1 and it protects a user from a select box quietly
    rewriting their house.
  - `button` "Apply active profile" and `button` "Verify" exist and are config category.
  - Events fire on the bus with the documented shapes: `device_links_job_finished`,
    `device_links_drift_detected`, `device_links_pending_wakeup` (FR-E2).
  - Every event payload is JSON-serializable, since automations and the recorder consume it.

- [x] **Steps 2 to 5.**

```bash
git commit -m "feat(ha): profile select, apply and verify buttons, bus events"
```

---

### Task 4: Services

**Files:** create `services.py`, `services.yaml`; tests

- [ ] **Step 1: Write the failing tests.** Cover:
  - Services are registered in `async_setup`, not `async_setup_entry` (`action-setup`), and
    exist even when the entry has not loaded, raising `ServiceValidationError` in that case.
  - `device_links.apply` with `profile_id`, `rule_ids`, `device_id`, `remove_unmanaged`,
    `deep_verify`; `verify`; `set_rule_enabled`; `activate_profile`; `export_profile` and
    `import_profile` with responses.
  - **Bad input raises `ServiceValidationError` and backend failures raise
    `HomeAssistantError`, both with translation keys** (`action-exceptions`,
    `exception-translations`). Test an unknown rule id, an unknown profile id, and a
    malformed YAML import.
  - `import_profile` **never writes to a device**. It updates desired state and returns a
    plan summary. Assert zero writes.
  - The advanced raw services (`zwave_get_associations`, `zwave_add_association`,
    `zwave_remove_association`) are **not registered unless the option is on** (D14), and
    when on, they refuse to touch a lifeline (S11).
  - `services.yaml` documents every service and every field, and every service in the file
    exists in code and vice versa. Write that as a test: a drifted `services.yaml` is a
    documentation bug users hit in the UI.

- [ ] **Steps 2 to 5.**

```bash
git commit -m "feat(ha): services with validated input and translated exceptions"
```

---

### Task 5: The WebSocket API

**Files:** create `websocket.py`; tests

This is the surface the panel calls in Phase 1E, so its shape decides the panel's shape.
Everything the panel can do is therefore also scriptable, which PRD 17.2 relies on for
remote debugging.

- [ ] **Step 1: Write the failing tests.** Cover:
  - Every command from PRD Section 8.7 is registered under `device_links/...`.
  - **Every command requires admin.** Test a non-admin user is rejected for at least
    `plan`, `apply` and `profiles/update`, and assert the standard unauthorized error.
  - `plan` returns a serialized plan including its token, grouped by device.
  - `apply` accepts a plan token and rejects a stale one (FR-A3).
  - `jobs/subscribe` streams progress and stops cleanly when the connection closes. Test
    that no callback fires after unsubscribe: a listener outliving its connection is a leak
    that survives a reload.
  - `rules/validate` returns compiler warnings and errors without saving anything.
  - Every response is JSON-serializable, and every error carries `code`, `message` and
    `translation_key`.

- [ ] **Steps 2 to 5.**

```bash
git commit -m "feat(ha): admin WebSocket API for the panel"
```

---

### Task 6: Diagnostics and Repairs

**Files:** create `diagnostics.py`, `repairs.py`; tests

- [ ] **Step 1: Write the failing tests.** Cover diagnostics:
  - A config-entry diagnostics dump includes version, options, backend status, the active
    profile with per-link desired versus observed, the observed cache, and the last jobs.
  - **Redaction is real**: the Z-Wave home id, Zigbee IEEE addresses, Matter node ids and any
    DSK are redacted. Assert by searching the serialized output for the raw values, not by
    trusting `async_redact_data` was called. A diagnostics file is the artifact users paste
    into public issue trackers.
  - Device-level diagnostics for one device.

  And Repairs:
  - **E1**: a backend's upstream integration not loaded raises an issue naming it.
  - **E5**: a link pending wake-up for more than 24 hours raises an issue carrying the wake
    instruction from the profile database.
  - **E19**: a rule referencing a device no longer in the registry raises an issue.
  - Each issue is removed when its condition clears. An issue that outlives its cause trains
    users to ignore Repairs.

- [ ] **Steps 2 to 5.**

```bash
git commit -m "feat(ha): redacted diagnostics and Repairs issues"
```

---

### Task 7: Strings, translations and icons

**Files:** modify `strings.json`, `translations/en.json`, `icons.json`; tests

This closes open item **S5**. Every diagnostic key the compiler, planner, adapter and
executor emit needs an entry, plus config flow, options, services, entities and exceptions.

- [ ] **Step 1: Write a test that finds missing keys mechanically.**

  Do not hand-maintain this list. Walk the source for `translation_key=` and
  `Diagnostic(translation_key=...)` literals, collect them, and assert every one has an entry
  in `strings.json`. Assert the reverse too, so dead keys are found. A hand-written list goes
  stale the first time someone adds a key in a hurry, which is exactly when the user sees a
  raw key in their UI.

- [ ] **Step 2: Confirm it fails, listing the missing keys.**

- [ ] **Step 3: Write the entries.** Real sentences, in the plain, specific register the rest
  of the project uses. A message a user cannot act on is not done: prefer "Group 'Button 2 -
  Pressed' is full (5 of 5). Remove an unmanaged entry or use a group target." over "Capacity
  exceeded".

- [ ] **Step 4: Confirm, and check `hassfest` passes locally if you can run it.**

- [ ] **Step 5: Commit.**

```bash
git commit -m "feat(ha): translations for every user-facing string"
```

---

## Phase 1D exit criteria

- [ ] Every entity in PRD Section 6.6 exists with the right category and default
- [ ] Rule entities attach to the user's existing device, proven by a device count
- [ ] The config entry unloads cleanly, leaving upstream devices untouched (closes P2)
- [ ] Every WebSocket command requires admin, tested
- [ ] `import_profile` and a profile switch never write to a device
- [ ] Diagnostics redaction proven by searching the output for raw values
- [ ] Every translation key resolves, checked mechanically rather than by hand
- [ ] `./scripts/lint` and `./scripts/test` exit 0, CI green, coverage at or above 95%
- [ ] No apply has been run against Jayant's network

## What Phase 1D does not do

No panel. The sidebar UI is Phase 1E and consumes the WebSocket API built here.
