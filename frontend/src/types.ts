/**
 * The API payloads, mirrored from `custom_components/device_links/serialize.py`.
 *
 * Hand written rather than generated, and then asserted rather than trusted:
 * `tests/test_panel_contract.py` builds real objects, runs them through the real
 * `Serializer`, and compares the key set of every payload with the interfaces below. So a
 * field added, removed or renamed in `serialize.py` fails the Python suite on the next
 * run rather than breaking the panel at the moment somebody opens it. The same test
 * checks that every string union here has exactly the members of the `StrEnum` it
 * mirrors, and that every command `api.ts` sends is one the backend registers.
 *
 * That is the whole reason these interfaces are flat and boring: every one of them is
 * one serializer method's dictionary, one property per line, so the check is exact rather
 * than approximate. Resist nesting an object literal inline; give it a name instead.
 */

// --------------------------------------------------------------------------------------
// The enumerations, mirroring the StrEnums the backend stringifies.
// --------------------------------------------------------------------------------------

/** `models.Backend`. Note `zigbee2mqtt` rather than `zigbee`. */
export type Backend = "zwave" | "zigbee2mqtt" | "matter";

/** `models.Feature`. */
export type Feature = "on_off" | "level_set" | "level_hold" | "scene" | "color" | "status_report";

/** `models.Template`, the intents a rule can be authored with. */
export type TemplateId =
  | "remote"
  | "virtual_3way"
  | "scene_button"
  | "off_all"
  | "status_feedback"
  | "custom";

/** `models.Direction`. */
export type Direction = "one_way" | "two_way";

/** `models.MirrorChoice`, what a rule asks the source device's own load to do. */
export type MirrorChoice = "on" | "off" | "leave";

/**
 * `models.HybridKind`: one thing a rule asks for that no radio can carry.
 *
 * Every one of these is executed by Home Assistant rather than written to a device, and
 * every screen that shows one says so. See PRD Section 6.7 and Decision D3.
 */
export type HybridKind = "on_only" | "off_only" | "self_load" | "button_led";

/** `models.PlanOp`, which is also the key each plan device buckets its work under. */
export type PlanOp = "add" | "remove" | "set_param" | "blocked" | "pending";

/** `coordinator.RuleState`, what one rule's links are currently doing. */
export type RuleState = "in_sync" | "drift" | "pending" | "blocked" | "disabled" | "unknown";

/** `executor.JobStatus`, how a whole apply ended. */
export type JobStatus = "completed" | "partial" | "cancelled" | "interrupted";

/** `executor.LinkOutcome`, what became of one link in one job. */
export type LinkOutcome =
  | "applied"
  | "already_present"
  | "unverified"
  | "unconfirmed"
  | "pending_wakeup"
  | "failed"
  | "blocked"
  | "stale_plan"
  | "cancelled"
  | "interrupted";

// --------------------------------------------------------------------------------------
// Messages.
// --------------------------------------------------------------------------------------

/**
 * `serialize.diagnostic`: a translation key and its placeholders, never a sentence.
 *
 * Render it with `localizeDiagnostic` from `messages.ts` rather than reading either field
 * directly. A bare key is not something to show a user.
 */
export interface Diagnostic {
  translation_key: string;
  placeholders: Record<string, string>;
}

// --------------------------------------------------------------------------------------
// Devices.
// --------------------------------------------------------------------------------------

/**
 * `Serializer.device`: one device as the device list shows it.
 *
 * `receiving_endpoint` is where a link lands on this device when nobody named an endpoint:
 * the endpoint a Zigbee binding must address, and null on Z-Wave, where an association
 * names a node and an endpoint only when the user asked for one. The rule editor fills a
 * target's endpoint from it, which is why it is on the list row rather than only on the
 * detail: the targets step has the list and nothing else.
 */
export interface DeviceRow {
  identity: string;
  device_id: string | null;
  name: string;
  backend: Backend;
  protocol_id: string;
  available: boolean;
  links: number;
  emitters: number;
  is_long_range: boolean;
  receiving_endpoint: number | null;
}

