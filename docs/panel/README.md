# What the panel looks like

Screenshots from `frontend/harness/`, which mounts the real panel against a mock `hass`
whose answers come from the Stage 0 captures. Run it with `npm run harness` in `frontend/`
and open <http://localhost:4321/harness/index.html>. The toolbar at the top of that page
switches theme, width, the version banner and whether Home Assistant's own elements are
pretended to exist.

**These prove layout and interaction, not that the panel works inside Home Assistant.** The
harness defines its own stand-ins for `ha-top-app-bar-fixed`, `ha-tab-group`, `ha-icon` and
`ha-alert`, so it cannot answer the question open item **R1** asks, which is whether Home
Assistant's lazily defined elements resolve inside a custom panel at all. Closing R1 needs a
deploy and a restart.

The fixture network is deliberately not a tidy one: one device is not answering, one
association group is full, one entry belongs to no rule, one is a lifeline, and the rules
are one of each state.

| File | What it shows |
|---|---|
| `01-overview-light.png` | Overview: active profile, state chips, Needs attention, recent jobs |
| `02-overview-dark.png` | The same screen on the dark theme |
| `03-rules-light.png` | The rules table with source, targets, features, status and the enabled switch |
| `04-rule-editor-review-z7-warning.png` | The review step, with the Stage 0 Z7 warning above the save buttons |
| `05-plan-dialog-light.png` | The plan dialog: add, settings, blocked with its reason, pending, and an unticked unmanaged box |
| `06-plan-dialog-applying.png` | An apply in flight. There is no close control while it writes |
| `07-plan-dialog-result.png` | The result, which stays until it is dismissed |
| `08-devices-light.png` | A device: its controls with capacity, its entries, the lifeline with no Remove control |
| `09-devices-dark.png` | The same device on the dark theme |
| `10-activity-light.png` | Jobs, per-link outcomes, the backend's own error under an expander, and the snapshots |
| `11-profiles-light.png` | Profiles, where activating opens a plan rather than writing |
| `12-rules-narrow.png` | The rules table at phone width, where it becomes a list of cards |
| `13-plan-dialog-narrow.png` | The plan dialog full screen on a phone |
| `14-rule-editor-narrow.png` | The review step on a phone, Z7 warning included |
| `15-rule-editor-error.png` | A rule the compiler refuses: Save anyway is offered, Save and apply is not |
| `16-fallback-and-version-banner.png` | Every Home Assistant element missing, plus the E33 version banner |
