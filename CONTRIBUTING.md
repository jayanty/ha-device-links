# Contributing to Device Links

Thank you for wanting to help. This document covers the two things a contributor most often
comes here to do: add a device to the curated profile database, and get a change through the
gates.

Everything else about how this project is built is in `docs/PRD.md` (the specification),
`docs/stage0-report.md` (what has been proven against real hardware), and `CLAUDE.md` (the
engineering rules).

One style rule applies to everything, code and prose alike: **no em dash characters**. Use a
plain hyphen or a colon. A test enforces it.

---

## Contributing a device profile

### What the profile database is for, and what it is not

Device Links works on every device without a profile entry. Links are derived from what the
device itself reports: its association groups on Z-Wave, its endpoint clusters on Zigbee and
Matter. A profile entry does two things that derivation cannot:

1. **It puts a control back together and gives it a name.** An Inovelli paddle reports three
   Z-Wave association groups with three different profiles, so the generic derivation offers
   three emitters called "Group 2", "Group 3" and "Group 4". A curated entry says those are
   one paddle, and calls it "Paddle".
2. **It says which configuration parameter carries which setting** (Z-Wave and Zigbee only),
   so that a rule can ask for "mirror hub commands" rather than for "parameter 59 bit 2".

So an entry is worth contributing when a model's controls are hard to make sense of from
what it reports, or when it has a setting a rule should be able to ask for by name.

**A curated entry overrides the device.** A wrong group number writes an association to the
wrong place with complete confidence and no error, which is why loading is strict, why every
field is validated, and why the section below asks you to capture rather than to look up.

### Where the files are

```
custom_components/device_links/profiles_db/
  schema.json          the shape, documented; your editor can validate against it
  inovelli.json        Inovelli, Z-Wave
  inovelli_blue.json   Inovelli Blue series, Zigbee
  inovelli_white.json  Inovelli White series, Matter
  zooz.json            Zooz, Z-Wave
```

One file per manufacturer or product line. A file may hold entries for several protocols;
which shape an entry has is decided by its `backend` key, which is `zwave` when it is absent
because every entry written before Phase 2 is one.

`schema.json` is documentation and an editor aid. It is **not** executed at runtime: the
integration ships no JSON Schema validator and `profile_db.py` must not import one, so
`profile_db.py` enforces the same rules with hand written checks. The two cannot drift apart
silently, because `tests/test_profile_db.py` compares this document's key sets and enums
against the constants `profile_db.py` validates with.

### Capture first, write second

**Please do not write an entry from a manual.** Every group number, endpoint and cluster in
this database came off a real device, and the test suite cross-checks each one against a
capture committed in `tests/fixtures/`. An entry nobody could check against hardware is
exactly the entry not to ship: `inovelli_blue.json` deliberately omits the VZM35-SN for that
reason, and `inovelli_white.json` omits two devices the PRD expected to be Matter binding
sources and which turned out not to be.

What to capture, by protocol:

- **Z-Wave.** In Z-Wave JS UI, the node's association groups: for each group its number,
  label, `maxNodes`, `isLifeline`, whether it is multi-channel, and the command classes it
  issues. `tools/probe_zwave_ws.js` does this from the add-on, and
  `tests/fixtures/z2_associations.json` is what it produced here.
- **Zigbee2MQTT.** The device's entry in the retained `bridge/devices` topic: its
  `definition.vendor` and `definition.model`, and for each endpoint its `clusters.input` and
  `clusters.output`. `tools/probe_zigbee.py` captures the whole topic;
  `tests/fixtures/g1_bridge.json` is one such capture.
- **Matter.** For each endpoint, `Descriptor.ClientList` (attribute `<endpoint>/29/2`) and
  `Descriptor.ServerList` (`<endpoint>/29/1`), plus the node's vendor and product names.
  `tools/probe_matter.py` captures all of it; `tests/fixtures/m1_matter.json` is one such
  capture. Note that an endpoint can only be a control if it **also** serves the Binding
  cluster (30) in its server list.