/**
 * `Serializer._emitter`: one control on a device, and what it can reach.
 *
 * `endpoint` is where this control drives from: 0 on the Z-Wave root, 2 on an Inovelli
 * Blue paddle. A rule's source endpoint is this number, and nothing else can supply it.
 */
export interface Emitter {
  emitter_id: string;
  label: string;
  endpoint: number;
  group_ids: string[];
  actions: Partial<Record<Feature, string>>;
  capacity: number;
  supports_endpoint_targets: boolean;
  is_lifeline: boolean;
  grouping: string;
  semantics: string | null;
  /**
   * The Central Scene number this control reports when it is pressed, or null when the
   * device has not said. Null means the on-only, off-only and own-load hybrid legs cannot
   * be offered for this control: the compiler refuses them rather than guessing a number
   * and reacting to a different button.
   */
  scene_id: number | null;
  /** The Indicator CC id of this control's own LED, or null when nothing knows it. */
  indicator_id: number | null;
}

/** One end of a link, as `Serializer.link` writes both ends. */
export interface LinkEndpoint {
  identity: string;
  protocol_id: string;
  name: string;
  device_id: string | null;
  endpoint: number | null;
}

/** `Serializer.link`: one link, desired or observed, in one shape. */
export interface LinkRow {
  fingerprint: string;
  backend: Backend;
  feature: Feature;
  emitter_id: string;
  emitter_group: string;
  source: LinkEndpoint;
  target: LinkEndpoint;
  rule_id: string | null;
  rule_name: string | null;
  is_system: boolean;
  managed_by: string | null;
}

/** A link the plan found on a device that no rule claims, plus whether it was dismissed. */
export interface UnmanagedLink extends LinkRow {
  ignored: boolean;
}

/** `websocket._device_detail`: everything the device page shows about one device. */
export interface DeviceDetail {
  device: DeviceRow;
  emitters: Emitter[];
  links: LinkRow[];
  settings: Record<string, unknown>;
  deep_verified: boolean;
}

// --------------------------------------------------------------------------------------
// Rules and profiles.
// --------------------------------------------------------------------------------------

/**
 * `yaml_io.rule_to_data`, the source half: which control on which device.
 *
 * `endpoint` is a number and never null, which is a deliberately tight type rather than a
 * mirror of `number | null` on the target half. `yaml_io._require_int` refuses a rule
 * whose source endpoint is missing, so a client that sends null has every save refused,
 * which is exactly what happened between Phase 1E and open item T50. It is the emitter's
 * own `endpoint`, so there is always a number to send.
 */
export interface RuleSourceData {
  device: string;
  endpoint: number;
  emitter_id: string;
}

/** `yaml_io.rule_to_data`, one target: a device identity and an optional endpoint. */
export interface RuleTargetData {
  device: string;
  endpoint: number | null;
}

/** `yaml_io.rule_to_data`: one rule as stored, referring to devices by identity. */
export interface RuleData {
  id: string;
  name: string;
  template: TemplateId;
  backend: Backend;
  enabled: boolean;
  direction: Direction;
  mirror_source: MirrorChoice;
  features: Feature[];
  /**
   * The HA-executed legs this rule opts into (FR-H1). Empty on almost every rule, and
   * always written rather than omitted, so a rule says out loud that it asks nothing of
   * Home Assistant. Opting in here does nothing while the integration's own hybrid legs
   * option is off.
   */
  hybrid: HybridKind[];
  source: RuleSourceData;
  targets: RuleTargetData[];
}

/** `Serializer.rule`: one rule with what it is currently doing. */
export interface RuleRow {
  rule: RuleData;
  state: RuleState;
  links_total: number;
  links_in_sync: number;
}

/** `Serializer.setting`: one device setting a rule asked for, and where it really lives. */
export interface SettingWrite {
  device_identity: string;
  capability: string;
  parameter: number;
  bitmask: number | null;
  value: number;
}

