# CLAUDE.md - Device Links

Operating manual for every Claude Code session in this repository. Read this first, then
`docs/PRD.md` (the full product requirements) and `docs/stage0-report.md` (validated facts).

Style rule for everything generated here (code comments, docs, UI strings, commit messages):
**never use the em dash character.** Use a plain hyphen or a colon.

---

## 1. Purpose and status

`device_links` is a HACS-distributable Home Assistant custom integration that gives Z-Wave
associations, Zigbee bindings, and Matter bindings a single native UI with intent-level
templates, profiles, plan/apply/verify, drift detection, and device-swap handling. It reuses
the `zwave_js`, `mqtt`, and `matter` integrations' existing clients; it opens no network
surface of its own.

- Full spec: `docs/PRD.md` (PRD v1.2, 2026-09-05, owner Jayant)
- Validated facts and fixtures: `docs/stage0-report.md`, `tests/fixtures/`
- Decision register: `docs/PRD.md` Section 14, mirrored in Section 9 below
- It supersedes the `zwave_zigbee_assoc` prototype (services only, mock tested, never deployed)

Delivery stages: Stage 0 validation, Phase 1 Z-Wave end to end, Phase 2 Zigbee + swap +
hybrid legs, Phase 3 Matter + polish.

---

## 2. Static environment (verified 2026-09-05, re-verify if something looks wrong)

### 2.1 This machine (where Claude Code runs)

| Item | Value |
|---|---|
| Host | Jayant's Mac, macOS 26.6.2 (build 25G83), arm64 |
| Working directory | `/Users/jayant/agents/ha-device-links` |
| LAN address | `10.10.1.157` on `en0` (the Mac also holds 7 other VLAN addresses) |
| Python | 3.14.6 at `/opt/homebrew/bin/python3`; `uv` 0.11.27 |
| Node | v26.4.0, npm 11.17.0 |
| git | 2.39.5, identity `Jayant <4827706+jayanty@users.noreply.github.com>` (set globally) |
| gh CLI | 2.96.0, authenticated as `jayanty`, git protocol ssh, scopes `admin:public_key, gist, read:org, repo` |
| SSH key | `~/.ssh/id_ed25519` (already authorized on the HA SSH add-on) |

**Known networking gotcha.** The Mac has eight interfaces across VLANs, and outbound
connections to `10.10.1.11` intermittently pick the wrong source interface, which looks like
"host unreachable". If `curl`, `nc`, or `ssh` to Home Assistant fails, retry pinned to en0:

```bash
curl --interface 10.10.1.157 http://10.10.1.11:8123/
ssh -b 10.10.1.157 root@10.10.1.11
```

This is a local routing quirk, not a permission or firewall problem. Never conclude that
Home Assistant is unreachable without trying the pinned form first.

### 2.2 GitHub

| Item | Value |
|---|---|
| Repository | `https://github.com/jayanty/ha-device-links` (public) |
| Owner | GitHub user `jayanty` (numeric id 4827706) |
| Remote | ssh (`git@github.com:jayanty/ha-device-links.git`) |
| Default branch | `main` (protected: CI must pass, no force push) |
| Working branch | `dev` - all iteration lands here; `main` receives merges only when CI is green |
| Docs / issues URL | used verbatim in `manifest.json` `documentation` and `issue_tracker` |

`gh`'s token does **not** carry the `workflow` scope. Pushing `.github/workflows/*` works
because git uses ssh, but `gh api` calls that edit workflows will fail. Push, do not API-edit.

### 2.3 Home Assistant instance

| Item | Value |
|---|---|
| URL | `http://10.10.1.11:8123` (internal only, no TLS, no cloud exposure in use here) |
| Core | 2026.8.3 on Home Assistant OS 18.1, Supervisor 2026.08.0, Python 3.14.6 |
| HA Core container | docker name `homeassistant` |
| Config directory | `/config` (not a git repository) |
| MCP server | `ha-mcp` 8.4.3, started by Claude Desktop as `uvx ha-mcp@latest`, config in `~/Library/Application Support/Claude/claude_desktop_config.json` (`HOMEASSISTANT_URL`, `HOMEASSISTANT_TOKEN`) |
| Library versions in HA Core | `zwave-js-server-python` 0.73.0, `aiomqtt` 2.5.1, `paho-mqtt` 2.1.0, `python-matter-server` not installed (Matter Server runs as an add-on) |

