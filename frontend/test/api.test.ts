import { beforeEach, describe, expect, it, vi } from "vitest";

import { COMMANDS, DeviceLinksApi, DeviceLinksApiError, describeError } from "../src/api";
import type { RuleData } from "../src/types";
import { type MockHass, mockHass } from "./mock-hass";

function client(options?: Parameters<typeof mockHass>[0]): {
  api: DeviceLinksApi;
  hass: MockHass;
} {
  const hass = mockHass(options);
  return { api: new DeviceLinksApi(hass), hass };
}

const A_RULE: RuleData = {
  id: "bedroom-main",
  name: "036 main button controls Master Bedroom Lights",
  template: "remote",
  backend: "zwave",
  enabled: true,
  direction: "one_way",
  mirror_source: "leave",
  features: ["on_off", "level_set"],
  source: { device: "zwave:0xd4f2a1b3:36", endpoint: 0, emitter_id: "g2" },
  targets: [{ device: "zwave:0xd4f2a1b3:37", endpoint: null }],
};

describe("the command each wrapper sends", () => {
  let api: DeviceLinksApi;
  let hass: MockHass;

  beforeEach(() => {
    ({ api, hass } = client());
  });

  it("lists profiles and keeps both fields, because both are shown", async () => {
    hass.results.set(COMMANDS.profilesList, {
      active_profile_id: "bedroom",
      profiles: [{ id: "bedroom", name: "Bedroom", rules: 2, enabled_rules: 1, is_active: true }],
    });
    const result = await api.listProfiles();
    expect(hass.sent).toEqual([{ type: "device_links/profiles/list" }]);
    expect(result.active_profile_id).toBe("bedroom");
    expect(result.profiles).toHaveLength(1);
  });

  it("unwraps the profile a write answers with", async () => {
    const profile = { id: "b", name: "B", rules: 0, enabled_rules: 0, is_active: false };
    hass.results.set(COMMANDS.profilesCreate, { profile });
    await expect(api.createProfile({ id: "b", name: "B", rules: [] })).resolves.toEqual(profile);
    expect(hass.sent[0]).toEqual({
      type: "device_links/profiles/create",
      profile: { id: "b", name: "B", rules: [] },
    });
  });

  it("sends the profile id every profile command is about", async () => {
    hass.results.set(COMMANDS.profilesGet, { profile: {}, rules: [] });
    await api.getProfile("bedroom");
    await api.deleteProfile("bedroom");
    await api.activateProfile("bedroom");
    expect(hass.sent.map((message) => message.type)).toEqual([
      "device_links/profiles/get",
      "device_links/profiles/delete",
      "device_links/profiles/activate",
    ]);
    expect(hass.sent.every((message) => message.profile_id === "bedroom")).toBe(true);
  });

  it("leaves an optional name out of a duplicate rather than sending undefined", async () => {
    hass.results.set(COMMANDS.profilesDuplicate, { profile: {} });
    await api.duplicateProfile("bedroom");
    expect(hass.sent[0]).toEqual({
      type: "device_links/profiles/duplicate",
      profile_id: "bedroom",
    });
    await api.duplicateProfile("bedroom", "Guests");
    expect(hass.sent[1]).toMatchObject({ name: "Guests" });
  });

  it("exports the active profile when no id is given", async () => {
    hass.results.set(COMMANDS.profilesExport, { profile_id: "a", name: "A", yaml: "x" });
    await api.exportProfile();
    expect(hass.sent[0]).toEqual({ type: "device_links/profiles/export" });
  });

  it("validates a rule without storing it, and returns warnings as a result", async () => {
    hass.results.set(COMMANDS.rulesValidate, {
      links: [],
      settings: [],
      warnings: [{ translation_key: "button_semantics_unknown", placeholders: {} }],
      errors: [],
    });
    const compiled = await api.validateRule(A_RULE);
    expect(hass.sent[0]).toEqual({ type: "device_links/rules/validate", rule: A_RULE });
    expect(compiled.warnings).toHaveLength(1);
  });

  it("upserts a rule into the active profile unless one is named", async () => {
    hass.results.set(COMMANDS.rulesUpsert, { rule: A_RULE, state: "unknown" });
    await api.upsertRule(A_RULE);
    expect(hass.sent[0]).toEqual({ type: "device_links/rules/upsert", rule: A_RULE });
    await api.upsertRule(A_RULE, "guests");
    expect(hass.sent[1]).toMatchObject({ profile_id: "guests" });
  });

  it("reports that a rule toggle was rate limited rather than lost", async () => {
    hass.results.set(COMMANDS.rulesSetEnabled, {
      rule_id: "bedroom-main",
      enabled: false,
      rate_limited: true,
    });
    const result = await api.setRuleEnabled("bedroom-main", false);
    expect(hass.sent[0]).toEqual({
      type: "device_links/rules/set_enabled",
      rule_id: "bedroom-main",
      enabled: false,
    });
    expect(result.rate_limited).toBe(true);
  });

  it("unwraps the device list", async () => {
    hass.results.set(COMMANDS.devicesList, { devices: [{ identity: "zwave:1:36" }] });
    await expect(api.listDevices()).resolves.toEqual([{ identity: "zwave:1:36" }]);
  });

  it("asks the device itself only when deep is set", async () => {
    hass.results.set(COMMANDS.devicesRefresh, {});
    await api.refreshDevice("dev1");
    await api.refreshDevice("dev1", true);
    expect(hass.sent[0]).toEqual({
      type: "device_links/devices/refresh",
      device_id: "dev1",
      deep: false,
    });
    expect(hass.sent[1]).toMatchObject({ deep: true });
  });

  it("unwraps the template list", async () => {
    hass.results.set(COMMANDS.templatesList, { templates: [{ id: "remote" }] });
    await expect(api.listTemplates()).resolves.toEqual([{ id: "remote" }]);
  });

  it("plans over everything when no scope names anything", async () => {
    hass.results.set(COMMANDS.plan, { token: "t", is_empty: true });
    await api.plan();
    await api.plan({ rule_ids: [], device_ids: [] });
    expect(hass.sent[0]).toEqual({ type: "device_links/plan" });
    expect(hass.sent[1]).toEqual({ type: "device_links/plan" });
  });

  it("sends only the scope keys that name something", async () => {
    hass.results.set(COMMANDS.plan, {});
    await api.plan({ device_ids: ["dev1"] }, ["fp1"]);
    expect(hass.sent[0]).toEqual({
      type: "device_links/plan",
      device_ids: ["dev1"],
      remove_unmanaged: ["fp1"],
    });
  });

  it("applies with the token of the plan the user looked at", async () => {
    hass.results.set(COMMANDS.apply, { job_id: "j1", status: "running" });
    const started = await api.apply({ planToken: "tok", scope: { rule_ids: ["r1"] } });
    expect(hass.sent[0]).toEqual({
      type: "device_links/apply",
      plan_token: "tok",
      rule_ids: ["r1"],
    });
    expect(started.job_id).toBe("j1");
  });

  it("reports an empty apply as nothing_to_do with no job", async () => {
    hass.results.set(COMMANDS.apply, { job_id: null, status: "nothing_to_do" });
    const started = await api.apply({ planToken: "tok" });
    expect(started).toEqual({ job_id: null, status: "nothing_to_do" });
  });

  it("verifies without writing, over the scope it is given", async () => {
    hass.results.set(COMMANDS.verify, { devices: 3, rules: { r1: "in_sync" } });
    const result = await api.verify({ rule_ids: ["r1"] });
    expect(hass.sent[0]).toEqual({ type: "device_links/verify", rule_ids: ["r1"] });
    expect(result.rules.r1).toBe("in_sync");
  });

  it("lists jobs with whichever one is running", async () => {
    hass.results.set(COMMANDS.jobsList, {
      jobs: [],
      running: { id: "j1", total: 4, completed: 1 },
    });
    const result = await api.listJobs();
    expect(result.running?.completed).toBe(1);
  });

  it("unwraps the cancelled flag", async () => {
    hass.results.set(COMMANDS.jobsCancel, { cancelled: true });
    await expect(api.cancelJob()).resolves.toBe(true);
    expect(hass.sent[0]).toEqual({ type: "device_links/jobs/cancel" });
  });

  it("ignores and un-ignores unmanaged links by fingerprint", async () => {
    hass.results.set(COMMANDS.unmanagedIgnore, { ignored: ["fp1"] });
    await expect(api.setUnmanagedIgnored(["fp1"], true)).resolves.toEqual(["fp1"]);
    expect(hass.sent[0]).toEqual({
      type: "device_links/unmanaged/ignore",
      fingerprints: ["fp1"],
      ignored: true,
    });
  });

  it("removes only the fingerprints it was given", async () => {
    hass.results.set(COMMANDS.unmanagedRemove, { job_id: "j2", status: "completed" });
    await api.removeUnmanaged(["fp1", "fp2"]);
    expect(hass.sent[0]).toEqual({
      type: "device_links/unmanaged/remove",
      fingerprints: ["fp1", "fp2"],
    });
  });

  it("unwraps the snapshot list", async () => {
    hass.results.set(COMMANDS.snapshotsList, { snapshots: [{ id: "s1" }] });
    await expect(api.listSnapshots()).resolves.toEqual([{ id: "s1" }]);
  });

  it("gets one job by id", async () => {
    hass.results.set(COMMANDS.jobsGet, { id: "j1", results: [] });
    await api.getJob("j1");
    expect(hass.sent[0]).toEqual({ type: "device_links/jobs/get", job_id: "j1" });
  });

  it("deletes a rule from the active profile unless one is named", async () => {
    hass.results.set(COMMANDS.rulesDelete, { rule_id: "r1", deleted: true });
    await api.deleteRule("r1");
    expect(hass.sent[0]).toEqual({ type: "device_links/rules/delete", rule_id: "r1" });
  });

  it("imports and updates a profile", async () => {
    hass.results.set(COMMANDS.profilesImport, { profile: {}, is_active: false });
    await api.importProfile("id: a\n");
    expect(hass.sent[0]).toEqual({ type: "device_links/profiles/import", yaml: "id: a\n" });
    hass.results.set(COMMANDS.profilesUpdate, { profile: { id: "a" } });
    await api.updateProfile({ id: "a", name: "A", rules: [] });
    expect(hass.sent[1]?.type).toBe("device_links/profiles/update");
  });

  it("gets one device by its Home Assistant device id", async () => {
    hass.results.set(COMMANDS.devicesGet, { device: {}, emitters: [] });
    await api.getDevice("dev1");
    expect(hass.sent[0]).toEqual({ type: "device_links/devices/get", device_id: "dev1" });
  });
});