/**
 * `Serializer.hybrid_leg`: one leg Home Assistant carries because no radio can.
 *
 * Deliberately not a `LinkRow`. A leg is a listener inside Home Assistant, not an entry on
 * a device, and rendering the two in one list would blur the boundary Decision D3 exists to
 * keep visible. Show it under its own heading, always labelled HA-executed.
 */
export interface HybridLegRow {
  identity: string;
  kind: HybridKind;
  rule_id: string;
  feature: Feature;
  emitter_id: string;
  source: HybridLegDevice;
  target: HybridLegTarget;
  scene_id: number | null;
  indicator_id: number | null;
}

/** The device a hybrid leg is authored on. */
export interface HybridLegDevice {
  identity: string;
  name: string;
  device_id: string | null;
}

/** The device a hybrid leg acts on or watches, which for `self_load` is the source. */
export interface HybridLegTarget extends HybridLegDevice {
  endpoint: number | null;
}

/**
 * `rules/validate`: what this rule compiles to, plus what it would join up.
 *
 * The loops are a separate field rather than another warning because they are about the
 * profile with this rule folded into it, not about this rule: one rule cannot loop.
 */
export interface RuleValidation extends CompiledRule {
  loops: LoopWarning[];
}

/** `Serializer.compiled`: what one rule compiles to, warnings and refusals included. */
export interface CompiledRule {
  links: LinkRow[];
  settings: SettingWrite[];
  hybrid_legs: HybridLegRow[];
  warnings: Diagnostic[];
  errors: Diagnostic[];
}

/**
 * `Serializer.loop`: a set of devices that can pass a command round between them (FR-R7).
 *
 * A warning and never a block (E30): the analysis knows what the links say and not what
 * the devices do, and the user may know something it does not. Show it, name the rules,
 * and let the rule be saved.
 */
export interface LoopWarning {
  devices: LoopDevice[];
  rule_ids: string[];
  rule_names: string[];
}

/** One device on a loop. */
export interface LoopDevice {
  identity: string;
  name: string;
  device_id: string | null;
}

/** `Serializer.profile`: one profile as the profile list shows it. */
export interface ProfileRow {
  id: string;
  name: string;
  rules: number;
  enabled_rules: number;
  is_active: boolean;
}

// --------------------------------------------------------------------------------------
// Plans.
// --------------------------------------------------------------------------------------

/** `Serializer.item`: one step of a plan, with the reason it is blocked when it is. */
export interface PlanItem {
  op: PlanOp;
  device_identity: string;
  link: LinkRow | null;
  setting: SettingWrite | null;
  reason: Diagnostic | null;
}

/**
 * `Serializer._bucket`: one device's share of a plan.
 *
 * Every bucket is present on every device, empty when there is nothing in it, so a view
 * can render the sections it wants without checking whether the key exists.
 */
export interface PlanDevice {
  identity: string;
  device_id: string | null;
  name: string;
  backend: Backend | null;
  available: boolean;
  add: PlanItem[];
  remove: PlanItem[];
  set_param: PlanItem[];
  blocked: PlanItem[];
  pending: PlanItem[];
  unmanaged: UnmanagedLink[];
}

/** `Serializer.plan`: what applying a scope would do, grouped by device. */
export interface Plan {
  token: string;
  is_empty: boolean;
  unchanged_count: number;
  counts: Record<PlanOp | "unmanaged", number>;
  devices: PlanDevice[];
}

// --------------------------------------------------------------------------------------
// Jobs and snapshots.
// --------------------------------------------------------------------------------------

/** One link's outcome inside a stored job summary. */
export interface JobResult {
  fingerprint: string;
  status: LinkOutcome;
  reason: string | null;
}

/** `Serializer.job`: one apply as the Activity view shows it afterwards. */
export interface Job {
  id: string;
  created_at: string;
  scope: string;
  status: JobStatus;
  total: number;
  results: JobResult[];
}

/**
 * `snapshots/rollback`: what putting a snapshot's devices back would do.
 *
 * `status` is `preview` when no plan token was sent, which is how the dialog is opened:
 * nothing has been written and the plan is what the user is being asked about.
 *
 * `returns_on_next_apply` is the part a user has to see before confirming. A rollback puts
 * the devices back and leaves the rules alone, so a link some enabled rule still asks for
 * is removed now and written again the next time that rule is applied. Each one is a
 * removal in the plan as well; this is the same links, said as the consequence rather than
 * as the operation.
 */
