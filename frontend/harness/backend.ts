/**
 * A Home Assistant-shaped answering machine, for looking at the panel.
 *
 * It is not a simulator of the integration and does not pretend to be: it answers each
 * WebSocket command with a payload of the shape `serialize.py` produces, from the fixtures
 * next door. Three behaviours are real rather than canned, because they are the ones the
 * screens are built around and a canned answer would hide whatever is wrong with them.
 *
 * - **The plan token depends on the plan.** Ticking an unmanaged link re-plans, gets a new
 *   token, and moves that link into the removals, exactly as `planner._classify` does.
 * - **Apply refuses a token that is not the current one**, with `plan_out_of_date`, which
 *   is the FR-A3 path the plan dialog has to handle.
 * - **A job streams progress and then finishes**, so the progress and result phases of the
 *   dialog can be watched rather than imagined.
 */

import type {
  CompiledRule,
  Job,
  JobEvent,
  Plan,
  PlanDevice,
  PlanItem,
  RuleData,
  RuleRow,
  UnmanagedLink,
} from "../src/types";
import {
  DEVICES,
  deviceDetail,
  identity,
  JOBS,
  name,
  PROFILES,
  RULES,
  SNAPSHOTS,
} from "./fixtures";

type Listener = (event: JobEvent) => void;

function planItem(
  op: PlanItem["op"],
  link: PlanItem["link"],
  reason?: PlanItem["reason"],
): PlanItem {
  return {
    op,
    device_identity: link?.source.identity ?? "",
    link,
    setting: null,
    reason: reason ?? null,
  };
}

function emptyBuckets(): Pick<
  PlanDevice,
  "add" | "remove" | "set_param" | "blocked" | "pending" | "unmanaged"
> {
  return { add: [], remove: [], set_param: [], blocked: [], pending: [], unmanaged: [] };
}

function planDevice(node: number, extra: Partial<PlanDevice> = {}): PlanDevice {
  const row = DEVICES.find((device) => device.identity === identity(node));
  return {
    identity: identity(node),
    device_id: row?.device_id ?? null,
    name: name(node),
    backend: "zwave",
    available: row?.available ?? true,
    ...emptyBuckets(),
    ...extra,
  };
}

/** The one unmanaged entry on this fake network: somebody's own association on node 36. */
function unmanaged(): UnmanagedLink {
  const detail = deviceDetail("ha36");
  const link = detail?.links[4];
  if (link === undefined) {
    throw new Error("the node 36 fixture lost its unmanaged link");
  }
  return { ...link, ignored: false };
}

/** The link an Off-all rule wants and cannot have, because group 2 on node 37 is full. */
function blockedLink(): PlanItem {
  const detail = deviceDetail("ha37");
  const link = detail?.links[2];
  if (link === undefined) {
    throw new Error("the node 37 fixture lost its group 2 entries");
  }
  return planItem(
    "blocked",
    { ...link, rule_id: "rule-offall", rule_name: "Goodnight, everything off" },
    {
      translation_key: "group_full",
      placeholders: {
        group: "2",
        device: name(37),
        used: "5",
        capacity: "5",
        target: name(42),
      },
    },
  );
}

export class HarnessBackend {
  private readonly listeners = new Set<Listener>();

  private jobs: Job[] = [...JOBS];

  private rules: RuleRow[] = RULES.map((row) => ({ ...row, rule: { ...row.rule } }));

  private token = "plan-0";

  private running: { id: string; total: number; completed: number } | null = null;

  private timer: ReturnType<typeof setInterval> | undefined;

