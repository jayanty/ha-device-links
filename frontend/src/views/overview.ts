/**
 * Overview: what is true right now, and the two buttons that change it.
 *
 * The screen answers three questions in the order somebody actually asks them. Is
 * anything wrong? What do I do about it? What happened recently? So the state chips come
 * first, "Needs attention" second with every row leading to the thing that fixes it, and
 * the last few jobs last.
 *
 * Neither button here writes to anything on its own. Verify only reads, and reads from
 * the devices rather than from a cache. Plan and apply opens the plan dialog, which is
 * the only path in this panel to a device write (Decision D18).
 */

import { html, nothing, type TemplateResult } from "lit";
import { customElement, state } from "lit/decorators.js";

import { DeviceLinksApiError, describeError, type PlanScope } from "../api";
import "../dialogs/plan-dialog";
import {
  formatTime,
  jobStatusLabel,
  jobStatusTone,
  plural,
  ruleStateExplanation,
  ruleStateLabel,
  ruleStateTone,
  timeAgo,
} from "../format";
import { sharedStyles } from "../styles";
import type { DeviceRow, Job, ProfileRow, RuleRow, RuleState } from "../types";
import { DeviceLinksView } from "./view-base";

/** The states that put a rule on the "Needs attention" list, worst first. */
const ATTENTION_STATES: readonly RuleState[] = ["blocked", "drift", "pending", "unknown"];

/** The order the state chips are shown in, which is also worst first after "in sync". */
const CHIP_STATES: readonly RuleState[] = [
  "in_sync",
  "drift",
  "pending",
  "blocked",
  "disabled",
  "unknown",
];

@customElement("device-links-overview")
export class DeviceLinksOverview extends DeviceLinksView {
  static override styles = sharedStyles;

  @state() private _profile: ProfileRow | null = null;

  @state() private _rules: RuleRow[] = [];

  @state() private _devices: DeviceRow[] = [];

  @state() private _jobs: Job[] = [];

  @state() private _loading = true;

  @state() private _error: string | null = null;

  @state() private _verifying = false;

  @state() private _verifiedAt: string | null = null;

  @state() private _verifiedDevices = 0;

  @state() private _planOpen = false;

  @state() private _planScope: PlanScope | undefined;

  @state() private _planHeading = "Plan and apply";

  override connectedCallback(): void {
    super.connectedCallback();
    void this._load();
  }

