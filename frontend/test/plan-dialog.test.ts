/**
 * The dialog that stands between a click and a radio write.
 *
 * These are the assertions that hold Decision D18 and Decision D9 in place: the token
 * applied is the token that was shown, an unmanaged box starts unticked, a select-all
 * never reaches a system link, and a stale plan writes nothing and says so.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COMMANDS, DeviceLinksApi } from "../src/api";
import type { DeviceLinksPlanDialog } from "../src/dialogs/plan-dialog";
import { componentSet } from "../src/ha-components";
import { plan } from "./fixtures";
import { type MockHass, mockHass } from "./mock-hass";

async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

async function open(hass: MockHass): Promise<DeviceLinksPlanDialog> {
  const dialog = document.createElement("dl-plan-dialog");
  dialog.hass = hass;
  dialog.api = new DeviceLinksApi(hass);
  dialog.components = componentSet([]);
  dialog.scope = { rule_ids: ["rule-1"] };
  document.body.append(dialog);
  dialog.open = true;
  await dialog.updateComplete;
  await flush();
  await dialog.updateComplete;
  return dialog;
}

function text(dialog: DeviceLinksPlanDialog): string {
  return dialog.shadowRoot?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function boxes(dialog: DeviceLinksPlanDialog): HTMLInputElement[] {
  return [
    ...(dialog.shadowRoot?.querySelectorAll("input[type=checkbox]") ?? []),
  ] as HTMLInputElement[];
}

function button(dialog: DeviceLinksPlanDialog, label: string): HTMLButtonElement | undefined {
  return [...(dialog.shadowRoot?.querySelectorAll("button") ?? [])].find((candidate) =>
    candidate.textContent?.includes(label),
  );
}

beforeEach(async () => {
  await import("../src/dialogs/plan-dialog");
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("the plan dialog", () => {
  it("asks for a plan for the scope it was given, and renders every bucket", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = await open(hass);

    expect(hass.sent[0]).toEqual({ type: COMMANDS.plan, rule_ids: ["rule-1"] });
    const shown = text(dialog);
    expect(shown).toContain("Add");
    expect(shown).toContain("Settings");
    expect(shown).toContain("Blocked");
    expect(shown).toContain("Bedroom Scene Controller");
    // The blocked reason is a sentence, never a bare translation key.
    expect(shown).toContain("is full (5 of 5)");
    expect(shown).not.toContain("group_full");
  });

  it("says when a device in the plan could not be read", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = await open(hass);

    expect(text(dialog)).toContain("Not answering");
    expect(text(dialog)).toContain("what it holds is what was last seen");
  });

  it("starts every unmanaged box unticked", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = await open(hass);

    const ticks = boxes(dialog);
    expect(ticks.length).toBeGreaterThan(0);
    expect(ticks.every((box) => !box.checked)).toBe(true);
  });

  it("offers no tick box at all when the flow says it would ignore them", async () => {
    // The swap is the flow that says no: it removes exactly the links its own rewrite
    // orphans, so a tick box here would be one the job ignores, which is worse than none.
    const hass = mockHass();
    const answer = plan();
    const dialog = document.createElement("dl-plan-dialog");
    dialog.hass = hass;
    dialog.api = new DeviceLinksApi(hass);
    dialog.components = componentSet([]);
    dialog.flow = {
      plan: async () => answer,
      apply: async () => ({ job_id: "j1", status: "running" }),
      acceptsUnmanaged: false,
    };
    document.body.append(dialog);
    dialog.open = true;
    await dialog.updateComplete;
    await flush();
    await dialog.updateComplete;

    expect(boxes(dialog)).toHaveLength(0);
    expect(text(dialog)).toContain("does not touch them");
    expect(button(dialog, "Select all")).toBeUndefined();
  });

  it("offers no tick box at all for a system link, and leaves it out of select all", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = await open(hass);

    // Two unmanaged entries, one of them a system link: one box, not two.
    expect(boxes(dialog)).toHaveLength(1);
    expect(text(dialog)).toContain("System link");

    button(dialog, "Select it")?.click();
    await flush();
    await dialog.updateComplete;

    const replan = hass.sent.filter((message) => message.type === COMMANDS.plan);
    expect(replan.at(-1)?.remove_unmanaged).toEqual([
      "zwave|zwave:home:36|0|7|zwave:home:38||on_off",
    ]);
    expect(replan.at(-1)?.remove_unmanaged).not.toContain("system-fingerprint");
  });

  it("re-plans when a box is ticked, so the token describes the work it authorises", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = await open(hass);

    hass.results.set(COMMANDS.plan, plan({ token: "token-2" }));
    const box = boxes(dialog)[0];
    expect(box).toBeDefined();
    box?.click();
    await flush();
    await dialog.updateComplete;

    hass.results.set(COMMANDS.apply, { job_id: "job-9", status: "running" });
    button(dialog, "Apply")?.click();
    await flush();

    const apply = hass.sent.find((message) => message.type === COMMANDS.apply);
    expect(apply?.plan_token).toBe("token-2");
    expect(apply?.remove_unmanaged).toEqual(["zwave|zwave:home:36|0|7|zwave:home:38||on_off"]);
  });

  it("applies the token of the plan on screen rather than a fresh one", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    hass.results.set(COMMANDS.apply, { job_id: "job-9", status: "running" });
    const dialog = await open(hass);

    button(dialog, "Apply")?.click();
    await flush();

    // One plan, then the apply. A second plan between them would mean the user confirmed
    // one thing and applied another.
    expect(hass.sent.map((message) => message.type)).toEqual([COMMANDS.plan, COMMANDS.apply]);
    expect(hass.sent.at(-1)?.plan_token).toBe("token-1");
  });

  it("counts only the work an apply would do", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = await open(hass);

    // One add and one setting; the blocked and pending items are not applied.
    expect(button(dialog, "Apply")?.textContent?.replace(/\s+/g, " ").trim()).toBe(
      "Apply 2 changes",
    );
  });

  it("follows the job it started and shows the result when it ends", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    hass.results.set(COMMANDS.apply, { job_id: "job-9", status: "running" });
    const dialog = await open(hass);

    button(dialog, "Apply")?.click();
    await flush();
    hass.emit({
      type: "progress",
      job: { id: "job-9", total: 4, completed: 2, devices_in_flight: ["Bedroom Scene Controller"] },
    });
    await dialog.updateComplete;
    expect(text(dialog)).toContain("2 of 4 done");

    hass.emit({
      type: "finished",
      job: {
        id: "job-9",
        scope: "rule",
        status: "partial",
        created_at: new Date().toISOString(),
        total: 4,
        results: { applied: 3, failed: 1 },
        rule_ids: ["rule-1"],
      },
    });
    await dialog.updateComplete;
    expect(text(dialog)).toContain("Partly done");
    expect(text(dialog)).toContain("Failed 1");
    expect(hass.unsubscribes).toBe(1);
  });

  it("ignores a job somebody else started", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    hass.results.set(COMMANDS.apply, { job_id: "job-9", status: "running" });
    const dialog = await open(hass);

    button(dialog, "Apply")?.click();
    await flush();
    hass.emit({
      type: "finished",
      job: {
        id: "somebody-elses-job",
        scope: "rule",
        status: "completed",
        created_at: new Date().toISOString(),
        total: 1,
        results: { applied: 1 },
        rule_ids: [],
      },
    });
    await dialog.updateComplete;

    expect(text(dialog)).toContain("Writing to your devices");
  });

  it("says nothing was written when the plan turned out to be stale (FR-A3)", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    hass.failures.set(COMMANDS.apply, {
      code: "plan_out_of_date",
      message: "This plan was made before something changed, so nothing was written.",
      translation_key: "plan_out_of_date",
    });
    const dialog = await open(hass);

    button(dialog, "Apply")?.click();
    await flush();
    await dialog.updateComplete;

    expect(text(dialog)).toContain("nothing was written");
    expect(text(dialog)).toContain("Plan again");
  });

  it("opens with the links a caller pre-selected, and says so on screen", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = document.createElement("dl-plan-dialog");
    dialog.hass = hass;
    dialog.api = new DeviceLinksApi(hass);
    dialog.initialRemoveUnmanaged = ["zwave|zwave:home:36|0|7|zwave:home:38||on_off"];
    document.body.append(dialog);
    dialog.open = true;
    await dialog.updateComplete;
    await flush();
    await dialog.updateComplete;

    expect(hass.sent[0]?.remove_unmanaged).toEqual([
      "zwave|zwave:home:36|0|7|zwave:home:38||on_off",
    ]);
    expect(boxes(dialog)[0]?.checked).toBe(true);
  });

  it("cannot be dismissed while it is writing", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    hass.results.set(COMMANDS.apply, { job_id: "job-9", status: "running" });
    const dialog = await open(hass);
    const closed = vi.fn();
    dialog.addEventListener("dl-plan-closed", closed);

    button(dialog, "Apply")?.click();
    await flush();
    await dialog.updateComplete;

    dialog.shadowRoot
      ?.querySelector("dl-dialog")
      ?.dispatchEvent(new CustomEvent("dl-dialog-closed"));
    expect(closed).not.toHaveBeenCalled();
  });

  it("says on close whether anything was applied and what was left undone", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    const dialog = await open(hass);
    const closed = vi.fn();
    dialog.addEventListener("dl-plan-closed", (event) => {
      closed((event as CustomEvent<{ applied: boolean; changes: number }>).detail);
    });

    button(dialog, "Cancel")?.click();
    expect(closed).toHaveBeenCalledWith({ applied: false, changes: 2 });
  });

  it("ends its job subscription when it leaves the document", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, plan());
    hass.results.set(COMMANDS.apply, { job_id: "job-9", status: "running" });
    const dialog = await open(hass);

    button(dialog, "Apply")?.click();
    await flush();
    dialog.remove();
    await flush();

    expect(hass.unsubscribes).toBe(1);
  });
});

describe("the HA-executed legs a plan carries", () => {
  it("lists them under their own heading and says the apply does not touch them", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.plan, {
      ...plan(),
      hybrid_legs: [
        {
          identity: "off_only|zwave:home:36|button_2|on_off|zwave:home:38|",
          kind: "off_only",
          rule_id: "rule-1",
          feature: "on_off",
          emitter_id: "button_2",
          source: {
            identity: "zwave:home:36",
            name: "Bedroom Scene Controller",
            device_id: "ha36",
          },
          target: {
            identity: "zwave:home:38",
            name: "Bedside Light L",
            device_id: "ha38",
            endpoint: null,
          },
          scene_id: 2,
          indicator_id: null,
        },
      ],
    });
    const dialog = await open(hass);

    const rendered = text(dialog);
    expect(rendered).toContain("Run by Home Assistant");
    expect(rendered).toContain("not part of this apply");
    expect(rendered).toContain("Bedside Light L");
  });
});
