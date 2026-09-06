import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { componentSet } from "../src/ha-components";
import { BUNDLE_VERSION, type DeviceLinksPanel } from "../src/panel";
import { TABS, tabFromPath } from "../src/tabs";
import { type MockHass, mockHass } from "./mock-hass";

/**
 * Mount a panel and wait until it has rendered.
 *
 * The component load is awaited too: the shell renders a loading line until it finishes,
 * and every assertion below is about what comes after that.
 */
async function mount(options: {
  hass?: MockHass;
  path?: string;
  backendVersion?: string | null;
  narrow?: boolean;
  /** Which Home Assistant elements this mount should pretend resolved. */
  components?: readonly string[];
}): Promise<{ panel: DeviceLinksPanel; hass: MockHass }> {
  const hass = options.hass ?? mockHass();
  const panel = document.createElement("device-links-panel") as DeviceLinksPanel;
  const available = componentSet(options.components ?? []);
  panel.componentLoader = () => Promise.resolve(available);
  panel.hass = hass;
  panel.narrow = options.narrow ?? false;
  panel.route = { prefix: "/device_links", path: options.path ?? "/overview" };
  panel.panel = {
    config: options.backendVersion === undefined ? {} : { version: options.backendVersion },
  };
  document.body.append(panel);
  await panel.updateComplete;
  // The loader resolves on a microtask, and the render it triggers is the one every
  // assertion below is about.
  await new Promise((resolve) => setTimeout(resolve, 0));
  await panel.updateComplete;
  return { panel, hass };
}

function text(panel: DeviceLinksPanel): string {
  return panel.shadowRoot?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

beforeEach(async () => {
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  await import("../src/panel");
});

afterEach(() => {
  document.body.replaceChildren();
});

describe("the tab router", () => {
  it("reads the tab out of the panel route", () => {
    expect(tabFromPath("/rules")).toBe("rules");
    expect(tabFromPath("/devices/zwave%3A36")).toBe("devices");
  });

  it("lands on the first tab for an empty or unknown path", () => {
    expect(tabFromPath(undefined)).toBe("overview");
    expect(tabFromPath("/")).toBe("overview");
    expect(tabFromPath("/a-tab-from-a-later-version")).toBe("overview");
  });

  it("has an element registered behind every tab", () => {
    for (const tab of TABS) {
      expect(customElements.get(tab.tagName), tab.tagName).toBeDefined();
    }
  });
});

describe("the shell", () => {
  it("renders the tab the route names, and only that one", async () => {
    const { panel } = await mount({ path: "/rules" });
    expect(panel.tab).toBe("rules");
    expect(panel.shadowRoot?.querySelector("device-links-rules")).not.toBeNull();
    expect(panel.shadowRoot?.querySelector("device-links-overview")).toBeNull();
  });

  it("hands every view the hass, the client and the narrow flag", async () => {
    const { panel, hass } = await mount({ narrow: true });
    const view = panel.shadowRoot?.querySelector("device-links-overview") as HTMLElement & {
      hass: unknown;
      api: unknown;
      narrow: boolean;
      components: unknown;
    };
    expect(view.hass).toBe(hass);
    expect(view.api).toBe(panel.api);
    expect(view.narrow).toBe(true);
    expect(view.components).not.toBeNull();
  });

  it("builds one client and keeps it pointed at the current hass", async () => {
    const { panel } = await mount({});
    const first = panel.api;
    const second = mockHass();
    panel.hass = second;
    await panel.updateComplete;
    expect(panel.api).toBe(first);
    expect(panel.api?.hass).toBe(second);
  });

  it("navigates by pushing the URL and telling the router", async () => {
    const { panel } = await mount({ path: "/overview" });
    const events: string[] = [];
    panel.addEventListener("location-changed", () => events.push(location.pathname));
    const button = panel.shadowRoot?.querySelectorAll("nav.plain-tabs button")[1] as HTMLElement;
    button.click();
    expect(location.pathname).toBe("/device_links/rules");
    expect(events).toEqual(["/device_links/rules"]);
  });

  it("does nothing when the tab that is already open is clicked", async () => {
    const { panel } = await mount({ path: "/overview" });
    const events: string[] = [];
    panel.addEventListener("location-changed", () => events.push("moved"));
    const button = panel.shadowRoot?.querySelector("nav.plain-tabs button") as HTMLElement;
    button.click();
    expect(events).toEqual([]);
  });

  it("degrades to a plain bar and plain tabs when the HA elements are absent", async () => {
    // Nothing defines `ha-top-app-bar-fixed` or `ha-tab-group` in this environment, which
    // is exactly the case the fallback exists for.
    const { panel } = await mount({});
    expect(panel.shadowRoot?.querySelector("ha-top-app-bar-fixed")).toBeNull();
    expect(panel.shadowRoot?.querySelector("header.plain-bar")).not.toBeNull();
    const tabs = panel.shadowRoot?.querySelectorAll("nav.plain-tabs button") ?? [];
    expect(tabs).toHaveLength(TABS.length);
    expect(text(panel)).toContain("Overview");
  });

  it("marks the open tab for a screen reader, and every tab is a real button", async () => {
    const { panel } = await mount({ path: "/devices" });
    const tabs = [...(panel.shadowRoot?.querySelectorAll("nav.plain-tabs button") ?? [])];
    const current = tabs.filter((tab) => tab.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]?.textContent?.trim()).toBe("Devices");
    expect(tabs.every((tab) => tab.tagName === "BUTTON")).toBe(true);
  });

  it("ends every subscription when the panel leaves the document", async () => {
    const { panel, hass } = await mount({});
    panel.api?.subscribeJobs(() => undefined);
    await Promise.resolve();
    panel.remove();
    expect(hass.unsubscribes).toBe(1);
    expect(panel.api).toBeNull();
  });
});

