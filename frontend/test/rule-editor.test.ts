/**
 * The stepper, and the four things it owes the person using it.
 *
 * Capacity while choosing rather than after applying, the Stage 0 Z7 warning where it is
 * read rather than logged, a compiler error that stops an apply without swallowing the
 * work, and a payload the backend will actually accept.
 *
 * The last one is open item T50, and it is the reason "the payload it sends" below drives
 * the whole stepper rather than asserting on a draft object. From Phase 1E until T50 was
 * closed, every rule this editor could save was refused by `rules/upsert`, because the
 * source endpoint was hard-coded null and no test put the two halves together.
 * `tests/test_panel_save_path.py` is the Python half, which pushes what this builds through
 * the real handler; this is the half that pins what "what this builds" means.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COMMANDS, DeviceLinksApi } from "../src/api";
import type { DeviceLinksRuleEditor } from "../src/dialogs/rule-editor";
import { componentSet } from "../src/ha-components";
import type { DeviceDetail, DeviceRow, RuleData } from "../src/types";
import { deviceDetail, deviceRow, emitter, ruleData } from "./fixtures";
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

// --------------------------------------------------------------------------------------
// What the stepper actually sends (open item T50)
// --------------------------------------------------------------------------------------

// A Zigbee pair, because Zigbee is where the endpoints are not both zero and not both
// null: the aux paddle drives from endpoint 2 and the light's load receives on endpoint 1.
// Neither number can be guessed, and a rule missing either is refused by the backend.
const AUX = "zigbee2mqtt:0x0000000000004340";
const LIGHT = "zigbee2mqtt:0x000000000000ce64";

function auxRow(): DeviceRow {
  return deviceRow({
    identity: AUX,
    device_id: "haaux",
    name: "Entrance Inside Lights Aux",
    backend: "zigbee2mqtt",
    protocol_id: "0x0000000000004340",
    emitters: 1,
    receiving_endpoint: 1,
  });
}

function lightRow(): DeviceRow {
  return deviceRow({
    identity: LIGHT,
    device_id: "halight",
    name: "Entrance Inside Lights",
    backend: "zigbee2mqtt",
    protocol_id: "0x000000000000ce64",
    emitters: 1,
    receiving_endpoint: 1,
  });
}

function auxDetail(): DeviceDetail {
  return deviceDetail({
    device: auxRow(),
    emitters: [
      emitter({
        emitter_id: "ep2",
        label: "Paddle",
        endpoint: 2,
        group_ids: ["genOnOff", "genLevelCtrl"],
        actions: { on_off: "genOnOff", level_set: "genLevelCtrl", level_hold: "genLevelCtrl" },
        grouping: "endpoint",
        semantics: null,
      }),
    ],
    links: [],
  });
}

/** Click the first button whose text contains this fragment. */
function pressContaining(editor: DeviceLinksRuleEditor, fragment: string): void {
  const button = buttons(editor).find((candidate) => candidate.textContent?.includes(fragment));
  expect(button, `no button contains ${fragment}`).toBeDefined();
  button?.click();
}

async function settle(editor: DeviceLinksRuleEditor): Promise<void> {
  await editor.updateComplete;
  await flush();
  await editor.updateComplete;
}

describe("the payload the rule editor sends", () => {
  it("takes the source endpoint from the control and the target endpoint from the device", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.devicesGet, auxDetail());
    hass.results.set(COMMANDS.rulesValidate, {
      links: [],
      settings: [],
      warnings: [],
      errors: [],
    });
    const editor = document.createElement("dl-rule-editor");
    editor.hass = hass;
    editor.api = new DeviceLinksApi(hass);
    editor.components = componentSet([]);
    editor.devices = [auxRow(), lightRow()];
    editor.rule = null;
    editor.initialTemplate = "remote";
    document.body.append(editor);
    editor.open = true;
    await settle(editor);

    // Step 1, the intent, is already chosen by the template card that opened this.
    press(editor, "Next");
    await settle(editor);
    // Step 2: the device, and then the control on it.
    pressContaining(editor, "Entrance Inside Lights Aux");
    await settle(editor);
    pressContaining(editor, "Paddle");
    await settle(editor);
    press(editor, "Next");
    await settle(editor);
    // Step 3: the target. Its endpoint is shown while it is being ticked, not only sent.
    const target = [...(editor.shadowRoot?.querySelectorAll("input[type=checkbox]") ?? [])].at(
      -1,
    ) as HTMLInputElement;
    target.checked = true;
    target.dispatchEvent(new Event("change"));
    await settle(editor);
    expect(text(editor)).toContain("Endpoint 1");
    press(editor, "Next");
    await settle(editor);
    press(editor, "Next");
    await settle(editor);
    press(editor, "Save");
    await flush();

    const upsert = hass.sent.find((message) => message.type === COMMANDS.rulesUpsert);
    const rule = upsert?.rule as RuleData;
    expect(rule.source).toEqual({ device: AUX, endpoint: 2, emitter_id: "ep2" });
    expect(rule.targets).toEqual([{ device: LIGHT, endpoint: 1 }]);
    // And the rule that was compiled for the review step is the rule that was saved: one
    // shape validated and another stored is how a user is shown a plan they do not get.
    const validated = hass.sent.find((message) => message.type === COMMANDS.rulesValidate);
    expect(validated?.rule).toEqual(rule);
  });
});
