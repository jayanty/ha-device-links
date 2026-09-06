/**
 * The words the panel puts on the backend's enumerations, in one place.
 *
 * Every one of these is an English literal rather than a translation key, which is open
 * item T30: a custom panel's own strings are not among the categories the Home Assistant
 * frontend loads, so there is nowhere to look them up yet. What is deliberately *not*
 * here is anything the backend can say: a `Diagnostic` is rendered by
 * `messages.localizeDiagnostic`, which is localised. This file names states and features,
 * which are the panel's own vocabulary.
 *
 * The tone functions are the other half. A state is shown as a chip, and the chip's tone
 * says how worried to be before the word is read: `ok`, `info`, `warn`, `error`, `muted`.
 * They are chosen once here so that "pending" never looks like a fault in one view and
 * like nothing in another.
 */

import type {
  Backend,
  Feature,
  HybridKind,
  HybridLegRow,
  JobStatus,
  LinkEndpoint,
  LinkOutcome,
  LinkRow,
  PlanOp,
  RuleState,
  TemplateId,
} from "./types";

/** The five tones a chip can take, in order of how much attention each asks for. */
export type Tone = "ok" | "info" | "warn" | "error" | "muted";

const FEATURE_LABELS: Record<Feature, string> = {
  on_off: "On and off",
  level_set: "Brightness",
  level_hold: "Hold to dim",
  scene: "Scenes",
  color: "Colour",
  status_report: "Status feedback",
};

const FEATURE_ICONS: Record<Feature, string> = {
  on_off: "mdi:power",
  level_set: "mdi:brightness-6",
  level_hold: "mdi:gesture-tap-hold",
  scene: "mdi:palette-outline",
  color: "mdi:invert-colors",
  status_report: "mdi:arrow-left-right",
};

const BACKEND_LABELS: Record<Backend, string> = {
  zwave: "Z-Wave",
  zigbee2mqtt: "Zigbee",
  matter: "Matter",
};

const TEMPLATE_LABELS: Record<TemplateId, string> = {
  remote: "Remote control",
  virtual_3way: "Virtual 3-way",
  scene_button: "Scene button",
  off_all: "Off all",
  status_feedback: "Status feedback",
  custom: "Custom",
};

const TEMPLATE_SUMMARIES: Record<TemplateId, string> = {
  remote: "One control drives one or more lights, on, off and dimming.",
  virtual_3way: "Two switches control each other, so either one works like the other.",
  scene_button: "A scene button sends one command to the devices you pick.",
  off_all: "One press turns a set of devices off.",
  status_feedback: "A device reports its state back to the control that drives it.",
  custom: "Choose the control, the targets and the features yourself.",
};

const RULE_STATE_LABELS: Record<RuleState, string> = {
  in_sync: "In sync",
  drift: "Drift",
  pending: "Pending",
  blocked: "Blocked",
  disabled: "Disabled",
  unknown: "Unknown",
};

const RULE_STATE_TONES: Record<RuleState, Tone> = {
  in_sync: "ok",
  drift: "error",
  pending: "warn",
  blocked: "error",
  disabled: "muted",
  unknown: "muted",
};

const RULE_STATE_EXPLANATIONS: Record<RuleState, string> = {
  in_sync: "Every link this rule asks for is on the devices.",
  drift: "The devices do not hold what this rule asks for. Something changed them.",
  pending: "This rule has links waiting to be written. Plan and apply to write them.",
  blocked: "This rule compiles to nothing. Open it to see why.",
  disabled: "This rule is off, so its links are not on the devices.",
  unknown: "A device this rule uses could not be read, so its state cannot be judged.",
};

const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  completed: "Completed",
  partial: "Partly done",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

const JOB_STATUS_TONES: Record<JobStatus, Tone> = {
  completed: "ok",
  partial: "warn",
  cancelled: "muted",
  interrupted: "error",
};

