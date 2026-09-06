# Phase 1E: the sidebar panel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Home Assistant sidebar panel that lets a user read what is configured on their devices, express intent with templates, and apply it with a plan they confirmed.

**Architecture:** A Lit + TypeScript custom element bundled by vite into a single ES module, served from the integration directory and registered with `panel_custom`. It talks to the Phase 1D WebSocket API and to nothing else. It uses Home Assistant's own web components so it inherits theme, dark mode, typography and dialog behaviour.

**Tech Stack:** TypeScript, Lit 3, vite, vitest, Home Assistant frontend components.

---

## What Stage 0 already settled

Item P1 scanned the installed frontend (`home-assistant-frontend` 20260729.7 on HA 2026.8.3). Every component PRD Section 7.1 names is present **except `ha-tabs`**, and `ha-tab-group` is the one that exists. Use `ha-tab-group`. Do not write runtime detection between the two: the answer is known for the version this targets, and a detection branch nobody can trigger is untested code pretending to be robustness.

`ha-fab` and `ha-textfield` are also absent. Do not reach for them.

The runtime half of P1 (that each element actually resolves through `customElements.whenDefined` after the card-helpers force-load) is open item **R1** and needs a running Home Assistant. Task 8 closes it.

## Ground rules

Read `CLAUDE.md`, `docs/stage0-report.md` and `docs/open-items.md` first.

- **The panel calls the WebSocket API and nothing else.** No REST, no direct state access for
  anything the API covers. If the panel needs something the API does not expose, that is a
  Phase 1D gap to fix there, not a workaround here.
- **No CDN imports.** Everything is bundled. The panel must work on an instance with no
  internet access, which is the whole point of a local-first integration.
- **The built bundle is committed**, and CI asserts it matches a fresh build (PRD Section 16).
- **Never restart Home Assistant.** Deploy, notify, stop.
- Never use the em dash, in code, comments or UI copy.
- Conventional commits ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Register anything unresolved in `docs/open-items.md`**, continuing from T28.

## The rule that shapes every screen

**The panel never writes to a device without showing a plan the user confirmed.** Decision
D18: the plan dialog is always shown, and "Save and apply" opens it pre-confirmed rather
than skipping it. There is no path in this UI from a click to a radio write without the user
seeing what will change, per device, with blocked items and their reasons.

That is not a UI preference. It is the difference between a tool a person trusts with their
house and one they do not.

---

## File structure

| Path | Responsibility |
|---|---|
| `frontend/package.json`, `vite.config.ts`, `tsconfig.json` | Toolchain. |
| `frontend/src/panel.ts` | The custom element, routing between tabs. |
| `frontend/src/api.ts` | Typed wrappers over the WebSocket commands. |
| `frontend/src/ha-components.ts` | Force-loading HA components, with graceful degradation. |
| `frontend/src/views/*.ts` | Overview, Rules, Devices, Profiles, Activity. |
| `frontend/src/dialogs/*.ts` | Rule editor stepper, plan and apply dialog. |
| `frontend/src/types.ts` | Types mirroring the API payloads. |
| `frontend/test/*.test.ts` | vitest unit tests against a mock hass. |
| `custom_components/device_links/frontend/` | The committed bundle. |
| `custom_components/device_links/panel.py` | Static paths and panel registration. |

---

### Task 1: Toolchain and the committed bundle

- [ ] Set up `frontend/` with vite building `src/panel.ts` to a single ES module at
      `custom_components/device_links/frontend/device-links-panel.js`, target `es2022`,
      no code splitting, no external CDN.
- [ ] `npm run build`, `npm run test`, `npm run lint` (eslint + prettier or `oxlint`, your
      choice, but pick one and wire it into CI).
- [ ] Add a CI job that runs the frontend build and tests, and **fails if the committed
      bundle differs from a fresh build**. Rebuild determinism matters here: if the bundle
      is not reproducible, this check becomes noise everyone learns to force past. If vite
      output is not byte-stable, compare a normalized hash and say what you normalized.
- [ ] Commit: `build(frontend): vite toolchain and reproducible bundle check`

### Task 2: Panel registration

- [ ] `panel.py` registering static paths with
      `hass.http.async_register_static_paths([StaticPathConfig(url, path, cache_headers)])`
      and the panel with `panel_custom.async_register_panel(..., require_admin=True,
      embed_iframe=False)`.
- [ ] The static URL carries the integration version (`/device_links_static/<version>/...`)
      so a browser cannot serve a stale bundle after an update.
- [ ] `cache_headers=False` in a dev deployment so a hard refresh picks up a frontend-only
      change without a restart, which is what the deploy tool's `browser_reload` flag is for.
- [ ] Registration happens in `async_setup_entry` and is removed on unload. Test that a
      reload does not leave two panels or a dead static path.
- [ ] **Test the version handshake**: the panel reports the bundle version it was built
      from, and the backend exposes its own. A mismatch after an update without a reload
      shows a banner asking the user to refresh (E33), rather than failing in a way that
      looks like a bug in their configuration.
- [ ] Commit: `feat(panel): register the admin sidebar panel and static assets`

### Task 3: The API client and types

- [ ] `api.ts` wrapping every command the panel uses, typed against the Phase 1D payloads.
      The plan shape is documented in that phase's work; mirror it exactly rather than
      reshaping it here.
- [ ] Errors carry `code`, `message` and `translation_key`. Surface `message`; never show a
      raw exception or a bare key.
- [ ] `jobs/subscribe` wired as a subscription with teardown on disconnect. **A subscription
      that outlives its view leaks and fires against a dead component**, which in a
      long-lived panel session is a real memory and correctness problem, not a tidiness one.
