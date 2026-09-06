/**
 * An icon when Home Assistant has one, and nothing at all when it does not.
 *
 * Every icon in this panel is decorative: the label beside it says the same thing in
 * words. That is what makes rendering nothing an acceptable fallback, and it is also why
 * every one of these is `aria-hidden`, so a screen reader is not told "power icon, on and
 * off" for one chip.
 */

import { html, nothing, type TemplateResult } from "lit";

import type { ComponentSet } from "../ha-components";

export function renderIcon(
  components: ComponentSet | null | undefined,
  icon: string,
): TemplateResult | typeof nothing {
  if (!components?.has("ha-icon")) {
    return nothing;
  }
  return html`<ha-icon .icon=${icon} aria-hidden="true"></ha-icon>`;
}
