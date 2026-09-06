/**
 * Activity: every apply this integration remembers.
 *
 * Task 5 fills this in: the job list with scope, timing and result counts, and a job
 * detail with per-link rows and the raw backend error under an expander, where it is
 * available for a bug report without becoming the primary message.
 */

import type { TemplateResult } from "lit";
import { customElement } from "lit/decorators.js";

import { sharedStyles } from "../styles";
import { placeholder } from "./placeholder";
import { DeviceLinksView } from "./view-base";

@customElement("device-links-activity")
export class DeviceLinksActivity extends DeviceLinksView {
  static override styles = sharedStyles;

  protected override render(): TemplateResult {
    return placeholder("Activity", "Every apply, and what became of each link in it.");
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-activity": DeviceLinksActivity;
  }
}
