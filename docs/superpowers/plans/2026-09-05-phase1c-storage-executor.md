# Phase 1C: storage, ownership, and the executor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist profiles across restarts, work out which observed links are ours, and turn a plan into a sequenced, retrying, cancellable job that verifies what it wrote.

**Architecture:** Four modules. `yaml_io.py` is pure (export and import). `storage.py` wraps Home Assistant's `Store` with schema versions and migrations. `coordinator.py` owns the observed-state cache and resolves ownership, which the adapter deliberately left to it. `executor.py` runs jobs.

**Tech Stack:** Python 3.14, Home Assistant `Store`, `asyncio`, the Phase 1B fakes.

---

## The three things that make this phase dangerous

1. **Storage is where user work lives.** A migration that loses a profile loses hours of a
   user's configuration with no undo. Every schema version needs a migration and a test that
   round-trips real data through it.
2. **Ownership decides removals.** The planner removes exactly what `managed_by` claims and
   nothing else. If the coordinator guesses "this is ours" about a link the user made by
   hand in Z-Wave JS UI, the next apply deletes it. Ownership must be recorded, never
   inferred from shape.
3. **A job writes to real hardware.** Retries, concurrency and cancellation are not
   ergonomics here: an unbounded retry loop hammers a mesh, and a cancel that does not stop
   scheduling leaves a half-applied plan.

## Ground rules

Read `CLAUDE.md`, `docs/stage0-report.md` and `docs/open-items.md` first.

- `yaml_io.py` is a **pure module** and must be added to `PURE_MODULES` in
  `tests/test_manifest.py`. No `homeassistant` import, no file I/O: it takes and returns text.
- `storage.py`, `coordinator.py` and `executor.py` may import Home Assistant.
- **No test in this phase may touch Jayant's real network.** Use the Phase 1B fakes.
- Never use the em dash. `mypy --strict` clean. Coverage gate 95%; the repo is at 100%.
- Conventional commits ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Ruff formats Python blocks inside Markdown; run `ruff format` on any `.md` you touch.
- **Register anything you cannot resolve in `docs/open-items.md`** with an id, what it
  blocks, and what would close it. Do not leave a bare TODO in code.

## Facts from Stage 0 that set the budgets

Add took **67 ms**, remove **253 ms** on a listening mains-powered node. Those are the
numbers to size timeouts and backoff against, not guesses. A 30 second per-operation timeout
is two orders of magnitude of headroom and still bounded.

---

## File structure

| File | Responsibility |
|---|---|
| `custom_components/device_links/yaml_io.py` | Profile to YAML text and back, with validation. Pure. |
| `custom_components/device_links/storage.py` | `Store` wrapper: load, save, schema version, migrations, snapshots, job history. |
| `custom_components/device_links/coordinator.py` | Observed-state cache, ownership resolution, drift evaluation, backend availability. |
| `custom_components/device_links/executor.py` | Job model and runner: sequencing, concurrency, retries, cancel, verify. |

---

### Task 1: YAML export and import

**Files:** create `custom_components/device_links/yaml_io.py`, `tests/test_yaml_io.py`; modify `tests/test_manifest.py`

Export exists so a user can keep their design in git (FR-P2). Import must never write to a
device by itself: it updates desired state and the user sees a plan.

- [x] **Step 1: Write the failing tests.** Cover at least:
  - A profile round-trips: `parse_profile(dump_profile(p)) == p`, for a profile containing
    two rules, several targets, a disabled rule, mirror choices and tags.
  - Export is **deterministic**: dumping the same profile twice gives byte-identical text, and
    keys are ordered stably. A diff that churns on every save is useless in git.
  - Export contains no `ha_device_id` and no `name_at_authoring` beyond a comment field:
    those are local to one instance and would make an exported profile misleading elsewhere.
  - `parse_profile` on an unknown schema version raises `ProfileFormatError` naming the
    version it found and the versions it supports (E38).
  - `parse_profile` on malformed YAML raises `ProfileFormatError` with the line number.
  - `parse_profile` rejects a rule referring to a template that does not exist, a feature
    that is not in `Feature`, and a rule with no targets, each with a distinct message.
  - Every error message names the offending rule by id or index, because "invalid profile"
    is unactionable in a file with forty rules.

- [x] **Step 2: Run and confirm failure.**

- [x] **Step 3: Implement.** `dump_profile(profile) -> str` and `parse_profile(text) -> Profile`,
  plus `SCHEMA_VERSION`. Use `yaml.safe_dump` with `sort_keys=True` and an explicit
  `default_flow_style=False`. `yaml` ships with Home Assistant, so it is not a new
  dependency, but **it is not importable in a pure module context without care**: import
  `yaml` directly (it is a third-party package, not `homeassistant`), which keeps the module
  pure by the project's definition. Confirm the manifest test still passes after adding
  `yaml_io.py` to `PURE_MODULES`.

