/**
 * The dialog every write in this product goes through.
 *
 * Decision D18, and the rule that shapes every screen: no path in this panel reaches a
 * device without a plan the user looked at and confirmed. So there is one dialog, it is
 * opened from the Overview, the Rules table, the rule editor, the Devices view and the
 * Profiles view, and each of those hands it a scope rather than a shortcut. "Save and
 * apply" in the rule editor opens this with the plan already loaded; it does not skip it.
 *
 * **The token is the plan that was on screen.** `api.apply` is given the token of the
 * plan this dialog is showing, never a fresh one, because that token is what makes a
 * stale plan detectable (FR-A3). Anything that changes what would be written, which here
 * means ticking an unmanaged link, re-plans and gets a new token: a tick that changed the
 * work without changing the token would be a change the user confirmed by seeing
 * something else.
 *
 * **The unmanaged boxes start unticked and "select all" skips system links.** Decision D9
 * says an unmanaged link is reported, never removed by default, and this dialog is the
 * last place a user can be protected from taking off an association they made by hand in
 * Z-Wave JS UI years ago. The planner already keeps system links out of the unmanaged
 * bucket entirely; the select-all filter here is the second lock on the same door.
 *
 * **Every bucket is always present**, empty when empty, so the sections below render
 * without existence checks.
 */

