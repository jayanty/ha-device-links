import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { BUNDLE_VERSION, type DeviceLinksPanel } from "../src/panel";

/**
 * The toolchain, end to end.
 *
 * Small on purpose: what is being proved here is that vite's build-time constants reach
 * the code, that the decorators compile, and that the element defines and renders. Task 4
 * replaces this with the tests for the shell.
 */

beforeEach(async () => {
  await import("../src/panel");
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("the panel element", () => {
  it("knows the version it was built from", () => {
    expect(BUNDLE_VERSION).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("defines itself under the tag panel_custom is told to load", () => {
    expect(customElements.get("device-links-panel")).toBeDefined();
  });

  it("renders", async () => {
    const panel = document.createElement("device-links-panel") as DeviceLinksPanel;
    document.body.append(panel);
    await panel.updateComplete;
    expect(panel.shadowRoot?.textContent).toContain("Device Links");
  });
});
