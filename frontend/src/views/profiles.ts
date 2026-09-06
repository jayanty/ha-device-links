/**
 * Profiles: the sets of rules, and which one is in force.
 *
 * Task 7 fills this in alongside the rules table: list, activate, duplicate, import and
 * export. Activating opens a plan rather than writing, which is FR-E1.
 */

import type { TemplateResult } from "lit";
import { customElement } from "lit/decorators.js";

import { sharedStyles } from "../styles";
import { placeholder } from "./placeholder";
import { DeviceLinksView } from "./view-base";

@customElement("device-links-profiles")
export class DeviceLinksProfiles extends DeviceLinksView {
  static override styles = sharedStyles;

  protected override render(): TemplateResult {
    return placeholder("Profiles", "The sets of rules, and which one is in force.");
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-profiles": DeviceLinksProfiles;
  }
}
