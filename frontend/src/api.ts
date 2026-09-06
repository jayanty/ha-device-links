/**
 * The panel's only route to the backend: a typed wrapper over the Phase 1D WebSocket API.
 *
 * Nothing else in this panel is allowed to reach Home Assistant. Not the REST API, not
 * `hass.states`, not a second connection. Everything the UI can show is something
 * `custom_components/device_links/websocket.py` answers, and if a view needs something
 * that file does not expose, that is a gap to fix there rather than to work around here.
 *
 * **Every command name lives in `COMMANDS`.** A Python test reads the command strings out
 * of this file and asserts that each one is registered by the backend and that none of
 * them is on its deferred list, so a command that was renamed on the Python side fails the
 * suite rather than failing in somebody's browser.
 *
 * **Errors arrive as a payload, not as an `Error`.** Home Assistant rejects with a plain
 * object carrying `code`, `message` and, when the handler raised a translated exception,
 * `translation_key` and its placeholders. `DeviceLinksApiError` normalises all of that,
 * including the rejections that are not that shape at all, so no view has to guess what it
 * caught.
 *
 * **A subscription is owned by whoever started it.** `subscribeJobs` hands back a handle
 * with `unsubscribe`, and the client keeps every live one so `close()` can end them all
 * when the panel goes away. A subscription that outlives its view keeps firing into a
 * component that is no longer in the document, which in a panel somebody leaves open all
 * day is a leak and a stream of errors rather than an untidiness.
 */

import type { HassErrorPayload, HomeAssistant } from "./hass";
import { fillPlaceholders, lookupMessage } from "./messages";
import type {
  DeviceDetail,
  DeviceRow,
  Job,
  JobEvent,
  JobList,
  JobStarted,
  Plan,
  ProfileActivation,
  ProfileDetail,
  ProfileExport,
  ProfileImport,
  ProfileList,
  ProfileRow,
  RuleData,
  RuleEnabled,
  RuleRow,
  RuleValidation,
  Snapshot,
  SnapshotRollback,
  TemplateRow,
  VerifyResult,
} from "./types";

/**
 * Every command the panel sends, spelled once.
 *
 * The full `device_links/...` string is written out rather than assembled from a prefix,
 * because the check that keeps this file honest against the backend works by reading these
 * literals, and a name built at runtime is a name that check cannot see.
 */
export const COMMANDS = {
  profilesList: "device_links/profiles/list",
  profilesGet: "device_links/profiles/get",
  profilesCreate: "device_links/profiles/create",
  profilesUpdate: "device_links/profiles/update",
  profilesDelete: "device_links/profiles/delete",
  profilesActivate: "device_links/profiles/activate",
  profilesDuplicate: "device_links/profiles/duplicate",
  profilesExport: "device_links/profiles/export",
  profilesImport: "device_links/profiles/import",
  rulesValidate: "device_links/rules/validate",
  rulesUpsert: "device_links/rules/upsert",
  rulesDelete: "device_links/rules/delete",
  rulesSetEnabled: "device_links/rules/set_enabled",
  devicesList: "device_links/devices/list",
  devicesGet: "device_links/devices/get",
  devicesRefresh: "device_links/devices/refresh",
  templatesList: "device_links/templates/list",
  plan: "device_links/plan",
  apply: "device_links/apply",
  verify: "device_links/verify",
  jobsList: "device_links/jobs/list",
  jobsGet: "device_links/jobs/get",
  jobsCancel: "device_links/jobs/cancel",
  jobsSubscribe: "device_links/jobs/subscribe",
  unmanagedIgnore: "device_links/unmanaged/ignore",
  unmanagedRemove: "device_links/unmanaged/remove",
  snapshotsList: "device_links/snapshots/list",
  snapshotsRollback: "device_links/snapshots/rollback",
} as const;

/** The part of a plan or an apply that says which rules and devices it is about. */
export interface PlanScope {
  rule_ids?: readonly string[];
  device_ids?: readonly string[];
}

/** What `profiles/create` and `profiles/update` take. Devices are resolved by the backend. */
export interface ProfileInput {
  id: string;
  name: string;
  rules: RuleData[];
}

/** A live subscription, and the one way to end it. */
export interface Subscription {
  /** True once `unsubscribe` has been called, or once the subscription failed to start. */
  readonly closed: boolean;
  unsubscribe(): void;
}

/**
 * What the panel throws, whatever the backend rejected with.
 *
 * `message` is always a sentence somebody can read: the backend's own, or the translated
 * text for `translationKey` when the backend sent one, and never a bare key. `code` is
 * kept so a view can tell "not admin" from "no config entry loaded" without matching on
 * prose.
 */
