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

## 1b. Assumptions made to keep going without Jayant

Instructed on 2026-09-05 to complete as much as possible without waiting, using reasonable
defaults, and to defer deployment until the open items are addressed. Every assumption made
under that instruction is recorded here so it can be overturned cheaply rather than
discovered later in the code.

**Deployment to Jayant's Home Assistant is paused.** The last deployed commit is the Phase 1C
merge. Nothing since then has been sent, and nothing will be until the items in section 1 are
addressed. The deploy loop itself is proven and unchanged; it is simply not being used.

| # | Assumption | If it is wrong |
|---|---|---|
| A1 | Sleeping-node writes queue and report `pending_wakeup`, closing on the node's next wake-up event (J1 unproven) | The Zigbee-style retry path may be needed for Z-Wave battery devices; affects the executor's pending handling only |
| A2 | Zigbee bind and unbind behave as the Zigbee2MQTT documentation describes: `transaction` correlates the response, per-cluster failures are reported in `failed`, and `bridge/devices` reflects the change within a few seconds (J2 unproven) | The Phase 2 Zigbee adapter's write path needs rework; reads are already proven by G1 |
| A3 | A Zooz small button's Pressed group sends a **toggle**, not a fixed OFF (J3 unproven) | Treated as the pessimistic case: Off-all refuses to compile silently onto those buttons and warns instead. If it turns out to send a fixed OFF, the warning can simply be removed |
| A4 | An external association change emits a value-updated event we can subscribe to (J4 unproven) | Drift detection falls back to periodic verify and goal G3 is not met for external changes; the option already exists |
| A5 | Home Assistant's lazily defined components resolve inside a custom panel after the card-helpers force-load (R1 unproven) | The panel already degrades gracefully with zero HA components, so the cost is appearance rather than function |
| A6 | Zigbee2MQTT republishes `bridge/devices` after a bind, and quickly enough for a verify to read it, and it republishes its retained state **before** it answers a request rather than merely eventually (part of J2, unproven) | A deep read after an apply waits five seconds for the republish and reports `unconfirmed` rather than `applied` if it does not come. If a real bridge is slower or does not republish at all, every Zigbee apply reads as unconfirmed and the deep-verify wait needs replacing with something else (there is no request that re-reads a binding table on demand). The ordering half matters in one remaining place: `_unbind_through_group` decides whether a managed group is now empty from `bridge/groups` as it stands immediately after the member-remove response, so a bridge that answers first would leave the group undeleted and its binding orphaned. The group id no longer depends on the ordering: it is read out of the creation response |
| A7 | An Inovelli config button's press is **not** established as a fixed OFF (mirrors A3) | Marked `semantics: "unknown"` in the profile entries, so the Off-all template warns rather than compiling silently onto it. If it turns out to send a fixed OFF, the marker comes off |
| A8 | The Inovelli Zigbee setting property names and payload labels are what Zigbee2MQTT's converter exposes (unverifiable from G1, which trimmed `definition.exposes`) | The adapter refuses to write a Zigbee setting and says so, so a wrong name costs a refusal rather than a wrong write. See T45 |

---

## 2. Waiting on a Home Assistant restart

Not blocked on a decision, just on timing. Both resolve during Phase 1D and 1E, when there
is finally something worth restarting for.

| # | Item | Detail |
|---|---|---|
| R1 | Panel spike runtime half (P1) | The static half is done: every component the UI spec names exists on 2026.8.3 except `ha-tabs`, and `ha-tab-group` is the one to use. Still unconfirmed is that each element actually resolves through `customElements.whenDefined` after the card-helpers force-load. Phase 1E Task 4 built `ha-components.ts` so that whatever does not resolve degrades to a plain element rather than to a blank screen, and the shell is tested both ways, so this is now a question about how the panel looks rather than about whether it works. Task 8's harness went further and reduced the exposure: the views, both dialogs and the rules table are built out of plain elements and Home Assistant's CSS custom properties, so the only Home Assistant elements the panel needs are the app bar, the tab strip, `ha-icon` and `ha-alert`, and the harness was looked at with all of them present and with none of them (`docs/panel/16-fallback-and-version-banner.png`). Closing it still needs a deploy and Jayant's restart. |
| R3 | `ha-tab-group-tab` was never probed | The P1 capture recorded `ha-tab-group` and not the tab element inside it, so the child tag name the panel renders (`ha-tab-group-tab`, and the `slot="nav"` and `panel` attributes it takes) is taken from the Home Assistant frontend's source rather than from this instance. The shell needs both `ha-tab-group` and `ha-tab-group-tab` to resolve before it uses either, and falls back to a plain nav of buttons otherwise, so a wrong guess costs the tab strip's appearance and nothing else. Confirmed by the same deploy that closes R1. |