describe("what a rejected command becomes", () => {
  it("keeps the code, the message and the translation key Home Assistant sent", async () => {
    const { api, hass } = client();
    hass.failures.set(COMMANDS.apply, {
      code: "home_assistant_error",
      message: "this plan was built against a state that has since changed",
      translation_key: "plan_out_of_date",
      translation_domain: "device_links",
      translation_placeholders: null,
    });
    const error = await api.apply({ planToken: "stale" }).catch((caught) => caught);
    expect(error).toBeInstanceOf(DeviceLinksApiError);
    expect(error.code).toBe("home_assistant_error");
    expect(error.translationKey).toBe("plan_out_of_date");
    expect(error.message).toContain("since changed");
  });

  it("turns a dropped connection into a sentence rather than [object Object]", async () => {
    const { api, hass } = client();
    hass.failures.set(COMMANDS.plan, undefined);
    const error = await api.plan().catch((caught) => caught);
    expect(error).toBeInstanceOf(DeviceLinksApiError);
    expect(error.code).toBe("connection_error");
    expect(error.message).toContain("connection to Home Assistant");
  });

  it("keeps a thrown Error's own message", async () => {
    const { api, hass } = client();
    hass.failures.set(COMMANDS.plan, new Error("socket closed"));
    const error = await api.plan().catch((caught) => caught);
    expect(error.message).toBe("socket closed");
    expect(error.code).toBe("connection_error");
  });

  it("never re-wraps one of its own", () => {
    const original = new DeviceLinksApiError("already ours");
    expect(DeviceLinksApiError.from(original)).toBe(original);
  });

  it("prefers the localised text for the key over the backend's English", () => {
    const hass = mockHass({
      translations: {
        "component.device_links.exceptions.group_full.message": "Gruppe {group} ist voll",
      },
    });
    const error = new DeviceLinksApiError("Group 7 is full", {
      translationKey: "group_full",
      placeholders: { group: "7" },
    });
    expect(describeError(hass, error)).toBe("Gruppe 7 ist voll");
  });

  it("falls back to the message it was given, with placeholders filled", () => {
    const error = new DeviceLinksApiError("no rule has the id {rule}", {
      translationKey: "no_such_thing_anywhere",
      placeholders: { rule: "r9" },
    });
    expect(describeError(null, error)).toBe("no rule has the id r9");
  });
});

