/**
 * The network the harness pretends to be, derived from the Stage 0 captures.
 *
 * Every device name, node id, association group number and group label here comes from
 * `tests/fixtures/z2_associations.json` and `tests/fixtures/z7_button_semantics.json`, and
 * the emitter ids and labels come from `custom_components/device_links/profiles_db/zooz.json`
 * and `inovelli.json`. That matters: a harness built out of "Device 1" and "Group A" will
 * happily show a layout that falls apart the moment a real label like
 * "Main Button - Start / Stop (MultiLevel)" arrives, and the point of looking at this is to
 * find exactly that kind of thing.
 *
 * It is deliberately not a tidy network either. One device is unavailable, one group is
 * full, one entry is unmanaged, one is a lifeline, one rule is blocked and one is in drift,
 * because a screen that has only ever been seen in its happy state has not been seen.
 */

import type {
  DeviceDetail,
  DeviceRow,
  Emitter,
  Job,
  LinkRow,
  ProfileRow,
  RuleRow,
  Snapshot,
} from "../src/types";

const HOME = "3538613642";

/** Home Assistant device registry ids, which is how the API names a device. */
export const DEVICE_IDS: Record<string, string> = {
  n21: "ha21",
  n29: "ha29",
  n30: "ha30",
  n35: "ha35",
  n36: "ha36",
  n37: "ha37",
  n38: "ha38",
  n39: "ha39",
  n40: "ha40",
  n42: "ha42",
};

function identity(node: number): string {
  return `zwave:${HOME}:${node}`;
}

function device(node: number, name: string, options: Partial<DeviceRow> = {}): DeviceRow {
  return {
    identity: identity(node),
    device_id: DEVICE_IDS[`n${node}`] ?? null,
    name,
    backend: "zwave",
    protocol_id: `${HOME}:${node}`,
    available: true,
    links: 0,
    emitters: 0,
    is_long_range: false,
    // Z-Wave: an association names a node, and an endpoint only when the user asked for
    // one. Every device on this network is single-endpoint, so this is null throughout.
    receiving_endpoint: null,
    ...options,
  };
}

/** The Z-Wave lifeline, which every device has and no rule may ever touch. */
function lifeline(): Emitter {
  return {
    emitter_id: "g1",
    label: "Lifeline",
    endpoint: 0,
    group_ids: ["1"],
    actions: {},
    capacity: 10,
    supports_endpoint_targets: true,
    is_lifeline: true,
    grouping: "lifeline",
    semantics: null,
    scene_id: null,
    indicator_id: null,
  };
}

/** The ZEN35's controls, exactly as `profiles_db/zooz.json` describes them. */
function zen35Emitters(): Emitter[] {
  return [
    lifeline(),
    {
      emitter_id: "main_button",
      label: "Main Button",
      endpoint: 0,
      group_ids: ["2", "3", "4"],
      actions: { on_off: "2", level_set: "3", level_hold: "4" },
      capacity: 5,
      supports_endpoint_targets: true,
      is_lifeline: false,
      grouping: "paddle",
      semantics: null,
      scene_id: null,
      indicator_id: null,
    },
    ...[1, 2, 3, 4].map((button) => ({
      emitter_id: `button_${button}`,
      label: `Button ${button}`,
      endpoint: 0,
      group_ids: [String(3 + button * 2), String(4 + button * 2)],
      actions: { on_off: String(3 + button * 2), level_hold: String(4 + button * 2) },
      capacity: 5,
      supports_endpoint_targets: true,
      is_lifeline: false,
      grouping: "button",
      // Stage 0 item Z7: nobody has observed what a small button sends on a press.
      semantics: "unknown",
      // What `profiles_db/zooz.json` says, which is what makes the HA-executed opt-ins
      // offerable on these four controls and on nothing else on this device.
      scene_id: button,
      indicator_id: 66 + button,
    })),
  ];
}

/** An Inovelli VZW32-SN dimmer's controls. */
function dimmerEmitters(): Emitter[] {
  return [
    lifeline(),
    {
      emitter_id: "paddle",
      label: "Paddle",
      endpoint: 0,
      group_ids: ["2", "3", "4"],
      actions: { on_off: "2", level_set: "3", level_hold: "4" },
      capacity: 10,
      supports_endpoint_targets: true,
      is_lifeline: false,
      grouping: "paddle",
      semantics: null,
      scene_id: null,
      indicator_id: null,
    },
    {
      emitter_id: "config_button",
      label: "Config Button",
      endpoint: 0,
      group_ids: ["7"],
      actions: { on_off: "7" },
      capacity: 10,
      supports_endpoint_targets: true,
      is_lifeline: false,
      grouping: "button",
      semantics: null,
      scene_id: null,
      indicator_id: null,
    },
  ];
}

