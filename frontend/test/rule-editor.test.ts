/**
 * The stepper, and the three things it owes the person using it.
 *
 * Capacity while choosing rather than after applying, the Stage 0 Z7 warning where it is
 * read rather than logged, and a compiler error that stops an apply without swallowing the
 * work.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COMMANDS, DeviceLinksApi } from "../src/api";
import type { DeviceLinksRuleEditor } from "../src/dialogs/rule-editor";
import { componentSet } from "../src/ha-components";
import { deviceDetail, deviceRow, ruleData } from "./fixtures";
import { type MockHass, mockHass } from "./mock-hass";

const Z7 = {
  translation_key: "button_semantics_unknown",
  placeholders: { emitter: "Button 2", device: "Bedroom Scene Controller" },
};

async function flush(): Promise<void> {
  for (let round = 0; round < 4; round += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

async function open(hass: MockHass): Promise<DeviceLinksRuleEditor> {
  const editor = document.createElement("dl-rule-editor");
  editor.hass = hass;
  editor.api = new DeviceLinksApi(hass);
  editor.components = componentSet([]);
  editor.devices = [
    deviceRow(),
    deviceRow({ identity: "zwave:home:38", device_id: "ha38", name: "Bedside Light L" }),
  ];
  editor.rule = ruleData();
  document.body.append(editor);
  editor.open = true;
  await editor.updateComplete;
  await flush();
  await editor.updateComplete;
  return editor;
}

function text(editor: DeviceLinksRuleEditor): string {
  return editor.shadowRoot?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function buttons(editor: DeviceLinksRuleEditor): HTMLButtonElement[] {
  return [...(editor.shadowRoot?.querySelectorAll("button") ?? [])];
}

function press(editor: DeviceLinksRuleEditor, label: string): void {
  buttons(editor)
    .find((button) => button.textContent?.trim() === label)
    ?.click();
}

async function toReview(editor: DeviceLinksRuleEditor): Promise<void> {
  for (let step = 0; step < 4; step += 1) {
    press(editor, "Next");
    await editor.updateComplete;
    await flush();
    await editor.updateComplete;
  }
}

beforeEach(async () => {
  await import("../src/dialogs/rule-editor");
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("the rule editor", () => {
  it("shows each control's headroom while it is being chosen", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.devicesGet, deviceDetail());
    const editor = await open(hass);

    press(editor, "Next");
    await editor.updateComplete;
    await flush();
    await editor.updateComplete;

    // One entry on group 7 out of the five that group holds, from the device's own
    // capabilities and its observed links.
    expect(text(editor)).toContain("1 of 5 used in group 7");
  });

  it("shows a lifeline and does not let a rule be built on it", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.devicesGet, deviceDetail());
    const editor = await open(hass);
    press(editor, "Next");
    await editor.updateComplete;
    await flush();
    await editor.updateComplete;

    expect(text(editor)).toContain("Lifeline");
    expect(text(editor)).toContain("Device Links never writes to it");
    const lifeline = buttons(editor).find((button) => button.textContent?.includes("Lifeline"));
    expect(lifeline).toBeUndefined();
  });

  it("puts the Z7 warning in front of the user before they save", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.devicesGet, deviceDetail());
    hass.results.set(COMMANDS.rulesValidate, {
      links: [],
      settings: [],
      warnings: [Z7],
      errors: [],
    });
    const editor = await open(hass);
    await toReview(editor);

    const shown = text(editor);
    expect(shown).toContain("may toggle rather than always sending off");
    expect(shown).not.toContain("button_semantics_unknown");
    // The warning does not stop the rule being applied: it is a thing to know, not a fault.
    const apply = buttons(editor).find((button) => button.textContent?.includes("Save and apply"));
    expect(apply?.disabled).toBe(false);
  });

  it("lets a rule with a compiler error be saved but not applied", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.devicesGet, deviceDetail());
    hass.results.set(COMMANDS.rulesValidate, {
      links: [],
      settings: [],
      warnings: [],
      errors: [
        {
          translation_key: "feature_unavailable_on_off",
          placeholders: { emitter: "Button 2", feature: "on_off" },
        },
      ],
    });
    const editor = await open(hass);
    await toReview(editor);

    expect(text(editor)).toContain("does not send an on or off command");
    expect(text(editor)).toContain("it will show as blocked in the rules table");
    const apply = buttons(editor).find((button) => button.textContent?.includes("Save and apply"));
    const save = buttons(editor).find((button) => button.textContent?.includes("Save anyway"));
    expect(apply?.disabled).toBe(true);
    expect(save?.disabled).toBe(false);
  });

  it("stores the rule and asks for a plan when Save and apply is used", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.devicesGet, deviceDetail());
    hass.results.set(COMMANDS.rulesValidate, {
      links: [],
      settings: [],
      warnings: [],
      errors: [],
    });
    const editor = await open(hass);
    const saved = vi.fn();
    editor.addEventListener("dl-rule-saved", (event) => {
      saved((event as CustomEvent<{ apply: boolean }>).detail.apply);
    });
    await toReview(editor);

    press(editor, "Save and apply");
    await flush();

    expect(hass.sent.some((message) => message.type === COMMANDS.rulesUpsert)).toBe(true);
    expect(saved).toHaveBeenCalledWith(true);
  });

  it("never writes to a device by itself", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.devicesGet, deviceDetail());
    hass.results.set(COMMANDS.rulesValidate, {
      links: [],
      settings: [],
      warnings: [],
      errors: [],
    });
    const editor = await open(hass);
    await toReview(editor);
    press(editor, "Save and apply");
    await flush();

    expect(hass.sent.some((message) => message.type === COMMANDS.apply)).toBe(false);
  });
});