  /** Answer one command, or reject the way Home Assistant rejects. */
  async send(message: Record<string, unknown>): Promise<unknown> {
    const type = String(message.type).replace("device_links/", "");
    switch (type) {
      case "profiles/list":
        return { active_profile_id: "profile-main", profiles: PROFILES };
      case "profiles/get":
        return { profile: PROFILES[0], rules: this.rules };
      case "profiles/activate":
        return { profile_id: message.profile_id, plan: this.plan([]) };
      case "profiles/export":
        return {
          profile_id: message.profile_id,
          name: "House",
          yaml: "id: profile-main\nname: House\nrules:\n  - id: rule-bedside\n    name: Bedside pair from the paddle\n",
        };
      case "profiles/import":
        return { profile: PROFILES[0], is_active: false };
      case "profiles/create":
      case "profiles/update":
      case "profiles/duplicate":
        return { profile: PROFILES[1] };
      case "profiles/delete":
        return { profile_id: message.profile_id, deleted: true };
      case "devices/list":
        return { devices: DEVICES };
      case "devices/get":
      case "devices/refresh": {
        const detail = deviceDetail(String(message.device_id));
        if (detail === null) {
          throw { code: "unknown_device", message: "No such device." };
        }
        return { ...detail, deep_verified: message.deep === true ? false : detail.deep_verified };
      }
      case "templates/list":
        return {
          templates: [
            { id: "remote" },
            { id: "virtual_3way" },
            { id: "scene_button" },
            { id: "off_all" },
            { id: "status_feedback" },
            { id: "custom" },
          ],
        };
      case "rules/validate":
        return this.compile(message.rule as RuleData);
      case "rules/upsert": {
        const rule = message.rule as RuleData;
        const existing = this.rules.find((row) => row.rule.id === rule.id);
        if (existing === undefined) {
          this.rules = [
            ...this.rules,
            { rule, state: "pending", links_total: 0, links_in_sync: 0 },
          ];
        } else {
          existing.rule = rule;
          existing.state = rule.enabled ? "pending" : "disabled";
        }
        return { rule, state: "pending", links_total: 0, links_in_sync: 0 };
      }
      case "rules/delete":
        this.rules = this.rules.filter((row) => row.rule.id !== message.rule_id);
        return { rule_id: message.rule_id, deleted: true };
      case "rules/set_enabled":
        return { rule_id: message.rule_id, enabled: message.enabled, rate_limited: false };
      case "plan":
        return this.plan((message.remove_unmanaged as string[]) ?? []);
      case "apply":
        return this.apply(String(message.plan_token));
      case "verify":
        return { devices: 9, rules: { "rule-bedside": "in_sync" } };
      case "jobs/list":
        return {
          jobs: this.jobs,
          running:
            this.running === null ? null : { ...this.running, devices_in_flight: [name(36)] },
        };
      case "jobs/get":
        return this.jobs.find((job) => job.id === message.job_id) ?? this.jobs[0];
      case "jobs/cancel":
        this.finish("cancelled");
        return { cancelled: true };
      case "unmanaged/ignore":
        return { ignored: message.ignored === true ? message.fingerprints : [] };
      case "unmanaged/remove":
        return { job_id: "job-3", status: "completed" };
      case "snapshots/list":
        return { snapshots: SNAPSHOTS };
      default:
        throw { code: "unknown_command", message: `The harness has no answer for ${type}.` };
    }
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private compile(rule: RuleData): CompiledRule {
    const source = DEVICES.find((device) => device.identity === rule.source.device);
    const detail = source?.device_id === null ? null : deviceDetail(source?.device_id ?? "");
    const emitter = detail?.emitters.find(
      (candidate) => candidate.emitter_id === rule.source.emitter_id,
    );
    const links = rule.targets.flatMap((target) =>
      rule.features.flatMap((feature) => {
        const group = emitter?.actions[feature];
        if (group === undefined) {
          return [];
        }
        const targetRow = DEVICES.find((device) => device.identity === target.device);
        return [
          {
            fingerprint: ["zwave", rule.source.device, "0", group, target.device, "", feature].join(
              "|",
            ),
            backend: "zwave" as const,
            feature,
            emitter_id: rule.source.emitter_id,
            emitter_group: group,
            source: {
              identity: rule.source.device,
              protocol_id: source?.protocol_id ?? "",
              name: source?.name ?? rule.source.device,
              device_id: source?.device_id ?? null,
              endpoint: 0,
            },
            target: {
              identity: target.device,
              protocol_id: targetRow?.protocol_id ?? "",
              name: targetRow?.name ?? target.device,
              device_id: targetRow?.device_id ?? null,
              endpoint: target.endpoint,
            },
            rule_id: rule.id,
            rule_name: rule.name,
            is_system: false,
            managed_by: null,
          },
        ];
      }),
    );
    const warnings = [];
    const errors = [];
    if (rule.template === "off_all" && emitter?.semantics === "unknown") {
      warnings.push({
        translation_key: "button_semantics_unknown",
        placeholders: { emitter: emitter.label, device: source?.name ?? "" },
      });
    }
    if (links.length === 0) {
      errors.push({
        translation_key: "feature_unavailable_on_off",
        placeholders: { emitter: emitter?.label ?? rule.source.emitter_id, feature: "on_off" },
      });
    }
    return {
      links,
      // The harness compiles no HA-executed legs: the option is off in it, which is the
      // shipped default, so what it renders is what a user sees before they opt in.
      hybrid_legs: [],
      settings:
        rule.mirror_source === "leave"
          ? []
          : [
              {
                device_identity: rule.source.device,
                capability: "mirror_hub_commands",
                parameter: 35,
                bitmask: 4,
                value: rule.mirror_source === "on" ? 1 : 0,
              },
            ],
      warnings,
      errors,
    };
  }

  private plan(removeUnmanaged: string[]): Plan {
    this.token = `plan-${removeUnmanaged.length}-${Date.now()}`;
    const detail36 = deviceDetail("ha36");
    const wanted = detail36?.links[1];
    const foreign = unmanaged();
    const removed = removeUnmanaged.includes(foreign.fingerprint);
    const adds =
      wanted === undefined
        ? []
        : [
            planItem("add", {
              ...wanted,
              target: { ...wanted.target, identity: identity(21), name: name(21) },
              emitter_group: "7",
              emitter_id: "button_2",
              rule_id: "rule-offall",
              rule_name: "Goodnight, everything off",
            }),
          ];
    const sleeping =
      wanted === undefined
        ? []
        : [
            planItem("pending", {
              ...wanted,
              source: { ...wanted.source, identity: identity(40), name: name(40) },
              emitter_group: "2",
            }),
          ];
    const devices: PlanDevice[] = [
      planDevice(36, {
        add: adds,
        set_param: [
          {
            op: "set_param",
            device_identity: identity(36),
            link: null,
            setting: {
              device_identity: identity(36),
              capability: "mirror_hub_commands",
              parameter: 35,
              bitmask: 4,
              value: 0,
            },
            reason: null,
          },
        ],
        unmanaged: [foreign],
        remove: removed ? [planItem("remove", foreign)] : [],
      }),
      planDevice(37, { blocked: [blockedLink()] }),
      planDevice(40, { pending: sleeping }),
      planDevice(29),
    ];
    const counts = devices.reduce(
      (total, device) => ({
        add: total.add + device.add.length,
        remove: total.remove + device.remove.length,
        set_param: total.set_param + device.set_param.length,
        blocked: total.blocked + device.blocked.length,
        pending: total.pending + device.pending.length,
        unmanaged: total.unmanaged + device.unmanaged.length,
      }),
      { add: 0, remove: 0, set_param: 0, blocked: 0, pending: 0, unmanaged: 0 },
    );
    return {
      token: this.token,
      is_empty: counts.add + counts.remove + counts.set_param === 0,
      unchanged_count: 7,
      counts,
      devices,
    };
  }

  private apply(token: string): { job_id: string; status: string } {
    if (token !== this.token) {
      throw {
        code: "plan_out_of_date",
        message: "This plan was made before something changed, so nothing was written.",
        translation_key: "plan_out_of_date",
        translation_placeholders: {},
      };
    }
    const id = `job-${this.jobs.length + 1}`;
    this.running = { id, total: 4, completed: 0 };
    this.emit({ type: "progress", job: { ...this.running, devices_in_flight: [name(36)] } });
    this.timer = setInterval(() => {
      if (this.running === null) {
        return;
      }
      this.running.completed += 1;
      if (this.running.completed >= this.running.total) {
        this.finish("completed");
        return;
      }
      this.emit({
        type: "progress",
        job: { ...this.running, devices_in_flight: [name(36), name(37)] },
      });
    }, 700);
    return { job_id: id, status: "running" };
  }

  private finish(status: "completed" | "cancelled"): void {
    clearInterval(this.timer);
    const running = this.running;
    this.running = null;
    if (running === null) {
      return;
    }
    const job: Job = {
      id: running.id,
      created_at: new Date().toISOString(),
      scope: "Goodnight, everything off",
      status: status === "cancelled" ? "cancelled" : "completed",
      total: running.total,
      results: [],
    };
    this.jobs = [job, ...this.jobs];
    this.emit({ type: "progress", job: null });
    this.emit({
      type: "finished",
      job: {
        id: running.id,
        scope: job.scope,
        status: job.status,
        created_at: job.created_at,
        total: running.total,
        results:
          status === "cancelled"
            ? { applied: running.completed, cancelled: running.total - running.completed }
            : { applied: 3, pending_wakeup: 1 },
        rule_ids: ["rule-offall"],
      },
    });
  }

  private emit(event: JobEvent): void {
    for (const listener of [...this.listeners]) {
      listener(event);
    }
  }
}