import { css, html, LitElement, nothing, type TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import {
  type DeviceLinksApi,
  DeviceLinksApiError,
  describeError,
  type PlanScope,
  type Subscription,
} from "../api";
import "../components/dialog";
import {
  backendLabel,
  describeLink,
  jobStatusLabel,
  jobStatusTone,
  outcomeLabel,
  outcomeTone,
  plural,
} from "../format";
import type { ComponentSet } from "../ha-components";
import type { HomeAssistant } from "../hass";
import { localizeDiagnostic } from "../messages";
import { sharedStyles } from "../styles";
import type {
  JobFinished,
  JobProgress,
  LinkOutcome,
  Plan,
  PlanDevice,
  PlanItem,
  UnmanagedLink,
} from "../types";

/** What the dialog is doing, which decides what fills it and what the buttons say. */
type Phase = "loading" | "plan" | "applying" | "finished";

/** What a caller learns when a job this dialog started has ended. */
export interface PlanAppliedDetail {
  job: JobFinished;
}

@customElement("dl-plan-dialog")
export class DeviceLinksPlanDialog extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;

  @property({ attribute: false }) api!: DeviceLinksApi;

  @property({ attribute: false }) components: ComponentSet | null = null;

  @property({ type: Boolean }) narrow = false;

  @property({ type: Boolean }) open = false;

  /** What this plan is about. Empty means the whole active profile. */
  @property({ attribute: false }) scope: PlanScope | undefined;

  /** The dialog's title, so the caller can say which rule or device this is for. */
  @property({ type: String }) heading = "Plan and apply";

  /**
   * A plan the caller already has, used instead of asking for one.
   *
   * `profiles/activate` answers with the plan activating it opened, so the Profiles view
   * has the plan before this dialog exists. Re-planning would be a second, different plan
   * for the same act, and the token the user confirms should belong to the plan they were
   * shown.
   */
  @property({ attribute: false }) initialPlan: Plan | null = null;

  /**
   * Unmanaged links to open with already ticked.
   *
   * The Devices view's Remove control is what sets this: the user pointed at one entry, so
   * the plan they are shown is the plan for taking that entry off, with the box ticked and
   * visible rather than a removal that happens somewhere they cannot see it. It is still
   * their plan to cancel, and the token still describes exactly this work.
   */
  @property({ attribute: false }) initialRemoveUnmanaged: readonly string[] = [];

  @state() private _plan: Plan | null = null;

  @state() private _phase: Phase = "loading";

  @state() private _error: string | null = null;

  @state() private _stale = false;

  @state() private _removeUnmanaged: string[] = [];

  @state() private _progress: JobProgress | null = null;

  @state() private _finished: JobFinished | null = null;

  @state() private _cancelling = false;

  private _jobId: string | null = null;

  private _subscription: Subscription | null = null;

  static override styles = [
    sharedStyles,
    css`
      .summary {
        margin-bottom: 12px;
      }

      .device {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 12px;
      }

      .device > header {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }

      .device h3 {
        margin: 0;
        overflow-wrap: anywhere;
      }

      .bucket {
        margin-top: 10px;
      }

      .bucket h4 {
        margin: 0 0 4px;
        color: var(--secondary-text-color, #727272);
        text-transform: uppercase;
        font-size: 11px;
        letter-spacing: 0.06em;
      }

      .item {
        padding: 4px 0;
        overflow-wrap: anywhere;
      }

      .reason {
        color: var(--secondary-text-color, #727272);
        margin: 2px 0 0;
      }

      .bar {
        height: 8px;
        border-radius: 4px;
        background: var(--divider-color, rgba(0, 0, 0, 0.12));
        overflow: hidden;
        margin: 12px 0 8px;
      }

      .bar > div {
        height: 100%;
        background: var(--primary-color, #03a9f4);
        transition: width 120ms linear;
      }

      .unmanaged-item {
        display: flex;
        gap: 8px;
        align-items: flex-start;
        padding: 4px 0;
      }

      .unmanaged-item input {
        margin-top: 3px;
        min-height: 0;
      }
    `,
  ];

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    // A job subscription that outlives the dialog fires into a component that is no
    // longer in the document, and a panel is a page somebody leaves open all day.
    this._unsubscribe();
  }

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (!changed.has("open")) {
      return;
    }
    if (this.open) {
      this._start();
    } else {
      this._reset();
    }
  }

  protected override render(): TemplateResult {
    return html`
      <dl-dialog
        .open=${this.open}
        .narrow=${this.narrow}
        .heading=${this.heading}
        .dismissible=${this._phase !== "applying"}
        @dl-dialog-closed=${this._requestClose}
      >
        ${this._renderBody()}
        <div slot="actions">${this._renderActions()}</div>
      </dl-dialog>
    `;
  }

  // ------------------------------------------------------------------------------------
  // The body, one shape per phase.
  // ------------------------------------------------------------------------------------

  private _renderBody(): TemplateResult {
    if (this._error !== null) {
      return html`
        <div class="notice error" role="alert">
          <p>${this._error}</p>
          ${
            this._stale
              ? html`<p class="secondary">
                Nothing was written. Plan again to see what would happen now.
              </p>`
              : nothing
          }
        </div>
      `;
    }
    if (this._phase === "loading") {
      return html`<p class="secondary">Working out what would change.</p>`;
    }
    if (this._phase === "applying") {
      return this._renderProgress();
    }
    if (this._phase === "finished") {
      return this._renderResult();
    }
    return this._renderPlan();
  }

  private _renderPlan(): TemplateResult {
    const plan = this._plan;
    if (plan === null) {
      return html`<p class="secondary">No plan yet.</p>`;
    }
    if (plan.is_empty && plan.counts.unmanaged === 0) {
      return html`
        <p>Nothing to do. Every link this covers is already on the devices.</p>
        ${
          plan.unchanged_count > 0
            ? html`<p class="secondary">
              ${plural(plan.unchanged_count, "link")} checked and left alone.
            </p>`
            : nothing
        }
      `;
    }
    return html`
      ${this._renderSummary(plan)}
      ${plan.devices.map((device) => this._renderDevice(device))}
    `;
  }

  private _renderSummary(plan: Plan): TemplateResult {
    const counts = plan.counts;
    return html`
      <div class="summary">
        <p>
          ${plural(this._changeCount(plan), "change")} on
          ${plural(plan.devices.length, "device")}.
          ${
            plan.unchanged_count > 0
              ? html`<span class="secondary">
                ${plural(plan.unchanged_count, "link")} already correct.
              </span>`
              : nothing
          }
        </p>
        <div class="chips">
          ${this._countChip("Add", counts.add, "ok")}
          ${this._countChip("Remove", counts.remove, "warn")}
          ${this._countChip("Settings", counts.set_param, "info")}
          ${this._countChip("Blocked", counts.blocked, "error")}
          ${this._countChip("Pending", counts.pending, "warn")}
          ${this._countChip("Unmanaged", counts.unmanaged, "muted")}
        </div>
        ${this._renderUnmanagedControls(plan)}
      </div>
    `;
  }

  private _countChip(label: string, count: number, tone: string): TemplateResult | typeof nothing {
    if (count === 0) {
      return nothing;
    }
    return html`<span class="chip ${tone}">${label} ${count}</span>`;
  }

  /**
   * The one control that can tick several boxes at once, and what it will not tick.
   *
   * System links are excluded here as well as by the planner, which never puts one in the
   * unmanaged bucket. Two locks on the same door, because this is the door.
   */
  private _renderUnmanagedControls(plan: Plan): TemplateResult | typeof nothing {
    const selectable = this._selectableUnmanaged(plan);
    if (selectable.length === 0) {
      return nothing;
    }
    const selected = this._removeUnmanaged.length;
    return html`
      <div class="notice">
        <p>
          ${plural(selectable.length, "link")} on these devices belong to no rule. They are
          left alone unless you tick them.
        </p>
        <div class="row">
          <span class="secondary">${selected} selected for removal</span>
          <button
            type="button"
            class="link"
            @click=${() => this._selectAllUnmanaged(selectable)}
            ?disabled=${selected === selectable.length}
          >
            ${selectable.length === 1 ? "Select it" : `Select all ${selectable.length}`}
          </button>
          <button
            type="button"
            class="link"
            @click=${() => this._setRemoveUnmanaged([])}
            ?disabled=${selected === 0}
          >
            Clear
          </button>
        </div>
      </div>
    `;
  }

  private _renderDevice(device: PlanDevice): TemplateResult {
    return html`
      <section class="device">
        <header>
          <h3>${device.name}</h3>
          <span class="chip muted">${backendLabel(device.backend)}</span>
          ${
            device.available
              ? nothing
              : html`<span class="chip warn" title="This device is not answering right now">
                Not answering
              </span>`
          }
        </header>
        ${
          device.available
            ? nothing
            : html`<p class="secondary">
              Device Links cannot read this device right now, so what it holds is what was
              last seen. Anything planned for it may be refused when apply runs.
            </p>`
        }
        ${this._renderBucket("Add", device.add)}
        ${this._renderBucket("Remove", device.remove)}
        ${this._renderBucket("Settings", device.set_param)}
        ${this._renderBucket("Blocked", device.blocked)}
        ${this._renderBucket("Waiting for the device to wake", device.pending)}
        ${this._renderUnmanaged(device.unmanaged)}
      </section>
    `;
  }

  private _renderBucket(title: string, items: PlanItem[]): TemplateResult | typeof nothing {
    if (items.length === 0) {
      return nothing;
    }
    return html`
      <div class="bucket">
        <h4>${title}</h4>
        ${items.map((item) => this._renderItem(item))}
      </div>
    `;
  }

  private _renderItem(item: PlanItem): TemplateResult {
    const reason = item.reason === null ? null : localizeDiagnostic(this.hass, item.reason);
    return html`
      <div class="item">
        <div>${this._describeItem(item)}</div>
        ${reason === null ? nothing : html`<p class="reason">${reason}</p>`}
        ${
          item.op === "pending"
            ? html`<p class="reason">
              Battery devices only accept changes while they are awake. Press a button on
              it, or wait for it to check in.
            </p>`
            : nothing
        }
      </div>
    `;
  }

  private _describeItem(item: PlanItem): string {
    if (item.link !== null) {
      return describeLink(item.link);
    }
    if (item.setting !== null) {
      const setting = item.setting;
      const where = setting.bitmask === null ? "" : ` (bitmask ${setting.bitmask})`;
      return `Set ${setting.capability}, parameter ${setting.parameter}${where}, to ${setting.value}`;
    }
    return "A change this panel has no wording for yet.";
  }

  private _renderUnmanaged(links: UnmanagedLink[]): TemplateResult | typeof nothing {
    if (links.length === 0) {
      return nothing;
    }
    return html`
      <div class="bucket">
        <h4>Not managed by any rule</h4>
        ${links.map((link) => this._renderUnmanagedLink(link))}
      </div>
    `;
  }

  private _renderUnmanagedLink(link: UnmanagedLink): TemplateResult {
    // A system link should never reach this list, because the planner keeps lifelines and
    // coordinator bindings out of it. If one ever does, it is shown and it is not offered
    // a tick box: this is the last place a user could be led into removing one.
    if (link.is_system) {
      return html`
        <div class="unmanaged-item">
          <span class="chip muted">System link</span>
          <span>${describeLink(link)}</span>
        </div>
      `;
    }
    const checked = this._removeUnmanaged.includes(link.fingerprint);
    return html`
      <label class="unmanaged-item">
        <input
          type="checkbox"
          .checked=${checked}
          ?disabled=${this._phase !== "plan"}
          @change=${(event: Event) => this._toggleUnmanaged(link, event)}
        />
        <span>
          Also remove: ${describeLink(link)}
          ${link.ignored ? html`<span class="chip muted">Ignored</span>` : nothing}
        </span>
      </label>
    `;
  }

  private _renderProgress(): TemplateResult {
    const progress = this._progress;
    const total = progress?.total ?? 0;
    const completed = progress?.completed ?? 0;
    const percent = total === 0 ? 0 : Math.round((completed / total) * 100);
    return html`
      <p>Writing to your devices. Leave this open until it finishes.</p>
      <div class="bar"><div style=${`width: ${percent}%`}></div></div>
      <p class="secondary">
        ${total === 0 ? "Starting" : `${completed} of ${total} done`}
        ${
          progress?.devices_in_flight.length
            ? html`<span> &middot; now on ${progress.devices_in_flight.join(", ")}</span>`
            : nothing
        }
      </p>
      ${
        this._cancelling
          ? html`<p class="secondary">
            Stopping. What is already in flight still finishes.
          </p>`
          : nothing
      }
    `;
  }

  private _renderResult(): TemplateResult {
    const job = this._finished;
    if (job === null) {
      return html`<p>The job finished.</p>`;
    }
    const outcomes = Object.entries(job.results) as [LinkOutcome, number][];
    return html`
      <div class="row">
        <span class="chip ${jobStatusTone(job.status)}">${jobStatusLabel(job.status)}</span>
        <span class="secondary">${plural(job.total, "link")} attempted</span>
      </div>
      <div class="chips" style="margin-top: 12px">
        ${outcomes.map(
          ([outcome, count]) =>
            html`<span class="chip ${outcomeTone(outcome)}">
              ${outcomeLabel(outcome)} ${count}
            </span>`,
        )}
      </div>
      ${
        job.status === "completed"
          ? nothing
          : html`<p class="secondary" style="margin-top: 12px">
            Activity has the per-link detail, including what each device said.
          </p>`
      }
    `;
  }

  // ------------------------------------------------------------------------------------
  // The buttons.
  // ------------------------------------------------------------------------------------

  private _renderActions(): TemplateResult {
    if (this._error !== null) {
      return html`
        <button type="button" class="outlined" @click=${this._requestClose}>Close</button>
        <button type="button" class="primary" @click=${this._replan}>Plan again</button>
      `;
    }
    if (this._phase === "applying") {
      return html`
        <button type="button" class="danger" @click=${this._cancel} ?disabled=${this._cancelling}>
          Stop
        </button>
      `;
    }
    if (this._phase === "finished") {
      return html`
        <button type="button" class="outlined" @click=${this._replan}>Plan again</button>
        <button type="button" class="primary" @click=${this._requestClose}>Close</button>
      `;
    }
    const count = this._plan === null ? 0 : this._changeCount(this._plan);
    return html`
      <button type="button" class="outlined" @click=${this._requestClose}>Cancel</button>
      <button
        type="button"
        class="primary"
        ?disabled=${this._phase !== "plan" || count === 0}
        @click=${this._apply}
      >
        ${count === 0 ? "Nothing to apply" : `Apply ${plural(count, "change")}`}
      </button>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Loading, applying, and following the job.
  // ------------------------------------------------------------------------------------

  /** What one press of Apply would actually write. Blocked and pending are neither. */
  private _changeCount(plan: Plan): number {
    return plan.counts.add + plan.counts.remove + plan.counts.set_param;
  }

  private _selectableUnmanaged(plan: Plan): UnmanagedLink[] {
    return plan.devices.flatMap((device) => device.unmanaged.filter((link) => !link.is_system));
  }

  private _selectAllUnmanaged(selectable: UnmanagedLink[]): void {
    this._setRemoveUnmanaged(selectable.map((link) => link.fingerprint));
  }

  private _toggleUnmanaged(link: UnmanagedLink, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    const next = this._removeUnmanaged.filter((fingerprint) => fingerprint !== link.fingerprint);
    if (checked) {
      next.push(link.fingerprint);
    }
    this._setRemoveUnmanaged(next);
  }

  /**
   * Change what would be removed, and get a plan that says so.
   *
   * Re-planning rather than adjusting the list in place, because the plan token is
   * derived from the work: a tick that moved a link into the removals without changing
   * the token would let the user confirm one plan and apply another.
   */
  private _setRemoveUnmanaged(fingerprints: string[]): void {
    this._removeUnmanaged = fingerprints;
    void this._load();
  }

  private _start(): void {
    this._reset();
    this._removeUnmanaged = [...this.initialRemoveUnmanaged];
    if (this.initialPlan !== null) {
      this._plan = this.initialPlan;
      this._phase = "plan";
      return;
    }
    void this._load();
  }

  private _reset(): void {
    this._unsubscribe();
    this._plan = null;
    this._phase = "loading";
    this._error = null;
    this._stale = false;
    this._removeUnmanaged = [];
    this._progress = null;
    this._finished = null;
    this._cancelling = false;
    this._jobId = null;
  }

  private _replan(): void {
    this._error = null;
    this._stale = false;
    this._finished = null;
    this._progress = null;
    this._jobId = null;
    void this._load();
  }

  private async _load(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._phase = "loading";
    this._error = null;
    try {
      this._plan = await this.api.plan(this.scope, this._removeUnmanaged);
      this._phase = "plan";
    } catch (error) {
      this._fail(error);
    }
  }

  private async _apply(): Promise<void> {
    const plan = this._plan;
    if (!this.api || plan === null) {
      return;
    }
    this._phase = "applying";
    this._error = null;
    this._progress = null;
    // Subscribed before the apply is sent, so a job short enough to finish between the
    // two still reports its result here rather than only in the Activity view.
    this._subscribe();
    try {
      const started = await this.api.apply({
        planToken: plan.token,
        ...(this.scope === undefined ? {} : { scope: this.scope }),
        removeUnmanaged: this._removeUnmanaged,
      });
      this._jobId = started.job_id;
      if (started.job_id === null) {
        this._unsubscribe();
        this._phase = "plan";
        void this._load();
      }
    } catch (error) {
      this._unsubscribe();
      this._fail(error);
    }
  }

  private async _cancel(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._cancelling = true;
    try {
      await this.api.cancelJob();
    } catch (error) {
      this._fail(error);
    }
  }

  private _subscribe(): void {
    this._unsubscribe();
    this._subscription = this.api.subscribeJobs(
      (event) => {
        if (event.type === "progress") {
          this._progress = event.job;
          return;
        }
        // A job that is not ours belongs to another surface (a rule switch, a service
        // call). Following it here would replace this dialog's result with somebody
        // else's, so it is ignored until we know which id we are waiting for.
        if (this._jobId !== null && event.job.id !== this._jobId) {
          return;
        }
        this._finished = event.job;
        this._phase = "finished";
        this._progress = null;
        this._unsubscribe();
        this.dispatchEvent(
          new CustomEvent<PlanAppliedDetail>("dl-plan-applied", {
            detail: { job: event.job },
            bubbles: true,
            composed: true,
          }),
        );
      },
      (error) => {
        this._error = describeError(this.hass, error);
      },
    );
  }

  private _unsubscribe(): void {
    this._subscription?.unsubscribe();
    this._subscription = null;
  }

  private _fail(error: unknown): void {
    const api = DeviceLinksApiError.from(error);
    this._error = describeError(this.hass, api);
    // FR-A3 in the one place a user meets it: the plan they were looking at no longer
    // describes what would happen, so nothing was written and the answer is to look again.
    this._stale = api.translationKey === "plan_out_of_date";
    this._phase = "plan";
  }

  private _requestClose(): void {
    if (this._phase === "applying") {
      return;
    }
    this.dispatchEvent(new CustomEvent("dl-plan-closed", { bubbles: true, composed: true }));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dl-plan-dialog": DeviceLinksPlanDialog;
  }
}