export class DeviceLinksApiError extends Error {
  readonly code: string;
  readonly translationKey: string | null;
  readonly translationDomain: string | null;
  readonly placeholders: Record<string, string>;

  constructor(
    message: string,
    options: {
      code?: string;
      translationKey?: string | null;
      translationDomain?: string | null;
      placeholders?: Record<string, string> | null;
    } = {},
  ) {
    super(message);
    this.name = "DeviceLinksApiError";
    this.code = options.code ?? "unknown_error";
    this.translationKey = options.translationKey ?? null;
    this.translationDomain = options.translationDomain ?? null;
    this.placeholders = options.placeholders ?? {};
  }

  /**
   * Normalise anything a rejected command can produce into one of these.
   *
   * The interesting case is the middle one: Home Assistant rejects with a plain object,
   * so `instanceof Error` is false and a naive `catch` would render `[object Object]`.
   */
  static from(error: unknown): DeviceLinksApiError {
    if (error instanceof DeviceLinksApiError) {
      return error;
    }
    if (isHassErrorPayload(error)) {
      return new DeviceLinksApiError(error.message || "Device Links could not answer.", {
        code: error.code,
        translationKey: error.translation_key ?? null,
        translationDomain: error.translation_domain ?? null,
        placeholders: (error.translation_placeholders as Record<string, string>) ?? null,
      });
    }
    if (error instanceof Error) {
      return new DeviceLinksApiError(error.message || "Device Links could not answer.", {
        code: "connection_error",
      });
    }
    return new DeviceLinksApiError(
      "Device Links could not answer, and gave no reason. The connection to Home Assistant may have dropped.",
      { code: "connection_error" },
    );
  }
}

function isHassErrorPayload(value: unknown): value is HassErrorPayload {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === "string" && typeof candidate.message === "string";
}

/**
 * Return the best sentence for an error, localised when Home Assistant can localise it.
 *
 * Kept out of the error class so the class stays free of `hass`: the error is thrown in
 * places that have no panel around them, and the wording is chosen where it is shown.
 */
export function describeError(
  hass: HomeAssistant | null | undefined,
  error: DeviceLinksApiError,
): string {
  if (error.translationKey) {
    const translated = lookupMessage(hass, error.translationKey, error.placeholders);
    if (translated !== null) {
      return translated;
    }
  }
  return fillPlaceholders(error.message, error.placeholders);
}

/** Drop the scope keys that name nothing, so an empty selection is not sent as one. */
function scopeMessage(scope: PlanScope | undefined): Record<string, unknown> {
  const message: Record<string, unknown> = {};
  if (scope?.rule_ids?.length) {
    message.rule_ids = [...scope.rule_ids];
  }
  if (scope?.device_ids?.length) {
    message.device_ids = [...scope.device_ids];
  }
  return message;
}

/** The typed client. One per panel; the shell keeps `hass` on it up to date. */
export class DeviceLinksApi {
  hass: HomeAssistant;

  private readonly open = new Set<Subscription>();

  constructor(hass: HomeAssistant) {
    this.hass = hass;
  }

  // Profiles.

  async listProfiles(): Promise<ProfileList> {
    return this.send<ProfileList>(COMMANDS.profilesList);
  }

  async getProfile(profileId: string): Promise<ProfileDetail> {
    return this.send<ProfileDetail>(COMMANDS.profilesGet, { profile_id: profileId });
  }

  async createProfile(profile: ProfileInput): Promise<ProfileRow> {
    const result = await this.send<{ profile: ProfileRow }>(COMMANDS.profilesCreate, { profile });
    return result.profile;
  }

  async updateProfile(profile: ProfileInput): Promise<ProfileRow> {
    const result = await this.send<{ profile: ProfileRow }>(COMMANDS.profilesUpdate, { profile });
    return result.profile;
  }

  async deleteProfile(profileId: string): Promise<void> {
    await this.send<{ profile_id: string; deleted: boolean }>(COMMANDS.profilesDelete, {
      profile_id: profileId,
    });
  }

  /**
   * Make a profile the active one.
   *
   * Answers with the plan activating it opened, and writes to no device: FR-E1 makes
   * activating a decision about what should be true and applying it a separate act, so
   * the caller shows that plan rather than acting on it.
   */
  async activateProfile(profileId: string): Promise<ProfileActivation> {
    return this.send<ProfileActivation>(COMMANDS.profilesActivate, { profile_id: profileId });
  }

  async duplicateProfile(profileId: string, name?: string): Promise<ProfileRow> {
    const result = await this.send<{ profile: ProfileRow }>(COMMANDS.profilesDuplicate, {
      profile_id: profileId,
      ...(name === undefined ? {} : { name }),
    });
    return result.profile;
  }