  protected override render(): TemplateResult {
    return html`
      <div class="content">
        ${
          this._error === null
            ? nothing
            : html`<div class="notice error" role="alert">${this._error}</div>`
        }
        ${this._renderHeader()}
        ${this._renderAttention()}
        ${this._renderActivity()}
      </div>
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

  private _renderHeader(): TemplateResult {
    const counts = this._stateCounts();
    return html`
      <div class="card">
        <div class="spread">
          <div class="grow">
            <h2>${this._profile?.name ?? "No profile is active"}</h2>
            <p class="secondary">
              ${
                this._profile === null
                  ? "Activate a profile in the Profiles tab, or make one there."
                  : `${plural(this._profile.rules, "rule")}, ${
                      this._profile.enabled_rules
                    } enabled.`
              }
            </p>
            <div class="chips">
              ${CHIP_STATES.map((state) =>
                (counts.get(state) ?? 0) === 0
                  ? nothing
                  : html`<span class="chip ${ruleStateTone(state)}" title=${ruleStateExplanation(state)}>
                      ${ruleStateLabel(state)} ${counts.get(state)}
                    </span>`,
              )}
              ${
                this._loading
                  ? html`<span class="chip muted">Loading</span>`
                  : this._rules.length === 0
                    ? html`<span class="chip muted">No rules yet</span>`
                    : nothing
              }
            </div>
          </div>
          <div class="row">
            <button type="button" class="outlined" ?disabled=${this._verifying} @click=${this._verify}>
              ${this._verifying ? "Verifying" : "Verify"}
            </button>
            <button type="button" class="primary" @click=${() => this._openPlan()}>
              Plan and apply
            </button>
          </div>
        </div>
        <p class="secondary" style="margin: 12px 0 0">
          ${
            this._verifiedAt === null
              ? "Verify reads every device in the active profile and changes nothing."
              : `Verified ${timeAgo(this._verifiedAt)}: ${plural(
                  this._verifiedDevices,
                  "device",
                )} re-read.`
          }
        </p>
      </div>
    `;
  }

  private _renderAttention(): TemplateResult {
    const rules = this._rules.filter((row) => ATTENTION_STATES.includes(row.state));
    const unreadable = this._devices.filter((device) => !device.available);
    if (rules.length === 0 && unreadable.length === 0) {
      return html`
        <div class="card">
          <h3>Needs attention</h3>
          <p class="secondary">
            ${
              this._loading
                ? "Looking."
                : "Nothing. Every rule holds what it asks for, and every device answered."
            }
          </p>
        </div>
      `;
    }
    return html`
      <div class="card">
        <h3>Needs attention</h3>
        <ul class="list">
          ${rules
            .slice()
            .sort(
              (left, right) =>
                ATTENTION_STATES.indexOf(left.state) - ATTENTION_STATES.indexOf(right.state),
            )
            .map((row) => this._renderAttentionRule(row))}
          ${
            unreadable.length === 0
              ? nothing
              : html`
                <li>
                  <div class="spread">
                    <div class="grow">
                      <div class="row">
                        <span class="chip warn">Not answering</span>
                        <strong>${plural(unreadable.length, "device")}</strong>
                      </div>
                      <p class="secondary" style="margin: 4px 0 0">
                        ${unreadable.map((device) => device.name).join(", ")}. Their links are
                        shown from the last successful read and cannot be confirmed now.
                      </p>
                    </div>
                    <button type="button" class="outlined" @click=${() => this.goTo("devices")}>
                      Open devices
                    </button>
                  </div>
                </li>
              `
          }
        </ul>
      </div>
    `;
  }

  private _renderAttentionRule(row: RuleRow): TemplateResult {
    return html`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <span class="chip ${ruleStateTone(row.state)}">${ruleStateLabel(row.state)}</span>
              <strong>${row.rule.name}</strong>
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${ruleStateExplanation(row.state)}
              ${
                row.links_total > 0
                  ? ` ${row.links_in_sync} of ${row.links_total} links are in place.`
                  : ""
              }
            </p>
          </div>
          <div class="row">
            <button type="button" class="outlined" @click=${() => this.goTo("rules", row.rule.id)}>
              Open rule
            </button>
            <button
              type="button"
              class="primary"
              @click=${() => this._openPlan({ rule_ids: [row.rule.id] }, row.rule.name)}
            >
              Plan
            </button>
          </div>
        </div>
      </li>
    `;
  }

  private _renderActivity(): TemplateResult {
    return html`
      <div class="card">
        <div class="spread">
          <h3>Recent activity</h3>
          <button type="button" class="link" @click=${() => this.goTo("activity")}>
            See all
          </button>
        </div>
        ${
          this._jobs.length === 0
            ? html`<p class="secondary">Nothing has been applied yet.</p>`
            : html`
              <ul class="list">
                ${this._jobs.slice(0, 5).map(
                  (job) => html`
                    <li>
                      <button
                        type="button"
                        class="selectable"
                        @click=${() => this.goTo("activity", job.id)}
                      >
                        <span class="row">
                          <span class="chip ${jobStatusTone(job.status)}">
                            ${jobStatusLabel(job.status)}
                          </span>
                          <span class="grow truncate">${job.scope}</span>
                          <span class="secondary">${plural(job.total, "link")}</span>
                          <span class="secondary">${formatTime(job.created_at, this.hass?.language)}</span>
                        </span>
                      </button>
                    </li>
                  `,
                )}
              </ul>
            `
        }
      </div>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Data.
  // ------------------------------------------------------------------------------------

  private async _load(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._loading = true;
    try {
      const [profiles, jobs, devices] = await Promise.all([
        this.api.listProfiles(),
        this.api.listJobs(),
        this.api.listDevices(),
      ]);
      // Every one of these is a field the backend always sends. The fallbacks are for
      // the case where it did not: a view that renders an empty list says less than it
      // should, and a view that throws inside render says nothing at all.
      this._jobs = jobs.jobs ?? [];
      this._devices = devices ?? [];
      const active = (profiles.profiles ?? []).find((profile) => profile.is_active) ?? null;
      this._profile = active;
      this._rules = active === null ? [] : ((await this.api.getProfile(active.id)).rules ?? []);
      this._error = null;
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._loading = false;
    }
  }

  private _stateCounts(): Map<RuleState, number> {
    const counts = new Map<RuleState, number>();
    for (const row of this._rules) {
      counts.set(row.state, (counts.get(row.state) ?? 0) + 1);
    }
    return counts;
  }

  private async _verify(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._verifying = true;
    this._error = null;
    try {
      const result = await this.api.verify();
      this._verifiedDevices = result.devices;
      // The backend keeps no last-verified timestamp, so this is when this panel last
      // asked rather than when the integration last checked (open item T34).
      this._verifiedAt = new Date().toISOString();
      await this._load();
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._verifying = false;
    }
  }

  private _openPlan(scope?: PlanScope, name?: string): void {
    this._planScope = scope;
    this._planHeading = name === undefined ? "Plan and apply" : `Plan and apply: ${name}`;
    this._planOpen = true;
  }

  private _closePlan(): void {
    this._planOpen = false;
    void this._load();
  }

  private _afterApply(): void {
    void this._load();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-overview": DeviceLinksOverview;
  }
}
