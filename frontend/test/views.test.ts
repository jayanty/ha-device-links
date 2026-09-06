/**
 * The five views, and the promises each of them makes.
 *
 * The load in each case is a mock `hass` answering the same commands the backend answers,
 * so what is asserted is what a person would see: the chips on the Overview, the absence
 * of a Remove control beside a lifeline, the raw backend error kept under an expander, and
 * a rule switch that stores intent and asks for a plan rather than writing.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { COMMANDS, DeviceLinksApi } from "../src/api";
import { componentSet } from "../src/ha-components";
import type { DeviceLinksView } from "../src/views/view-base";
import {
  deviceDetail,
  deviceRow,
  job,
  link,
  plan,
  profileRow,
  ruleRow,
  SOURCE,
  snapshot,
} from "./fixtures";
import { type MockHass, mockHass } from "./mock-hass";

async function flush(): Promise<void> {
  for (let round = 0; round < 6; round += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

async function mount(tag: string, hass: MockHass, narrow = false): Promise<DeviceLinksView> {
  const view = document.createElement(tag) as DeviceLinksView;
  view.hass = hass;
  view.api = new DeviceLinksApi(hass);
  view.components = componentSet([]);
  view.narrow = narrow;
  document.body.append(view);
  await view.updateComplete;
  await flush();
  await view.updateComplete;
  return view;
}

function text(view: DeviceLinksView): string {
  return view.shadowRoot?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function buttons(view: DeviceLinksView): HTMLButtonElement[] {
  return [...(view.shadowRoot?.querySelectorAll("button") ?? [])];
}

/** The commands every view asks for on load, answered the way the backend would. */
function loaded(): MockHass {
  const hass = mockHass();
  hass.results.set(COMMANDS.profilesList, {
    active_profile_id: "p1",
    profiles: [profileRow(), profileRow({ id: "p2", name: "Guest mode", is_active: false })],
  });
  hass.results.set(COMMANDS.profilesGet, { profile: profileRow(), rules: [ruleRow()] });
  hass.results.set(COMMANDS.devicesList, {
    devices: [
      deviceRow(),
      deviceRow({ identity: "zwave:home:38", device_id: "ha38", name: "Bedside Light L" }),
      deviceRow({
        identity: "zwave:home:29",
        device_id: "ha29",
        name: "Mud Room Scene",
        available: false,
      }),
    ],
  });
  hass.results.set(COMMANDS.devicesGet, deviceDetail());
  hass.results.set(COMMANDS.devicesRefresh, deviceDetail());
  hass.results.set(COMMANDS.jobsList, { jobs: [job()], running: null });
  hass.results.set(COMMANDS.jobsGet, job());
  hass.results.set(COMMANDS.snapshotsList, { snapshots: [] });
  hass.results.set(COMMANDS.templatesList, { templates: [{ id: "remote" }, { id: "off_all" }] });
  hass.results.set(COMMANDS.plan, plan());
  return hass;
}

/** The Activity view with one snapshot on it, and a rollback the backend would answer. */
function withSnapshot(): MockHass {
  const hass = loaded();
  hass.results.set(COMMANDS.snapshotsList, { snapshots: [snapshot()] });
  hass.results.set(COMMANDS.snapshotsRollback, {
    snapshot: snapshot(),
    plan: plan(),
    returns_on_next_apply: [link({ rule_id: "rule-1", rule_name: "Goodnight, everything off" })],
    unreadable_devices: ["zwave:home:29"],
    job_id: null,
    status: "preview",
  });
  return hass;
}

