# Stage 0 validation report

| | |
|---|---|
| Date | 2026-09-05 |
| Spec | `docs/PRD.md` Section 13.1 |
| Plan | `docs/superpowers/plans/2026-09-05-stage0-validation.md` |
| Instance | Home Assistant 2026.8.3 on HAOS 18.1, Python 3.14.6, at `10.10.1.11` |
| Repository | https://github.com/jayanty/ha-device-links |
| Outcome | Stage 0 complete with two items deferred for lack of approval and one blocked on a physical button press. Phase 1 may start. |

Stage 0 shipped no product code beyond the Z-Wave driver accessor. What it shipped is
evidence: probe scripts under `tools/`, real fixtures under `tests/fixtures/`, and tests
that fail when the facts below stop being true.

---

## 1. Assumptions

PRD Section 3 marked four things as unverified. All four are now closed.

| # | Assumption | Verdict | Evidence |
|---|---|---|---|
| A1 | `zwave-js-server-python` exposes a check method and `wait_for_result` handling for sleeping nodes | **Confirmed, and better than assumed.** Version 0.73.0 exposes all eight association methods. The rename landed: it is `async_check_association`, not `async_is_association_allowed`. `async_add_associations`, `async_remove_associations` and `async_remove_node_from_all_associations` all take `wait_for_result: bool = False`, which is exactly the handle `pending_wakeup` needs. | `tests/test_zwave_accessor.py`, Section 2 below |
| A2 | The `zwave_js` `runtime_data` shape and helper names on 2026.8 | **Confirmed.** `ZwaveJSData` has fields `client`, `driver_events`, `old_server_log_level`, so the driver is `entry.runtime_data.client.driver`. `helpers.async_get_node_from_device_id(hass, device_id, dev_reg=None)` exists, is a `@callback`, and raises `ValueError`. | `custom_components/device_links/backends/zwave_accessor.py`, `tests/test_zwave_accessor.py` |
| A3 | Zigbee2MQTT `bridge/devices` carries per-endpoint `bindings`, `clusters.input/output` and `configured_reportings` | **Confirmed on 2.14.1.** All three keys present on every endpoint. Binding targets carry a `type` discriminator of `endpoint` or `group`. | `tests/fixtures/g1_bridge.json`, `tests/test_fixture_g1.py` |
| A4 | The HA `matter` integration exposes a client with `read_attribute`/`write_attribute` usable from a custom integration | **Confirmed, with a correction.** Both methods exist. The library is `matter-python-client` 1.3.0, not `python-matter-server`: the distribution was renamed and still installs the `matter_server` package, so the import path is unchanged but PRD Appendix C cites the retired project. | `tests/fixtures/m1_matter.json`, `tests/test_fixture_m1.py` |

---

## 2. Items

### Z1 - reaching the Z-Wave driver. Read-only. **Done.**

Decision D2 (a) is viable. `entry.runtime_data.client.driver` reaches the live driver and
`helpers.async_get_node_from_device_id` resolves a Home Assistant device id to a `Node`.
Both are wrapped in `backends/zwave_accessor.py`, the only module in the integration
permitted to touch `zwave_js` internals.

The accessor's guard tests do more than record these names. Renaming `client`, `driver`,
the helper, or the `ZwaveJSConfigEntry` alias each produce a `mypy --strict` error, and
the annotations that make that possible are themselves pinned by a test, because loosening
`zwave_js_entry: ZwaveJSConfigEntry` to a bare `ConfigEntry` would silently disable the
check while leaving every test green.

`AssociationCheckResult` values: `OK = 1`, then 2 through 7 for the refusal reasons.
**`OK` is not zero.** Code that tests this enum for truthiness inverts its meaning, and a
test pins the sentinel.

### Z2 - association topology. Read-only. **Done.**

Ten nodes dumped from zwave-js 15.28.0 / zwave-js-server 3.10.1, schema 50.

Confirmations: the ZEN35 small-button layout is exactly Appendix A's (5/6, 7/8, 9/10,
11/12); every node is classic (`protocol = 0`, all ids below 256); every group 1 is a
lifeline and contains node 1; no group other than group 1 claims to be a lifeline.

