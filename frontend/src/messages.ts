/**
 * Turning a translation key into a sentence.
 *
 * The backend never sends prose. A `Diagnostic` is a key and its placeholders, because a
 * message that crossed as English could not be localised at all, and an API error carries
 * `translation_key` beside the `message` for the same reason. So this is where the panel
 * turns one into something a person reads, and it never gives up and shows the key.
 *
 * Two sources, in order. Home Assistant's own `localize` first, so a user running in
 * German gets German the moment the frontend has this integration's translations loaded.
 * The English text inlined from `strings.json` at build time second, because a custom
 * integration's `exceptions` strings are not among the categories the frontend loads for
 * every panel, and a bare key in a plan dialog is worse than an English sentence in a
 * German UI.
 */

import type { HomeAssistant } from "./hass";
import type { Diagnostic } from "./types";

/** The translation namespace the integration's own strings live under. */
const DOMAIN_PREFIX = "component.device_links";

/** The sections of `strings.json` a diagnostic key can come from, in search order. */
const SECTIONS = ["exceptions", "issues"] as const;

/** Fill `{placeholder}` markers, leaving any the caller did not supply visible as-is. */
export function fillPlaceholders(
  template: string,
  placeholders: Record<string, string | number> | null | undefined,
): string {
  if (!placeholders) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = placeholders[name];
    return value === undefined || value === null ? whole : String(value);
  });
}

/**
 * Return the sentence for one translation key, or null when nothing has one.
 *
 * Null rather than the key: a caller decides what to say when there is no message, and
 * every caller in this panel says something other than the key.
 */
export function lookupMessage(
  hass: HomeAssistant | null | undefined,
  key: string,
  placeholders?: Record<string, string | number> | null,
): string | null {
  for (const section of SECTIONS) {
    const localized = hass?.localize(`${DOMAIN_PREFIX}.${section}.${key}.message`, {
      ...(placeholders ?? {}),
    });
    if (localized) {
      return localized;
    }
  }
  const fallback = __DL_MESSAGES__[key];
  return fallback === undefined ? null : fillPlaceholders(fallback, placeholders);
}

/**
 * Return what a diagnostic says, in words.
 *
 * The last resort is deliberately a sentence rather than the raw key: a key on its own
 * reads as a crash, and this reads as a message this build of the panel does not carry,
 * which is what it is.
 */
export function localizeDiagnostic(
  hass: HomeAssistant | null | undefined,
  diagnostic: Diagnostic | null | undefined,
): string {
  if (!diagnostic) {
    return "";
  }
  const message = lookupMessage(hass, diagnostic.translation_key, diagnostic.placeholders);
  if (message !== null) {
    return message;
  }
  const readable = diagnostic.translation_key.replace(/_/g, " ");
  return `Device Links reported "${readable}", and this panel has no wording for it yet.`;
}