Relevant add-ons (all running):

| Add-on | Version | Slug / container |
|---|---|---|
| Z-Wave JS UI | 7.6.0 | `a0d7b954_zwavejs2mqtt` / `app_a0d7b954_zwavejs2mqtt` |
| Zigbee2MQTT | 2.14.1-1 | `45df7312_zigbee2mqtt` / `app_45df7312_zigbee2mqtt` |
| Matter Server | 9.2.0 | `core_matter_server` / `app_core_matter_server` |
| Mosquitto broker | 7.1.0 | `core_mosquitto` / `app_core_mosquitto` |
| Advanced SSH & Web Terminal | 24.1.3 | `a0d7b954_ssh` (this is the SSH entry point, port 22) |
| Claude Terminal | 2.5.4 | `e498daa1_claude_terminal` |
| Studio Code Server | 6.0.1 | `a0d7b954_vscode` |
| OpenThread Border Router | 3.1.2 | `core_openthread_border_router` |
| HACS | 2.0.5 (integration, not an add-on) | |

Existing `custom_components` on the instance: alarmo, bermuda, browser_mod,
bubble_card_tools, dyson_local, ef_ble, frigate, ge_home, generac, hacs, local_openai,
nodered, openevse, scrypted, spook, spook_inverse, sunspec, webrtc. `device_links` is added
alongside them by the deploy tool.

### 2.4 SSH access to Home Assistant

`ssh root@10.10.1.11` works today with `~/.ssh/id_ed25519`, landing in the Advanced SSH
add-on container (`a0d7b954-ssh`, Python 3.14.7) with `/config` bind-mounted and `docker`
available. This is the workhorse for probes, log tailing, and the deploy tool.

```bash
# probe from inside HA Core (the supported way to reach the zwave_js driver objects)
ssh root@10.10.1.11 'docker exec homeassistant python3 -c "..."'

# probe zwave-js-server directly (prototype pattern, port 3000 is add-on internal)
ssh root@10.10.1.11 'docker exec app_a0d7b954_zwavejs2mqtt node -e "..."'

# HA Core logs
ssh root@10.10.1.11 'ha core logs' 2>&1 | tail -100
```