**The network has no associations at all beyond lifelines.** Phase 1 therefore starts from
a genuinely clean baseline, and the acceptance scenarios in PRD Section 15 can assume it.

Amendments:

- **The two association reads have different nesting depths.** `get_all_association_groups`
  returns `{groups: {endpoint: {group: G}}}`. `get_all_associations` returns
  `{associations: {nodeId: {endpoint: {group: [addr]}}}}`, one level deeper. Reading the
  second at the first's depth yields plausible-looking empty groups rather than an error.
  The probe hit exactly this and now asserts the node key is the one it asked for.
- **The ZEN37 800LR remote is not laid out as Appendix A guessed.** It has 9 groups: on/off
  per button pair (g2, g3), dimming per button pair (g4, g5), and a toggle group per button
  (g6 to g9). Capacity is 5 targets per group, not the ZEN35's 10.
- **Inovelli group 7** reports as `Multilevel Switch Set (Config Button)`, not the "cycle
  levels" group the PRD described. Parameter 130 does gate it, as the PRD said, and is
  labelled `Group 7: Enable`.
- A sleeping node (40) returned its groups from cache without waking, which is why FR-B4
  needs a real deep verify rather than trusting a read.

### Z3 - the write path. **WRITE, approved. Done, and restored.**

Node 36 group 8 ("Button 2 - Held"), confirmed empty first: add node 1, read back, remove,
read back. Before and after are identical and the lifeline was untouched.

- `async_check_association` returned `OK`.
- Timing for the FR-A2 executor budget: **add 67 ms, remove 253 ms** on a listening node.
- The driver cache reflected our own write immediately, so verifying our own apply is cheap.

**The finding that changes an FR:** `Node.async_refresh_cc_values` sends
`wait_for_result=False`. It is fire and forget and returned in 0 ms. FR-B4 describes deep
verify as refreshing the Association CC values and then reading, but a read issued
immediately after the refresh still returns the previous cache. **Phase 1 must refresh,
then wait for the resulting value-updated events or poll with a bounded timeout, before
comparing.** Implementing FR-B4 literally would produce a verify that always agrees with
itself.

Also recorded: `AssociationAddress` takes the controller as its first field on 0.73.0.

### Z4 - sleeping node write behavior. **NOT EXECUTED. Not approved.**

Jayant approved Z3 and Z8 only. Z4 would write to node 40, the battery ZEN37, and needs a
physical button press to wake it.

Consequence, stated plainly: **the `pending_wakeup` path is unproven against hardware.**
A1's confirmation that `wait_for_result=False` exists tells us the mechanism is available,
and Z2 showed a sleeping node serves cached reads, but nothing here proves what a queued
write to an asleep node actually does, how it reports, or which event closes it. Phase 1
must build that path against fakes and mark it unproven until Jayant approves Z4.

### Z5 - external-edit events. **NOT EXECUTED. Needs Jayant.**

Requires Jayant to change an association by hand in Z-Wave JS UI while a listener records
what the driver emits. Not attempted.

