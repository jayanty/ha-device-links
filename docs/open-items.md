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

---

## 3. Scheduled work

Claude-owned, sequenced, no input needed.

| # | Item | Lands in |
|---|---|---|
| S1 | Z-Wave adapter: live capabilities, observed state, writes, subscriptions | Phase 1B |
| S2 | Storage, profiles, snapshots, YAML export | Phase 1C |
| S3 | Executor: jobs, retries, concurrency, verify | Phase 1C |
| S4 | Entities, services, events, diagnostics, Repairs, WebSocket API | Phase 1D |
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
| T13 | A device handle carries no `ha_device_id`, and now deliberately never will | Phase 1D resolves the Home Assistant device from the handle at the moment it is needed, in `rule_entity.async_upstream_device`, rather than storing a copy on the handle. That is a change of plan from what `backends/zwave.py` says in its comment, and it is the better half of the trade: a stored id goes stale the first time somebody rebuilds their device registry or replaces a node, while a lookup keyed on `protocol_id` cannot. Anything in Phase 1E or later that wants an HA device id calls that function. The field stays empty and stays out of identity; `backends/zwave.py`'s comment is the only thing left that is out of date. |
| T14 | The YAML mirror (Decision D8, FR-P2) is not written | `yaml_io.py` produces the text and `storage.py` keeps the authoritative copy, but nothing writes `<config>/device_links/profiles/<slug>.yaml` on change. The option is off by default, so this is only owed when the options flow that turns it on lands in Phase 1D. |
| T15 | A cancel that arrives during a retry backoff is acted on only after the wait | The runner waits out the 1 s or 2 s and then stops, so a cancel can take up to two seconds to take effect. Nothing new is written in the meantime, so this is latency rather than safety. Closing it means racing the sleep against a stop event, which is more machinery than two seconds is worth today. |
| T16 | The executor cannot perform a `set_param` item, so a rule's `mirror_source` choice never reaches a device | `compiler.py` produces `SettingWrite`s and nothing turns them into plan items (T2), so the executor refuses `set_param` and `pending` as `unsupported_operation` rather than dropping them silently. The Z-Wave adapter's `async_write_setting` already exists and is tested, so closing this is planning work plus a branch in the runner, not new protocol work. |
| T17 | `stale_plan` covers both "somebody edited this device" and "this device stopped answering" | The two are separated only by the reason key (`stale_plan` against `device_unavailable`), so a caller that switches on the outcome cannot tell them apart. Both mean the same thing to the user today (re-plan), which is why they share an outcome; the panel in Phase 1E may want to say different things and would then want two. |
| T18 | A write reported `failed` is not checked against the re-read | E13 says retry twice and then report `failed`, so that is what happens, and a write that failed on the report path while actually landing is still reported as failed. What is understated is the job summary, which can say a link was not written when it was. The cache is not: until the executor commit fixing this review, a device where every write failed was written to and then never re-read, and "the device is deep-read anyway" was simply untrue, so the panel kept the pre-apply read and disagreed with the device. Every device the job attempted anything on is now re-read whatever its writes reported; only the checking is skipped when there is nothing verifiable. Closing the rest means deciding what a `failed` write that turns out to be present should be called, which is a wording question for the Activity view in Phase 1D rather than an executor one. |
| T19 | A job is not resumable and its progress is in memory only | E17 asks for `interrupted` and no auto-resume, which is what is implemented, but the running job's progress lives on the runner and is gone after a restart. The persisted summary records the terminal state only. Phase 1D decides whether a subscription needs more than that. |
| T21 | Switching the active profile drops per-rule entity customizations | Rule entities exist per rule of the active profile (FR-E1), so a rule that leaves the profile has its entity registry entry removed, which takes whatever the user renamed it to and whichever area they put it in. Keeping the entry instead would leave an unavailable switch per rule of every inactive profile, which is worse on a house with several profiles. Closing it properly means keeping the registry entries and marking them unavailable only while their profile is inactive, which needs the panel to explain what the user is looking at (Phase 1E). |
| T22 | Only one Z-Wave network is adapted | `_async_build_backends` takes the first loaded `zwave_js` config entry and stops. `BackendId` is one key per protocol, so two Z-Wave networks cannot both be represented without making the backend map key on the config entry as well, which changes `DeviceHandle.identity` (the home id already distinguishes them, so the data model is ready and the wiring is not). Nobody on this network has two, and a second one would silently be ignored rather than misread. |
| T23 | E18 raises its Repairs issue, and the entry still refuses to load instead of coming up read-only | Phase 1D Task 6 landed the half that explains itself: a `StorageSchemaError` now raises a Repairs issue naming the file and the reason before `async_setup_entry` fails, and a later setup that can read the file withdraws it. What is still missing is the read-only integration E18 also asks for, which means a coordinator that will not save, a runtime flag every write path (services, WebSocket commands, the rule switch, the buttons) checks before it does anything, and a translated refusal from each of them. That is a change to every surface this phase built rather than an addition to one, and the file is protected either way: it is never written over, which is the half that cannot be added later. |
| T25 | A group-level message names the association group by number, not by the label the device reports | "Group 7 on 'Bedroom Scene Controller' is full (5 of 5)" is actionable, and "Group 'Button 2 - Pressed' is full" is what PRD Section 9 (E6) actually asks for. The label lives on the emitter and the planner is handed links and capacities rather than emitters, so closing this means passing the label into `planner._group_placeholders`, which is pure-module work with its own tests. The panel shows labels beside every group, so the number is unambiguous in the place a user is most likely to be looking. |
| T26 | Four of the WebSocket commands PRD Section 8.7 lists are not implemented | `unmanaged/adopt` needs a per-link ownership record, which is a storage schema change and a migration (T11). `swap/candidates`, `swap/preview` and `swap/apply` are the Phase 2 device-swap flow, and `snapshots/rollback` is the Phase 2 flow that re-applies a snapshot as a plan. They are named in `websocket.DEFERRED_COMMANDS` with the phase that owns each, and a test asserts that the implemented set plus the deferred set is exactly what the PRD lists, so a fifth one cannot go missing quietly. |
| T27 | `verify_not_confirmed` knows whether the device was asleep or simply did not answer, and its message does not say which | The executor supplies `why` as `asleep` or `no_answer` and the sentence leaves it out, because the two words are tokens rather than translated text and a message cannot translate a placeholder. Saying it properly means two keys, as the pending wake-up issue already has, and the wording depends on open item T10: until J4 is closed, "the device did not confirm" may be the normal answer on real hardware rather than an unusual one. |
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
| 6.6 (FR-E3) | `device_links.apply` takes `remove_unmanaged` as a list of link fingerprints, not as a boolean. A boolean would put "remove every link Device Links did not create" behind one word in a YAML automation, which is the whole-network deletion CLAUDE.md Section 3 rule 5 and Decision D9 exist to prevent. The panel ticks fingerprints; an automation names them. |
| 6.6 (FR-E3) | `device_links.apply` has no `deep_verify` field. The executor deep-verifies every device it wrote to, always (Phase 1C), so a field offering to turn that off would describe a behaviour that does not exist. `device_links.verify` reads deeply by definition. |
| 6.6 (FR-E3) | `device_links.zigbee_bind` and `device_links.zigbee_unbind` are not registered. There is no Zigbee adapter until Phase 2, and a service that can only refuse is worse than one that is absent. |

