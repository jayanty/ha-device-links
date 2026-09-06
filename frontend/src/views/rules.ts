/**
 * Rules: what each control should do, and what it is doing.
 *
 * The table is a plain one rather than `ha-data-table`. Every cell here is something the
 * user acts on (a switch, chips, three buttons), the row-template API of that element
 * differs between frontend versions, and open item R1 says nobody has yet confirmed that
 * Home Assistant's lazily defined elements resolve inside this panel at all. A table that
 * renders as an empty box is a rules screen with no rules on it, which is the one failure
 * this view cannot survive. It scrolls inside its own box so a phone-width screen does not
 * scroll sideways, and it is registered as open item T36.
 *
 * **The enabled switch does not write to a device by itself.** Enabling a rule physically
 * adds its links (Decision D7), so the switch here stores the change and then opens the
 * plan dialog, which is the only path in this panel to a write. Cancelling the plan puts
 * the switch back where it was, so a plan somebody walked away from leaves nothing behind.
 */

import { html, nothing, type TemplateResult } from "lit";
import { customElement, state } from "lit/decorators.js";

import { DeviceLinksApiError, describeError, type PlanScope } from "../api";
import "../components/dialog";
import "../dialogs/plan-dialog";
import "../dialogs/rule-editor";
import { renderIcon } from "../components/icon";
import { renderLoops } from "../components/loops";
import type { PlanClosedDetail } from "../dialogs/plan-dialog";
import type { RuleSavedDetail } from "../dialogs/rule-editor";
import {
  backendLabel,
  featureIcon,
  featureLabel,
  plural,
  ruleStateExplanation,
  ruleStateLabel,
  ruleStateTone,
  templateLabel,
  templateSummary,
} from "../format";
import { sharedStyles } from "../styles";
import type {
  Backend,
  DeviceRow,
  LoopWarning,
  ProfileRow,
  RuleData,
  RuleRow,
  RuleState,
  TemplateId,
} from "../types";
import { DeviceLinksView } from "./view-base";

/** The templates offered when there are no rules yet, if the backend answers with none. */
const FALLBACK_TEMPLATES: readonly TemplateId[] = [
  "remote",
  "virtual_3way",
  "scene_button",
  "off_all",
  "status_feedback",
  "custom",
];

const STATE_FILTERS: readonly RuleState[] = [
  "in_sync",
  "drift",
  "pending",
  "blocked",
  "disabled",
  "unknown",
];

/** A switch that was flipped, and what it was before, so cancelling can put it back. */
interface StagedToggle {
  rule: RuleData;
  wasEnabled: boolean;
}

@customElement("device-links-rules")
export class DeviceLinksRules extends DeviceLinksView {
  static override styles = sharedStyles;

  @state() private _profile: ProfileRow | null = null;

  @state() private _rules: RuleRow[] = [];

  /** What the active profile's rules, together, can make chase each other (FR-R7). */
  @state() private _loops: LoopWarning[] = [];

  @state() private _devices: DeviceRow[] = [];

  @state() private _templates: TemplateId[] = [...FALLBACK_TEMPLATES];

  /** Emitter labels by "device identity/emitter id", filled in as devices are read. */
  @state() private _emitterLabels: Record<string, string> = {};

  @state() private _loading = true;

  @state() private _error: string | null = null;

  @state() private _search = "";

  @state() private _backendFilter = "";

  @state() private _stateFilter = "";

  @state() private _editorOpen = false;

  @state() private _editing: RuleData | null = null;

  @state() private _editorTemplate: TemplateId | null = null;

  @state() private _planOpen = false;

  @state() private _planScope: PlanScope | undefined;

  @state() private _planHeading = "Plan and apply";

  @state() private _confirmDelete: RuleRow | null = null;

  private _staged: StagedToggle | null = null;

  private _appliedDuringPlan = false;