- [x] **Step 4: Confirm tests pass. Step 5: Commit.**

```bash
git commit -m "feat(core): deterministic profile export and validating import"
```

---

### Task 2: Storage with migrations

**Files:** create `custom_components/device_links/storage.py`, `tests/test_storage.py`

- [x] **Step 1: Write the failing tests.** Cover at least:
  - A fresh install loads an empty store without error and without writing a file.
  - Save then load round-trips profiles, the active profile id, ignored unmanaged
    fingerprints, snapshots and job summaries.
  - **Loading a version 1 store when the code is at version 1 does not migrate.**
  - **A future schema version is refused rather than guessed at**: loading a store whose
    version is higher than the code supports raises, and the integration is expected to come
    up read-only (E18). Assert the raised error names both versions.
  - Snapshots are capped at 20 and the oldest is dropped first (FR-P3).
  - Job summaries are capped at 50 (PRD Section 8.2).
  - `ignored_unmanaged` survives a round trip: a user who dismissed a link must not see it
    re-flagged after a restart (FR-A5).
  - Saving is debounced: ten rapid saves produce fewer than ten writes. Use HA's
    `Store.async_delay_save` and assert against the store's write count.

- [x] **Step 2: Run and confirm failure.**

- [x] **Step 3: Implement.** `DeviceLinksStore` wrapping `homeassistant.helpers.storage.Store`
  with `STORAGE_VERSION = 1` and `STORAGE_KEY = "device_links.profiles"` from `const.py`.

  Write `_async_migrate_func(old_major_version, old_minor_version, old_data)` even though
  there is nothing to migrate yet, and **test it with a synthetic version 0 payload**. The
  first real migration is the one most likely to lose data, and writing the mechanism now,
  with a test, means the first migration is an edit rather than a new invention.

- [x] **Step 4: Confirm tests pass. Step 5: Commit.**

```bash
git commit -m "feat(core): profile storage with schema versioning and migration"
```

---

### Task 3: The coordinator, and the ownership rule

**Files:** create `custom_components/device_links/coordinator.py`, `tests/test_coordinator.py`

This is where `ObservedLink.managed_by` gets filled in, which Phase 1B deliberately left to
this layer. Get it wrong in the "ours" direction and the next apply deletes something a user
made by hand.

- [x] **Step 1: Write the failing tests.** Cover at least:
  - **Ownership is by recorded fingerprint, never by shape.** A link whose fingerprint is in
    the active profile's compiled set is `managed_by` that rule. A link that merely *looks*
    like something a rule would produce, but is not in the compiled set, is unmanaged.
    Make this test explicit and name it so its intent survives: an observed link identical in
    every field except that no rule compiled it must come back unmanaged.
  - A system link is never assigned an owner, even if a rule's compiled set somehow contains
    its fingerprint. Belt and braces over the planner's own guard.
  - Disabling a rule leaves its links owned, not unmanaged: they must be planned for
    removal, and an unowned link is never removed by default. **This is the subtle one.**
    Getting it wrong turns a disable into a permanent orphan.
  - Deleting a rule from the profile makes its links unmanaged, so they are reported rather
    than silently removed.
  - The cache refreshes on a backend subscription callback, debounced.
  - When a backend goes unavailable, devices from it are marked unavailable rather than
    having their links reported as removed. **A dropped connection must never look like
    someone deleted every association** (E1).
  - Drift is computed only after a successful apply, and a device whose state is unknown
    (dead, not ready) is `unknown`, not `drift` (E4).

- [x] **Step 2: Run and confirm failure.**

- [x] **Step 3: Implement.** `DeviceLinksCoordinator` holding the backends, the store, the
  observed cache and the active profile. Public surface: `async_refresh(handle=None)`,
  `observed_for(handle)`, `async_plan(scope)`, `drift_state()`, and subscription
  registration and teardown.

  Ownership: compile the active profile once per refresh, index by link fingerprint, and
  assign `managed_by` by exact fingerprint match. Nothing else.

- [x] **Step 4: Confirm tests pass. Step 5: Commit.**

```bash
git commit -m "feat(core): coordinator with fingerprint-based ownership resolution"
```

---

### Task 4: The job runner

**Files:** create `custom_components/device_links/executor.py`, `tests/test_executor.py`

