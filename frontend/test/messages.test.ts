import { describe, expect, it } from "vitest";

import { fillPlaceholders, localizeDiagnostic, lookupMessage } from "../src/messages";
import { mockHass } from "./mock-hass";

describe("filling placeholders", () => {
  it("substitutes what it was given", () => {
    expect(fillPlaceholders("Group {group} on {device}", { group: 7, device: "036" })).toBe(
      "Group 7 on 036",
    );
  });

  it("leaves a marker nobody supplied visible rather than printing undefined", () => {
    expect(fillPlaceholders("Group {group}", {})).toBe("Group {group}");
    expect(fillPlaceholders("Group {group}", null)).toBe("Group {group}");
  });
});

describe("finding the sentence for a key", () => {
  it("prefers what Home Assistant can localise", () => {
    const hass = mockHass({
      translations: {
        "component.device_links.exceptions.group_full.message": "Gruppe {group} ist voll",
      },
    });
    expect(lookupMessage(hass, "group_full", { group: "7" })).toBe("Gruppe 7 ist voll");
  });

  it("looks in the issues section too", () => {
    const hass = mockHass({
      translations: { "component.device_links.issues.pending_wakeup.message": "Aufwachen" },
    });
    expect(lookupMessage(hass, "pending_wakeup")).toBe("Aufwachen");
  });

  it("falls back to the English inlined from strings.json at build time", () => {
    // No `hass` at all, which is what a frontend that has not loaded this integration's
    // translations amounts to for these keys.
    const message = lookupMessage(null, "button_semantics_unknown", {
      emitter: "Button 2 - Pressed",
      device: "036",
    });
    expect(message).toContain("Button 2 - Pressed");
    expect(message).toContain("036");
    expect(message).not.toContain("{");
  });

  it("says nothing rather than guessing for a key it does not have", () => {
    expect(lookupMessage(null, "a_key_no_release_ever_had")).toBeNull();
  });
});

describe("rendering a diagnostic", () => {
  it("returns the sentence, never the key", () => {
    const text = localizeDiagnostic(null, {
      translation_key: "group_full",
      placeholders: { group: "7", device: "036", target: "037" },
    });
    expect(text).not.toBe("group_full");
    expect(text.length).toBeGreaterThan(10);
  });

  it("says so in words when this build carries no wording for the key", () => {
    const text = localizeDiagnostic(null, {
      translation_key: "invented_by_a_later_backend",
      placeholders: {},
    });
    expect(text).toContain("invented by a later backend");
    expect(text).toContain("no wording");
  });

  it("renders nothing for no diagnostic, so a caller can interpolate it directly", () => {
    expect(localizeDiagnostic(null, null)).toBe("");
  });
});