describe("the version handshake", () => {
  it("says nothing when the backend runs the version this bundle was built from", async () => {
    const { panel } = await mount({ backendVersion: BUNDLE_VERSION });
    expect(panel.versionMismatch).toBe(false);
    expect(text(panel)).not.toContain("Reload");
  });

  it("says nothing when the backend did not send a version", async () => {
    const { panel } = await mount({ backendVersion: null });
    expect(panel.backendVersion).toBeNull();
    expect(panel.versionMismatch).toBe(false);
  });

  it("asks for a reload, in those words, when the backend has moved on", async () => {
    const { panel } = await mount({ backendVersion: "9.9.9" });
    expect(panel.versionMismatch).toBe(true);
    const banner = text(panel);
    expect(banner).toContain("9.9.9");
    expect(banner).toContain(BUNDLE_VERSION);
    expect(banner).toContain("Reload the page");
    // Read as an update, not as a fault: nothing in it says error or failed.
    expect(banner.toLowerCase()).not.toContain("error");
    expect(banner.toLowerCase()).not.toContain("failed");
  });

  it("still renders the panel under the banner rather than replacing it", async () => {
    const { panel } = await mount({ backendVersion: "9.9.9", path: "/activity" });
    expect(panel.shadowRoot?.querySelector("device-links-activity")).not.toBeNull();
  });

  it("reloads the page from the button in the banner", async () => {
    const { panel } = await mount({ backendVersion: "9.9.9" });
    const reload = vi.fn();
    (panel as unknown as { _reload: () => void })._reload = reload;
    const button = [...(panel.shadowRoot?.querySelectorAll("button") ?? [])].find(
      (candidate) => candidate.textContent?.trim() === "Reload",
    );
    button?.click();
    expect(reload).toHaveBeenCalled();
  });
});

describe("when Home Assistant's own components are there", () => {
  const FULL = [
    "ha-top-app-bar-fixed",
    "ha-menu-button",
    "ha-tab-group",
    "ha-tab-group-tab",
    "ha-alert",
    "ha-icon",
  ];

  it("uses the app bar, the menu button and the tab group", async () => {
    const { panel, hass } = await mount({ components: FULL });
    const root = panel.shadowRoot;
    expect(root?.querySelector("ha-top-app-bar-fixed")).not.toBeNull();
    expect(root?.querySelector("header.plain-bar")).toBeNull();
    const menu = root?.querySelector("ha-menu-button") as HTMLElement & { hass: unknown };
    expect(menu.hass).toBe(hass);
    expect(root?.querySelectorAll("ha-tab-group-tab")).toHaveLength(TABS.length);
  });

  it("navigates from a tab-group tab, not only from the plain fallback", async () => {
    const { panel } = await mount({ components: FULL, path: "/overview" });
    const events: string[] = [];
    panel.addEventListener("location-changed", () => events.push(location.pathname));
    const tabs = [...(panel.shadowRoot?.querySelectorAll("ha-tab-group-tab") ?? [])];
    (tabs[2] as HTMLElement).click();
    expect(events).toEqual(["/device_links/devices"]);
  });

  it("keeps the plain nav when only half the tab strip exists", async () => {
    const { panel } = await mount({ components: ["ha-top-app-bar-fixed", "ha-tab-group"] });
    expect(panel.shadowRoot?.querySelector("ha-tab-group")).toBeNull();
    expect(panel.shadowRoot?.querySelectorAll("nav.plain-tabs button")).toHaveLength(TABS.length);
  });

  it("shows an icon with its label on a narrow screen", async () => {
    const { panel } = await mount({ components: FULL, narrow: true });
    const icons = [...(panel.shadowRoot?.querySelectorAll("ha-icon") ?? [])];
    expect(icons).toHaveLength(TABS.length);
    expect(icons[0]?.getAttribute("aria-label")).toBe("Overview");
  });

  it("puts the version banner in an ha-alert when there is one", async () => {
    const { panel } = await mount({ components: FULL, backendVersion: "9.9.9" });
    const alert = panel.shadowRoot?.querySelector("ha-alert");
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain("Reload the page");
    expect(panel.shadowRoot?.querySelector(".banner-plain")).toBeNull();
  });
});
