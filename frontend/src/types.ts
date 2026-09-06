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

/** `Serializer.device`: one device as the device list shows it. */
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
}

/** `Serializer._emitter`: one control on a device, and what it can reach. */
export interface Emitter {
  emitter_id: string;
  label: string;
  group_ids: string[];
  actions: Partial<Record<Feature, string>>;
  capacity: number;
  supports_endpoint_targets: boolean;
  is_lifeline: boolean;
  grouping: string;
  semantics: string | null;
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

/** `yaml_io.rule_to_data`, the source half: which control on which device. */
export interface RuleSourceData {
  device: string;
  endpoint: number | null;
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

/** `Serializer.compiled`: what one rule compiles to, warnings and refusals included. */
export interface CompiledRule {
  links: LinkRow[];
  settings: SettingWrite[];
  warnings: Diagnostic[];
  errors: Diagnostic[];
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

/** `profiles/get`. */
export interface ProfileDetail {
  profile: ProfileRow;
  rules: RuleRow[];
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

/** One intent a rule can be authored with. Names and descriptions are translation keys. */
export interface TemplateRow {
  id: TemplateId;
}