`compileall` syntax checks must run with HA Core's interpreter (`docker exec homeassistant
python3 -m compileall`), not the SSH add-on's, so the check matches the runtime.

---

## 3. Safety rules (these override convenience, always)

1. **Never restart Home Assistant.** Not `ha_restart` over MCP, not
   `homeassistant.restart`, not `ha core restart` over SSH, and never a config-entry reload
   used as a substitute. Python changes need a restart to load: deploy, raise a persistent
   notification saying which commit is waiting, and stop. Jayant restarts. Resume live
   validation on the next session or when the health sensor reports the new commit.
2. **Never restart or reconfigure an add-on** (Z-Wave JS UI, Zigbee2MQTT, Matter Server,
   Mosquitto, SSH). Read from them; do not manage them.
3. **Device writes are approval-gated.** Read before write, verify after write, restore
   after a probe. Pre-approved sandbox as of 2026-09-05:
   - **Z3 approved**: node 36 (Bedroom Scene Controller, Zooz ZEN35) association group 8
     ("Button 2 - Held", unused by design) - add node 1, read back, remove, read back.
   - **Z8 approved**: node 36 LED-mode parameter for small button 2 (param 3) - record the
     current value, write, read back, restore to the recorded value.
   - **Not approved, do not execute**: Z4 (node 40 ZEN37 sleeping-node write test) and
     G2 (Zigbee bind/unbind on "Entrance Inside Lights Aux"). Both are deferred pending
     Jayant's approval. Build against fixtures and fakes; mark the affected write paths as
     unproven in `docs/stage0-report.md` and in the phase exit criteria.
   - Anything else that writes to a device requires a fresh, specific question to Jayant.
4. **Hard-protected forever, in code and not only in the UI**: Z-Wave lifeline associations
   (group 1), Zigbee coordinator bindings, and Matter ACL entries with Administer privilege.
   These are never planned for removal, never editable, and every path that could touch them
   has a test proving it refuses.
5. **Never remove an unmanaged link by default.** Removal requires explicit per-link opt-in.
6. **Never pass `force: true`** to `addAssociations` or any equivalent override.
7. **Never write to `/config/.storage` directly.** Read it for diagnosis only.
8. **Never commit secrets.** No tokens, no DSKs, no network keys, no `secrets.yaml`
   contents, no long-lived access token from the MCP config. Diagnostics redact home id,
   IEEE addresses, and Matter node ids.
9. **Do not modify Jayant's HA configuration** beyond the one-time deploy bootstrap
   (`/config/tools/ha_deploy.py` plus the `shell_command:` block). Nothing else in `/config`
   is ours to edit.

---

## 4. Architecture invariants

- **Pure modules never import Home Assistant.** `models.py`, `compiler.py`, `planner.py`,
  `yaml_io.py`, and every `backends/*_protocol.py` must import zero `homeassistant.*`. They
  are unit-tested without the HA harness and reused by `tools/` probe scripts. A test asserts
  this by scanning imports.
- **Every backend implements the `Backend` Protocol** in `backends/base.py`. Core code never
  branches on backend id; new protocols arrive as new adapters. Nothing in core may assume
  MQTT, or assume Z-Wave semantics.
- **The Z-Wave driver is reached through the `zwave_js` config entry's `runtime_data`**
  (Decision D2 (a)), isolated in one version-guarded accessor, `backends/zwave_accessor.py`. Never
  open a second WebSocket to zwave-js-server from the integration. The accessor has an
  automated test against a faked `zwave_js` entry so upstream refactors break CI, not users.
- **Storage schema changes require a migration and a migration test** from every prior
  version. `.storage/device_links.profiles` is authoritative; the YAML mirror is a mirror.
- **The frontend bundle is committed** and must byte-match a fresh build; CI enforces it.
- **No new Python requirements** without a decision-register entry. The integration ships
  with an empty `requirements` list.
- **Compilation and planning are pure and deterministic**: `compile(rule, capabilities)` and
  `plan(desired, observed)` take data in and return data out, with no I/O and no clock reads
  that are not injected.

---

## 5. Commands

```bash
scripts/setup            # create .venv, install HA test deps, install frontend deps
scripts/lint             # ruff check + ruff format --check + mypy --strict
scripts/test             # pytest with coverage gate (95% overall, 100% on pure modules)
scripts/test --live      # opt-in live suite against Jayant's HA, never runs in CI
cd frontend && npm run build && npm run test
```

Live tests read `HA_URL` and `HA_TOKEN` from the environment and talk to the integration's
own WebSocket API. Because of the interface quirk in Section 2.1, the live runner pins the
source interface; if it cannot connect, fall back to driving the same WebSocket commands
through MCP (`ha_call_service(ws_command="device_links/plan", ...)`).

### Deploy loop (GitHub to Home Assistant, PRD Section 17.5)

Home Assistant pulls from GitHub. Nothing is ever copied from the laptop into `/config`.

```bash
# 1. local gates must be green first
scripts/lint && scripts/test

# 2. commit and push to dev
git commit -m "feat(zwave): ..." && git push origin dev

# 3. trigger the pull on the HA side.
# Note the docker exec: the tool must run under HA Core's interpreter, because it
# compileall-checks the downloaded code before swapping it in. Running it directly in
# the SSH add-on container would validate against that container's Python instead.
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py deploy \
  --repo jayanty/ha-device-links --branch dev --domain device_links'
# or, once shell_command is loaded, over MCP:
#   ha_call_service(domain="shell_command", service="deploy_device_links", return_response=True)

# rollback and status use the same shapes
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py rollback --domain device_links'
ssh root@10.10.1.11 'docker exec homeassistant python3 /config/tools/ha_deploy.py status --domain device_links'
```

The tool prints one JSON object: `{ok, commit, previous_commit, changed_files,
restart_required, browser_reload}`. `restart_required` is true when anything outside
`frontend/` changed.

**When `restart_required` is true**: create a persistent notification through MCP naming the
commit, then **stop**. Do not restart. When only `browser_reload` is true, say that a hard
refresh of the panel is enough and continue.

After Jayant restarts: poll `sensor.device_links_health` until its `commit` attribute equals
the pushed SHA and its state is `ok`, then run the read-only live checks and read Repairs.

---

## 6. Working with Jayant's Home Assistant

| Need | Use |
|---|---|
| First look when something is wrong | `ha_get_state("sensor.device_links_health")` |
| Repairs and notifications | `ha_get_system_health(include="repairs")`, `ha_get_overview` |
| Full integration diagnostics | `ha_get_integration(entry_id=..., include_diagnostics=True, diagnostics_fields=[...])`, page big lists with `diagnostics_data_path` + `diagnostics_data_limit` |
| See the plan a user would see | `ha_call_service(ws_command="device_links/plan", data={...})` |
| Raise log level | `logger.set_level` with `custom_components.device_links: debug`, then `ha_get_logs(source="system", search="device_links")` |
| Read-only reproduction | `device_links.verify` (never writes) |
| Device state, registries, entities | `ha_get_device`, `ha_get_entity`, `ha_search` |
| Anything the MCP cannot do | SSH (Section 2.4): `ha core logs`, read `/config/.storage/device_links.profiles`, `docker exec` probes, deploy tool |

Scoped `device_links.apply` writes to devices, so it follows Section 3 rule 3: it needs
approval unless every link it would touch is inside the approved sandbox.

Debug bundles land in `/config/device_links/debug/<timestamp>.json` and never leave the host.

---

## 7. Coding standards

- Python 3.13+ syntax targeting HA 2026.8 on 3.14. `mypy --strict` with zero errors, `py.typed`,
  typed `runtime_data`, no `Any` in public signatures.
- Ruff for lint and format, Home Assistant's ruleset, enforced by `pre-commit` and CI.
- Every user-facing string is a translation key: `strings.json`, `translations/en.json`,
  `icons.json`. Exceptions use `translation_key` so errors are translated too.
- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`), scoped by
  area where useful (`feat(zwave):`).
- Tests are part of the change, not a follow-up. A feature without tests is not done.
- Logging: `_LOGGER` per module, INFO for lifecycle and job summaries, wire-level payloads
  only at DEBUG, never raw payloads above DEBUG.
- No em dash anywhere, including generated docs and UI copy.

---

## 8. Testing and the regression rule

Levels, all of which must pass before a push:

1. Pure-module unit tests, no HA imports, 100% line coverage on those modules, plus
   Hypothesis property tests on a `FakeBackend`: plan-then-apply converges, a second plan is
   empty, lifelines are never removed, capacity is never exceeded, unmanaged links survive.
2. Backend contract tests against Stage 0 fixtures through fake upstream clients.
3. HA integration tests with `pytest-homeassistant-custom-component`: config flow and options
   at 100%, setup/unload/reload, entity attachment, availability, services, WebSocket
   commands with admin gating, Repairs, diagnostics redaction, storage migrations.
4. Scenario tests S1-S12 from PRD Section 15, encoded as data files, run against in-process
   simulators. The same files drive the live runner.
5. Frontend vitest unit tests plus Playwright smoke tests against a mocked `hass`.

**Regression rule.** Every bug fix adds a test named `test_issue_<n>_<slug>` that fails
before the fix and passes after. Gates: coverage >= 95% overall and 100% on pure modules,
`mypy --strict`, `ruff check`, `ruff format --check`, hassfest, HACS validation, frontend
build and test, and a check that the committed bundle matches a fresh build.

---

## 9. Decisions in force

Resolved (do not relitigate): D1 domain `device_links`; D2 (a) reuse the `zwave_js` driver;
D3 hybrid legs in scope, Phase 2, per-rule opt-in, global option off; D4 never touch Zooz
param 19 unless a rule selects it; D6 button-LED status via hybrid leg kind (c); D7 the rule
switch physically adds and removes links; D11 Matter is Phase 3 behind a flag; D13 refuse
Long Range nodes; D16 Lit + TypeScript + vite; D17 MIT; D20 `jayanty/ha-device-links`;
D21 (b) branch-tracked dev deploy through GitHub.

Defaults applied because they were not overridden: D5 managed Zigbee groups on with the
`dl_` prefix; D8 YAML mirror off; D9 unmanaged links are report-only; D10 single active
profile; D12 no ZHA backend in v1; D14 raw services kept but off by default; D15 node 036
small button 2 left unassigned, off-all excludes the device's own load unless hybrid legs
are enabled, native status feedback only for the no-load controller 036; D18 the plan dialog
is always shown; D19 the prototype client survives only as `tools/probe_zwave.py`;
D22 MCP plus SSH for debugging.

Session decisions layered on top (2026-09-05): device-write approval is limited to Z3 and Z8;
restarts stay manual; SSH is the bootstrap and debugging channel.

---

## 10. Known gotchas

- **Long Range**: LR nodes (id >= 256) cannot be an association source or target, ever. The
  protocol is fixed at inclusion time and nothing changes it later. This network is all
  classic today. Refuse LR nodes with a clear message and raise a Repairs issue if a rule's
  device turns out to be LR after a replace.
- **Sleeping nodes**: battery devices (node 40 ZEN37) return `pending_wakeup`, not failure.
  Close it on wake-up and value-updated events; raise Repairs after 24 h pending. Never busy-wait.
- **Zigbee2MQTT friendly names change.** Store the IEEE address in the handle and resolve the
  friendly name at request time.
- **Unbinding removes attribute reporting** unless `skip_disable_reporting` is set. Say so in
  the plan.
- **An on-only binding is impossible.** `genOnOff` carries both on and off, Z-Wave groups
  carry both, Matter bindings carry both. Only a hybrid leg can express it.
- **A device cannot be in its own association group** (`Forbidden_SelfAssociation`).
- **Zooz small-button LEDs only follow the device's own load.** No association reaches them.
- **Matter**: struct values serialize by TLV tag; ACL writes fail with capacity errors; write
  the ACL grant first and the binding entry only after it succeeds.
- **HA frontend components are lazily defined.** Force-load them with the card-helpers
  technique before use, and degrade gracefully when one is missing.
- **The stale Zigbee2MQTT bridge device** (IEEE `0x00124b0031dd0be5`, sw 2.8.0) is a registry
  leftover. The active bridge is `0x00124b002e1dfd4a`. Select the base topic explicitly and
  tolerate multiple bridge devices.
- **Node 13 to node 42** is a real, already-completed device swap on this network. Use it as
  the swap test fixture rather than inventing one.
- **`getAssociations` returns the driver's cached view.** Deep verify refreshes the CC values
  from the device first.

---

## 11. When in doubt, ask

Stop and ask Jayant before:

- any device write outside the approved Z3 / Z8 sandbox,
- anything that would restart Home Assistant or an add-on,
- a storage schema change that cannot be migrated automatically,
- a change to what counts as a system link (lifeline, coordinator binding, Administer ACL),
- adding a Python or frontend runtime dependency,
- editing anything in `/config` other than the deploy tool and its `shell_command` block,
- publishing a release or submitting to HACS default or `home-assistant/brands`.

Everything else in the PRD is already decided. Build it, test it, deploy it, report it.