If you cannot capture, open a device profile request issue instead (there is a template).
Somebody with the hardware can pick it up, and the issue is a better record than a guess.

### What each shape looks like

**Z-Wave.** `actions` maps a feature to the **association group number** that carries it.

```json
{
  "model": "ZEN32",
  "manufacturer": "Zooz",
  "fingerprints": [{ "manufacturer_id": 634, "product_type": 40960, "product_id": 8449 }],
  "emitters": [
    {
      "emitter_id": "button_1",
      "label": "Button 1",
      "kind": "button",
      "actions": { "on_off": "2", "level_set": "3" }
    }
  ],
  "settings": {
    "mirror_hub_commands": { "parameter": 12, "bitmask": 2, "values": { "off": 0, "on": 1 } }
  }
}
```

**Zigbee.** `backend` is required, an emitter names the **endpoint** it drives from, and
`actions` maps a feature to a **cluster name** exactly as Zigbee2MQTT spells it. A settings
adapter names an MQTT property, and its `values` and `payloads` must name the same choices:
`values` is the integer the rest of the system carries and `payloads` is the label the bridge
expects.

```json
{
  "backend": "zigbee2mqtt",
  "model": "VZM31-SN",
  "manufacturer": "Inovelli",
  "fingerprints": [{ "vendor": "Inovelli", "model": "VZM31-SN" }],
  "emitters": [
    {
      "emitter_id": "paddle",
      "label": "Paddle",
      "kind": "paddle",
      "endpoint": 2,
      "actions": { "on_off": "genOnOff", "level_set": "genLevelCtrl" }
    }
  ]
}
```

**Matter.** As Zigbee, with **cluster ids** rather than names, and no settings section at
all: a Matter device is configured through the attributes of its own clusters rather than
through a numbered parameter list, and Device Links writes none of them.

```json
{
  "backend": "matter",
  "model": "VTM31-SN",
  "manufacturer": "Inovelli",
  "fingerprints": [{ "vendor": "Inovelli", "product": "VTM31-SN" }],
  "emitters": [
    {
      "emitter_id": "paddle",
      "label": "Paddle",
      "kind": "paddle",
      "endpoint": 2,
      "actions": { "on_off": 6, "level_set": 8, "level_hold": 8 }
    }
  ]
}
```

### The fields, and the traps in them

| Field | What to put in it |
|---|---|
| `fingerprints` | Every exact model identity this entry describes. No wildcards and no ranges: an entry overrides what the hardware says about itself, and a wildcard spreads one mistake across a catalogue. Firmware is deliberately not part of it, so one entry covers every firmware of a model. |
| `emitter_id` | A stable id, unique within the entry, **never changed once shipped**: a saved rule stores it. If the generic derivation already produces a control covering the same endpoint and clusters, your entry's control keeps the derived id automatically, so adding an entry never renames a control out from under existing rules. |
| `label` | What a person sees. Say what is written on the device. |
| `kind` | One of `paddle`, `button`, `config_button`, `gesture`. Used for icons and wording. |
| `actions` | One or more features, each pointing at the group, cluster name or cluster id that carries it. Two features may point at one cluster, because `genLevelCtrl` and Matter's LevelControl really do carry both setting a level and holding to dim: there is no way to bind one without the other. |
| `semantics` | Set to `"unknown"` when what a control sends on a press is **not established as a fixed OFF**. That makes the Off-all template warn rather than compile silently onto it. Leave it out only when you have watched the device and know. |
| `scene_id`, `indicator_id` | Z-Wave only, and only for a control that reports a Central Scene number or has an addressable indicator. They are what an HA-executed leg fires on and writes to, so a guessed number is a leg that fires on somebody else's button. Leave them out unless you have observed them. |
| `wake_instruction` | Battery devices only, and only a sequence you have actually performed. It is shown to somebody whose apply is waiting. |
| `notes` | Why the entry says what it says: which capture the numbers came from, and what in it is still unverified. JSON has no comments, so this is where the reasoning goes. Read the existing files: this field is doing real work in all of them. |