const OUTCOME_LABELS: Record<LinkOutcome, string> = {
  applied: "Written",
  already_present: "Already there",
  unverified: "Written, not verified",
  unconfirmed: "Written, not confirmed",
  pending_wakeup: "Waiting for the device to wake",
  failed: "Failed",
  blocked: "Blocked",
  stale_plan: "Plan was out of date",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

const OUTCOME_TONES: Record<LinkOutcome, Tone> = {
  applied: "ok",
  already_present: "ok",
  unverified: "warn",
  unconfirmed: "warn",
  pending_wakeup: "warn",
  failed: "error",
  blocked: "error",
  stale_plan: "warn",
  cancelled: "muted",
  interrupted: "error",
};

const PLAN_OP_LABELS: Record<PlanOp, string> = {
  add: "Add",
  remove: "Remove",
  set_param: "Settings",
  blocked: "Blocked",
  pending: "Pending",
};

export function featureLabel(feature: Feature): string {
  return FEATURE_LABELS[feature] ?? feature;
}

export function featureIcon(feature: Feature): string {
  return FEATURE_ICONS[feature] ?? "mdi:link-variant";
}

export function backendLabel(backend: Backend | null): string {
  return backend === null ? "Unknown protocol" : (BACKEND_LABELS[backend] ?? backend);
}

export function templateLabel(template: TemplateId): string {
  return TEMPLATE_LABELS[template] ?? template;
}

export function templateSummary(template: TemplateId): string {
  return TEMPLATE_SUMMARIES[template] ?? "";
}

export function ruleStateLabel(state: RuleState): string {
  return RULE_STATE_LABELS[state] ?? state;
}

export function ruleStateTone(state: RuleState): Tone {
  return RULE_STATE_TONES[state] ?? "muted";
}

export function ruleStateExplanation(state: RuleState): string {
  return RULE_STATE_EXPLANATIONS[state] ?? "";
}

export function jobStatusLabel(status: JobStatus): string {
  return JOB_STATUS_LABELS[status] ?? status;
}

export function jobStatusTone(status: JobStatus): Tone {
  return JOB_STATUS_TONES[status] ?? "muted";
}

export function outcomeLabel(outcome: LinkOutcome): string {
  return OUTCOME_LABELS[outcome] ?? outcome;
}

export function outcomeTone(outcome: LinkOutcome): Tone {
  return OUTCOME_TONES[outcome] ?? "muted";
}

export function planOpLabel(op: PlanOp): string {
  return PLAN_OP_LABELS[op] ?? op;
}

/** One control's headroom, in whichever of its groups has the least left. */
export interface Usage {
  group: string;
  used: number;
  capacity: number;
  free: number;
}

/**
 * How much room one control has left.
 *
 * The two numbers come from different places on purpose. The capacity is what the device
 * says the group holds; the used count is what was actually read off it, which includes
 * entries no rule of ours claims. A control that writes to several groups reports the
 * busiest one, because that is the group that refuses first, and its number is what the
 * planner will block an add against with `group_full`.
 */
export function emitterUsage(
  emitter: { group_ids: string[]; actions: Partial<Record<Feature, string>>; capacity: number },
  links: readonly { emitter_group: string }[],
): Usage | null {
  const groups = emitter.group_ids.length
    ? emitter.group_ids
    : Object.values(emitter.actions).filter((group): group is string => group !== undefined);
  let worst: Usage | null = null;
  for (const group of groups) {
    const used = links.filter((link) => link.emitter_group === group).length;
    if (worst === null || used > worst.used) {
      worst = {
        group,
        used,
        capacity: emitter.capacity,
        free: Math.max(0, emitter.capacity - used),
      };
    }
  }
  return worst;
}

/** How one end of a link is named: its device, and its endpoint when it has one. */
export function endpointName(endpoint: LinkEndpoint): string {
  const name = endpoint.name || endpoint.identity;
  return endpoint.endpoint === null || endpoint.endpoint === 0
    ? name
    : `${name} (endpoint ${endpoint.endpoint})`;
}

/** One link as a sentence fragment: what it carries, from where, to where. */
export function describeLink(link: LinkRow): string {
  return `${featureLabel(link.feature)} from ${endpointName(link.source)} group ${
    link.emitter_group
  } to ${endpointName(link.target)}`;
}

/** How each HA-executed leg reads, in the words the checkbox that created it used. */
const HYBRID_SENTENCES: Record<HybridKind, string> = {
  on_only: "turns on, and never off",
  off_only: "turns off, and never on",
  self_load: "turns off this device's own load",
  button_led: "keeps this button's LED in sync with",
};

/**
 * One HA-executed leg, said as what Home Assistant will do rather than as a link.
 *
 * Deliberately a different sentence shape from `describeLink`. A link is written into a
 * device; a leg is Home Assistant standing in for a wire, and a reader who cannot tell the
 * two apart at a glance cannot tell which half of their rule survives a restart.
 */
export function describeHybridLeg(leg: HybridLegRow): string {
  const control = `${leg.source.name} ${leg.emitter_id}`;
  if (leg.kind === "self_load") {
    return `When ${control} is pressed, Home Assistant ${HYBRID_SENTENCES[leg.kind]}`;
  }
  if (leg.kind === "button_led") {
    return `Home Assistant ${HYBRID_SENTENCES[leg.kind]} ${leg.target.name}, on ${control}`;
  }
  return `When ${control} is pressed, Home Assistant ${HYBRID_SENTENCES[leg.kind]} ${leg.target.name}`;
}

/**
 * A link fingerprint, taken apart for display only.
 *
 * A job result names a link by its fingerprint and nothing else, so the Activity view has
 * the choice of showing that string or reading it. The format is `models.Link.fingerprint`:
 * seven fields joined with `|`, with a backslash escaping either character, and it is
 * deliberately a stable, readable identity rather than an opaque hash. Nothing here
 * depends on parsing succeeding: the raw fingerprint is shown when it does not, which is
 * also what the expander shows either way, because the raw string is what makes a bug
 * report useful.
 */
export interface ParsedFingerprint {
  backend: string;
  source: string;
  sourceEndpoint: string;
  group: string;
  target: string;
  targetEndpoint: string;
  feature: string;
}

export function parseFingerprint(fingerprint: string): ParsedFingerprint | null {
  const parts: string[] = [];
  let current = "";
  let escaped = false;
  for (const character of fingerprint) {
    if (escaped) {
      current += character;
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else if (character === "|") {
      parts.push(current);
      current = "";
    } else {
      current += character;
    }
  }
  parts.push(current);
  const [backend, source, sourceEndpoint, group, target, targetEndpoint, feature] = parts;
  if (parts.length !== 7 || backend === undefined) {
    return null;
  }
  return {
    backend,
    source: source ?? "",
    sourceEndpoint: sourceEndpoint ?? "",
    group: group ?? "",
    target: target ?? "",
    targetEndpoint: targetEndpoint ?? "",
    feature: feature ?? "",
  };
}

/** One fingerprint as a sentence, with device identities turned into names by `nameOf`. */
export function describeFingerprint(
  fingerprint: string,
  nameOf: (identity: string) => string,
): string {
  const parsed = parseFingerprint(fingerprint);
  if (parsed === null) {
    return fingerprint;
  }
  const feature = FEATURE_LABELS[parsed.feature as Feature] ?? parsed.feature;
  const target = parsed.targetEndpoint
    ? `${nameOf(parsed.target)} (endpoint ${parsed.targetEndpoint})`
    : nameOf(parsed.target);
  return `${feature} from ${nameOf(parsed.source)} group ${parsed.group} to ${target}`;
}

/** "1 link" or "4 links", because "1 links" reads as a bug in the counting. */
export function plural(count: number, singular: string, plural_?: string): string {
  return `${count} ${count === 1 ? singular : (plural_ ?? `${singular}s`)}`;
}

/**
 * A stored timestamp as a local date and time.
 *
 * The backend writes ISO 8601 with an offset. Anything that does not parse is shown as
 * it arrived rather than as "Invalid Date", which tells the reader nothing and looks
 * like a fault in their clock.
 */
export function formatTime(iso: string, language?: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) {
    return iso;
  }
  try {
    return new Intl.DateTimeFormat(language || undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(when);
  } catch {
    return when.toISOString();
  }
}

/** How long ago, in the roughest unit that is still true. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const when = new Date(iso).getTime();
  if (Number.isNaN(when)) {
    return "";
  }
  const seconds = Math.max(0, Math.round((now - when) / 1000));
  if (seconds < 60) {
    return "just now";
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${plural(minutes, "minute")} ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${plural(hours, "hour")} ago`;
  }
  return `${plural(Math.round(hours / 24), "day")} ago`;
}
