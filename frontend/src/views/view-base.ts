/**
 * What every view of the panel is given, and therefore what a view may assume.
 *
 * The shell sets all four properties before a view is ever rendered, and keeps `hass` and
 * `narrow` up to date afterwards. A view should read `api` for anything it needs from the
 * backend and `components` before rendering a Home Assistant element, and should not reach
 * for `hass.states`, `hass.callWS` or the REST API: the WebSocket commands in `api.ts` are
 * the whole of what this panel is allowed to see.
 */

import { LitElement } from "lit";
import { property } from "lit/decorators.js";

import type { DeviceLinksApi } from "../api";
import type { ComponentSet } from "../ha-components";
import type { HomeAssistant } from "../hass";

export abstract class DeviceLinksView extends LitElement {
  /** The live Home Assistant object. Replaced on every state change, so never cache it. */
  @property({ attribute: false }) hass!: HomeAssistant;

  /** The typed WebSocket client. One per panel, shared by every view. */
  @property({ attribute: false }) api!: DeviceLinksApi;

  /** Which Home Assistant elements resolved. Ask before rendering one. */
  @property({ attribute: false }) components!: ComponentSet;

  /** True on a narrow screen, where lists stack and dialogs go full screen. */
  @property({ type: Boolean }) narrow = false;
}
