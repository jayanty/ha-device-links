import { beforeEach, describe, expect, it, vi } from "vitest";

import { HA_COMPONENTS, loadHaComponents } from "../src/ha-components";

/** A registry a test controls, so nothing here depends on the real element definitions. */
function registry(defined: string[]): CustomElementRegistry {
  const known = new Set(defined);
  const waiting = new Map<string, () => void>();
  return {
    get: (tag: string) =>
      known.has(tag) ? (class {} as CustomElementElementConstructor) : undefined,
    whenDefined: (tag: string) =>
      known.has(tag)
        ? Promise.resolve(class {} as CustomElementElementConstructor)
        : new Promise((resolve) => {
            waiting.set(tag, () => resolve(class {} as CustomElementElementConstructor));
          }),
  } as unknown as CustomElementRegistry;
}

type CustomElementElementConstructor = CustomElementConstructor;

beforeEach(() => {
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});

describe("loading Home Assistant's components", () => {
  it("reports what resolved and renders those tags as themselves", async () => {
    const components = await loadHaComponents(["ha-card", "ha-alert"], {
      registry: registry(["ha-card", "ha-alert"]),
      loadHelpers: () => undefined,
    });
    expect(components.has("ha-card")).toBe(true);
    expect(components.tag("ha-card")).toBe("ha-card");
    expect(components.missing).toEqual([]);
  });

  it("falls back to a plain element rather than rendering nothing", async () => {
    const components = await loadHaComponents(["ha-card", "ha-button", "ha-select"], {
      registry: registry([]),
      timeoutMs: 1,
      loadHelpers: () => undefined,
    });
    expect(components.has("ha-card")).toBe(false);
    expect(components.tag("ha-card")).toBe("div");
    expect(components.tag("ha-button")).toBe("button");
    expect(components.tag("ha-select")).toBe("select");
    expect(components.missing).toEqual(["ha-button", "ha-card", "ha-select"]);
  });

  it("falls back to a div for a tag nobody wrote a substitute for", async () => {
    const components = await loadHaComponents([], {
      registry: registry([]),
      loadHelpers: () => undefined,
    });
    expect(components.tag("ha-invented-later")).toBe("div");
  });

  it("gives up on an element that is never defined instead of hanging", async () => {
    const started = Date.now();
    const components = await loadHaComponents(["ha-card"], {
      registry: registry([]),
      timeoutMs: 5,
      loadHelpers: () => undefined,
    });
    expect(components.has("ha-card")).toBe(false);
    expect(Date.now() - started).toBeLessThan(2000);
  });

  it("survives a frontend with no card helpers at all", async () => {
    const components = await loadHaComponents(["ha-card"], {
      registry: registry(["ha-card"]),
      loadHelpers: () => undefined,
    });
    expect(components.has("ha-card")).toBe(true);
  });

  it("survives card helpers that throw, because that is not fatal to a panel", async () => {
    const components = await loadHaComponents(["ha-card"], {
      registry: registry(["ha-card"]),
      loadHelpers: () => Promise.reject(new Error("no helpers on this version")),
    });
    expect(components.has("ha-card")).toBe(true);
  });

  it("uses the card helpers to force the lazy definitions in", async () => {
    const getConfigElement = vi.fn().mockResolvedValue(undefined);
    class FakeCard extends HTMLElement {
      static getConfigElement = getConfigElement;
    }
    const createCardElement = vi.fn().mockResolvedValue(Object.create(FakeCard.prototype));
    await loadHaComponents(["ha-card"], {
      registry: registry(["ha-card"]),
      loadHelpers: () => Promise.resolve({ createCardElement }),
    });
    expect(createCardElement).toHaveBeenCalledWith({ type: "entities", entities: [] });
    expect(getConfigElement).toHaveBeenCalled();
  });

  it("reports everything missing when the environment has no registry at all", async () => {
    // Not a browser this panel would ever run in, but the branch is the difference
    // between a plain screen and an exception during the first render.
    vi.stubGlobal("customElements", undefined);
    try {
      const components = await loadHaComponents(["ha-card"], { loadHelpers: () => undefined });
      expect(components.has("ha-card")).toBe(false);
      expect(components.tag("ha-card")).toBe("div");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("names none of the components Stage 0 found to be absent", () => {
    expect(HA_COMPONENTS).not.toContain("ha-tabs");
    expect(HA_COMPONENTS).not.toContain("ha-fab");
    expect(HA_COMPONENTS).not.toContain("ha-textfield");
    expect(HA_COMPONENTS).toContain("ha-tab-group");
  });
});