export interface SnapshotRollback {
  snapshot: Snapshot;
  plan: Plan;
  returns_on_next_apply: LinkRow[];
  /** Devices the snapshot covers that nobody can read now, so nothing is planned for them. */
  unreadable_devices: string[];
  job_id: string | null;
  status: JobStatus | "preview" | "nothing_to_do";
}

/** `Serializer.snapshot`: what a pre-apply snapshot covers, not what is in it. */
export interface Snapshot {
  id: string;
  created_at: string;
  reason: string;
  devices: string[];
  links: number;
}

/** `websocket._progress`: where the running job has got to. */
export interface JobProgress {
  id: string;
  total: number;
  completed: number;
  devices_in_flight: string[];
}

/**
 * The job summary carried by the `device_links_job_finished` bus event.
 *
 * Deliberately not the same shape as `Job`: this one counts outcomes rather than listing
 * them, because it is an event payload that automations and the recorder also see. Call
 * `jobs/get` when you need the per-link detail.
 */
export interface JobFinished {
  id: string;
  scope: string;
  status: JobStatus;
  created_at: string;
  total: number;
  results: Partial<Record<LinkOutcome, number>>;
  rule_ids: string[];
}

/** What `jobs/subscribe` streams: progress, then a summary for each job that ends. */
export type JobEvent =
  | { type: "progress"; job: JobProgress | null }
  | { type: "finished"; job: JobFinished };

// --------------------------------------------------------------------------------------
// Command results that are not one of the shapes above.
// --------------------------------------------------------------------------------------

/** `profiles/list`. */
export interface ProfileList {
  active_profile_id: string | null;
  profiles: ProfileRow[];
}

/**
 * `profiles/get`.
 *
 * `loops` is empty for every profile but the active one, because only the active profile's
 * links are on the devices: a loop in a profile nobody has activated is a warning about a
 * house that does not exist.
 */
export interface ProfileDetail {
  profile: ProfileRow;
  rules: RuleRow[];
  loops: LoopWarning[];
}

/** `diff.ChangeKind`, what happened to one rule or one link between two sides. */
export type ChangeKind = "added" | "removed" | "changed" | "unchanged";

/** One link on either side of a comparison, and what would happen to it. */
export interface LinkChange {
  kind: ChangeKind;
  link: LinkRow;
}

/**
 * One rule as a comparison sees it (FR-P4).
 *
 * `writes_nothing_new` is the one a reader needs first: a renamed rule is a change to the
 * profile and no change at all to the house, and saying so is the difference between a
 * diff somebody can act on and two lists of fingerprints.
 */
export interface RuleDiffRow {
  rule_id: string;
  name: string;
  kind: ChangeKind;
  fields: string[];
  writes_nothing_new: boolean;
  links_added: LinkRow[];
  links_removed: LinkRow[];
  links_unchanged: number;
}

/**
 * `profiles/diff`: what changes if this profile becomes that one, or that snapshot.
 *
 * `rules` is empty when the other side is a snapshot, which has no rules in it, and
 * `devices` then names the devices the snapshot covers, which is the only part of the
 * house that comparison can honestly speak for.
 */
export interface ProfileDiff {
  is_empty: boolean;
  counts: Record<string, number>;
  devices: string[];
  rules: RuleDiffRow[];
  links: LinkChange[];
}

/** `profiles/export`. */
export interface ProfileExport {
  profile_id: string;
  name: string;
  yaml: string;
}

/** `profiles/import`, whose plan is present only when the imported profile is active. */
export interface ProfileImport {
  profile: ProfileRow;
  is_active: boolean;
  /**
   * Devices the file names that are not on this network, which the import was allowed to
   * keep. Empty unless `allow_missing_devices` was sent, because the import is refused
   * otherwise (E38). A device swap starts here: the rules come in naming the switch that
   * has gone, and the swap flow re-points them.
   */
  missing_devices: string[];
  plan?: Plan;
}

