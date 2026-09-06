/**
 * The swap wizard: what it sends, and the one thing it will not let happen quietly.
 *
 * A swap rewrites somebody's whole configuration in one move, so the review step is the
 * product rather than a formality. The tests below are about the two properties that make
 * it one: a lossy swap cannot be confirmed without a person ticking a box next to what is
 * lost, and a replacement that is not answering cannot be swapped onto at all, because
 * nothing is planned for a device that cannot be read.
 */

import { beforeEach, describe, expect, it } from "vitest";

import { COMMANDS, DeviceLinksApi } from "../src/api";
import type { DeviceLinksSwapWizard } from "../src/dialogs/swap-wizard";
import { componentSet } from "../src/ha-components";
import type { SwapPreview } from "../src/types";
import { deviceDetail, deviceRow, plan, ruleData } from "./fixtures";
import { type MockHass, mockHass } from "./mock-hass";

const OLD = "zwave:home:13";
const NEW = deviceRow({ identity: "zwave:home:42", device_id: "ha42", name: "Ceiling Lights" });

function preview(overrides: Partial<SwapPreview> = {}): SwapPreview {
  return {
    proposal: {
      old: deviceRow({ identity: OLD, device_id: null, name: "Ceiling Lights Old" }),
      new: NEW,
      same_model: false,
      is_lossy: false,
      is_applicable: true,
      unmapped: [],
      errors: [],
      mappings: [
        {
          old_emitter_id: "paddle",
          new_emitter_id: "button_2",
          new_label: "Button 2",
          new_endpoint: 0,
          basis: "same_features",
          features_needed: ["on_off", "level_set"],
          features_carried: ["on_off", "level_set"],
        },
      ],
      rewrites: [
        {
          rule_id: "rule-1",
          name: "Ceiling paddle",
          before: ruleData(),
          after: ruleData(),
          is_lossy: false,
          losses: [],
          notes: [],
          errors: [],
        },
      ],
    },
    plan: plan(),
    old_listed: false,
    old_reachable: false,
    new_reachable: true,
    removes: [],
    ...overrides,
  };
}

