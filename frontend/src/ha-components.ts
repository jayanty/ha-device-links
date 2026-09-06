/**
 * Getting Home Assistant's own components to exist before the panel renders with them.
 *
 * Home Assistant defines most of its elements lazily: the class for `ha-select` is not
 * registered until something that uses it has been loaded. A custom panel is loaded on its
 * own, so none of them are defined when it first renders, and an undefined custom element
 * renders as an empty inline box rather than as an error. The known way round it is the
 * card-helpers technique: ask the frontend for its card helpers, build a throwaway
 * entities card, and ask that card for its config element, which pulls in the editor
 * bundle where the form controls live. Then wait for each tag to be defined.
 *
 * **What matters more than the loading is the failing.** Stage 0 scanned the frontend this
 * targets, so we know `ha-tabs`, `ha-fab` and `ha-textfield` are gone and `ha-tab-group` is
 * what exists, and nothing here detects between them. What this does handle is the version
 * nobody has seen yet: every tag that does not resolve is simply reported as missing, and
 * the shell renders a plain element instead. A panel that looks plain tells a user their
 * configuration is fine and the styling is not; a panel that renders nothing tells them
 * their integration is broken, and they cannot tell the difference from a blank screen.
 */

/**
 * Every Home Assistant element this panel is allowed to use.
 *
 * Every one of these is present on `home-assistant-frontend` 20260729.7, which is what
 * Stage 0 item P1 established. Do not add `ha-tabs`, `ha-fab` or `ha-textfield`: they are
 * not there. Do add a tag here before rendering it, so that its absence on some other
 * version becomes a fallback rather than an empty box.
 */
export const HA_COMPONENTS = [
  "ha-alert",
  "ha-assist-chip",
  "ha-button",
  "ha-card",
  "ha-checkbox",
  "ha-chip-set",
  "ha-data-table",
  "ha-dialog",
  "ha-expansion-panel",
  "ha-form",
  "ha-icon",
  "ha-icon-button",
  "ha-list-item",
  "ha-markdown",
  "ha-menu-button",
  "ha-select",
  "ha-spinner",
  "ha-svg-icon",
  "ha-switch",
  "ha-tab-group",
  "ha-tab-group-tab",
  "ha-tooltip",
  "ha-top-app-bar-fixed",
] as const;

/**
 * What to render instead of each Home Assistant element when it is not there.
 *
 * Chosen so that the substitute keeps the behaviour that matters rather than the look:
 * a button stays focusable and clickable, a select stays a select, a container stays a
 * container. Anything whose structure a plain element cannot stand in for (the app bar
 * and the tab strip) is handled by the shell branching on `has`, not by a swap.
 */
const FALLBACKS: Record<string, string> = {
  "ha-alert": "div",
  "ha-assist-chip": "span",
  "ha-button": "button",
  "ha-card": "div",
  "ha-checkbox": "input",
  "ha-chip-set": "div",
  "ha-data-table": "div",
  "ha-dialog": "dialog",
  "ha-expansion-panel": "details",
  "ha-form": "div",
  "ha-icon": "span",
  "ha-icon-button": "button",
  "ha-list-item": "li",
  "ha-markdown": "div",
  "ha-menu-button": "span",
  "ha-select": "select",
  "ha-spinner": "span",
  "ha-svg-icon": "span",
  "ha-switch": "input",
  "ha-tab-group": "nav",
  "ha-tab-group-tab": "button",
  "ha-tooltip": "span",
  "ha-top-app-bar-fixed": "div",
};

/** How long to wait for one element to be defined before calling it absent. */
const DEFAULT_TIMEOUT_MS = 5000;

/** What resolved and what did not, and the one question a render should ask. */
export interface ComponentSet {
  /** True when this tag resolved and may be rendered. */
  has(tag: string): boolean;
  /** The tag to render: the Home Assistant one when it exists, a plain one when it does not. */
  tag(name: string): string;
  /** Everything that did not resolve, for the one warning the panel logs. */
  readonly missing: readonly string[];
}

/** Options, all of them so a test can drive this without a Home Assistant frontend. */
export interface LoadOptions {
  timeoutMs?: number;
  registry?: CustomElementRegistry;
  loadHelpers?: () => Promise<CardHelpers> | undefined;
}

class Loaded implements ComponentSet {
  constructor(
    private readonly defined: ReadonlySet<string>,
    readonly missing: readonly string[],
  ) {}

  has(tag: string): boolean {
    return this.defined.has(tag);
  }

  tag(name: string): string {
    return this.defined.has(name) ? name : (FALLBACKS[name] ?? "div");
  }
}

/**
 * Return a component set that simply says these tags exist.
 *
 * For the static harness and the tests, which mount the panel outside a Home Assistant
 * and would otherwise wait out the whole timeout for every element. Not a shortcut in
 * production code: nothing in `src/` outside a test calls it.
 */
export function componentSet(defined: readonly string[]): ComponentSet {
  const present = new Set(defined);
  return new Loaded(
    present,
    HA_COMPONENTS.filter((tag) => !present.has(tag)),
  );
}

/**
 * Pull Home Assistant's lazily defined elements into existence.
 *
 * Never rejects. Every way this can go wrong (no `loadCardHelpers`, a helper that throws,
 * an element that is never defined) ends in the same place: the tag is reported missing
 * and the caller renders the plain version. Throwing here would take the whole panel down
 * for a component one view wanted.
 */
export async function loadHaComponents(
  tags: readonly string[] = HA_COMPONENTS,
  options: LoadOptions = {},
): Promise<ComponentSet> {
  const registry = options.registry ?? globalThis.customElements;
  await forceLoad(options.loadHelpers ?? (() => window.loadCardHelpers?.()));
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const defined = new Set<string>();
  const missing: string[] = [];
  await Promise.all(
    tags.map(async (tag) => {
      if (await isDefined(registry, tag, timeoutMs)) {
        defined.add(tag);
      } else {
        missing.push(tag);
      }
    }),
  );
  missing.sort();
  if (missing.length) {
    console.warn(
      `Device Links: these Home Assistant components did not load, so plain elements are used instead: ${missing.join(", ")}`,
    );
  }
  return new Loaded(defined, missing);
}

/** Ask the frontend to load the bundle its own form controls live in. */
async function forceLoad(loadHelpers: () => Promise<CardHelpers> | undefined): Promise<void> {
  try {
    const helpers = await loadHelpers();
    if (!helpers) {
      return;
    }
    const card = await helpers.createCardElement({ type: "entities", entities: [] });
    const cardClass = card.constructor as { getConfigElement?: () => Promise<unknown> };
    await cardClass.getConfigElement?.();
  } catch {
    // An older or newer frontend that does not offer the helpers, or a card that will not
    // build one. Neither is fatal: the elements may still be defined, and the ones that
    // are not are reported as missing below.
  }
}

/** True when this tag is defined, or becomes defined before the deadline. */
async function isDefined(
  registry: CustomElementRegistry | undefined,
  tag: string,
  timeoutMs: number,
): Promise<boolean> {
  if (!registry) {
    return false;
  }
  if (registry.get(tag)) {
    return true;
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      registry.whenDefined(tag).then(() => true),
      new Promise<boolean>((resolve) => {
        timer = setTimeout(() => resolve(false), timeoutMs);
      }),
    ]);
  } catch {
    return false;
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}