describe("the jobs subscription", () => {
  it("subscribes with the right command and delivers events", async () => {
    const { api, hass } = client();
    const seen: unknown[] = [];
    const subscription = api.subscribeJobs((event) => seen.push(event));
    await Promise.resolve();
    expect(hass.subscriptions).toEqual([{ type: "device_links/jobs/subscribe" }]);
    hass.emit({ type: "progress", job: null });
    expect(seen).toEqual([{ type: "progress", job: null }]);
    subscription.unsubscribe();
    expect(hass.unsubscribes).toBe(1);
  });

  it("stops delivering the moment it is unsubscribed", async () => {
    const { api, hass } = client();
    const seen: unknown[] = [];
    const subscription = api.subscribeJobs((event) => seen.push(event));
    await Promise.resolve();
    subscription.unsubscribe();
    hass.emit({ type: "progress", job: null });
    expect(seen).toEqual([]);
    expect(subscription.closed).toBe(true);
  });

  it("unsubscribing twice does not unsubscribe twice", async () => {
    const { api, hass } = client();
    const subscription = api.subscribeJobs(() => undefined);
    await Promise.resolve();
    subscription.unsubscribe();
    subscription.unsubscribe();
    expect(hass.unsubscribes).toBe(1);
  });

  it("unsubscribing before the server answered still unsubscribes", async () => {
    const { api, hass } = client({ deferSubscribe: true });
    const subscription = api.subscribeJobs(() => undefined);
    subscription.unsubscribe();
    expect(hass.unsubscribes).toBe(0);
    await hass.settleSubscribe();
    expect(hass.unsubscribes).toBe(1);
  });

  it("reports a subscription that could not start, and closes itself", async () => {
    const { api } = client({ subscribeFails: { code: "unauthorized", message: "Unauthorized" } });
    const errors: DeviceLinksApiError[] = [];
    const subscription = api.subscribeJobs(
      () => undefined,
      (error) => errors.push(error),
    );
    await Promise.resolve();
    await Promise.resolve();
    expect(errors).toHaveLength(1);
    expect(errors[0]?.code).toBe("unauthorized");
    expect(subscription.closed).toBe(true);
  });

  it("close() ends every subscription the client started", async () => {
    const { api, hass } = client();
    const first = api.subscribeJobs(() => undefined);
    const second = api.subscribeJobs(() => undefined);
    await Promise.resolve();
    api.close();
    expect(hass.unsubscribes).toBe(2);
    expect(first.closed && second.closed).toBe(true);
  });

  it("swallows an unsubscribe that fails because the connection already went", async () => {
    const hass = mockHass();
    const api = new DeviceLinksApi(hass);
    vi.spyOn(hass.connection, "subscribeMessage").mockResolvedValue(() => {
      throw new Error("connection closed");
    });
    const subscription = api.subscribeJobs(() => undefined);
    await Promise.resolve();
    expect(() => subscription.unsubscribe()).not.toThrow();
  });
});