async function flush(): Promise<void> {
  for (let round = 0; round < 4; round += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

async function open(hass: MockHass): Promise<DeviceLinksSwapWizard> {
  hass.results.set(COMMANDS.swapCandidates, { replacements: [] });
  hass.results.set(COMMANDS.devicesGet, deviceDetail());
  const wizard = document.createElement("dl-swap-wizard");
  wizard.hass = hass;
  wizard.api = new DeviceLinksApi(hass);
  wizard.components = componentSet([]);
  wizard.devices = [NEW];
  wizard.oldIdentity = OLD;
  document.body.append(wizard);
  wizard.open = true;
  await wizard.updateComplete;
  await flush();
  await wizard.updateComplete;
  return wizard;
}

function text(wizard: DeviceLinksSwapWizard): string {
  return wizard.shadowRoot?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

function buttons(wizard: DeviceLinksSwapWizard): HTMLButtonElement[] {
  return [...(wizard.shadowRoot?.querySelectorAll("button") ?? [])];
}

function press(wizard: DeviceLinksSwapWizard, label: string): void {
  buttons(wizard)
    .find((button) => button.textContent?.trim() === label)
    ?.click();
}

/** Click the first button whose text contains this fragment, for the rows with chips in. */
function pressContaining(wizard: DeviceLinksSwapWizard, fragment: string): void {
  buttons(wizard)
    .find((button) => button.textContent?.includes(fragment))
    ?.click();
}

/** Walk from the replacement step to the review step, which is where the decisions are. */
async function toReview(wizard: DeviceLinksSwapWizard): Promise<void> {
  pressContaining(wizard, "Ceiling Lights");
  await wizard.updateComplete;
  await flush();
  await wizard.updateComplete;
  for (let step = 0; step < 2; step += 1) {
    press(wizard, "Next");
    await wizard.updateComplete;
    await flush();
    await wizard.updateComplete;
  }
}

beforeEach(async () => {
  document.body.replaceChildren();
  await import("../src/dialogs/swap-wizard");
});

describe("the swap wizard", () => {
  it("previews with the device that has gone and the replacement that was chosen", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.swapPreview, preview());
    const wizard = await open(hass);

    await toReview(wizard);

    const sent = hass.sent.filter((message) => message.type === COMMANDS.swapPreview);
    expect(sent.length).toBeGreaterThan(0);
    expect(sent[sent.length - 1]).toMatchObject({
      old_identity: OLD,
      new_device_id: "ha42",
    });
  });

  it("says the old device cannot be cleaned up when it has left the network", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.swapPreview, preview());
    const wizard = await open(hass);

    await toReview(wizard);

    // A device that is gone has no work in the plan, which without this reads as a swap
    // with nothing to clean up rather than as entries nobody can take off.
    expect(text(wizard)).toContain("has left the network");
  });

  it("will not let a lossy swap reach the plan until the loss is acknowledged", async () => {
    const hass = mockHass();
    const base = preview();
    const lossy = {
      ...base,
      proposal: {
        ...base.proposal,
        is_lossy: true,
        rewrites: base.proposal.rewrites.map((rewrite) => ({
          ...rewrite,
          is_lossy: true,
          losses: [{ translation_key: "swap_feature_lost", placeholders: {} }],
        })),
      },
    };
    hass.results.set(COMMANDS.swapPreview, lossy);
    const wizard = await open(hass);

    await toReview(wizard);

    const show = buttons(wizard).find((button) => button.textContent?.trim() === "Show the plan");
    expect(show?.disabled).toBe(true);
    const box = wizard.shadowRoot?.querySelector("input[type=checkbox]") as HTMLInputElement;
    box.checked = true;
    box.dispatchEvent(new Event("change"));
    await wizard.updateComplete;
    expect(
      buttons(wizard).find((button) => button.textContent?.trim() === "Show the plan")?.disabled,
    ).toBe(false);
  });

  it("refuses a replacement that is not answering, and says why", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.swapPreview, preview({ new_reachable: false }));
    const wizard = await open(hass);

    await toReview(wizard);

    expect(text(wizard)).toContain("is not answering");
    const show = buttons(wizard).find((button) => button.textContent?.trim() === "Show the plan");
    expect(show?.disabled).toBe(true);
  });

  it("sends the mapping the user chose rather than the one that was pre-filled", async () => {
    const hass = mockHass();
    hass.results.set(COMMANDS.swapPreview, preview());
    const wizard = await open(hass);
    pressContaining(wizard, "Ceiling Lights");
    await wizard.updateComplete;
    await flush();
    await wizard.updateComplete;
    press(wizard, "Next");
    await wizard.updateComplete;
    await flush();
    await wizard.updateComplete;

    const select = wizard.shadowRoot?.querySelector("select") as HTMLSelectElement;
    select.value = "button_2";
    select.dispatchEvent(new Event("change"));
    await wizard.updateComplete;
    await flush();

    const sent = hass.sent.filter((message) => message.type === COMMANDS.swapPreview);
    expect(sent[sent.length - 1]?.mapping).toEqual({ paddle: "button_2" });
  });
});

describe("a swap the backend has refused", () => {
  it("says why on the review step rather than only disabling the button", async () => {
    const hass = mockHass();
    const base = preview();
    hass.results.set(COMMANDS.swapPreview, {
      ...base,
      proposal: {
        ...base.proposal,
        is_applicable: false,
        mappings: [],
        rewrites: [],
        errors: [{ translation_key: "swap_across_backends", placeholders: {} }],
      },
    });
    const wizard = await open(hass);

    await toReview(wizard);

    // The panel localises the key, so what is on screen is the message rather than the
    // key: this asserts the reason reached the user, not that a key was printed at them.
    expect(text(wizard)).toContain("cannot be swapped for");
    expect(
      buttons(wizard).find((button) => button.textContent?.trim() === "Show the plan")?.disabled,
    ).toBe(true);
  });
});
