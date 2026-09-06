/**
 * The loop warning, rendered the same way wherever it is shown (FR-R7).
 *
 * One function rather than a copy in each view, because the wording is the whole of the
 * feature. A loop analysis that says "loop detected" has told the user nothing they can
 * act on: what makes it worth showing is naming the devices that are on the cycle and the
 * rules that join them, and saying plainly that this is a warning rather than a refusal
 * (E30). The analysis knows what the links say, not what the devices do, and the user may
 * know something it does not.
 */

import { html, nothing, type TemplateResult } from "lit";

import type { LoopWarning } from "../types";

/** Render every loop as a warning notice, or nothing at all when there are none. */
export function renderLoops(loops: readonly LoopWarning[]): TemplateResult | typeof nothing {
  if (loops.length === 0) {
    return nothing;
  }
  return html`
    ${loops.map(
      (loop) => html`
        <div class="notice warn" role="status">
          <p>
            <strong>Possible loop.</strong>
            ${loop.devices.map((device) => device.name).join(", ")}
            can pass a command round between them: each one is set to repeat what it
            receives to its own associations, and together their links form a circle.
          </p>
          <p class="secondary">
            ${
              loop.rule_names.length === 0
                ? "No rule of this profile joins them, so the links that close the circle came from somewhere else."
                : `Made by: ${loop.rule_names.join(", ")}.`
            }
            This is a warning, not a refusal. Turning off "make the control's own load
            follow the press" on any one of these devices breaks the circle, and so does
            making one of the rules one way.
          </p>
        </div>
      `,
    )}
  `;
}
