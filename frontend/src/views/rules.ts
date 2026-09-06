/**
 * Rules: the table, and the way in to the rule editor.
 *
 * Task 7 fills this in: an `ha-data-table` of rules with source, targets, features,
 * backend, status and an enabled toggle, search and filters, and an empty state offering
 * the template cards. The rule editor and the plan dialog are the heart of the product.
 */

import type { TemplateResult } from "lit";
import { customElement } from "lit/decorators.js";

import { sharedStyles } from "../styles";
import { placeholder } from "./placeholder";
import { DeviceLinksView } from "./view-base";

@customElement("device-links-rules")
export class DeviceLinksRules extends DeviceLinksView {
  static override styles = sharedStyles;

  protected override render(): TemplateResult {
    return placeholder("Rules", "What each control should do, and what it is doing.");
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-rules": DeviceLinksRules;
  }
}
