# Open items

Everything unresolved, in one place. Kept current as phases land: when an item is closed,
move it to the bottom section with the commit or PR that closed it rather than deleting it,
so the reasoning stays findable.

**Owner** is who has to act. "Jayant" means it cannot progress without a decision, an
approval, or a physical action at the house. "Claude" means it is scheduled work.

---

## 1. Needs Jayant

These four are the only things blocking work that is otherwise ready. Each says exactly what
is needed and what stays unproven until then.

### J1. Approve the sleeping-node write test (Stage 0 Z4)

| | |
|---|---|
| Issue | [#5](https://github.com/jayanty/ha-device-links/issues/5) |
| Blocks | The `pending_wakeup` path is unproven against hardware |
| Needs | Approval to write to node 40 (Master Bedroom Remote, ZEN37 800LR), plus a button press to wake it |

Stage 0 confirmed the mechanism exists: every association write method takes
`wait_for_result`, so a write to a sleeping node can be queued rather than blocking. What is
unproven is what actually happens: whether the call returns immediately or blocks, how the
result is reported, and which event fires when the node wakes and the write lands.

Phase 1B builds this path against fakes. Until Z4 runs, a battery remote's links will show
as `pending_wakeup` based on behaviour nobody has observed, and the acceptance scenario S5
cannot pass.

### J2. Approve the Zigbee bind round trip (Stage 0 G2)

| | |
|---|---|
| Issue | [#6](https://github.com/jayanty/ha-device-links/issues/6) |
| Blocks | The entire Zigbee write path (all of Phase 2) |
| Needs | Approval to bind and then unbind one pair |

Candidate pair, confirmed currently unbound by the G1 capture: "Entrance Inside Lights Aux"
endpoint 2 to "Entrance Inside Lights" endpoint 1, `genOnOff` only.

Bind and unbind payload shapes, per-cluster failure reporting, the `transaction` correlation
and the delay before `bridge/devices` reflects a change are all still taken from
documentation rather than observation. Phase 2 would otherwise treat its first real bind as
an experiment on a live switch.

### J3. Close the Zooz button semantics question (Stage 0 Z7)

| | |
|---|---|
| Issue | [#7](https://github.com/jayanty/ha-device-links/issues/7) |
| Blocks | The Off-all template on every Zooz scene button |
| Needs | Approval for node 36 group 7, plus pressing small button 2 twice |

Nobody has observed what value a Zooz small button sends to its Pressed group. If it toggles
rather than sending a fixed OFF, an "off all" button turns the lights back on every second
press, which is the opposite of the intent.

The approved Z3 sandbox cannot answer this: group 8 is "Button 2 - Held" and carries
Multilevel Switch, not Basic Set. This needs group 7 specifically.

Carried into the product meanwhile: those emitters are marked `semantics: "unknown"` in the
profile database, and the compiler emits a `button_semantics_unknown` warning rather than
silently compiling something that might be wrong.

### J4. Confirm drift detection actually gets an event (Stage 0 Z5)

| | |
|---|---|
| Issue | [#8](https://github.com/jayanty/ha-device-links/issues/8) |
| Blocks | Goal G3, drift reflected within 30 seconds |
| Needs | One manual association change in Z-Wave JS UI while a listener records what the driver emits |

This is the cheapest of the four and costs no device write of ours: change an association by
hand, and we record whether a value-updated event fires for CC 0x85 with the group id as
`propertyKey`.

If no event fires, drift detection has to fall back to the optional periodic verify, G3
cannot be met for externally-made changes, and that limitation belongs in the docs rather
than being discovered by a user.

---

## 2. Waiting on a Home Assistant restart

Not blocked on a decision, just on timing. Both resolve during Phase 1D and 1E, when there
is finally something worth restarting for.

| # | Item | Detail |
|---|---|---|
| R1 | Panel spike runtime half (P1) | The static half is done: every component the UI spec names exists on 2026.8.3 except `ha-tabs`, and `ha-tab-group` is the one to use. Still unconfirmed is that each element actually resolves through `customElements.whenDefined` after the card-helpers force-load. |
| R2 | Entity attachment unload half (P2) | Identifier formats are captured and pinned. Still unproven is that unloading our entities leaves the upstream `zwave_js` device entry untouched. |

---

## 3. Scheduled work

Claude-owned, sequenced, no input needed.

| # | Item | Lands in |
|---|---|---|
| S1 | Z-Wave adapter: live capabilities, observed state, writes, subscriptions | Phase 1B |
| S2 | Storage, profiles, snapshots, YAML export | Phase 1C |
| S3 | Executor: jobs, retries, concurrency, verify | Phase 1C |
| S4 | Entities, services, events, diagnostics, Repairs, WebSocket API | Phase 1D |
| S5 | `strings.json` entries for every diagnostic translation key the compiler, the planner and the executor emit | Phase 1D |
| S6 | The sidebar panel | Phase 1E |
| S7 | Zigbee backend, device swap, hybrid legs | Phase 2 |
| S8 | Matter backend behind the options flag | Phase 3 |

---

## 4. Technical debt and follow-ups

Small, known, and deliberately deferred rather than forgotten.

| # | Item | Why it is not urgent |
|---|---|---|
| T1 | `zwave_protocol.BlockedReason` and `models.Diagnostic` are the same shape | Unifying them means touching committed, tested code for no behaviour change. Do it when a second backend needs blocked reasons. |
| T2 | `PlanOp.SET_PARAM` and `PENDING`, `PlanItem.setting`, `CompiledRule.hybrid_legs` are specified but nothing produces them yet | Phase 1B and 1C fill them. They exist so the shape does not change later. |
| T3 | ZEN32 (node 29) has no curated profile entry | Falls back to per-group emitters, which is safe but crude. Its layout is already in the fixture. |
| T4 | ZEN37 has no settings adapters and no wake instruction | Its config values were never captured, because that needed Z4. Closing J1 unblocks this too. |
| T5 | `ha_deploy.py` does not update itself | When the tool changes in the repo, `/config/tools/ha_deploy.py` must be re-fetched by hand. A real foot-gun; worth automating if the tool changes often. |
| T6 | The nightly job covers HA `latest` and `beta`, not `dev` | PRD Section 16 asks for `dev`, which needs a git install of core and brings a frontend build problem. Needs a decision. |
| T7 | The nightly job has never actually fired | The issue-creation path is untested. It will prove itself the first time upstream breaks something, which is a bad time to find a bug in it. |
| T8 | The capacity property is exercised on roughly 4% of generated networks | Enough to catch a systematic off-by-one, as fault injection confirmed. Thinner cover for capacity-10 groups specifically. |
| T9 | The Z-Wave adapter reports one receivable feature set for every device | The Stage 0 capture recorded association groups, not each node's supported command classes, so `backends/zwave.py` reports the set every target in that capture supports (on/off, level set, level hold) rather than narrowing per device. Every target on this network is a dimmer, so it is right here; a plain switch elsewhere would be offered a level link that does nothing. Narrowing it needs the driver's per-node command class list, and a fake that carries one, which means capturing it first. |
| T10 | A deep verify cannot tell "the device answered and nothing had changed" from "the device did not answer" | The only positive signal a refresh produces is the value-updated event, and whether a real driver emits one when the refreshed value is unchanged was never measured (same probe as J4). So `deep_verify_timed_out` may fire routinely on real hardware in the common case where nothing was stale. It is reported as "not confirmed" rather than as an error and logged at debug for exactly that reason, but the UI wording depends on closing J4. |
| T11 | Ownership is derived from the profile as it compiles today, not from a record written when a link was applied | A rule that is edited to point somewhere else stops claiming the fingerprints it wrote, so its old links become unmanaged: they are reported rather than removed (safe), but they are orphaned, and the user has to take them off by hand. Disabling a rule is handled (a disabled rule still compiles for the ownership index) and deleting one is deliberate, but editing is neither. Closing it means writing a per-link ownership record at apply time and preferring that record over the compiled set, which is a storage schema change and therefore a migration. |
| T12 | The coordinator cannot tell a dead node from a healthy one | E4 asks for a dead node to be `unknown` rather than `drift`. What is implemented is "the backend could not answer for this device", which covers a dropped connection and a failed read but not a node the driver reports as dead while still answering from its cache. Closing it needs `BackendDevice` to carry readiness, and a fake that can report a dead node. |
| T13 | A device handle from the Z-Wave adapter carries no `ha_device_id` | `backends/zwave.py` leaves it empty and says the coordinator fills it in from the device registry; the coordinator does not, because nothing in Phase 1C needs it and resolving it needs the registry mapping Phase 1D builds for entities. Identity never depends on it (`DeviceHandle.identity` is backend plus `protocol_id`), so nothing is wrong today: a profile saved now simply has empty ids until Phase 1D fills them. |
| T14 | The YAML mirror (Decision D8, FR-P2) is not written | `yaml_io.py` produces the text and `storage.py` keeps the authoritative copy, but nothing writes `<config>/device_links/profiles/<slug>.yaml` on change. The option is off by default, so this is only owed when the options flow that turns it on lands in Phase 1D. |
| T15 | A cancel that arrives during a retry backoff is acted on only after the wait | The runner waits out the 1 s or 2 s and then stops, so a cancel can take up to two seconds to take effect. Nothing new is written in the meantime, so this is latency rather than safety. Closing it means racing the sleep against a stop event, which is more machinery than two seconds is worth today. |
| T16 | The executor cannot perform a `set_param` item, so a rule's `mirror_source` choice never reaches a device | `compiler.py` produces `SettingWrite`s and nothing turns them into plan items (T2), so the executor refuses `set_param` and `pending` as `unsupported_operation` rather than dropping them silently. The Z-Wave adapter's `async_write_setting` already exists and is tested, so closing this is planning work plus a branch in the runner, not new protocol work. |
| T17 | `stale_plan` covers both "somebody edited this device" and "this device stopped answering" | The two are separated only by the reason key (`stale_plan` against `device_unavailable`), so a caller that switches on the outcome cannot tell them apart. Both mean the same thing to the user today (re-plan), which is why they share an outcome; the panel in Phase 1E may want to say different things and would then want two. |
| T18 | A write reported `failed` is not checked against the re-read | E13 says retry twice and then report `failed`, so that is what happens, and a write that failed on the report path while actually landing is still reported as failed. What is understated is the job summary, which can say a link was not written when it was. The cache is not: until the executor commit fixing this review, a device where every write failed was written to and then never re-read, and "the device is deep-read anyway" was simply untrue, so the panel kept the pre-apply read and disagreed with the device. Every device the job attempted anything on is now re-read whatever its writes reported; only the checking is skipped when there is nothing verifiable. Closing the rest means deciding what a `failed` write that turns out to be present should be called, which is a wording question for the Activity view in Phase 1D rather than an executor one. |
| T19 | A job is not resumable and its progress is in memory only | E17 asks for `interrupted` and no auto-resume, which is what is implemented, but the running job's progress lives on the runner and is gone after a restart. The persisted summary records the terminal state only. Phase 1D decides whether a subscription needs more than that. |
| T20 | A job that only queued writes to a sleeping node reports `completed` | `pending_wakeup` is in the successful set, so an apply against a battery remote alone ends green having confirmed nothing. Deliberate: a queued write to a sleeping node is the documented, expected answer (CLAUDE.md Section 10), and reporting the expected answer as `partial` teaches a user to ignore the status that means something is wrong (E4). Nothing is hidden either, because the link keeps the outcome `pending_wakeup` and the rule is not recorded as applied, so it reads as pending rather than in sync. What is missing is a status that means "done, nothing confirmed yet", and a fifth `JobStatus` member changes what every consumer switches on, so it belongs with the panel that would show it (Phase 1E) and with closing J1, which is what would tell us how often this really happens. |

---

## 5. Housekeeping on Jayant's Home Assistant

Things we put on the instance that should come off eventually.

| # | Item |
|---|---|
| H1 | `/config/configuration.yaml.bak-device-links`, the backup taken before adding the `shell_command` block. Safe to delete once the block has proved itself. |
| H2 | The `shell_command:` block and `/config/tools/ha_deploy.py` both come out when Device Links moves to a HACS install (Decision D21). |
| H3 | `/config/device_links/backups/` accumulates up to 5 deployment backups. Self-pruning, but worth knowing it is there. |

---

## 6. Release prerequisites

Not needed until the first tagged release, listed so they are not discovered late.

| # | Item |
|---|---|
| P1 | Pull request to `home-assistant/brands` adding `custom_integrations/device_links`. The repo already ships its own brand assets so HACS validation passes meanwhile. |
| P2 | HACS default-repository submission, after the first stable release |
| P3 | `quality_scale.yaml` with every rule accounted for |

---

## 7. Documentation amendments owed to the PRD

`docs/PRD.md` is the original specification and is deliberately left as written. These are the
places where reality diverged from it. They are recorded in `docs/stage0-report.md` in full;
this is the index.

| Section | Amendment |
|---|---|
| 3.1 | The Aqara H2 switch and IKEA BILRESA button are not Matter binding sources. Only the two Inovelli VTM31-SN are. |
| 3.2 | A Zooz small button's LED *can* follow a remote device, through Indicator CC. The claim that no path exists holds only for the LED-mode parameters. |
| 3.2 | Inovelli group 7 is a config-button group issuing Basic Set, not a "cycle levels" group. Its own label says Multilevel, and the label is wrong. |
| 3.3 | `getAllAssociationGroups` and `getAllAssociations` do not share a nesting depth. |
| 5.1 | AGI `profile` cannot be the basis for emitter identity: it is unreliable on two of three models present. |
| 6.4 (FR-B4) | Deep verify cannot be "refresh then read". `refresh_cc_values` is fire and forget. |
| 9 (E27, E28) | ACL headroom on Eve Energy is 2 entries, not a theoretical concern. |
| 11 | Python 3.13 is not usable. Home Assistant 2026.8.3 requires 3.14.2 or newer. |
| Appendix A | The ZEN37 group layout is not a Basic/Multilevel pair per button, and capacity is 5, not 10. |
| Appendix C | The Matter library is `matter-python-client`, not the retired `python-matter-server`. |

---

## Closed

Nothing yet. Items move here with the PR that closed them.