---

## 3. Scheduled work

Claude-owned, sequenced, no input needed.

| # | Item | Lands in |
|---|---|---|
| S1 | Z-Wave adapter: live capabilities, observed state, writes, subscriptions | Phase 1B |
| S2 | Storage, profiles, snapshots, YAML export | Phase 1C |
| S3 | Executor: jobs, retries, concurrency, verify | Phase 1C |
| S4 | Entities, services, events, diagnostics, Repairs, WebSocket API | Phase 1D |
| S6 | The sidebar panel: toolchain, registration, API client and shell | Phase 1E Tasks 1 to 4, landed |
| S9 | The panel's views, dialogs and static harness | Phase 1E Tasks 5 to 8, landed |
| S7 | Zigbee backend, device swap, hybrid legs | Phase 2. The Zigbee backend landed in Phase 2A: pure protocol, adapter, managed groups, curated entries and the mixed-backend loop test, and is built at setup as of the T42 commit. Not deployed. Device swap and hybrid legs remain |
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
| T28 | The E1 Repairs issue has no grace period, so a brief Z-Wave JS restart can raise an error-severity issue and withdraw it seconds later | The issue is raised the moment a read fails and withdrawn the moment one succeeds, which is honest and is also a flash of red in the Repairs panel for something that fixed itself. Debouncing it means remembering how long a backend has been down across checks, which is state this module deliberately does not keep (everything is recomputed, which is what makes an issue impossible to leave behind). Worth doing when there is evidence of how often it actually happens on this network, which needs the integration to have been running for a while. |
| T29 | A frontend-only dev deploy needs a hard refresh, not a normal reload | The static URL carries the integration version, so a release cannot be served from cache. Within one version the URL does not move, which is exactly the frontend-only deploy case, and nothing re-registers the static path without a restart. `cache_headers=False` is what makes the bytes fetchable again: aiohttp sends `Last-Modified` and an `ETag` and no `Cache-Control`, so a hard refresh always gets the new file and a normal reload may serve a heuristically fresh copy. This is what the deploy tool's `browser_reload` flag means, and the alternative (a URL that claimed to have moved when nothing re-registered it) would be worse. |
| T30 | The panel's UI copy is English literals, not translation keys | Every message from the backend is localised: a `Diagnostic` and an API error both arrive as a translation key and are rendered through `messages.ts`, which asks `hass.localize` first and falls back to the English inlined from `strings.json` at build time. The panel's own chrome (tab labels, button labels, the version banner) is not, because a custom panel's strings are not among the translation categories the Home Assistant frontend loads for a panel and `tests/test_translations.py` asserts a strict correspondence between `strings.json` and the keys the Python raises, which a panel-only section would break. Closing it means deciding where panel strings live and how the frontend gets them, which is a decision rather than a piece of work. |
| T31 | The panel's diagnostic fallback duplicates `strings.json` inside the bundle | `build-defines.ts` inlines the `exceptions` and `issues` messages at build time, which is roughly 12 kB of the 40 kB bundle. It is generated rather than copied, so it cannot go stale (a `strings.json` change that was not rebuilt fails the CI bundle check), but it is still two copies of the same text shipped in one release. Closing it means the frontend loading this integration's translations properly, which is T30. |
| T32 | The bundle's byte stability is proven on macOS only | Three clean builds here, plus one from a different working directory with the vite cache cleared, are byte identical, and nothing in `vite.config.ts` reads a clock, an environment variable or an absolute path. What is untested until CI runs is whether the same pinned rolldown and oxc produce identical bytes on Linux. If they do not, the CI check becomes noise, and the answer then is to say what is normalised rather than to delete the check. Watch the first `frontend` job on `dev`. |
| T33 | The tab strip renders no icon-only fallback on a narrow screen without `ha-icon` | On a narrow screen the tabs show icons rather than labels, which needs `ha-icon`. Without it the plain nav shows full labels and wraps, which is correct but wide. Not worth a second fallback until somebody sees it. |
| T34 | The API exposes no "last verified" time, so the Overview can only say when this panel last asked | `verify` answers with how many devices it re-read and what each rule now looks like, and nothing records when a verify last happened. The Overview therefore says "Verified 3 minutes ago" only for a verify run from this browser tab, and says nothing after a reload. Closing it means the coordinator keeping a timestamp per device and the serializer carrying it, which is a storage-adjacent change for a line of text. |
| T35 | Nothing answers "what controls this device", so the Devices view reads every device to find out | `devices/get` returns the links stored *on* a device, which is the outgoing half. The incoming half is every other device's outgoing half, so the panel builds an index by calling `devices/get` once per device the first time a device page is opened, and keeps it for the life of the view. That is 36 cached-read commands on this network, which is cheap but silly. A `links/list` command, or links on the `devices/list` rows, would answer it in one. |
| T36 | The rules table is a plain table, not `ha-data-table` | The Phase 1E plan named `ha-data-table`. Every cell in this table is something the user acts on (a switch, chips, three buttons), that element's row-template API differs between frontend versions, and R1 means nobody has yet confirmed Home Assistant's lazily defined elements resolve inside this panel at all. A rules table that renders as an empty box is a rules screen with no rules on it. The plain table scrolls inside its own container on a narrow screen, and on a narrow screen it becomes a list of cards instead. Revisit once R1 is closed and the element is known to resolve. |
| T37 | The panel's dialogs are its own overlay, not `ha-dialog` | Same reasoning as T36 and the same trigger to revisit: the plan dialog and the rule editor are the two screens the product cannot work without, and R1 is open. `dl-dialog` gives Escape, scrim dismiss, focus return and a full-screen narrow layout, and it is themed entirely from Home Assistant's custom properties. What it does not give is Home Assistant's dialog stacking and its mobile back-button behaviour. |
| T38 | The panel's rule switch does not go through the E35 rate limiter | Enabling a rule physically writes its links (Decision D7), and `rules/set_enabled` writes them immediately, which is a device write with no plan in front of it. The panel's switch instead stores the change with `rules/upsert` and opens the plan dialog, and puts the switch back if the plan is cancelled. That keeps the "no write without a confirmed plan" rule whole, and it means a burst of toggles from the panel is limited by a human confirming each plan rather than by `RuleToggleLimiter`. The switch entity and the service still go through the limiter, which is where an automation would come from. |
| T39 | The rule editor always targets the whole device, never one endpoint | `RuleTargetData.endpoint` exists and the compiler honours it (downgrading with a warning when the control cannot address an endpoint), and the editor sends null for every target. Every Z-Wave device on this network is single-endpoint, so nothing is lost there; a multi-endpoint target elsewhere would be linked whole. On Zigbee it is not merely a loss of precision, it is a refusal: see T50. Closing it means an endpoint picker in the targets step, which needs the target device's endpoint list, which `devices/get` does not carry yet. |
| T40 | The panel's own English strings are still not translatable, and there are now many more of them | T30 named the problem when the panel was a shell with five tab labels. Tasks 5 to 8 added several hundred words of UI copy, so the cost of closing T30 has gone up and the reason has not changed. Everything the backend says is still localised; everything the panel says is still English literals. |
| T41 | Nothing removes a managed Zigbee group whose rule was deleted while Home Assistant was down | The `Backend` protocol writes one link at a time and never sees a rule, so the adapter cannot know that a rule has stopped existing. In the normal case nothing is owed: disabling a rule plans removals, the last member comes out of the group, and the group goes with it. What is left is the same gap T11 describes, seen through a group: a rule deleted (or edited to point elsewhere) stops claiming its links, they become unmanaged, and the `dl_` group they sit in is reported rather than removed. `ZigbeeBackend.async_drop_managed_group` and `managed_group_rule_ids` are the two halves of the answer, both tested, and nothing calls them: wiring them up means giving the coordinator a way to tell a backend that a rule is gone, which is a deliberate change to the protocol rather than a quiet special case in core. A narrower case sits under the same heading: a managed group deleted by hand while bindings still point at its id. Zigbee2MQTT drops those bindings itself when it deletes a group, so it should not arise; if it did, the next apply recreates the group under a new id and the dead binding is reported as an unmanaged link to `group:<id>` rather than being removed. |
| T43 | A Zigbee binding table's real size is not reported, so capacity is a bound rather than a measurement | `zigbee_protocol.BINDING_TABLE_CAPACITY` is 8 per endpoint cluster. Zigbee2MQTT does not publish a device's binding table size and the Zigbee specification leaves it to the manufacturer, so there is no number to read. Too low blocks a plan that would have worked; too high lets one through that the device refuses, which is now reported per cluster rather than silently. Decision D5's managed group is what keeps this from mattering: a group is one entry however many members it has. |
| T44 | The planner counts group capacity per device and group, not per endpoint | `planner._planned_adds` keys its capacity count on `(source identity, emitter_group)`, and `_capacity_of` takes the first emitter whose `group_ids` hold the group. On Zigbee the writable slot is `(endpoint, cluster)`, so two endpoints driving `genOnOff` share one bucket and the reporting bindings on a switch's load endpoint count against its paddle's. Latent rather than active on this network: the counts are small and every Zigbee emitter reports the same capacity, so nothing is blocked today. The same conflation in `executor.JobRunner._is_system` was narrowed in Phase 2A and closed for good with T49, which is where the reasoning about what a slot is per protocol now lives (`backends.base.SystemScope`). This one is left alone because no test fails on it and changing the planner changes every plan token. |
| T45 | Zigbee device settings are read as "not reported" and refused on write | The four Inovelli adapters (`smart_bulb_mode`, `local_protection`, `remote_protection`, `binding_off_to_on_sync_level`) ship in the profile entries, and their property names and payload labels come from Zigbee2MQTT's converter rather than from the G1 capture, which trimmed `definition.exposes` out. A write would also need the `set` and state round trip, which nobody has observed either, so building one would stack a second unverified model on the first and prove only that the two agree. Nothing can reach it today in any case: the compiler emits a setting write only for `mirror_hub_commands`, a Z-Wave concept, and the executor cannot carry out a `set_param` item at all (T16). Closing it means subscribing to each device's own state topic and confirming the property names, which G2 or a fresh capture would settle. |
| T46 | A `genLevelCtrl` binding a rule only half asked for is reported as unmanaged | One cluster carries setting a level and holding to dim, so a rule that asks for one of them gets both, and the one it did not ask for reads back as a link nobody claims. Reported rather than removed, which is safe, and worded as though somebody else made it, which is not quite true: Device Links made it, as an unavoidable side effect of what the user did ask for. Closing it means a third ownership state between "ours" and "somebody's own", which is a change to what the panel shows and to what `managed_by` means. Cheap alternative: have the rule editor offer the two level features as one choice on a Zigbee rule, which is what the hardware offers. |
| T47 | A binding on a cluster Device Links cannot drive is reported as a status report | `zigbee_protocol.features_of_binding` answers `STATUS_REPORT` for `seMetering`, `manuSpecificInovelli` and the rest, the same answer the Z-Wave side gives a group that issues nothing usable. It keeps a device's binding table described whole, which is what the capacity count and the device view need, and it is a slight overstatement: those entries do not all report anything. Nothing acts on it (no emitter maps a feature to those clusters, so none can ever be desired), so this is wording rather than behaviour. |
| T50 | The rule editor sends null for every endpoint, so no rule saved from the panel is accepted | Two halves, found while closing T48 and both worse than T39 said. **The source endpoint**: `rule-editor.ts` builds `source: {device, endpoint: null, emitter_id}` and never fills the endpoint in, while `yaml_io._require_int` requires a whole number, so `rules/upsert` refuses every rule the panel sends with `profile_invalid` ("rule ... source endpoint must be a whole number, not nothing"). That is every rule, on every protocol, and it is why nothing here has been seen working: deployment has been paused since Phase 1C, so the panel's save path has never met the backend. **The target endpoint**: the editor sends null there too (T39), which costs a Z-Wave rule precision and refuses a Zigbee one outright, because a Zigbee binding always names a target endpoint and the adapter answers `zigbee_target_endpoint_required` rather than choosing one. Closing it is a decision rather than a patch: either the editor picks both endpoints (which needs a device's endpoint list on `devices/get`, and `Emitter.endpoint` on the emitter payload, T55), or the backend resolves a null source endpoint from the named emitter and a null target endpoint from `DeviceCapabilities.receiving_endpoint` (both of which exist as of T48) and says in the plan which endpoint it chose. **Nothing usable ships from the panel until this is settled**, so it is the first thing Phase 2B should take. |
| T51 | A Zigbee2MQTT bridge that starts after Device Links is not adapted until a reload | `_async_build_zigbee` subscribes once at setup and waits ten seconds for the retained `bridge/devices`. A broker that is up with Zigbee2MQTT still starting, or a base topic that was wrong and has been corrected in the add-on rather than in our options, leaves the entry loaded with no Zigbee backend until somebody reloads it. It is a warning in the log naming the topic, and the Z-Wave half of the house keeps working. Refusing to set up instead (`ConfigEntryNotReady`) was rejected: somebody who runs an MQTT broker for something else entirely and no Zigbee2MQTT would then have Device Links retrying for ever over a bridge they do not own. Closing it properly means watching for the retained payload arriving later and building the backend then, which is a second setup path. |
| T52 | Only one Zigbee2MQTT instance is adapted | The exact shape of T22 one protocol along. The options flow takes one base topic, `BackendId` is one key per protocol, and `DeviceHandle.protocol_id` is the IEEE address with no instance in it, so two instances on one broker cannot both be represented without keying the backend map and the handle on the instance as well. A user with two configures the one they want Device Links to manage and sees nothing at all of the other: no devices, no links, no error. That is the same answer a second Z-Wave network gets, and it is the reason the base topic is a setting rather than a constant: the room to grow is there, and only the wiring is missing. |
| T53 | `DeviceCapabilities.receiving_endpoint` takes the lowest endpoint that can receive | Added for T48, and derived rather than curated: the Zigbee adapter answers with the lowest endpoint whose input clusters carry a bindable feature, which is endpoint 1, the load, on every switch in the G1 capture. On a device with two receiving endpoints (a two-gang switch) that is a choice made for the user. It is the same approximation `DeviceCapabilities.receivable` already makes by being a union across endpoints, and it is only consulted where the user was offered no choice at all, so nothing silently overrides something they asked for. A curated entry naming the receiving endpoint per model is the obvious close, and it wants a device that needs it first. |
| T54 | `Emitter.is_lifeline` is always False and nothing can make it true | `zwave_protocol._usable_groups` drops lifeline groups before an emitter is built, and the Zigbee side sets it False outright, so no emitter in the product has ever carried True. It is serialized to the panel and read by `services._group_view`, both of which therefore ask a question with one possible answer. Harmless, and misleading to the next person who reaches for it as the answer to "is this slot the protocol's own" (which is what T49 needed and what `backends.base.SystemScope` now answers). Either give it a meaning or take it out; taking it out is a change to the panel's `Emitter` interface and so to the bundle. |
| T55 | `Emitter.endpoint` is not serialized to the panel | The field exists on the shared capability model as of T48 and `Serializer._emitter` does not carry it, so the panel cannot show which endpoint a control drives from and cannot use it to fill in a target endpoint. Left out deliberately: adding a field to that payload means a `types.ts` change and a bundle rebuild, and nothing in the panel reads it yet. It is what T50's endpoint picker would want first. |
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
| T48 | A two-way Zigbee rule compiled a reverse leg that could never be written | `fix(compiler): a two-way rule's reverse leg is written from real endpoints` (bc38078). `_compile_reverse` wrote the leg from `writer_endpoint=0` onto `rule.source.endpoint or None`, the Z-Wave root and the Z-Wave whole-node target. On Zigbee the paddle is endpoint 2 and the load is endpoint 1, so the leg was refused at apply with `zigbee_source_cannot_send` while the compiler reported neither a warning nor an error: the plan looked clean and never converged, on the two-Inovelli-Blue 3-way the panel defaults to. Closed by completing the shared capability model rather than by teaching core about Zigbee: `Emitter.endpoint` says where a control drives from and `DeviceCapabilities.receiving_endpoint` says where a link lands when nobody was offered the choice. Z-Wave answers 0 and None, which is what was hardcoded, so no Z-Wave rule changed. `zigbee_protocol.Control` went with it: it existed only to carry the endpoint beside an emitter. Rules store `emitter_id` and never an `Emitter`, and neither `storage.py` nor `yaml_io.py` mentions either type, so no storage migration was needed. Left behind: T50, T53 and T55. |
| T49 | `JobRunner._is_system` refused a whole endpoint cluster over one binding in it | `fix(executor): system-ness is a slot on Z-Wave and an entry on Zigbee` (a9ecfd0). The guard treated a writable slot as reserved whenever it held an entry a backend had marked system. That is a Z-Wave truth (an association group has one purpose, so a group holding the controller is a lifeline and nothing else may go into it) and false on Zigbee (an endpoint's cluster is a table of independent bindings). Zigbee2MQTT puts a reporting binding on exactly the endpoint and cluster a button's presses come from, so every rule from the first Zigbee remote added to a network was refused with no way out from the UI. Closed by each backend declaring which its `is_system` mark means, `backends.base.SystemScope`, so core asks rather than guessing and still never branches on a backend id. Z-Wave answers `SLOT` and behaves exactly as before; Zigbee answers `ENTRY`. Nothing was taken off the coordinator: a removal of the bridge's own binding is still refused by that entry's own `is_system`, and `ZigbeeBackend._absolute_refusal` still refuses any binding to the coordinator on its own account. CLAUDE.md Section 12 asks for Jayant before a change to what counts as a system link; this one was his instruction. |
| T42 | The Zigbee backend was not built at setup, so nothing in the product used it | `feat(zigbee): build the Zigbee backend at setup and report it like the other` (8cc3611). `backends/mqtt_client.py` is the `MqttClient` seam over Home Assistant's `mqtt`, with every import of that package inside a function for the reason `zwave_accessor` does the same with `zwave_js`. The base topic is an option defaulting to `zigbee2mqtt` (E25), trimmed on save, and an emptied field returns to the default. No `mqtt` integration is silent and is not an error; a broker with nothing on the configured topic is one warning and leaves the rest of the integration working. `BackendInfo` carries a version reader rather than a string, so an upgraded Zigbee2MQTT is reported truthfully by the Health sensor and the diagnostics; the Z-Wave answer is still fixed for the life of the entry. The adapter's four subscriptions come down through `entry.async_on_unload`. Left behind: T51 and T52. |
| R2 | Entity attachment unload half (P2) | Phase 1D Task 2. `tests/test_rule_entities.py::test_unloading_removes_our_entities_and_leaves_the_upstream_device_alone` unloads the config entry with rule entities attached and asserts the `zwave_js` device entry comes through with the same id, the same identifiers, the same primary config entry and the same name, and that the device list is unchanged. Note what Home Assistant 2026.8 changed underneath P2: device registry identifiers are unique per config entry since the composite-device split, so attaching means registering our own record carrying the identifiers `zwave_js` registered, and Home Assistant groups the two. `rule_entity.py` never spells an identifier out; it copies them back from the record it found, which is what makes a near miss impossible rather than merely unlikely. |