function link(options: {
  source: number;
  sourceName: string;
  target: number;
  targetName: string;
  group: string;
  feature: LinkRow["feature"];
  emitter: string;
  rule?: [string, string] | null;
  system?: boolean;
}): LinkRow {
  const rule = options.rule ?? null;
  return {
    fingerprint: [
      "zwave",
      identity(options.source),
      "0",
      options.group,
      identity(options.target),
      "",
      options.feature,
    ].join("|"),
    backend: "zwave",
    feature: options.feature,
    emitter_id: options.emitter,
    emitter_group: options.group,
    source: {
      identity: identity(options.source),
      protocol_id: `${HOME}:${options.source}`,
      name: options.sourceName,
      device_id: DEVICE_IDS[`n${options.source}`] ?? null,
      endpoint: 0,
    },
    target: {
      identity: identity(options.target),
      protocol_id: `${HOME}:${options.target}`,
      name: options.targetName,
      device_id: DEVICE_IDS[`n${options.target}`] ?? null,
      endpoint: null,
    },
    rule_id: rule === null ? null : rule[0],
    rule_name: rule === null ? null : rule[1],
    is_system: options.system ?? false,
    managed_by: rule === null ? null : rule[0],
  };
}

const CONTROLLER = "Z-Wave Controller";

/** One lifeline entry, which is what every device holds on group 1. */
function lifelineLink(node: number, name: string): LinkRow {
  return link({
    source: node,
    sourceName: name,
    target: 1,
    targetName: CONTROLLER,
    group: "1",
    feature: "status_report",
    emitter: "g1",
    system: true,
  });
}

const NAMES: Record<number, string> = {
  21: "Bath Light",
  29: "Mud Room Scene",
  30: "Hallway Scene",
  35: "Entrance Lobby Light",
  36: "Bedroom Scene Controller",
  37: "Master Bedroom Lights",
  38: "Bedside Light L",
  39: "Bedside Light R",
  40: "Master Bedroom Remote",
  42: "Ceiling Lights",
};

function name(node: number): string {
  return NAMES[node] ?? `Node ${node}`;
}

/** Node 36's own links: a lifeline, three managed entries and one nobody claims. */
function node36Links(): LinkRow[] {
  return [
    lifelineLink(36, name(36)),
    link({
      source: 36,
      sourceName: name(36),
      target: 38,
      targetName: name(38),
      group: "2",
      feature: "on_off",
      emitter: "main_button",
      rule: ["rule-bedside", "Bedside pair from the paddle"],
    }),
    link({
      source: 36,
      sourceName: name(36),
      target: 39,
      targetName: name(39),
      group: "2",
      feature: "on_off",
      emitter: "main_button",
      rule: ["rule-bedside", "Bedside pair from the paddle"],
    }),
    link({
      source: 36,
      sourceName: name(36),
      target: 37,
      targetName: name(37),
      group: "3",
      feature: "level_set",
      emitter: "main_button",
      rule: ["rule-bedside", "Bedside pair from the paddle"],
    }),
    link({
      source: 36,
      sourceName: name(36),
      target: 42,
      targetName: name(42),
      group: "7",
      feature: "on_off",
      emitter: "button_2",
    }),
  ];
}

export const DEVICES: DeviceRow[] = [
  device(21, name(21), { links: 1, emitters: 3 }),
  device(29, name(29), { links: 2, emitters: 6, available: false }),
  device(30, name(30), { links: 1, emitters: 6 }),
  device(35, name(35), { links: 1, emitters: 3 }),
  device(36, name(36), { links: 5, emitters: 6 }),
  device(37, name(37), { links: 6, emitters: 3 }),
  device(38, name(38), { links: 1, emitters: 3 }),
  device(39, name(39), { links: 1, emitters: 3 }),
  device(40, name(40), { links: 1, emitters: 5 }),
  device(42, name(42), { links: 1, emitters: 3 }),
];

/** Node 37's paddle group 2, deliberately full, so the capacity path can be looked at. */
function node37Links(): LinkRow[] {
  return [
    lifelineLink(37, name(37)),
    ...[21, 30, 35, 38, 42].map((target) =>
      link({
        source: 37,
        sourceName: name(37),
        target,
        targetName: name(target),
        group: "2",
        feature: "on_off",
        emitter: "paddle",
        rule: target === 38 ? ["rule-3way", "Master and bedside 3-way"] : null,
      }),
    ),
  ];
}

const DETAIL_LINKS: Record<number, LinkRow[]> = {
  21: [lifelineLink(21, name(21))],
  29: [
    lifelineLink(29, name(29)),
    link({
      source: 29,
      sourceName: name(29),
      target: 35,
      targetName: name(35),
      group: "2",
      feature: "on_off",
      emitter: "main_button",
      rule: ["rule-mud", "Mud room scene"],
    }),
  ],
  30: [lifelineLink(30, name(30))],
  35: [lifelineLink(35, name(35))],
  36: node36Links(),
  37: node37Links(),
  38: [lifelineLink(38, name(38))],
  39: [lifelineLink(39, name(39))],
  40: [lifelineLink(40, name(40))],
  42: [lifelineLink(42, name(42))],
};

