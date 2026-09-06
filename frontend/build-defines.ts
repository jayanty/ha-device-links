/**
 * The two things the bundle learns from the Python side at build time.
 *
 * Shared by `vite.config.ts` and `vitest.config.ts` so the panel sees the same values
 * under test as it does in a browser. Both are read from files in
 * `custom_components/device_links/`, which makes the build a pure function of the
 * repository: the same commit built twice produces the same bytes, which is what the
 * committed-bundle check in CI depends on. Nothing here reads a clock, an environment
 * variable or a path outside the repository.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/** The integration package, which owns both the version and the translated messages. */
export const componentDir = resolve(here, "../custom_components/device_links");

/** Where the built bundle is committed, and therefore where vite writes it. */
export const bundleDir = resolve(componentDir, "frontend");

/** The one file the panel is built to. */
export const bundleName = "device-links-panel.js";

function readJson(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(componentDir, name), "utf8")) as Record<string, unknown>;
}

/**
 * Every message a `Diagnostic` or a Repairs issue can carry, keyed the way the backend
 * keys it.
 *
 * The backend sends a diagnostic as a translation key and its placeholders, never as a
 * sentence, so the panel has to turn one into text. Home Assistant's own `localize` is
 * asked first and this is the fallback, inlined from the same `strings.json` the
 * integration ships. Without it a diagnostic renders as a bare key on any instance whose
 * frontend has not loaded this integration's translations, and a bare key is exactly what
 * the plan says never to show a user.
 */
function messages(): Record<string, string> {
  const strings = readJson("strings.json");
  const out: Record<string, string> = {};
  for (const section of ["exceptions", "issues"]) {
    const entries = (strings[section] ?? {}) as Record<string, { message?: string }>;
    for (const [key, value] of Object.entries(entries)) {
      if (typeof value?.message === "string") {
        out[key] = value.message;
      }
    }
  }
  return out;
}

/** The compile-time constants, in the shape vite's `define` option wants. */
export function buildDefines(): Record<string, string> {
  const manifest = readJson("manifest.json");
  return {
    __DL_BUNDLE_VERSION__: JSON.stringify(String(manifest.version)),
    __DL_MESSAGES__: JSON.stringify(messages()),
  };
}
