/**
 * The body every view has until the view that belongs there is written.
 *
 * Phase 1E Tasks 5 to 7 replace each of the five view bodies with the real thing. Until
 * then the shell has to render something honest: a named, empty view says the panel is
 * working and this part is not built yet, which is a different message from a blank
 * screen and is the true one.
 */

import { html, type TemplateResult } from "lit";

export function placeholder(title: string, summary: string): TemplateResult {
  return html`
    <div class="content">
      <div class="card">
        <h2>${title}</h2>
        <p class="secondary">${summary}</p>
        <p class="secondary">This view is not built yet.</p>
      </div>
    </div>
  `;
}