---

## Closed

| # | Item | Closed by |
|---|---|---|
| S5 | `strings.json` entries for every diagnostic translation key the compiler, the planner and the executor emit | Phase 1D Task 7. `tests/test_translations.py` collects every key from the syntax tree (`_attr_translation_key`, `translation_key=`, and the first argument of every `Diagnostic` and `BlockedReason`) and asserts both directions: no key without a message, and no message without a key. It also asserts that every placeholder a message uses is supplied everywhere that message is raised, which found three keys raised from two places with different placeholders (`unknown_group`, `settings_not_available` and `backend_not_loaded`); two were given matching placeholders and one was split into `group_not_offered`. |
| T24 | Entity name strings written ahead of Task 7 | Phase 1D Task 7, which wrote everything else `strings.json` owns: the exception and diagnostic messages, the Repairs issues, the services and their fields, and the options flow. The mechanical check under S5 above is what keeps the entity half honest from here. |
| R2 | Entity attachment unload half (P2) | Phase 1D Task 2. `tests/test_rule_entities.py::test_unloading_removes_our_entities_and_leaves_the_upstream_device_alone` unloads the config entry with rule entities attached and asserts the `zwave_js` device entry comes through with the same id, the same identifiers, the same primary config entry and the same name, and that the device list is unchanged. Note what Home Assistant 2026.8 changed underneath P2: device registry identifiers are unique per config entry since the composite-device split, so attaching means registering our own record carrying the identifiers `zwave_js` registered, and Home Assistant groups the two. `rule_entity.py` never spells an identifier out; it copies them back from the record it found, which is what makes a near miss impossible rather than merely unlikely. |
