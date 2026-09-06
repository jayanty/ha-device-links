/**
 * List beside detail on a wide screen, one at a time on a narrow one.
 *
 * The same layout is wanted by Devices, Rules and Profiles, so it lives here rather than
 * three times. On a narrow screen the detail replaces the list rather than sitting under
 * it, because a phone-width column of a list followed by a detail means scrolling past
 * everything to read the thing you tapped.
 *
 * The host view owns the selection: it sets `showDetail` when something is selected and
 * clears it when the back control in its own detail pane is used.
 */

import { css, html, LitElement, type TemplateResult } from "lit";
import { customElement, property } from "lit/decorators.js";

@customElement("dl-two-pane")
export class DeviceLinksTwoPane extends LitElement {
  /** True on a narrow screen, where only one pane is shown at a time. */
  @property({ type: Boolean, reflect: true }) narrow = false;

  /** True when a detail is selected. Only consulted while `narrow`. */
  @property({ type: Boolean, attribute: "show-detail" }) showDetail = false;

  static override styles = css`
    :host {
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(280px, 1fr) minmax(0, 2fr);
      align-items: start;
    }

    :host([narrow]) {
      grid-template-columns: 1fr;
    }

    .pane {
      min-width: 0;
    }

    .hidden {
      display: none;
    }
  `;

  protected override render(): TemplateResult {
    const hideList = this.narrow && this.showDetail;
    const hideDetail = this.narrow && !this.showDetail;
    return html`
      <div class="pane ${hideList ? "hidden" : ""}"><slot name="list"></slot></div>
      <div class="pane ${hideDetail ? "hidden" : ""}"><slot name="detail"></slot></div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dl-two-pane": DeviceLinksTwoPane;
  }
}
