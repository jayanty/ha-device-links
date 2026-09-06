/**
 * The smallest payloads that exercise the views, in the shapes `serialize.py` produces.
 *
 * Hand written rather than captured, and deliberately awkward: one device that cannot be
 * read, one group that is full, one link nobody owns, one lifeline. A fixture where
 * everything is fine tests the half of each screen that never goes wrong.
 */

import type {
  DeviceDetail,
  DeviceRow,
  Emitter,
  Job,
  LinkRow,
  Plan,
  PlanDevice,
  ProfileRow,
  RuleData,
  RuleRow,
  UnmanagedLink,
} from "../src/types";

export const SOURCE = "zwave:home:36";
export const TARGET = "zwave:home:38";

export function deviceRow(overrides: Partial<DeviceRow> = {}): DeviceRow {
  return {
    identity: SOURCE,
    device_id: "ha36",
    name: "Bedroom Scene Controller",
    backend: "zwave",
    protocol_id: "home:36",
    available: true,
    links: 2,
    emitters: 2,
    is_long_range: false,
    // Z-Wave: a link lands on the node, not on an endpoint of it.
    receiving_endpoint: null,
    ...overrides,
  };
}

export function emitter(overrides: Partial<Emitter> = {}): Emitter {
  return {
    emitter_id: "button_2",
    label: "Button 2",
    endpoint: 0,
    group_ids: ["7", "8"],
    actions: { on_off: "7", level_hold: "8" },
    capacity: 5,
    supports_endpoint_targets: true,
    is_lifeline: false,
    grouping: "button",
    semantics: "unknown",
    ...overrides,
  };
}

export function lifelineEmitter(): Emitter {
  return emitter({
    emitter_id: "g1",
    label: "Lifeline",
    group_ids: ["1"],
    actions: {},
    is_lifeline: true,
    grouping: "lifeline",
    semantics: null,
  });
}

export function link(overrides: Partial<LinkRow> = {}): LinkRow {
  return {
    fingerprint: "zwave|zwave:home:36|0|7|zwave:home:38||on_off",
    backend: "zwave",
    feature: "on_off",
    emitter_id: "button_2",
    emitter_group: "7",
    source: {
      identity: SOURCE,
      protocol_id: "home:36",
      name: "Bedroom Scene Controller",
      device_id: "ha36",
      endpoint: 0,
    },
    target: {
      identity: TARGET,
      protocol_id: "home:38",
      name: "Bedside Light L",
      device_id: "ha38",
      endpoint: null,
    },
    rule_id: null,
    rule_name: null,
    is_system: false,
    managed_by: null,
    ...overrides,
  };
}

export function lifelineLink(): LinkRow {
  return link({
    fingerprint: "zwave|zwave:home:36|0|1|zwave:home:1||status_report",
    feature: "status_report",
    emitter_id: "g1",
    emitter_group: "1",
    is_system: true,
    target: {
      identity: "zwave:home:1",
      protocol_id: "home:1",
      name: "Z-Wave Controller",
      device_id: null,
      endpoint: null,
    },
  });
}

export function deviceDetail(overrides: Partial<DeviceDetail> = {}): DeviceDetail {
  return {
    device: deviceRow(),
    emitters: [lifelineEmitter(), emitter()],
    links: [lifelineLink(), link()],
    settings: { mirror_hub_commands: "off" },
    deep_verified: false,
    ...overrides,
  };
}

export function ruleData(overrides: Partial<RuleData> = {}): RuleData {
  return {
    id: "rule-1",
    name: "Goodnight, everything off",
    template: "off_all",
    backend: "zwave",
    enabled: true,
    direction: "one_way",
    mirror_source: "off",
    features: ["on_off"],
    source: { device: SOURCE, endpoint: 0, emitter_id: "button_2" },
    targets: [{ device: TARGET, endpoint: null }],
    ...overrides,
  };
}

export function ruleRow(overrides: Partial<RuleRow> = {}): RuleRow {
  return { rule: ruleData(), state: "pending", links_total: 3, links_in_sync: 1, ...overrides };
}

export function profileRow(overrides: Partial<ProfileRow> = {}): ProfileRow {
  return { id: "p1", name: "House", rules: 1, enabled_rules: 1, is_active: true, ...overrides };
}

export function unmanagedLink(overrides: Partial<UnmanagedLink> = {}): UnmanagedLink {
  return { ...link(), ignored: false, ...overrides };
}

function planDevice(overrides: Partial<PlanDevice> = {}): PlanDevice {
  return {
    identity: SOURCE,
    device_id: "ha36",
    name: "Bedroom Scene Controller",
    backend: "zwave",
    available: true,
    add: [],
    remove: [],
    set_param: [],
    blocked: [],
    pending: [],
    unmanaged: [],
    ...overrides,
  };
}

/** A plan with something in every bucket, which is what the dialog has to render. */
export function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    token: "token-1",
    is_empty: false,
    unchanged_count: 4,
    counts: { add: 1, remove: 0, set_param: 1, blocked: 1, pending: 1, unmanaged: 2 },
    devices: [
      planDevice({
        add: [
          {
            op: "add",
            device_identity: SOURCE,
            link: link({ rule_id: "rule-1", rule_name: "Goodnight, everything off" }),
            setting: null,
            reason: null,
          },
        ],
        set_param: [
          {
            op: "set_param",
            device_identity: SOURCE,
            link: null,
            setting: {
              device_identity: SOURCE,
              capability: "mirror_hub_commands",
              parameter: 35,
              bitmask: 4,
              value: 0,
            },
            reason: null,
          },
        ],
        blocked: [
          {
            op: "blocked",
            device_identity: SOURCE,
            link: link(),
            setting: null,
            reason: {
              translation_key: "group_full",
              placeholders: {
                group: "7",
                device: "Bedroom Scene Controller",
                used: "5",
                capacity: "5",
                target: "Bedside Light L",
              },
            },
          },
        ],
        pending: [
          {
            op: "pending",
            device_identity: SOURCE,
            link: link(),
            setting: null,
            reason: null,
          },
        ],
        // One link a person made by hand, and one the planner should never have put here.
        // The second is a belt-and-braces case: the UI must not offer to remove it.
        unmanaged: [
          unmanagedLink(),
          unmanagedLink({ fingerprint: "system-fingerprint", is_system: true }),
        ],
      }),
      planDevice({
        identity: "zwave:home:29",
        device_id: "ha29",
        name: "Mud Room Scene",
        available: false,
      }),
    ],
    ...overrides,
  };
}

export function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    created_at: new Date().toISOString(),
    scope: "Goodnight, everything off",
    status: "partial",
    total: 2,
    results: [
      { fingerprint: link().fingerprint, status: "applied", reason: null },
      {
        fingerprint: "zwave|zwave:home:36|0|7|zwave:home:21||on_off",
        status: "failed",
        reason: "ZWaveError: Timeout while waiting for an ACK",
      },
    ],
    ...overrides,
  };
}