beforeEach(async () => {
  await Promise.all([
    import("../src/views/overview"),
    import("../src/views/rules"),
    import("../src/views/devices"),
    import("../src/views/activity"),
    import("../src/views/profiles"),
  ]);
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("the overview", () => {
  it("says what the active profile is doing and what needs attention", async () => {
    const view = await mount("device-links-overview", loaded());
    const shown = text(view);

    expect(shown).toContain("House");
    expect(shown).toContain("Pending 1");
    expect(shown).toContain("Goodnight, everything off");
    expect(shown).toContain("This rule has links waiting to be written");
    // A device that cannot be read is an attention row of its own.
    expect(shown).toContain("Mud Room Scene");
    expect(shown).toContain("last successful read");
  });

  it("verifies without writing, and says when it last read", async () => {
    const hass = loaded();
    hass.results.set(COMMANDS.verify, { devices: 9, rules: {} });
    const view = await mount("device-links-overview", hass);

    buttons(view)
      .find((button) => button.textContent?.trim() === "Verify")
      ?.click();
    await flush();
    await view.updateComplete;

    expect(hass.sent.some((message) => message.type === COMMANDS.verify)).toBe(true);
    expect(hass.sent.some((message) => message.type === COMMANDS.apply)).toBe(false);
    expect(text(view)).toContain("9 devices re-read");
  });

  it("opens a plan rather than applying when Plan and apply is pressed", async () => {
    const hass = loaded();
    const view = await mount("device-links-overview", hass);

    buttons(view)
      .find((button) => button.textContent?.includes("Plan and apply"))
      ?.click();
    await flush();

    expect(hass.sent.some((message) => message.type === COMMANDS.plan)).toBe(true);
    expect(hass.sent.some((message) => message.type === COMMANDS.apply)).toBe(false);
  });
});

describe("the rules table", () => {
  it("lists each rule with its state and its source control's label", async () => {
    const view = await mount("device-links-rules", loaded());
    const shown = text(view);

    expect(shown).toContain("Goodnight, everything off");
    expect(shown).toContain("Off all");
    expect(shown).toContain("Pending");
    // The control's own label, read from the device, rather than the stored emitter id.
    expect(shown).toContain("Button 2");
    expect(shown).not.toContain("button_2");
  });

  it("stores the switch and opens a plan rather than writing to the device", async () => {
    const hass = loaded();
    hass.results.set(COMMANDS.rulesUpsert, ruleRow({ state: "disabled" }));
    const view = await mount("device-links-rules", hass);

    const toggle = view.shadowRoot?.querySelector<HTMLInputElement>("input[type=checkbox]");
    expect(toggle?.checked).toBe(true);
    toggle?.click();
    await flush();
    await view.updateComplete;

    // Decision D7 physically adds and removes links, so the switch stores the intent and
    // then shows the plan. It never calls set_enabled, which would write straight away.
    expect(hass.sent.some((message) => message.type === COMMANDS.rulesUpsert)).toBe(true);
    expect(hass.sent.some((message) => message.type === COMMANDS.rulesSetEnabled)).toBe(false);
    expect(hass.sent.some((message) => message.type === COMMANDS.plan)).toBe(true);
    expect(hass.sent.some((message) => message.type === COMMANDS.apply)).toBe(false);
  });

  it("puts a cancelled switch back where it was", async () => {
    const hass = loaded();
    hass.results.set(COMMANDS.rulesUpsert, ruleRow({ state: "disabled" }));
    const view = await mount("device-links-rules", hass);

    view.shadowRoot?.querySelector<HTMLInputElement>("input[type=checkbox]")?.click();
    await flush();
    await view.updateComplete;

    const dialog = view.shadowRoot?.querySelector("dl-plan-dialog");
    dialog?.dispatchEvent(
      new CustomEvent("dl-plan-closed", { detail: { applied: false, changes: 2 } }),
    );
    await flush();

    const upserts = hass.sent.filter((message) => message.type === COMMANDS.rulesUpsert);
    expect(upserts).toHaveLength(2);
    const restored = upserts.at(-1)?.rule as { enabled: boolean } | undefined;
    expect(restored?.enabled).toBe(true);
  });

  it("leaves a staged switch alone when the plan had nothing in it", async () => {
    const hass = loaded();
    hass.results.set(COMMANDS.rulesUpsert, ruleRow({ state: "disabled" }));
    const view = await mount("device-links-rules", hass);

    view.shadowRoot?.querySelector<HTMLInputElement>("input[type=checkbox]")?.click();
    await flush();
    await view.updateComplete;

    // The devices already hold what the switch asked for, so there is nothing to walk
    // away from and putting the switch back would make it look broken.
    view.shadowRoot
      ?.querySelector("dl-plan-dialog")
      ?.dispatchEvent(
        new CustomEvent("dl-plan-closed", { detail: { applied: false, changes: 0 } }),
      );
    await flush();

    expect(hass.sent.filter((message) => message.type === COMMANDS.rulesUpsert)).toHaveLength(1);
  });

  it("warns that deleting a rule leaves what it wrote behind", async () => {
    const view = await mount("device-links-rules", loaded());

    buttons(view)
      .find((button) => button.textContent?.trim() === "Delete")
      ?.click();
    await view.updateComplete;

    expect(text(view)).toContain("becomes unmanaged");
  });
});

describe("the devices view", () => {
  it("offers no Remove control beside a system link", async () => {
    const hass = loaded();
    const view = await mount("device-links-devices", hass);

    view.shadowRoot?.querySelector<HTMLButtonElement>(".selectable")?.click();
    await flush();
    await view.updateComplete;

    const shown = text(view);
    expect(shown).toContain("System link. Device Links never removes this.");
    // One removable entry (the unmanaged one), and none for the lifeline.
    expect(buttons(view).filter((button) => button.textContent?.trim() === "Remove")).toHaveLength(
      1,
    );
  });

  it("shows capacity, and what controls the device from elsewhere", async () => {
    const view = await mount("device-links-devices", loaded());
    view.shadowRoot?.querySelector<HTMLButtonElement>(".selectable")?.click();
    await flush();
    await view.updateComplete;

    expect(text(view)).toContain("1 of 5 used in group 7");
    expect(text(view)).toContain("Incoming");
  });

  it("says a device that is not answering is showing what was last seen", async () => {
    const hass = loaded();
    hass.results.set(
      COMMANDS.devicesGet,
      deviceDetail({ device: deviceRow({ available: false, name: "Mud Room Scene" }) }),
    );
    const view = await mount("device-links-devices", hass);
    view.shadowRoot?.querySelector<HTMLButtonElement>(".selectable")?.click();
    await flush();
    await view.updateComplete;

    expect(text(view)).toContain("This device is not answering");
    expect(text(view)).toContain("what Device Links last read from it");
  });

  it("reports a deep verify that could not be confirmed as exactly that", async () => {
    const hass = loaded();
    const view = await mount("device-links-devices", hass);
    view.shadowRoot?.querySelector<HTMLButtonElement>(".selectable")?.click();
    await flush();
    await view.updateComplete;

    buttons(view)
      .find((button) => button.textContent?.trim() === "Deep verify")
      ?.click();
    await flush();
    await view.updateComplete;

    expect(hass.sent.some((message) => message.type === COMMANDS.devicesRefresh)).toBe(true);
    expect(text(view)).toContain("did not come back confirmed");
    expect(text(view)).not.toContain("Read from the device itself just now");
  });

  it("takes an unmanaged link off through a plan, not through a direct removal", async () => {
    const hass = loaded();
    const view = await mount("device-links-devices", hass);
    view.shadowRoot?.querySelector<HTMLButtonElement>(".selectable")?.click();
    await flush();
    await view.updateComplete;

    buttons(view)
      .find((button) => button.textContent?.trim() === "Remove")
      ?.click();
    await flush();

    expect(hass.sent.some((message) => message.type === COMMANDS.unmanagedRemove)).toBe(false);
    const planned = hass.sent.filter((message) => message.type === COMMANDS.plan);
    expect(planned.at(-1)?.remove_unmanaged).toEqual([
      "zwave|zwave:home:36|0|7|zwave:home:38||on_off",
    ]);
  });
});

describe("the activity view", () => {
  it("names each link in words and keeps the backend's own text under an expander", async () => {
    const view = await mount("device-links-activity", loaded());
    const shown = text(view);

    expect(shown).toContain("Partly done");
    expect(shown).toContain("On and off from Bedroom Scene Controller group 7 to Bedside Light L");
    expect(shown).toContain("ZWaveError: Timeout");
    const details = view.shadowRoot?.querySelectorAll("details") ?? [];
    expect(details.length).toBeGreaterThan(0);
    // Closed by default: the raw text is available, not the first thing read.
    expect([...details].every((element) => !element.open)).toBe(true);
  });

  it("restores a snapshot through the plan dialog, and writes nothing to open it", async () => {
    const hass = withSnapshot();
    const view = await mount("device-links-activity", hass);

    buttons(view)
      .find((button) => button.textContent?.trim() === "Restore")
      ?.click();
    await flush();
    await view.updateComplete;

    // The plan came from the rollback command, without a token, so nothing was written.
    const sent = hass.sent.filter((message) => message.type === COMMANDS.snapshotsRollback);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ snapshot_id: "job-1" });
    expect(sent[0]?.plan_token).toBeUndefined();
    const dialog = view.shadowRoot?.querySelector("dl-plan-dialog");
    expect(dialog?.shadowRoot?.textContent).toContain("Bedroom Scene Controller");
  });

  it("says in the dialog which removals a rule that is still on will undo", async () => {
    const hass = withSnapshot();
    const view = await mount("device-links-activity", hass);

    buttons(view)
      .find((button) => button.textContent?.trim() === "Restore")
      ?.click();
    await flush();
    await view.updateComplete;

    const dialog = view.shadowRoot?.querySelector("dl-plan-dialog");
    const shown = dialog?.shadowRoot?.textContent?.replace(/\s+/g, " ") ?? "";
    expect(shown).toContain("rules that are still on: Goodnight, everything off");
    expect(shown).toContain("read as drifted");
    expect(shown).toContain("cannot be read");
  });

  it("applies a rollback with the token of the plan on screen and no other", async () => {
    const hass = withSnapshot();
    const view = await mount("device-links-activity", hass);
    buttons(view)
      .find((button) => button.textContent?.trim() === "Restore")
      ?.click();
    await flush();
    await view.updateComplete;

    const dialog = view.shadowRoot?.querySelector("dl-plan-dialog");
    [...(dialog?.shadowRoot?.querySelectorAll("button") ?? [])]
      .find((button) => button.textContent?.trim().startsWith("Apply"))
      ?.click();
    await flush();

    const applied = hass.sent.filter(
      (message) => message.type === COMMANDS.snapshotsRollback && message.plan_token !== undefined,
    );
    expect(applied).toHaveLength(1);
    expect(applied[0]).toMatchObject({ snapshot_id: "job-1", plan_token: "token-1" });
    // And never through the ordinary apply, which would plan from the profile instead.
    expect(hass.sent.some((message) => message.type === COMMANDS.apply)).toBe(false);
  });
});