const DETAIL_EMITTERS: Record<number, Emitter[]> = {
  21: dimmerEmitters(),
  29: zen35Emitters(),
  30: zen35Emitters(),
  35: dimmerEmitters(),
  36: zen35Emitters(),
  37: dimmerEmitters(),
  38: dimmerEmitters(),
  39: dimmerEmitters(),
  40: zen35Emitters().slice(0, 5),
  42: dimmerEmitters(),
};

export function deviceDetail(deviceId: string): DeviceDetail | null {
  const entry = Object.entries(DEVICE_IDS).find(([, id]) => id === deviceId);
  if (entry === undefined) {
    return null;
  }
  const node = Number(entry[0].slice(1));
  const row = DEVICES.find((candidate) => candidate.identity === identity(node));
  if (row === undefined) {
    return null;
  }
  return {
    device: row,
    emitters: DETAIL_EMITTERS[node] ?? [],
    links: DETAIL_LINKS[node] ?? [],
    settings:
      node === 36
        ? { mirror_hub_commands: "off", report_command_class: "basic", local_control: 1 }
        : {},
    deep_verified: false,
  };
}

export const PROFILES: ProfileRow[] = [
  { id: "profile-main", name: "House", rules: 4, enabled_rules: 3, is_active: true },
  { id: "profile-guest", name: "Guest mode", rules: 2, enabled_rules: 2, is_active: false },
];

export const RULES: RuleRow[] = [
  {
    rule: {
      id: "rule-bedside",
      name: "Bedside pair from the paddle",
      template: "remote",
      backend: "zwave",
      enabled: true,
      direction: "one_way",
      mirror_source: "leave",
      features: ["on_off", "level_set", "level_hold"],
      hybrid: [],
      source: { device: identity(36), endpoint: 0, emitter_id: "main_button" },
      targets: [
        { device: identity(38), endpoint: null },
        { device: identity(39), endpoint: null },
      ],
    },
    state: "in_sync",
    links_total: 6,
    links_in_sync: 6,
  },
  {
    rule: {
      id: "rule-3way",
      name: "Master and bedside 3-way",
      template: "virtual_3way",
      backend: "zwave",
      enabled: true,
      direction: "two_way",
      mirror_source: "leave",
      features: ["on_off", "level_set"],
      hybrid: [],
      source: { device: identity(37), endpoint: 0, emitter_id: "paddle" },
      targets: [{ device: identity(38), endpoint: null }],
    },
    state: "drift",
    links_total: 4,
    links_in_sync: 2,
  },
  {
    rule: {
      id: "rule-offall",
      name: "Goodnight, everything off",
      template: "off_all",
      backend: "zwave",
      enabled: true,
      direction: "one_way",
      mirror_source: "off",
      features: ["on_off"],
      hybrid: [],
      source: { device: identity(36), endpoint: 0, emitter_id: "button_2" },
      targets: [
        { device: identity(37), endpoint: null },
        { device: identity(42), endpoint: null },
        { device: identity(21), endpoint: null },
      ],
    },
    state: "pending",
    links_total: 3,
    links_in_sync: 1,
  },
  {
    rule: {
      id: "rule-mud",
      name: "Mud room scene",
      template: "scene_button",
      backend: "zwave",
      enabled: false,
      direction: "one_way",
      mirror_source: "leave",
      features: ["on_off"],
      hybrid: [],
      source: { device: identity(29), endpoint: 0, emitter_id: "button_1" },
      targets: [{ device: identity(35), endpoint: null }],
    },
    state: "blocked",
    links_total: 0,
    links_in_sync: 0,
  },
];

export const JOBS: Job[] = [
  {
    id: "job-2",
    created_at: new Date(Date.now() - 26 * 60 * 1000).toISOString(),
    scope: "Goodnight, everything off",
    status: "partial",
    total: 3,
    results: [
      {
        fingerprint: DETAIL_LINKS[36]?.[4]?.fingerprint ?? "",
        status: "applied",
        reason: null,
      },
      {
        fingerprint: ["zwave", identity(36), "0", "7", identity(21), "", "on_off"].join("|"),
        status: "failed",
        reason:
          "ZWaveError: Timeout while waiting for an ACK from the controller (ZW0201) after 3 attempts",
      },
      {
        fingerprint: ["zwave", identity(40), "0", "2", identity(37), "", "on_off"].join("|"),
        status: "pending_wakeup",
        reason: null,
      },
    ],
  },
  {
    id: "job-1",
    created_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    scope: "House",
    status: "completed",
    total: 6,
    results: [
      {
        fingerprint: DETAIL_LINKS[36]?.[1]?.fingerprint ?? "",
        status: "applied",
        reason: null,
      },
      {
        fingerprint: DETAIL_LINKS[36]?.[2]?.fingerprint ?? "",
        status: "already_present",
        reason: null,
      },
    ],
  },
];

export const SNAPSHOTS: Snapshot[] = [
  {
    id: "snap-1",
    created_at: new Date(Date.now() - 26 * 60 * 1000).toISOString(),
    reason: "before apply",
    devices: [identity(36), identity(37)],
    links: 11,
  },
];

export { identity, name };
