/**
 * The Device Links panel: the element Home Assistant loads.
 *
 * This is the entry point vite builds, and at this commit it is deliberately no more than
 * that: enough of a panel to prove the toolchain end to end, which is what Task 1 is for.
 * Task 4 turns it into the shell, with the tabs, the component loading and the version
 * banner. What is already load bearing is the shape: one custom element, the four
 * properties Home Assistant sets on a panel, and the build-time version constant.
 */

import { css, html, LitElement, type TemplateResult } from "lit";
import { customElement, property } from "lit/decorators.js";

import type { HomeAssistant, PanelInfo, Route } from "./hass";
import { sharedStyles } from "./styles";

/** The version this bundle was built from, substituted by vite from `manifest.json`. */
export const BUNDLE_VERSION = __DL_BUNDLE_VERSION__;

@customElement("device-links-panel")
export class DeviceLinksPanel extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;

  @property({ type: Boolean, reflect: true }) narrow = false;

  @property({ attribute: false }) route?: Route;

  @property({ attribute: false }) panel?: PanelInfo;

  static override styles = [
    sharedStyles,
    css`
      :host {
        display: block;
        height: 100%;
        background: var(--primary-background-color, #fafafa);
      }
    `,
  ];

  protected override render(): TemplateResult {
    return html`
      <div class="content">
        <div class="card">
          <h2>Device Links</h2>
          <p class="secondary">Panel version ${BUNDLE_VERSION}.</p>
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-panel": DeviceLinksPanel;
  }
}