  /** Export a profile as YAML. With no id, the active profile. */
  async exportProfile(profileId?: string): Promise<ProfileExport> {
    return this.send<ProfileExport>(COMMANDS.profilesExport, {
      ...(profileId === undefined ? {} : { profile_id: profileId }),
    });
  }

  async importProfile(yaml: string): Promise<ProfileImport> {
    return this.send<ProfileImport>(COMMANDS.profilesImport, { yaml });
  }

  // Rules.

  /**
   * Compile a rule against the devices as they are now, and store nothing.
   *
   * Warnings and errors come back as a result rather than as a rejection, deliberately: a
   * rule the compiler refuses is the answer to "will this work?", and the editor shows the
   * reason beside the rule the user is still editing.
   */
  async validateRule(rule: RuleData): Promise<RuleValidation> {
    return this.send<RuleValidation>(COMMANDS.rulesValidate, { rule });
  }

  async upsertRule(rule: RuleData, profileId?: string): Promise<RuleRow> {
    return this.send<RuleRow>(COMMANDS.rulesUpsert, {
      rule,
      ...(profileId === undefined ? {} : { profile_id: profileId }),
    });
  }

  async deleteRule(ruleId: string, profileId?: string): Promise<void> {
    await this.send<{ rule_id: string; deleted: boolean }>(COMMANDS.rulesDelete, {
      rule_id: ruleId,
      ...(profileId === undefined ? {} : { profile_id: profileId }),
    });
  }

  /**
   * Enable or disable one rule, which physically adds or removes its links (D7).
   *
   * `rate_limited` in the answer means the toggle was accepted and deferred by the shared
   * limiter, not that it was lost. Say so rather than showing the switch snapping back.
   */
  async setRuleEnabled(ruleId: string, enabled: boolean): Promise<RuleEnabled> {
    return this.send<RuleEnabled>(COMMANDS.rulesSetEnabled, { rule_id: ruleId, enabled });
  }

  // Devices and templates.

  async listDevices(): Promise<DeviceRow[]> {
    const result = await this.send<{ devices: DeviceRow[] }>(COMMANDS.devicesList);
    return result.devices;
  }

  async getDevice(deviceId: string): Promise<DeviceDetail> {
    return this.send<DeviceDetail>(COMMANDS.devicesGet, { device_id: deviceId });
  }

  /** Re-read one device. `deep` asks the device itself rather than the driver's cache. */
  async refreshDevice(deviceId: string, deep = false): Promise<DeviceDetail> {
    return this.send<DeviceDetail>(COMMANDS.devicesRefresh, { device_id: deviceId, deep });
  }

  async listTemplates(): Promise<TemplateRow[]> {
    const result = await this.send<{ templates: TemplateRow[] }>(COMMANDS.templatesList);
    return result.templates;
  }

  // Plan, apply, verify.

  /** What applying this scope would do, without doing any of it. */
  async plan(scope?: PlanScope, removeUnmanaged?: readonly string[]): Promise<Plan> {
    return this.send<Plan>(COMMANDS.plan, {
      ...scopeMessage(scope),
      ...(removeUnmanaged?.length ? { remove_unmanaged: [...removeUnmanaged] } : {}),
    });
  }

  /**
   * Apply the plan this token names.
   *
   * The token is the plan the user looked at. The backend refuses a token that no longer
   * describes what would happen (FR-A3), which is the mechanism behind the rule that no
   * device is written to without a confirmed plan, so never compute or reuse one here:
   * pass back the token from the plan that was actually on screen.
   *
   * Returns as soon as the job has an id. Follow the work through `subscribeJobs`.
   */
  async apply(options: {
    planToken: string;
    scope?: PlanScope;
    removeUnmanaged?: readonly string[];
  }): Promise<JobStarted> {
    return this.send<JobStarted>(COMMANDS.apply, {
      plan_token: options.planToken,
      ...scopeMessage(options.scope),
      ...(options.removeUnmanaged?.length
        ? { remove_unmanaged: [...options.removeUnmanaged] }
        : {}),
    });
  }

  /** Re-read the devices in scope from the devices themselves. Never writes. */
  async verify(scope?: PlanScope): Promise<VerifyResult> {
    return this.send<VerifyResult>(COMMANDS.verify, scopeMessage(scope));
  }

  // Jobs.

  async listJobs(): Promise<JobList> {
    return this.send<JobList>(COMMANDS.jobsList);
  }

  async getJob(jobId: string): Promise<Job> {
    return this.send<Job>(COMMANDS.jobsGet, { job_id: jobId });
  }

