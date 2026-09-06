/**
 * The constants vite substitutes at build time, from `build-defines.ts`.
 *
 * They are `define` replacements rather than imports on purpose: both are read from files
 * the Python package owns, so the bundle cannot disagree with the integration it ships
 * inside about either its version or its messages.
 */

/** The `version` field of `custom_components/device_links/manifest.json` at build time. */
declare const __DL_BUNDLE_VERSION__: string;

/** Every diagnostic and Repairs message from `strings.json`, keyed by translation key. */
declare const __DL_MESSAGES__: Record<string, string>;

interface Window {
  /**
   * Home Assistant's own card helper loader.
   *
   * Present on any frontend recent enough to matter and absent on one that is not, which
   * is why every call site treats it as optional rather than asserting it.
   */
  loadCardHelpers?: () => Promise<CardHelpers>;
}

/** The two helpers the force-load technique uses. Everything else on it is unused here. */
interface CardHelpers {
  createCardElement(config: Record<string, unknown>): Promise<HTMLElement>;
}