Two things the loader will refuse outright, so it is worth knowing before you run the tests:

- **Two entries claiming one model.** At most one entry may match a device, or the lookup
  depends on iteration order. The error names both files.
- **A feature mapped onto the Z-Wave lifeline (group 1).** It is never ours to write.

### Running the checks

```bash
scripts/setup                       # once
scripts/lint                        # ruff, format, mypy --strict
scripts/test                        # the whole suite, with the coverage gate
.venv/bin/python -m pytest tests/test_profile_db.py -q   # while you iterate
```

`tests/test_profile_db.py` is where a profile mistake surfaces. It checks that every entry
loads, that every group, endpoint and cluster it names exists on a real device in the
committed captures, that every feature it claims can really be carried by what it points at,
and that the entry survives resolution against each matching device without contradicting it.

If your model is not in a committed capture, those cross-checks cannot run for it. Say so in
your pull request, and put the capture in the PR body or attach it to the issue: a reviewer
with different hardware has no other way to check your work.

---

## Contributing a change

### Gates

Everything below has to pass before a change lands. CI runs all of it.

```bash
scripts/lint                                    # ruff check, ruff format --check, mypy --strict
scripts/test                                    # pytest, coverage >= 95%
scripts/test --slow-executor                    # the same suite with executor hops delayed
cd frontend && npm run lint && npm run test && npm run build
```

`--slow-executor` is not optional politeness. It delays every executor hop so that a test
which really asserts "the executor won a race" fails on your laptop instead of on a two vCPU
runner. If you touched anything that does work in the background, run it.

**The frontend bundle is committed and must byte-match a fresh build.** If you changed
anything under `frontend/`, or added a message to `strings.json` (the panel inlines them for
its English fallback), run the build and commit
`custom_components/device_links/frontend/device-links-panel.js` with your change.

### Testing rules that are not obvious

- **Pure modules import no Home Assistant.** `models.py`, `compiler.py`, `planner.py`,
  `yaml_io.py`, `profile_db.py` and every `backends/*_protocol.py`. A test enforces it. Put
  interpretation in the pure module and I/O in the adapter: a branch in an adapter that does
  not touch its client is a branch in the wrong place.
- **Every bug fix carries a regression test** named `test_issue_<n>_<slug>` that fails before
  the fix and passes after.
- **Assert across a boundary, not only about it.** Where one layer builds a payload another
  layer validates, send a payload the producer actually constructs through the real consumer.
  A test that checks only that the two agree on types passes while the producer sends a value
  the consumer refuses; the panel refused every rule it sent for two phases that way.
- **Block on background tasks when you assert on them.** `async_block_till_done()` does not
  wait for a config entry's background tasks unless you pass `wait_background_tasks=True`.

### Strings

Every user-facing string is a translation key. A message needs an entry in both
`custom_components/device_links/strings.json` and
`custom_components/device_links/translations/en.json`, which must be identical, and a
placeholder must never be wrapped in single quotes (hassfest refuses it).
`tests/test_translations.py` reads the keys out of the source, so a message you produce and
do not write, or write and do not produce, fails there.

### Commits

Conventional commits, scoped by area where it helps: `feat(matter):`, `fix(panel):`,
`test:`, `docs:`, `chore:`. Explain why in the body, not just what.

### What to ask about first

Open an issue before starting on any of these, because the answer shapes the work:

- a storage schema change that cannot be migrated automatically,
- a change to what counts as a system link (a Z-Wave lifeline, a Zigbee coordinator binding,
  a Matter Access Control entry with Administer privilege): those are protected in code, and
  every path that could touch one has a test proving it refuses,
- a new Python or frontend runtime dependency,
- anything that would write to a device outside a confirmed plan.