  /** Stop the running job from starting anything else. What is in flight still finishes. */
  async cancelJob(): Promise<boolean> {
    const result = await this.send<{ cancelled: boolean }>(COMMANDS.jobsCancel);
    return result.cancelled;
  }

  /**
   * Follow every job, whatever started it.
   *
   * Returns straight away with a handle rather than a promise, so a component can hold it
   * in a field and end it in `disconnectedCallback` without awaiting anything. Three
   * things are handled here that a caller should not have to think about:
   *
   * - unsubscribing before the server has answered still unsubscribes, once it does;
   * - a callback already in flight when `unsubscribe` runs is dropped rather than
   *   delivered into a component that has gone;
   * - a subscription that fails to start reports through `onError` and closes itself,
   *   rather than leaving the caller holding a handle to nothing.
   */
  subscribeJobs(
    onEvent: (event: JobEvent) => void,
    onError?: (error: DeviceLinksApiError) => void,
  ): Subscription {
    const handle = {
      closed: false,
      unsubscribe: () => {
        if (handle.closed) {
          return;
        }
        handle.closed = true;
        this.open.delete(handle);
        detach();
      },
    };
    let remove: (() => void | Promise<void>) | null = null;
    const detach = () => {
      const stop = remove;
      remove = null;
      if (!stop) {
        return;
      }
      // Both halves of "it went wrong" are swallowed, and for the same reason: the
      // connection going away before the unsubscribe reached it has the same outcome as
      // the unsubscribe landing, which is that nothing is listening. What must not happen
      // is either one escaping, because this runs inside `disconnectedCallback` and a
      // throw there stops the rest of a component's teardown.
      try {
        void Promise.resolve(stop()).catch(() => undefined);
      } catch {
        // Threw synchronously rather than rejecting. Same outcome, same answer.
      }
    };

    this.open.add(handle);
    this.hass.connection
      .subscribeMessage<JobEvent>(
        (event) => {
          if (!handle.closed) {
            onEvent(event);
          }
        },
        { type: COMMANDS.jobsSubscribe },
      )
      .then((unsubscribe) => {
        remove = unsubscribe;
        if (handle.closed) {
          detach();
        }
      })
      .catch((error: unknown) => {
        handle.closed = true;
        this.open.delete(handle);
        onError?.(DeviceLinksApiError.from(error));
      });
    return handle;
  }

  /** End every subscription this client started. Call it when the panel goes away. */
  close(): void {
    for (const subscription of [...this.open]) {
      subscription.unsubscribe();
    }
  }

  // Unmanaged links and snapshots.

  /** Remember that the user does not care about these links, or forget it (FR-A5). */
  async setUnmanagedIgnored(fingerprints: readonly string[], ignored: boolean): Promise<string[]> {
    const result = await this.send<{ ignored: string[] }>(COMMANDS.unmanagedIgnore, {
      fingerprints: [...fingerprints],
      ignored,
    });
    return result.ignored;
  }

  /**
   * Take these links off their devices, and nothing else.
   *
   * Per link, by fingerprint, because that is the whole of the opt-in Decision D9 asks
   * for. Never send a fingerprint the user did not tick.
   */
  async removeUnmanaged(fingerprints: readonly string[]): Promise<JobStarted> {
    return this.send<JobStarted>(COMMANDS.unmanagedRemove, { fingerprints: [...fingerprints] });
  }

  async listSnapshots(): Promise<Snapshot[]> {
    const result = await this.send<{ snapshots: Snapshot[] }>(COMMANDS.snapshotsList);
    return result.snapshots;
  }

  /**
   * Put a snapshot's devices back as they were (FR-P3).
   *
   * Without `planToken` this writes nothing and answers with the plan, which is what the
   * dialog is opened on. With one, the token has to be the token of that plan, so the
   * work applied is the work somebody looked at. Never send a token from anywhere else.
   */
  async rollbackSnapshot(
    snapshotId: string,
    options: { planToken?: string; removeUnmanaged?: readonly string[] } = {},
  ): Promise<SnapshotRollback> {
    return this.send<SnapshotRollback>(COMMANDS.snapshotsRollback, {
      snapshot_id: snapshotId,
      ...(options.planToken === undefined ? {} : { plan_token: options.planToken }),
      ...(options.removeUnmanaged?.length
        ? { remove_unmanaged: [...options.removeUnmanaged] }
        : {}),
    });
  }

  /** Send one command, and turn whatever it rejects with into a `DeviceLinksApiError`. */
  private async send<T>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    try {
      return await this.hass.connection.sendMessagePromise<T>({ type, ...payload });
    } catch (error) {
      throw DeviceLinksApiError.from(error);
    }
  }
}
