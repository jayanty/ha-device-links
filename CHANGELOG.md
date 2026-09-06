# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Repository skeleton, CI, and `CLAUDE.md` (Stage 0 items R1 and D1).
- Zigbee2MQTT backend (Phase 2A): pure protocol parsing driven by the Stage 0 G1
  capture, an adapter that reads the retained bridge topics and writes bindings,
  managed `dl_` groups for one-to-many rules, and curated profile entries for the
  Inovelli Blue VZM31-SN and VZM32-SN. The write path is modelled from the
  Zigbee2MQTT documentation and has never been performed against hardware
  (assumption A2, issue #6). The backend is built at config entry setup as of
  Phase 2A's last commit, over Home Assistant's own `mqtt` integration.
- Device swap (Phase 2B, FR-S1 to FR-S3): choose the device that has gone and the
  one that replaced it, map each control across (automatically when the ids or the
  features settle it, by asking when they do not), and see every rule before and
  after, everything that would be lost, and the whole plan, before anything is
  written. A device that leaves the network with a same-model replacement waiting,
  or that comes back answering as a different model, raises a Repairs issue
  offering the flow. Reachable over the WebSocket API; the panel wizard is still
  to come.
- Hybrid legs (Phase 2C, FR-H1 to FR-H3, Decision D3): the three intents no radio
  can carry, executed by Home Assistant and labelled HA-executed on every screen
  that shows one. Off for the whole integration until the option is turned on, and
  opted into per rule on top of that. On-only or off-only propagation and a scene
  button acting on its own device's load react to a Central Scene press; a scene
  button's LED following a light in another room writes Indicator CC, which Stage 0
  item Z8 measured at the same latency as a configuration parameter without the
  flash write. Legs are registered from the active profile and die with their rule,
  their profile and their config entry. Firing counts and failures are on each
  rule's status sensor and aggregated on the Health sensor, and a failure rate above
  a quarter raises a Repairs issue. When Home Assistant is down, only the legs stop:
  the native half of the same rule keeps working.
- Loop analysis (Phase 2C, FR-R7, E30): the active profile's control links plus
  what each device does with what it receives, as a graph, with every cycle whose
  nodes all relay reported before the rule that closes it is saved. A two-way pair
  is a cycle and is not a loop, which is why the graph is narrowed to the devices
  that forward before a cycle is looked for. A warning and never a refusal: the
  analysis knows what the links say rather than what the devices do. Shown in the
  rule editor's review step with the rule being edited folded in, and on the Rules
  tab for the profile as it stands.
- Profile diff (Phase 2C, FR-P4): compare two profiles, or a profile against a
  snapshot, rule by rule and link by link. Both levels, because they answer
  different questions: a renamed rule is a change to a profile and no change at
  all to a house, and a device swapped underneath an untouched rule is the
  reverse. A snapshot has no rules in it and covers only the devices it was taken
  of, and the comparison says so rather than letting "nothing differs" read as a
  claim about the whole network. Reachable from the Profiles tab for two profiles
  and beside Restore in Activity for a snapshot. It writes nothing and offers no
  button that does.
- Snapshot rollback (Phase 2B, FR-P3): put a snapshot's devices back the way they
  were, as a plan confirmed in the same dialog every other write goes through.
  Removals that an enabled rule will write again are named before the plan is
  applied, because a rollback restores devices and leaves the rules alone.
- The YAML mirror (Phase 2B, FR-P2, Decision D8): off by default, on it writes
  every profile to `<config>/device_links/profiles/` on change, so a configuration
  directory kept in version control shows the rules changing in a diff. A copy in
  one direction: files are never read back, and only files this integration wrote
  are ever changed or deleted.

### Fixed
- A Zigbee device could not be opened, refreshed or chosen as a rule's source
  anywhere in the panel, because only Z-Wave handles resolved to a Home Assistant
  device id. Every backend now names its own devices, so a Zigbee rule can be
  authored and its switch lands on that device's own page.