/** `profiles/activate`: the profile is in force and this is what applying it would do. */
export interface ProfileActivation {
  profile_id: string;
  plan: Plan;
}

/** `rules/set_enabled`, whose `rate_limited` says a toggle was deferred rather than lost. */
export interface RuleEnabled {
  rule_id: string;
  enabled: boolean;
  rate_limited: boolean;
}

/** `jobs/list`. */
export interface JobList {
  jobs: Job[];
  running: JobProgress | null;
}

/** `verify`: how many devices were re-read, and what each rule in scope now looks like. */
export interface VerifyResult {
  devices: number;
  rules: Record<string, RuleState>;
}

/**
 * `apply` and `unmanaged/remove`.
 *
 * `job_id` is null with the status `nothing_to_do` when the plan turned out to be empty,
 * which is a normal answer rather than a failure. `apply` answers `running` and streams
 * the rest through `jobs/subscribe`; `unmanaged/remove` is awaited and answers with the
 * job's final status.
 */
export interface JobStarted {
  job_id: string | null;
  status: JobStatus | "running" | "nothing_to_do";
}

// --------------------------------------------------------------------------------------
// Device swap (FR-S1 to FR-S3).
// --------------------------------------------------------------------------------------

/** `swap.MappingBasis`, why one control was proposed to take over from another. */
export type MappingBasis = "same_emitter_id" | "same_features" | "chosen" | "unmapped";

/** `Serializer.replacement`: a device the rules name that looks replaced. */
export interface SwapReplacement {
  old: DeviceRow;
  changed_in_place: boolean;
  rule_ids: string[];
  candidates: DeviceRow[];
}

/**
 * `Serializer._mapping`: one control on the old device and what would take over from it.
 *
 * `basis` is how confident the pre-fill is, and the two confident answers are not the same
 * claim: the ids agreeing says which physical control this is, and the features agreeing
 * says only that one control happens to fit. Present them differently.
 */
export interface SwapMapping {
  old_emitter_id: string;
  new_emitter_id: string | null;
  new_label: string | null;
  new_endpoint: number | null;
  basis: MappingBasis;
  features_needed: Feature[];
  features_carried: Feature[];
}

/** `Serializer._rewrite`: one rule as it stands and as the swap would leave it. */
export interface SwapRewrite {
  rule_id: string;
  name: string;
  before: RuleData;
  after: RuleData;
  is_lossy: boolean;
  losses: Diagnostic[];
  notes: Diagnostic[];
  errors: Diagnostic[];
}

/** `Serializer.proposal`: everything one swap would do, before any of it is done. */
export interface SwapProposal {
  old: DeviceRow;
  new: DeviceRow;
  same_model: boolean;
  is_lossy: boolean;
  is_applicable: boolean;
  unmapped: string[];
  errors: Diagnostic[];
  mappings: SwapMapping[];
  rewrites: SwapRewrite[];
}

/**
 * `swap/preview`: the whole swap, and the two questions the plan alone cannot answer.
 *
 * `old_reachable` is separate from the plan on purpose. A device that is gone has no work
 * in the plan, which without this reads as a swap with nothing to clean up rather than as
 * entries still sitting in a device nobody can reach. `new_reachable` is the more dangerous
 * half: nothing is planned for a device that cannot be read, so a swap onto one would strip
 * the old switch and write nothing to the new.
 */
export interface SwapPreview {
  proposal: SwapProposal;
  plan: Plan;
  old_listed: boolean;
  old_reachable: boolean;
  new_reachable: boolean;
  removes: string[];
}

/** `swap/apply`: the job it started, and the rules it rewrote whether or not it wrote. */
export interface SwapApplied {
  job_id: string | null;
  status: JobStatus | "running" | "nothing_to_do";
  rules_rewritten: string[];
}

/** One intent a rule can be authored with. Names and descriptions are translation keys. */
export interface TemplateRow {
  id: TemplateId;
}
