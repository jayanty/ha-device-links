/**
 * Overview: what is true right now, and the two buttons that change it.
 *
 * Task 5 fills this in: the active profile, chips for in sync, drift, pending and
 * blocked, the last verified time, Verify and Plan-and-apply, a "Needs attention" list
 * where every row links to its fix, and the last five jobs.
 */

import type { TemplateResult } from "lit";
import { customElement } from "lit/decorators.js";

import { sharedStyles } from "../styles";
import { placeholder } from "./placeholder";
import { DeviceLinksView } from "./view-base";

@customElement("device-links-overview")
export class DeviceLinksOverview extends DeviceLinksView {
  static override styles = sharedStyles;

  protected override render(): TemplateResult {
    return placeholder("Overview", "What every rule is doing, and what needs attention.");
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-overview": DeviceLinksOverview;
  }
}