- [ ] **Step 1: Write the failing tests.** Cover at least:
  - A plan of three adds across two devices applies all three and reports per-link results.
  - **Operations on one device are serialized.** Two writes to the same node must never be
    in flight together; a mesh handles one command per node at a time and overlapping writes
    produce timeouts that look like device faults.
  - At most `max_concurrent_devices` devices are worked at once (default 2, configurable).
  - A failed operation is retried twice with exponential backoff, then reported `failed`.
    Assert the number of attempts and that the delays increase.
  - A `blocked` result is **not** retried. Retrying a refusal wastes the mesh and cannot
    succeed.
  - Cancel stops scheduling new operations, lets in-flight ones finish, and reports the rest
    as cancelled. Assert no operation starts after cancel.
  - A stale plan token causes that device's operations to be skipped as `stale_plan` while
    other devices proceed (FR-A3, E15).
  - A second apply for the same profile while one is running is rejected with `job_running`
    (E16).
  - The job summary records per-link results and is persisted.
  - **A job interrupted by shutdown is marked `interrupted` and is not auto-resumed** (E17).
    Re-running apply is safe because the plan is recomputed.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement.** `JobRunner` with `async_apply(plan, *, scope, remove_unmanaged)`
  returning a `job_id`, plus progress that a WebSocket subscription can stream in Phase 1D.

  Timeouts: 30 seconds per operation, based on Stage 0's measured 67 ms and 253 ms. Backoff:
  1 s then 2 s. Both as named constants with the Stage 0 numbers in a comment, so a future
  reader knows they were measured rather than guessed.

- [ ] **Step 4: Confirm tests pass. Step 5: Commit.**

```bash
git commit -m "feat(core): job runner with per-device serialization, retries and cancel"
```

---

### Task 5: Verify after apply, and snapshots

**Files:** modify `executor.py`; create `tests/test_executor_verify.py`

- [ ] **Step 1: Write the failing tests.** Cover at least:
  - After a successful apply, observed state is re-read and every applied link is marked
    `verified_at`.
  - A link that was written but does not appear on re-read is `unverified` and flips the rule
    to drift, rather than being reported as applied (E14). **Sent is not the same as done**,
    and this test is the one that keeps that honest.
  - Verification uses deep verify for listening nodes and records when deep verify could not
    confirm, rather than treating "could not confirm" as "confirmed". Phase 1B's
    `deep_verified` and `deep_verify_timed_out` carry this.
  - Sleeping nodes stay `pending_wakeup` and are not reported as failures.
  - **A snapshot of every device the plan touches is taken before any write.** Assert the
    snapshot exists and matches pre-apply state even when the apply then fails.
  - Snapshots are capped at 20 by the store.

- [ ] **Step 2: Run and confirm failure. Step 3: Implement. Step 4: Confirm. Step 5: Commit.**

```bash
git commit -m "feat(core): verify after apply and pre-apply snapshots"
```

---

### Task 6: The full loop against the fakes

**Files:** create `tests/test_apply_loop.py`

The first test in the project that exercises compile, plan, apply, verify and re-plan
together. It is the closest thing to an acceptance test that does not need hardware.

- [ ] **Step 1: Write the tests.**
  - Build a profile expressing PRD scenario **S2** (Bedroom Scene Controller main button
    controls Master Bedroom Lights, with on/off, hold-to-dim and level sync). Plan it, apply
    it, verify it, and assert the fake device now holds exactly the expected entries in
    groups 2, 3 and 4.
  - **Re-plan and assert the plan is empty.** Convergence and idempotence, end to end.
  - Scenario **S3**: three scene buttons to three different lights, with dimming. Assert the
    Pressed and Held group pairs, and that button 2 is left empty (Decision D15).
  - Disable a rule, re-plan, and assert its links are planned for removal and nothing else is.
  - Add an unmanaged entry directly to the fake device, re-plan, and assert it is reported
    and **not** planned for removal.
  - Then select it explicitly and assert it is removed.
  - Corrupt the fake mid-apply (raise on the second write) and assert: the first link is
    applied, the failure is reported, the snapshot still reflects pre-apply state, and a
    re-plan proposes exactly the remaining work.

- [ ] **Step 2: Run, fix what it finds, commit.**

```bash
git commit -m "test(core): the full compile, plan, apply, verify loop against fakes"
```

---

## Phase 1C exit criteria

- [x] A profile survives a restart, and a future schema version is refused rather than guessed
- [x] Ownership is by recorded fingerprint only, with a named test proving a look-alike link
      is not adopted
- [x] A backend going unavailable never looks like mass deletion
- [ ] Per-device serialization, bounded concurrency, bounded retries, working cancel
- [ ] Written-but-unverified is reported as drift, not as success
- [ ] A snapshot exists before any write, including when the apply fails
- [ ] Scenarios S2 and S3 pass end to end against the fakes, and a second plan is empty
- [ ] `./scripts/lint` and `./scripts/test` exit 0, CI green, coverage at or above 95%
- [ ] Anything unresolved is registered in `docs/open-items.md`

## What Phase 1C does not do

No entities, no services, no WebSocket API, no panel, and **no writes to Jayant's real
network**. Phase 1D exposes this to Home Assistant.
