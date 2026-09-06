/**
 * Devices: what is actually on each device, rule or no rule.
 *
 * Task 6 fills this in: the device list, then per device the outgoing emitters with their
 * labels and capacity, the incoming links, and the association-relevant settings. A
 * lifeline entry is shown as a system link and offers no Remove control at all.
 */

import type { TemplateResult } from "lit";
import { customElement } from "lit/decorators.js";

import { sharedStyles } from "../styles";
import { placeholder } from "./placeholder";
import { DeviceLinksView } from "./view-base";

@customElement("device-links-devices")
export class DeviceLinksDevices extends DeviceLinksView {
  static override styles = sharedStyles;

  protected override render(): TemplateResult {
    return placeholder("Devices", "What each device holds, and who reaches it.");
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-devices": DeviceLinksDevices;
  }
}
