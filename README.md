# Device Links for Home Assistant

Native Home Assistant UI for **Z-Wave associations, Zigbee bindings, and Matter bindings**,
with intent-level templates, saved profiles, verified apply, drift detection, device swap,
and an automation surface.

> Status: Stage 0 (validation). Not yet installable. See `docs/PRD.md` for the full spec and
> `docs/stage0-report.md` for what has been proven against real hardware.

## Why

Direct device-to-device control is the most reliable way to make lighting work when the hub
is slow or down, and the only way to get smooth hold-to-dim from a remote switch. Today that
means hand-driving the Z-Wave JS UI group dialog, the Zigbee2MQTT bind tab, and the Matter
dashboard one entry at a time, with no record of what you intended and no warning when a
device silently loses its links.

Device Links keeps the intent ("this switch with no load is a remote for that light,
including dimming"), compiles it to the exact groups, clusters, endpoints, and configuration
parameters each device needs, applies it, reads the devices back to prove the result, and
tells you when reality drifts.

## What it does

- **Read** every association, binding, and the device settings that govern them, in one place.
- **Express intent** with guided templates instead of group numbers.
- **Plan, apply, verify**: a confirmed diff, executed per device, then re-read from the
  hardware. Never "we sent it, so it must be fine".
- **Profiles**: save the whole design, export to YAML for git, re-apply after a rebuild.
- **Drift detection** when something changes outside the integration.
- **Device swap**: re-point every rule that referenced a failed switch, in one guided flow.
- **Automations**: rule switches, status sensors, events, and services.

## What keeps working when Home Assistant is off

Nearly all of it, and this is the point of the product. Every link Device Links writes lives
in the devices themselves: an association entry, a binding table row, a configuration
parameter. Your switch drives your light over the radio, and Home Assistant is not in the
path. Restart it, upgrade it, unplug it: the lights carry on.

There is exactly one exception, and it is opt-in twice over. Three intents contain a piece
that no radio can carry:

- passing on but not off (or off but not on), because an association carries both together;
- a scene button acting on its own device's load, because a node cannot be a member of its
  own association group;
- a scene controller's small-button LED following a light in another room, because there is
  no per-button address for an association to reach.

For those, Device Links can be the missing wire itself: it listens to what Home Assistant
already receives and issues the one command that completes the intent. These are called
**HA-executed legs**, they are off for the whole integration until you turn them on in the
options, each rule opts in separately, and every screen that shows one labels it
HA-executed. **When Home Assistant is down or restarting, only these stop working.** The
native part of the same rule keeps working, and the counters on each rule's status sensor
say how often a leg has fired and how often it has failed.

## Design principles

- Local only. No cloud, no telemetry, no outbound calls, no new listening ports.
- Reuses the existing `zwave_js`, `mqtt`, and `matter` clients. It does not own the radio.
- Admin only. Every write comes from a plan you confirmed or a service call you made.
- Lifeline associations, coordinator bindings, and Administer ACL entries are untouchable.
- It never removes a link it did not create unless you explicitly select it.

## Requirements

- Home Assistant 2026.8.0 or newer
- At least one of: `zwave_js`, Zigbee2MQTT over `mqtt`, or `matter`

## Installation

Not yet released. HACS custom-repository instructions land with the first Phase 1 release.

## Documentation

- `docs/PRD.md` - full product requirements, architecture, and delivery plan
- `docs/stage0-report.md` - validated facts, fixtures, and open assumptions
- `CLAUDE.md` - engineering rules, environment, and safety constraints

## License

MIT. See `LICENSE`.