Consequence: drift detection (FR-B3, goal G3's 30-second target) rests on the expectation
that a value-updated event fires for CC 0x85 with `propertyKey` set to the group id. If it
does not, drift detection must fall back to the optional periodic verify, and goal G3
cannot be met for externally-made changes. This should be closed early in Phase 1, and it
costs Jayant one manual edit.

### Z6 - configuration parameter value ids. Read-only. **Done.**

Every parameter the settings adapters need exists, is writeable, and holds the value PRD
Section 3.2 recorded: Zooz p35 bits 1/2/4/8 all 1, p33 = 2, p19 = 0, p20 = 1; Inovelli p59
bit 1 = 1 and bit 2 = 0, p52 = 0, p130 = 0. Bit-level parameters are addressed as
`(property, property_key)`, so `mirror_hub_commands` is `(35, 4)` on Zooz and `(59, 2)` on
Inovelli.

Node 39 parameter 19 remains 0 (local control disabled). Per Decision D4 that is Jayant's
temporary state and the integration never writes it unless a rule selects it. A test pins
the value so a silent change is noticed.

### Z7 - Zooz small-button Basic Set semantics. **DEFERRED. Blocked, and it blocks a template.**

What the devices report is factual: every Pressed group issues Basic Set (CC 32 command 1),
every Held group issues Multilevel Switch, on both ZEN35 and ZEN32. Association Group
Information carries the command class but **not the payload**, and no configuration
parameter governs the value.

Why it could not be closed: determining the value needs the controller inside a button's
Pressed group while the button is physically pressed. The approved sandbox is node 36
**group 8**, which is "Button 2 - Held" and carries Multilevel, so reusing it cannot answer
a question about Basic Set. No answer was inferred from a manual and presented as a finding.

**Consequence: the Off-all template (UC4) is not safe to compile onto a Zooz small button.**
If a press toggles rather than always sending OFF, an "off all" button turns the lights
back on every second press, the opposite of the intent. Phase 1 must refuse Off-all on a
Zooz small button, or compile it with an explicit warning. The Remote and Scene button
templates are unaffected, because a toggle is acceptable or wanted there.

To close it: approve node 36 **group 7** temporarily, add node 1, have Jayant press small
button 2 twice, record whether the two `zwave_js_value_notification` events for CC 32 carry
the same or alternating values, remove node 1, verify.

### Z8 - button LED path. **WRITE, approved. Done, and restored.**

Both mechanisms measured on node 36 button 2. Parameter 3 went 0 to 3 to 0; Indicator CC
value 68 went false to true to false. Both restored.

**Decision D6 resolves to Indicator CC.** Node 36 exposes one writeable indicator per
button (ids 67 to 71, property 2) at 33 ms, the same as a parameter write, and an indicator
set does not touch device NVM. The parameter path works but costs a flash write on every
LED change, which for a leg mirroring a light's state is constant NVM churn.

**This amends PRD Section 3.2**, which concluded that no path exists to make a small
button's LED follow a remote device. That holds for the LED-mode parameters, which only
track the device's own load, but Indicator CC provides exactly the per-button addressing
the PRD assumed was missing.

FR-H2's rate limiting and deduplication are still required: each set is a radio frame, and
mirroring a dimming light would otherwise emit one per level change.

### G1 - Zigbee2MQTT bridge state. Read-only. **Done.**

Assumption A3 confirmed on 2.14.1. Inovelli Blue endpoint 2 emits `genOnOff` and
`genLevelCtrl` as Section 3.2 predicted, and endpoint 3 (config button) does too.

**Every binding on the network today targets the coordinator.** They are Zigbee2MQTT's own
reporting setup, not user intent, which is exactly why FR-B5 must classify coordinator
bindings as system links: presenting them as unmanaged would invite a user to delete the
thing that makes their devices report at all.

No Zigbee groups exist yet, so FR-B6's `dl_` prefix starts clean. The bridge reports exactly
one coordinator, so the stale second bridge device PRD Section 3.1 warns about is a Home
Assistant device-registry leftover rather than something Zigbee2MQTT knows about.

### G2 - Zigbee bind round trip. **NOT EXECUTED. Not approved.**

Consequence, stated plainly: **the entire Zigbee write path is unproven against hardware.**
Bind and unbind payload shapes, per-cluster failure reporting, the `transaction` correlation
and the delay before `bridge/devices` reflects a change are all still assumptions taken from
documentation. Phase 2 must build against fixtures and fakes and treat its first real bind
as an experiment. The candidate pair remains "Entrance Inside Lights Aux" EP2 to "Entrance
Inside Lights" EP1 on `genOnOff`, which G1 confirms is currently unbound.

### M1 - Matter feasibility. Read-only. **Done. Phase 3 is feasible but narrow.**

A4 confirmed. Server is matter-server 1.4.0 (matter.js 0.17.9), schema 13.

Three amendments:

- **The Aqara H2 switch and the IKEA BILRESA button are not binding sources.** PRD Section
  3.1 lists both as realistic sources. Neither exposes any control client cluster or a
  Binding cluster on any endpoint. The only real binding sources on this fabric are the two
  Inovelli VTM31-SN White switches, on endpoint 2, which expose Identify, OnOff and
  LevelControl as clients and carry a Binding cluster. Their binding lists are empty.
- **Every one of the 19 nodes advertises client cluster 41 on endpoint 0.** That is the OTA
  Software Update Provider, not a control emitter. A capability model that treats any client
  cluster as an emitter would offer every sensor, lock and thermostat on the fabric as a
  usable remote. Endpoint 0 and cluster 41 must be excluded when deriving Matter emitters.
- **ACL headroom is 2 entries, not a theoretical concern.** Eve Energy reports
  `AccessControlEntriesPerFabric` 6 and already uses 4. Other models report 4. E27 and E28
  are live constraints: merging a grant into an existing managed entry rather than adding a
  new one is load-bearing, and the ACL write must succeed before the binding entry is
  written so a rejection leaves no partial state.

Nothing was written. Matter writes stay behind the options flag that defaults to off.

### P1 - panel spike. Read-only. **Static half done, runtime half queued.**

Every component PRD Section 7.1 names is present in the installed frontend
(`home-assistant-frontend` 20260729.7) **except `ha-tabs`**, which the PRD already hedged
against by pairing it with `ha-tab-group`. On this version `ha-tab-group` is the one that
exists, so the runtime detection the spec asks for keeps its shape but has a known answer.

A methodological note worth keeping: the first attempt scanned for `customElements.define`
and reported all 26 components missing. Home Assistant registers elements with Lit's
`@customElement` decorator, which minifies away from a literal define call, so that scan was
a false negative rather than a finding. Detection is now by tag string literal, and a test
asserts the scan saw more than 300 distinct `ha-*` tags so a broken scan fails loudly
instead of quietly reporting everything absent.

The runtime half, registering a panel and confirming each element resolves through
`customElements.whenDefined` after the card-helpers force-load, needs a Home Assistant
restart and is queued behind Jayant's. It does not block Phase 1 planning, because the
question that shapes the UI code, which components exist on this version, is answered.

### P2 - entity attachment. Read-only. **Done.**

Identifier formats, which FR-E1 must reproduce exactly or it silently creates orphaned
devices instead of attaching:

| Backend | Identifier |
|---|---|
| `zwave_js` | `<home_id>-<node_id>`, plus `<home_id>-<node_id>-<mfr>:<type>:<product>` |
| `mqtt` | `<base_topic>_0x<ieee>` |
| `matter` | `deviceid_<compressed_fabric_id>-<node_id_hex_16>-MatterNodeDevice` |

The Z-Wave extended identifier carries the fingerprint, so it changes when a node is
replaced by a different model: that is the signal FR-S3 needs for swap detection. The Zigbee
identifier is prefixed with the MQTT base topic, so the backend must not hard-code
`zigbee2mqtt`. The Matter identifier embeds the compressed fabric id, which changes on
re-commissioning and would orphan every stored handle, so a Matter handle should key on node
id and treat a fabric change the way E21 treats a new Z-Wave home id.

Also recorded: on 2026.8.3 a device registry record has `config_entry_id` (singular) and
`primary_config_entry`, not the `config_entries` list older code expects, plus new
composite-device keys. No device on this instance uses composite identifiers.

The unload half of P2, proving that removing our entities leaves the upstream device entry
untouched, is queued with the P1 runtime spike because it needs a loaded integration.

### R1 - repository. **Done.**

https://github.com/jayanty/ha-device-links, public, described, eight topics, eight labels,
issue and PR templates, Dependabot for pip, npm and GitHub Actions. `main` is protected:
four required status checks, no force push, no deletion. `dev` is the working branch.

### R2 - dev deployment loop. **Done, and proven end to end.**

`tools/ha_deploy.py` is installed at `/config/tools/ha_deploy.py`, fetched from GitHub at a
pinned commit rather than copied from the laptop, and its sha256 was verified against the
repository copy. A `shell_command` block was appended to `configuration.yaml` (backed up
first to `configuration.yaml.bak-device-links`) and `ha core check` passes.

Proven against the live instance:

| Step | Result |
|---|---|
| Deploy `dev` head | `ok`, 12 files, `restart_required: true`, commit matches `origin/dev` |
| Deployed manifest | byte-identical to the repository copy |
| Rollback with no backup | fails cleanly with a message, exit 1, no traceback |
| Deploy an older ref | `ok`, correctly identified the single differing file |
| Rollback | `ok`, restored the previous commit |
| Neighbouring components | all 18 untouched |

The tool runs through `docker exec homeassistant` so its `compileall` check uses Home
Assistant's own interpreter. Running it directly over SSH would validate against the SSH
add-on's Python 3.14.7 instead; `CLAUDE.md` was corrected accordingly.

**Home Assistant has not been restarted.** A persistent notification tells Jayant that
commit `4dd36f7` is deployed and waiting. Until he restarts, the integration is present on
disk but not loaded, and the `shell_command` services do not exist yet, so deploys go over
SSH in the meantime.

### D1 - repository skeleton and CI. **Done.**

CI is green on `dev` and `main`: ruff lint and format, `mypy --strict`, pytest with a 95%
coverage gate, hassfest, and HACS validation. The integration currently measures 100%.
`CLAUDE.md` was written before any Phase 1 code, as PRD Section 18.4 requires.

Two things had to change to get there. The dev environment targets **Python 3.14**, not the
PRD's "3.13+": Home Assistant 2026.8.3 requires `>=3.14.2`, so a 3.13 environment cannot
install it at all. And brand assets were generated and committed so HACS brand validation
passes before the `home-assistant/brands` PR exists.

A nightly workflow runs the suite against an unpinned Home Assistant and opens a
`regression` issue on failure, because CI pins `homeassistant==2026.8.3` and would otherwise
stay green through every upstream release until a human bumped the pin, which is precisely
backwards for a guard whose job is to notice upstream drift.

---

## 3. Decision register: defaults applied without an answer

PRD Section 0 rule 4 requires recording these.

| ID | Default applied | Note |
|---|---|---|
| D5 | Managed Zigbee groups on, `dl_` prefix | No groups exist yet, so the prefix starts clean |
| D8 | YAML mirror off | |
| D9 | Unmanaged links report-only | |
| D10 | Single active profile | |
| D12 | No ZHA backend in v1 | |
| D14 | Raw services kept, off by default | |
| D15 | Node 036 small button 2 unassigned; Off-all excludes own load unless hybrid enabled; native status feedback only for the no-load controller 036 | Button 2 being unassigned is what made it the safe Z8 target |
| D18 | Plan dialog always shown | |
| D19 | Prototype client survives only as a probe | Realised as `tools/probe_zwave_write.py` and `tools/probe_zwave_ws.js` |

Decisions resolved in the PRD itself (D1, D2, D3, D4, D6, D7, D11, D13, D16, D17, D20, D21,
D22) were followed as written. D6's resolution was refined by Z8 from "Indicator CC if
available, otherwise parameters" to "Indicator CC, confirmed available".

Session decisions layered on top, from Jayant on 2026-09-05: device writes limited to Z3 and
Z8; Home Assistant restarts stay manual; SSH is the bootstrap and debugging channel; commits
authored as `Jayant <4827706+jayanty@users.noreply.github.com>`.

---

## 4. Exit criteria

| Criterion | Status |
|---|---|
| Read-only items complete (Z1, Z2, Z6, G1, M1, P2) | Done |
| Z7 | Deferred, blocked on a physical press. Blocks Off-all on Zooz buttons only |
| P1 | Static half done; runtime half queued behind a restart |
| R1, D1 | Done, CI green |
| Z3 write path proven | Done and restored |
| Z8, resolving D6 | Done and restored |
| Z4, G2 | Not approved, not executed, consequences recorded above |
| Z5 | Not executed, needs one manual edit by Jayant |
| Assumptions A1-A4 closed or amended | All four closed |
| Fixtures committed and asserted | 7 fixtures, 196 tests passing |
| `scripts/lint` and `scripts/test` exit 0, CI green | Yes |

**Stage 0 is complete enough for Phase 1 to begin**, with three carried risks that Phase 1
must design around rather than discover: the sleeping-node write path is unproven (Z4), the
Zigbee write path is unproven (G2), and Off-all on Zooz scene buttons is unsafe to compile
(Z7).
