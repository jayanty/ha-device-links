/**
 * The comparison dialog: both levels, and the one thing it must never offer.
 *
 * A diff is what makes a rollback or an import a decision rather than an act of faith, so
 * what it says has to be both true and readable: the rules, because that is where a user's
 * own edits live, and the links, because that is what will be written. The one thing it
 * must not have is a button that writes anything: applying goes through the plan dialog on
 * its own token (Decision D18), and a second door would be a device write with no plan.
 */

import { beforeEach, describe, expect, it } from "vitest";

import { COMMANDS, DeviceLinksApi } from "../src/api";
import type { DeviceLinksDiffDialog } from "../src/dialogs/diff-dialog";
import type { ProfileDiff } from "../src/types";
import { link } from "./fixtures";
import { type MockHass, mockHass } from "./mock-hass";

const CHANGED: ProfileDiff = {
  is_empty: false,
  counts: { rules_added: 1, rules_changed: 1, links_added: 1, links_removed: 0 },
  devices: [],
  rules: [
    {
      rule_id: "rule-1",
      name: "Bedside pair",
      kind: "changed",
      fields: ["name"],
      writes_nothing_new: true,
      links_added: [],
      links_removed: [],
      links_unchanged: 2,
    },
    {
      rule_id: "rule-2",
      name: "Lobby remote",
      kind: "added",
      fields: [],
      writes_nothing_new: false,
      links_added: [link()],
      links_removed: [],
      links_unchanged: 0,
    },
  ],
  links: [
    { kind: "added", link: link() },
    { kind: "unchanged", link: link({ fingerprint: "other" }) },
  ],
};

async function open(hass: MockHass, result: ProfileDiff): Promise<DeviceLinksDiffDialog> {
  hass.results.set(COMMANDS.profilesDiff, result);
  const dialog = document.createElement("dl-diff-dialog");
  dialog.hass = hass;
  dialog.api = new DeviceLinksApi(hass);
  dialog.profileId = "profile-main";
  dialog.against = { profileId: "profile-guest" };
  document.body.append(dialog);
  dialog.open = true;
  await dialog.updateComplete;
  await new Promise((resolve) => setTimeout(resolve, 0));
  await dialog.updateComplete;
  return dialog;
}

function text(dialog: DeviceLinksDiffDialog): string {
  return dialog.shadowRoot?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

beforeEach(async () => {
  document.body.replaceChildren();
  await import("../src/dialogs/diff-dialog");
});

describe("the comparison dialog", () => {
  it("sends the profile and the side it is compared with", async () => {
    const hass = mockHass();
    await open(hass, CHANGED);

    const sent = hass.sent.find((message) => message.type === COMMANDS.profilesDiff);
    expect(sent).toEqual({
      type: COMMANDS.profilesDiff,
      profile_id: "profile-main",
      other_profile_id: "profile-guest",
    });
  });

  it("names a renamed rule as changed and says it writes nothing", async () => {
    const dialog = await open(mockHass(), CHANGED);

    const rendered = text(dialog);
    expect(rendered).toContain("Bedside pair");
    expect(rendered).toContain("Different: name.");
    expect(rendered).toContain("No device change");
  });

  it("hides the links that are the same until they are asked for", async () => {
    const dialog = await open(mockHass(), CHANGED);

    const buttons = [...(dialog.shadowRoot?.querySelectorAll("button") ?? [])];
    const reveal = buttons.find((button) => button.textContent?.includes("that are the same"));
    expect(reveal).toBeDefined();
    expect(text(dialog)).not.toContain("Unchanged");

    reveal?.click();
    await dialog.updateComplete;
    expect(text(dialog)).toContain("Unchanged");
  });

  it("says what a snapshot comparison can and cannot speak for", async () => {
    const dialog = await open(mockHass(), {
      ...CHANGED,
      rules: [],
      devices: ["zwave:home:36", "zwave:home:38"],
    });

    expect(text(dialog)).toContain("covers 2 devices");
  });

  it("offers no button that writes anything", async () => {
    const dialog = await open(mockHass(), CHANGED);

    const labels = [...(dialog.shadowRoot?.querySelectorAll("button") ?? [])].map((button) =>
      button.textContent?.trim(),
    );
    expect(labels).not.toContain("Apply");
    expect(labels).not.toContain("Restore");
    expect(labels).toContain("Close");
  });

  it("says so plainly when the two sides describe the same thing", async () => {
    const dialog = await open(mockHass(), {
      is_empty: true,
      counts: {},
      devices: [],
      rules: [],
      links: [],
    });

    expect(text(dialog)).toContain("describe the same thing");
  });
});