- [ ] vitest tests against a mock `hass` object asserting each wrapper sends the right
      command and unwraps the right field.
- [ ] Commit: `feat(panel): typed WebSocket client`

### Task 4: The shell

- [ ] `ha-top-app-bar-fixed` with `ha-menu-button` (which gives the hamburger on narrow
      screens for free), `ha-tab-group` for the five tabs.
- [ ] `ha-components.ts` force-loads HA components with the card-helpers technique
      (`window.loadCardHelpers()`, create a throwaway `entities` card, then
      `customElements.whenDefined(...)`), and **degrades gracefully** when one is missing:
      fall back to a plain element rather than rendering nothing. A panel that renders
      nothing on an HA version we did not anticipate is worse than one that looks plain.
- [ ] Two-pane on wide screens, stacked with full-screen dialogs on narrow.
- [ ] Every action reachable by keyboard; every icon-only button has a label or tooltip.
- [ ] Commit: `feat(panel): app shell with tabs and HA component loading`

### Task 5: Overview and Activity

- [ ] **Overview**: active profile name; chips for in sync, drift, pending, blocked; last
      verified time; Verify and Plan-and-apply buttons; a "Needs attention" list (drift,
      pending wake-ups with the wake instruction, blocked rules) where each row links to the
      fix; recent activity (last 5 jobs).
- [ ] **Activity**: job list with scope, timing and result counts; job detail with per-link
      rows and the raw backend error under an expander. That raw text is what makes a bug
      report useful, and it stays under the expander so it never becomes the primary message.
- [ ] Commit: `feat(panel): overview and activity views`

### Task 6: Devices

- [ ] Device list with name, area, backend, status and counts of managed and unmanaged links.
- [ ] Device detail: **Outgoing** (each emitter with its label, capacity, and entries showing
      target names and either the owning rule or "Unmanaged" with Adopt, Ignore and Remove)
      and **Incoming** (who controls this device).
- [ ] Association-relevant settings with current and desired values.
- [ ] **A lifeline entry is shown as a system link and offers no Remove control at all.**
      Not disabled, not present. The backend refuses it three ways already; the UI should not
      invite the click.
- [ ] Refresh and Deep verify buttons. Deep verify reports honestly when it could not
      confirm, using the three states Phase 1B produces, rather than showing a green tick.
- [ ] Commit: `feat(panel): device view with observed state and unmanaged link actions`

### Task 7: Rules, the editor, and the plan dialog

The heart of the product.

- [ ] **Rules tab**: `ha-data-table` with rule, source (device plus emitter label), targets as
      chips, feature icons, backend, status chip and an enabled toggle. Search, filter by
      backend, area and status, group by source device or area. Empty state offers the
      template cards.
- [ ] **Rule editor**, a stepper: template cards; source device and then emitter picker
      showing labels, capability icons and capacity ("2 of 5 used"); targets; behaviour
      (feature toggles greyed with a reason when unsupported, direction, mirroring showing
      the exact parameter it will write, status feedback); review showing the compiled links
      and settings with warnings and errors from `rules/validate`.
- [ ] **The Stage 0 Z7 warning must reach the user.** An Off-all rule on a Zooz scene button
      compiles with `button_semantics_unknown`. Show it in the review step as a warning the
      user reads before saving, not buried in a log. Nobody has observed whether those
      buttons send a fixed OFF or toggle, and if they toggle the button turns the lights back
      on every second press.
- [ ] **Plan and apply dialog**, used everywhere apply happens: grouped by device, with Add,
      Remove, Settings, Blocked (with reasons), Pending (with wake instructions) and
      Unmanaged (with unticked "also remove" checkboxes). A summary line and a confirm button
      labelled with the count, for example "Apply 14 changes". Progress replaces the list
      during the job; the result stays until dismissed.
- [ ] **The unmanaged checkboxes start unticked and a "select all" does not include system
      links.** This is Decision D9 rendered as a UI, and it is the last place a user can be
      protected from deleting something they made by hand.
- [ ] Commit: `feat(panel): rules table, template editor and the plan dialog`

### Task 8: See it actually run

Everything above is tested against a mock hass. This task is about looking at it.

- [ ] Build a small static harness (`frontend/harness/index.html`) that mounts the panel
      against a mock `hass` whose WebSocket responses come from fixtures derived from
      `tests/fixtures/`. Serve it locally.
- [ ] Open it in a browser, and **look at every view and both dialogs, in light and dark
      theme, at desktop and narrow widths**. Fix what looks wrong. Screenshot each and save
      them under `docs/panel/`.
- [ ] This is not a substitute for R1. The harness proves layout and interaction; it does not
      prove the HA components resolve inside a real Home Assistant. Closing **R1** needs a
      deploy and Jayant's restart, and Task 8 ends by asking for that rather than assuming it.
- [ ] Commit: `test(panel): static harness and reviewed screenshots of every view`

---

## Phase 1E exit criteria

- [ ] The bundle is committed and CI proves it matches a fresh build
- [ ] The panel registers, unregisters cleanly on unload, and a version mismatch shows a
      banner rather than breaking
- [ ] No path in the UI reaches a device write without a confirmed plan
- [ ] Lifelines offer no Remove control; unmanaged checkboxes start unticked
- [ ] The Z7 warning is visible in the rule editor before saving
- [ ] Every view has been looked at in both themes and at both widths
- [ ] `./scripts/lint`, `./scripts/test`, `npm run lint`, `npm run test` and `npm run build`
      all pass, CI green
- [ ] Deployed, with a notification asking Jayant to restart so R1 can be closed

## What Phase 1E does not do

No Zigbee or Matter views beyond what the backend-neutral components render, no graph view,
no Lovelace card, no room matrix wizard. Those are Phase 2 and later.
