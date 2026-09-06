/**
 * What every view of the panel is given, and therefore what a view may assume.
 *
 * The shell sets all five properties before a view is ever rendered, and keeps `hass` and
 * `narrow` up to date afterwards. A view should read `api` for anything it needs from the
 * backend and `components` before rendering a Home Assistant element, and should not reach
 * for `hass.states`, `hass.callWS` or the REST API: the WebSocket commands in `api.ts` are
 * the whole of what this panel is allowed to see.
 *
 * `selected` and `goTo` are the two halves of moving between tabs. A row in the Overview's
 * "Needs attention" list is only useful if it leads to the thing that fixes it, and the
 * view it leads to has to be told which row was followed. The shell owns the route, so a
 * view asks rather than navigates.
 */

import { LitElement } from "lit";
import { property } from "lit/decorators.js";

import type { DeviceLinksApi } from "../api";
import type { ComponentSet } from "../ha-components";
import type { HomeAssistant } from "../hass";

/** What one view asks the shell to show next. */
export interface NavigateDetail {
  /** The tab id, as `tabs.ts` spells it. */
  tab: string;
  /** What that tab should open, if anything: a rule id, a device identity, a job id. */
  select?: string;
}

export abstract class DeviceLinksView extends LitElement {
  /** The live Home Assistant object. Replaced on every state change, so never cache it. */
  @property({ attribute: false }) hass!: HomeAssistant;

  /** The typed WebSocket client. One per panel, shared by every view. */
  @property({ attribute: false }) api!: DeviceLinksApi;

  /** Which Home Assistant elements resolved. Ask before rendering one. */
  @property({ attribute: false }) components!: ComponentSet;

  /** True on a narrow screen, where lists stack and dialogs go full screen. */
  @property({ type: Boolean }) narrow = false;

  /** What another view asked this one to open, or null when it was opened plainly. */
  @property({ attribute: false }) selected: string | null = null;

  /**
   * Whether this Home Assistant allows HA-executed legs (FR-H1).
   *
   * From the panel config rather than from a command, because it cannot change without the
   * config entry reloading. False is the default and the honest answer for an older
   * backend: no hybrid opt-in is offered, so nothing can be ticked that the backend would
   * never register.
   */
  @property({ type: Boolean }) hybridAllowed = false;

  /** Ask the shell to show another tab, and to open something in it. */
  protected goTo(tab: string, select?: string): void {
    this.dispatchEvent(
      new CustomEvent<NavigateDetail>("dl-navigate", {
        detail: select === undefined ? { tab } : { tab, select },
        bubbles: true,
        composed: true,
      }),
    );
  }
}