describe("the profiles view", () => {
  it("activates with the plan the backend answered with, and writes nothing", async () => {
    const hass = loaded();
    hass.results.set(COMMANDS.profilesActivate, { profile_id: "p2", plan: plan() });
    const view = await mount("device-links-profiles", hass);

    buttons(view)
      .find((button) => button.textContent?.trim() === "Activate")
      ?.click();
    await flush();
    await view.updateComplete;

    expect(hass.sent.some((message) => message.type === COMMANDS.profilesActivate)).toBe(true);
    expect(hass.sent.some((message) => message.type === COMMANDS.apply)).toBe(false);
    const dialog = view.shadowRoot?.querySelector("dl-plan-dialog");
    expect(dialog?.shadowRoot?.textContent).toContain("Bedroom Scene Controller");
  });
});

describe("every view", () => {
  it("says what went wrong in words when the backend refuses", async () => {
    const hass = mockHass();
    for (const command of Object.values(COMMANDS)) {
      hass.failures.set(command, {
        code: "not_loaded",
        message: "Device Links is not loaded, so there is nothing to act on.",
      });
    }
    for (const tag of [
      "device-links-overview",
      "device-links-rules",
      "device-links-devices",
      "device-links-activity",
      "device-links-profiles",
    ]) {
      const view = await mount(tag, hass);
      expect(text(view), tag).toContain("Device Links is not loaded");
      view.remove();
    }
  });

  it("reaches the backend only through the WebSocket commands", async () => {
    const hass = loaded();
    for (const tag of [
      "device-links-overview",
      "device-links-rules",
      "device-links-devices",
      "device-links-activity",
      "device-links-profiles",
    ]) {
      const view = await mount(tag, hass);
      view.remove();
    }
    const known = new Set<string>(Object.values(COMMANDS));
    expect(hass.sent.every((message) => known.has(message.type))).toBe(true);
    expect(SOURCE).toBe("zwave:home:36");
  });
});