  override connectedCallback(): void {
    super.connectedCallback();
    void this._load();
  }

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("selected") && this.selected !== null) {
      this._search = "";
      const wanted = this.selected;
      const row = this._rules.find((rule) => rule.rule.id === wanted);
      if (row !== undefined) {
        this._openEditor(row.rule);
      }
    }
  }

  protected override render(): TemplateResult {
    return html`
      <div class="content">
        ${
          this._error === null
            ? nothing
            : html`<div class="notice error" role="alert">${this._error}</div>`
        }
        ${renderLoops(this._loops)}
        <div class="card">
          ${this._renderToolbar()}
          ${this._renderBody()}
        </div>
      </div>
      ${this._renderDeleteConfirm()}
      <dl-rule-editor
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._editorOpen}
        .devices=${this._devices}
        .rule=${this._editing}
        .initialTemplate=${this._editorTemplate}
        .hybridAllowed=${this.hybridAllowed}
        @dl-editor-closed=${this._closeEditor}
        @dl-rule-saved=${this._onSaved}
      ></dl-rule-editor>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .scope=${this._planScope}
        .heading=${this._planHeading}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
  }

  private _renderToolbar(): TemplateResult {
    return html`
      <div class="spread">
        <div class="grow">
          <h2>Rules</h2>
          <p class="secondary">
            ${
              this._profile === null
                ? "No profile is active, so no rule is in force."
                : `In ${this._profile.name}. ${plural(this._rules.length, "rule")}.`
            }
          </p>
        </div>
        <button type="button" class="primary" @click=${() => this._openEditor(null)}>
          New rule
        </button>
      </div>
      <div class="toolbar">
        <label class="field grow">
          <span>Search</span>
          <input
            type="search"
            .value=${this._search}
            placeholder="Rule, device or target"
            @input=${(event: Event) => {
              this._search = (event.target as HTMLInputElement).value;
            }}
          />
        </label>
        <label class="field">
          <span>Protocol</span>
          <select
            .value=${this._backendFilter}
            @change=${(event: Event) => {
              this._backendFilter = (event.target as HTMLSelectElement).value;
            }}
          >
            <option value="">Any</option>
            <option value="zwave">Z-Wave</option>
            <option value="zigbee2mqtt">Zigbee</option>
            <option value="matter">Matter</option>
          </select>
        </label>
        <label class="field">
          <span>Status</span>
          <select
            .value=${this._stateFilter}
            @change=${(event: Event) => {
              this._stateFilter = (event.target as HTMLSelectElement).value;
            }}
          >
            <option value="">Any</option>
            ${STATE_FILTERS.map(
              (state) => html`<option value=${state}>${ruleStateLabel(state)}</option>`,
            )}
          </select>
        </label>
      </div>
    `;
  }

  private _renderBody(): TemplateResult {
    if (this._loading) {
      return html`<p class="secondary">Loading.</p>`;
    }
    if (this._rules.length === 0) {
      return this._renderEmpty();
    }
    const rows = this._filtered();
    if (rows.length === 0) {
      return html`<p class="empty">No rule matches those filters.</p>`;
    }
    if (this.narrow) {
      // A seven-column table on a phone is a table nobody reads: it scrolls sideways and
      // every cell is two words wide. The same rows as cards say the same things.
      return html`<ul class="list">${rows.map((row) => this._renderCard(row))}</ul>`;
    }
    return html`
      <div class="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Rule</th>
              <th>Source</th>
              <th>Targets</th>
              <th>Sends</th>
              <th>Status</th>
              <th>On</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => this._renderRow(row))}
          </tbody>
        </table>
      </div>
    `;
  }

  /** One rule as a card, which is what the table becomes on a narrow screen. */
  private _renderCard(row: RuleRow): TemplateResult {
    const rule = row.rule;
    return html`
      <li>
        <div class="row">
          <strong class="grow">${rule.name}</strong>
          <span class="chip ${ruleStateTone(row.state)}" title=${ruleStateExplanation(row.state)}>
            ${ruleStateLabel(row.state)}
          </span>
        </div>
        <p class="secondary" style="margin: 4px 0">
          ${this._nameOf(rule.source.device)},
          ${this._emitterLabel(rule.source.device, rule.source.emitter_id)} to
          ${rule.targets.map((target) => this._nameOf(target.device)).join(", ")}
        </p>
        <div class="chips" style="margin-bottom: 8px">
          <span class="chip muted">${templateLabel(rule.template)}</span>
          ${rule.features.map(
            (feature) => html`<span class="chip">
              ${renderIcon(this.components, featureIcon(feature))}${featureLabel(feature)}
            </span>`,
          )}
        </div>
        <label class="choice">
          <input
            type="checkbox"
            role="switch"
            .checked=${rule.enabled}
            @change=${(event: Event) => this._toggle(row, event)}
          />
          <span>Enabled</span>
        </label>
        <div class="row">
          <button type="button" class="outlined" @click=${() => this._openEditor(rule)}>Edit</button>
          <button
            type="button"
            class="outlined"
            @click=${() => this._openPlan({ rule_ids: [rule.id] }, rule.name)}
          >
            Plan
          </button>
          <button type="button" class="danger" @click=${() => this._askDelete(row)}>Delete</button>
        </div>
      </li>
    `;
  }

  private _renderRow(row: RuleRow): TemplateResult {
    const rule = row.rule;
    return html`
      <tr>
        <td>
          <strong>${rule.name}</strong>
          <div class="chips" style="margin-top: 4px">
            <span class="chip muted">${templateLabel(rule.template)}</span>
            <span class="chip muted">${backendLabel(rule.backend)}</span>
          </div>
        </td>
        <td>
          <div>${this._nameOf(rule.source.device)}</div>
          <div class="secondary">${this._emitterLabel(rule.source.device, rule.source.emitter_id)}</div>
        </td>
        <td>
          <div class="chips">
            ${rule.targets.map(
              (target) => html`<span class="chip">${this._nameOf(target.device)}</span>`,
            )}
          </div>
        </td>
        <td>
          <div class="chips">
            ${rule.features.map(
              (feature) => html`<span class="chip" title=${featureLabel(feature)}>
                ${renderIcon(this.components, featureIcon(feature))}${featureLabel(feature)}
              </span>`,
            )}
          </div>
          ${rule.direction === "two_way" ? html`<span class="secondary">Two way</span>` : nothing}
        </td>
        <td>
          <span class="chip ${ruleStateTone(row.state)}" title=${ruleStateExplanation(row.state)}>
            ${ruleStateLabel(row.state)}
          </span>
          ${
            row.links_total > 0
              ? html`<div class="secondary">${row.links_in_sync} of ${row.links_total} links</div>`
              : nothing
          }
        </td>
        <td>
          <label class="choice">
            <input
              type="checkbox"
              role="switch"
              aria-label=${`Enable ${rule.name}`}
              .checked=${rule.enabled}
              @change=${(event: Event) => this._toggle(row, event)}
            />
          </label>
        </td>
        <td class="actions">
          <div class="row nowrap">
            <button type="button" class="outlined" @click=${() => this._openEditor(rule)}>
              Edit
            </button>
            <button
              type="button"
              class="outlined"
              @click=${() => this._openPlan({ rule_ids: [rule.id] }, rule.name)}
            >
              Plan
            </button>
            <button type="button" class="danger" @click=${() => this._askDelete(row)}>
              Delete
            </button>
          </div>
        </td>
      </tr>
    `;
  }

  private _renderEmpty(): TemplateResult {
    return html`
      <p>No rules yet. Start from what you want the control to do.</p>
      <div
        class="chips"
        style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px"
      >
        ${this._templates.map(
          (template) => html`
            <button
              type="button"
              class="selectable"
              style="border-color: var(--divider-color, rgba(0, 0, 0, 0.12))"
              @click=${() => this._openEditor(null, template)}
            >
              <strong>${templateLabel(template)}</strong>
              <div class="secondary">${templateSummary(template)}</div>
            </button>
          `,
        )}
      </div>
    `;
  }

  private _renderDeleteConfirm(): TemplateResult {
    const row = this._confirmDelete;
    return html`
      <dl-dialog
        .open=${row !== null}
        .narrow=${this.narrow}
        .heading=${row === null ? "" : `Delete ${row.rule.name}?`}
        @dl-dialog-closed=${() => {
          this._confirmDelete = null;
        }}
      >
        <p>
          The rule is removed from the profile. What it already wrote stays on the devices
          and becomes unmanaged, which means it is reported rather than removed.
        </p>
        <p class="secondary">
          To take those links off as well, disable the rule first and apply that, then delete it.
        </p>
        <div slot="actions">
          <button
            type="button"
            class="outlined"
            @click=${() => {
              this._confirmDelete = null;
            }}
          >
            Cancel
          </button>
          <button type="button" class="danger" @click=${this._delete}>Delete the rule</button>
        </div>
      </dl-dialog>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Data.
  // ------------------------------------------------------------------------------------

  private _filtered(): RuleRow[] {
    const needle = this._search.trim().toLowerCase();
    return this._rules.filter((row) => {
      if (this._backendFilter && row.rule.backend !== (this._backendFilter as Backend)) {
        return false;
      }
      if (this._stateFilter && row.state !== (this._stateFilter as RuleState)) {
        return false;
      }
      if (!needle) {
        return true;
      }
      const haystack = [
        row.rule.name,
        this._nameOf(row.rule.source.device),
        ...row.rule.targets.map((target) => this._nameOf(target.device)),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }

  private _nameOf(identity: string): string {
    return this._devices.find((device) => device.identity === identity)?.name ?? identity;
  }

  private _emitterLabel(identity: string, emitterId: string): string {
    return this._emitterLabels[`${identity}/${emitterId}`] ?? emitterId;
  }

  private async _load(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._loading = true;
    try {
      const [profiles, devices, templates] = await Promise.all([
        this.api.listProfiles(),
        this.api.listDevices(),
        this.api.listTemplates(),
      ]);
      this._devices = devices ?? [];
      if (templates?.length) {
        this._templates = templates.map((template) => template.id);
      }
      const active = (profiles.profiles ?? []).find((profile) => profile.is_active) ?? null;
      this._profile = active;
      const detail = active === null ? null : await this.api.getProfile(active.id);
      this._rules = detail?.rules ?? [];
      // Answered for the active profile as it now stands, so enabling a rule from the
      // table shows the loop it closes. The rule editor asks the same question with the
      // rule being edited folded in, which is the earlier of the two answers (FR-R7).
      this._loops = detail?.loops ?? [];
      this._error = null;
      void this._loadEmitterLabels();
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._loading = false;
    }
  }

  /**
   * Put the control's own label in the table rather than its id.
   *
   * "Button 2 - Pressed" is what the device calls it and what the user is looking at;
   * "g7" is what the rule stores. One command per distinct source device, which is a
   * handful, and the id stays as the fallback for anything that could not be read.
   */
  private async _loadEmitterLabels(): Promise<void> {
    if (!this.api) {
      return;
    }
    const wanted = new Map<string, string>();
    for (const row of this._rules) {
      const device = this._devices.find(
        (candidate) => candidate.identity === row.rule.source.device,
      );
      if (device?.device_id != null) {
        wanted.set(device.identity, device.device_id);
      }
    }
    const labels: Record<string, string> = { ...this._emitterLabels };
    await Promise.all(
      [...wanted].map(async ([identity, deviceId]) => {
        try {
          const detail = await this.api.getDevice(deviceId);
          for (const emitter of detail.emitters) {
            labels[`${identity}/${emitter.emitter_id}`] = emitter.label;
          }
        } catch {
          // A device that cannot be read keeps its emitter ids in the table, which is
          // exactly what this is a nicety on top of.
        }
      }),
    );
    this._emitterLabels = labels;
  }

  // ------------------------------------------------------------------------------------
  // The editor.
  // ------------------------------------------------------------------------------------

  private _openEditor(rule: RuleData | null, template: TemplateId | null = null): void {
    this._editing = rule;
    this._editorTemplate = template;
    this._editorOpen = true;
  }

  private _closeEditor(): void {
    this._editorOpen = false;
    this._editing = null;
    this._editorTemplate = null;
  }

  private _onSaved(event: Event): void {
    const detail = (event as CustomEvent<RuleSavedDetail>).detail;
    this._closeEditor();
    void this._load();
    if (detail.apply) {
      // "Save and apply" opens the plan dialog rather than skipping it (Decision D18).
      this._openPlan({ rule_ids: [detail.rule.id] }, detail.rule.name);
    }
  }

  // ------------------------------------------------------------------------------------
  // The switch, which stores intent and then asks for a plan.
  // ------------------------------------------------------------------------------------

  private async _toggle(row: RuleRow, event: Event): Promise<void> {
    if (!this.api) {
      return;
    }
    const enabled = (event.target as HTMLInputElement).checked;
    const previous = row.rule.enabled;
    const updated: RuleData = { ...row.rule, enabled };
    try {
      await this.api.upsertRule(updated, this._profile?.id);
      this._staged = { rule: row.rule, wasEnabled: previous };
      this._appliedDuringPlan = false;
      await this._load();
      this._openPlan(
        { rule_ids: [row.rule.id] },
        `${enabled ? "Enable" : "Disable"} ${row.rule.name}`,
      );
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
      await this._load();
    }
  }

  // ------------------------------------------------------------------------------------
  // The plan dialog.
  // ------------------------------------------------------------------------------------

  private _openPlan(scope: PlanScope | undefined, name?: string): void {
    this._planScope = scope;
    this._planHeading = name === undefined ? "Plan and apply" : `Plan and apply: ${name}`;
    this._planOpen = true;
  }

  /**
   * Put a staged switch back when its plan was closed without being applied.
   *
   * Nothing was written, so the honest end state is the one the user started in. Leaving
   * the stored change behind would leave a rule that says it is enabled and links that are
   * not there, off the back of a dialog somebody dismissed. The exception is a plan that
   * had nothing in it, which means the devices already hold what the switch asked for.
   */
  private async _closePlan(event?: Event): Promise<void> {
    this._planOpen = false;
    const detail = (event as CustomEvent<PlanClosedDetail> | undefined)?.detail;
    const staged = this._staged;
    this._staged = null;
    // A plan with nothing in it is not something to walk away from: the rule was switched
    // to a state the devices are already in, so the stored change stands and reverting it
    // would make the switch look broken.
    const abandoned = !this._appliedDuringPlan && (detail?.changes ?? 1) > 0;
    if (staged !== null && abandoned && this.api) {
      try {
        await this.api.upsertRule(
          { ...staged.rule, enabled: staged.wasEnabled },
          this._profile?.id,
        );
      } catch (error) {
        this._error = describeError(this.hass, DeviceLinksApiError.from(error));
      }
    }
    this._appliedDuringPlan = false;
    void this._load();
  }

  private _afterApply(): void {
    this._appliedDuringPlan = true;
    void this._load();
  }

  // ------------------------------------------------------------------------------------
  // Deleting.
  // ------------------------------------------------------------------------------------

  private _askDelete(row: RuleRow): void {
    this._confirmDelete = row;
  }

  private async _delete(): Promise<void> {
    const row = this._confirmDelete;
    if (!this.api || row === null) {
      return;
    }
    this._confirmDelete = null;
    try {
      await this.api.deleteRule(row.rule.id, this._profile?.id);
      await this._load();
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-rules": DeviceLinksRules;
  }
}
