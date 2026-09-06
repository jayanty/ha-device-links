/**
 * Activity: every apply this integration remembers, and what became of each link in it.
 *
 * The list is on the left and one job's detail on the right, or one at a time on a narrow
 * screen. A job that is running now sits above both with its progress, because the
 * question somebody opens this tab with while a job is running is "how far has it got",
 * and the answer should not be behind a click.
 *
 * **The raw reason stays under an expander.** What a backend said when a write failed is
 * the thing that makes a bug report useful, and it is also the thing that reads as a
 * crash when it is the first sentence on the screen. So each row says what happened in
 * the panel's own words, and the backend's text is one disclosure away.
 */

import { html, nothing, type TemplateResult } from "lit";
import { customElement, state } from "lit/decorators.js";

import { DeviceLinksApiError, describeError, type Subscription } from "../api";
import type { PlanFlow } from "../dialogs/plan-dialog";
import "../components/two-pane";

import {
  describeFingerprint,
  formatTime,
  jobStatusLabel,
  jobStatusTone,
  outcomeLabel,
  outcomeTone,
  plural,
  timeAgo,
} from "../format";
import { sharedStyles } from "../styles";
import type { DeviceRow, Job, JobProgress, JobResult, Plan, Snapshot } from "../types";
import { DeviceLinksView } from "./view-base";

@customElement("device-links-activity")
export class DeviceLinksActivity extends DeviceLinksView {
  static override styles = sharedStyles;

  @state() private _jobs: Job[] = [];

  @state() private _running: JobProgress | null = null;

  @state() private _selectedId: string | null = null;

  @state() private _detail: Job | null = null;

  @state() private _devices: DeviceRow[] = [];

  @state() private _loading = true;

  @state() private _error: string | null = null;

  @state() private _cancelling = false;

  @state() private _snapshots: Snapshot[] = [];

  /** The snapshot the rollback dialog is open on, or null when it is closed. */
  @state() private _rollingBack: Snapshot | null = null;

  /**
   * What the last rollback plan said would come straight back, kept for the notice.
   *
   * Held rather than derived, because the dialog asks this view for a plan and then asks
   * it for the notices about that plan, and only the first of those two calls sees the
   * backend's answer. Set on every plan, so a re-plan after ticking an unmanaged link
   * cannot leave the notice describing the plan before it.
   */
  @state() private _returning: string[] = [];

  /** Devices the open snapshot covers that nobody can read, so nothing is planned for them. */
  @state() private _unreadable: string[] = [];

  private _subscription: Subscription | null = null;

  override connectedCallback(): void {
    super.connectedCallback();
    void this._load();
    this._subscribe();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    // Held in a field and ended here: a subscription that outlives its view fires into a
    // component that is no longer in the document.
    this._subscription?.unsubscribe();
    this._subscription = null;
  }

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("selected") && this.selected !== null) {
      this._select(this.selected);
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
        ${this._renderRunning()}
        <dl-two-pane .narrow=${this.narrow} ?show-detail=${this._selectedId !== null}>
          <div slot="list" class="card">${this._renderList()}</div>
          <div slot="detail" class="card">${this._renderDetail()}</div>
        </dl-two-pane>
        ${this._renderSnapshots()}
      </div>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._rollingBack !== null}
        .flow=${this._rollbackFlow()}
        .heading=${"Restore a snapshot"}
        @dl-plan-closed=${this._closeRollback}
        @dl-plan-applied=${this._afterRollback}
      ></dl-plan-dialog>
    `;
  }

  private _renderRunning(): TemplateResult | typeof nothing {
    const running = this._running;
    if (running === null) {
      return nothing;
    }
    return html`
      <div class="card">
        <div class="spread">
          <div class="grow">
            <h3>An apply is running</h3>
            <p class="secondary">
              ${running.completed} of ${running.total} done${
                running.devices_in_flight.length
                  ? `, now on ${running.devices_in_flight.join(", ")}`
                  : ""
              }.
            </p>
          </div>
          <button type="button" class="danger" ?disabled=${this._cancelling} @click=${this._cancel}>
            ${this._cancelling ? "Stopping" : "Stop"}
          </button>
        </div>
      </div>
    `;
  }

  private _renderList(): TemplateResult {
    if (this._loading) {
      return html`<p class="secondary">Loading.</p>`;
    }
    if (this._jobs.length === 0) {
      return html`<p class="empty">Nothing has been applied yet.</p>`;
    }
    return html`
      <h3>${plural(this._jobs.length, "job")}</h3>
      <ul class="list">
        ${this._jobs.map(
          (job) => html`
            <li>
              <button
                type="button"
                class="selectable"
                aria-current=${job.id === this._selectedId ? "true" : "false"}
                @click=${() => this._select(job.id)}
              >
                <span class="row">
                  <span class="chip ${jobStatusTone(job.status)}">${jobStatusLabel(job.status)}</span>
                  <span class="grow truncate">${job.scope}</span>
                </span>
                <span class="secondary">
                  ${formatTime(job.created_at, this.hass?.language)} &middot;
                  ${plural(job.total, "link")}
                </span>
              </button>
            </li>
          `,
        )}
      </ul>
    `;
  }

  private _renderDetail(): TemplateResult {
    const job = this._detail;
    if (job === null) {
      return html`<p class="empty">Choose a job to see what it did.</p>`;
    }
    return html`
      ${
        this.narrow
          ? html`<button type="button" class="link" @click=${this._clear}>Back to the list</button>`
          : nothing
      }
      <div class="row" style="margin: 8px 0">
        <span class="chip ${jobStatusTone(job.status)}">${jobStatusLabel(job.status)}</span>
        <strong class="grow">${job.scope}</strong>
      </div>
      <p class="secondary">
        ${formatTime(job.created_at, this.hass?.language)} (${timeAgo(job.created_at)}) &middot;
        ${plural(job.total, "link")}
      </p>
      <div class="chips" style="margin-bottom: 12px">
        ${[...this._outcomeCounts(job)].map(
          ([outcome, count]) =>
            html`<span class="chip ${outcomeTone(outcome)}">${outcomeLabel(outcome)} ${count}</span>`,
        )}
      </div>
      ${
        job.results.length === 0
          ? html`<p class="secondary">This job touched no links.</p>`
          : html`<ul class="list">${job.results.map((result) => this._renderResult(result))}</ul>`
      }
    `;
  }

  private _renderResult(result: JobResult): TemplateResult {
    return html`
      <li>
        <div class="row">
          <span class="chip ${outcomeTone(result.status)}">${outcomeLabel(result.status)}</span>
          <span class="grow">${describeFingerprint(result.fingerprint, (identity) => this._nameOf(identity))}</span>
        </div>
        <details>
          <summary class="secondary">What the backend reported</summary>
          <p class="mono">${result.reason ?? "Nothing beyond the outcome above."}</p>
          <p class="mono">${result.fingerprint}</p>
        </details>
      </li>
    `;
  }

  /**
   * The safety copies taken before an apply, and the button that puts one back.
   *
   * Restoring one opens the same plan dialog every other write in this panel goes through
   * (Decision D18), on a plan the backend built from the snapshot. Nothing about a
   * rollback skips that: it removes as well as adds, so it is the last place somebody can
   * decide not to.
   */
  private _renderSnapshots(): TemplateResult | typeof nothing {
    if (this._snapshots.length === 0) {
      return nothing;
    }
    return html`
      <div class="card">
        <h3>Snapshots</h3>
        <p class="secondary">
          Taken before an apply, so what a device held can be put back. Restoring one shows
          you the whole plan first, and takes off what has been added since as well as
          putting back what has gone.
        </p>
        <div class="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Taken</th>
                <th>Why</th>
                <th>Devices</th>
                <th>Links</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${this._snapshots.map(
                (snapshot) => html`
                  <tr>
                    <td>${formatTime(snapshot.created_at, this.hass?.language)}</td>
                    <td>${snapshot.reason}</td>
                    <td>${snapshot.devices.length}</td>
                    <td>${snapshot.links}</td>
                    <td>
                      <button
                        type="button"
                        class="outlined"
                        @click=${() => this._openRollback(snapshot)}
                      >
                        Restore
                      </button>
                    </td>
                  </tr>
                `,
              )}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Rolling one back.
  // ------------------------------------------------------------------------------------

  private _openRollback(snapshot: Snapshot): void {
    this._returning = [];
    this._rollingBack = snapshot;
  }

  private _closeRollback(): void {
    this._rollingBack = null;
    this._returning = [];
  }

  private _afterRollback(): void {
    void this._load();
  }

  /**
   * How the plan dialog plans and applies a rollback.
   *
   * The same dialog, the same token rule, the same unmanaged ticks: only the two calls
   * differ, because a rollback is planned from a snapshot rather than from the profile
   * and is applied through its own command. Rebuilt on each render, which is what makes
   * the closure hold the snapshot that is currently open rather than the first one that
   * ever was.
   */
  private _rollbackFlow(): PlanFlow | null {
    const snapshot = this._rollingBack;
    const api = this.api;
    if (snapshot === null || !api) {
      return null;
    }
    return {
      plan: async (removeUnmanaged: readonly string[]): Promise<Plan> => {
        const result = await api.rollbackSnapshot(snapshot.id, { removeUnmanaged });
        this._returning = result.returns_on_next_apply.map((link) => link.rule_name ?? "a rule");
        this._unreadable = result.unreadable_devices;
        return result.plan;
      },
      apply: async (planToken: string, removeUnmanaged: readonly string[]) => {
        const result = await api.rollbackSnapshot(snapshot.id, { planToken, removeUnmanaged });
        // `preview` is what the command answers when no token was sent, and one always is
        // from here, so this is a job outcome like any other apply's. Narrowed rather than
        // cast: an impossible value is mapped onto the harmless one instead of asserted
        // away, so a backend that ever did answer `preview` here reports "nothing to do"
        // rather than putting a status through the dialog that it cannot render.
        const status = result.status === "preview" ? "nothing_to_do" : result.status;
        return { job_id: result.job_id, status };
      },
      notices: () => this._rollbackNotices(),
    };
  }

  /**
   * What a user has to weigh before confirming a rollback, said in the dialog.
   *
   * A rollback puts the devices back and leaves the rules alone, so a link an enabled rule
   * still asks for is removed now and written again the next time that rule is applied.
   * Naming the rules is what makes that actionable: somebody who wants those links gone
   * for good disables the rule first.
   */
  private _rollbackNotices(): string[] {
    const notices: string[] = [];
    const rules = [...new Set(this._returning)].sort();
    if (rules.length > 0) {
      notices.push(
        `Some of these removals belong to rules that are still on: ${rules.join(", ")}. ` +
          "They will be written again the next time those rules are applied, and until " +
          "then those rules read as drifted. Turn a rule off first if you want its links " +
          "gone for good.",
      );
    }
    if (this._unreadable.length > 0) {
      notices.push(
        `${plural(this._unreadable.length, "device")} this snapshot covers cannot be read ` +
          "right now, so nothing is planned for them and whatever they hold stays as it is.",
      );
    }
    return notices;
  }

  private _outcomeCounts(job: Job): Map<JobResult["status"], number> {
    const counts = new Map<JobResult["status"], number>();
    for (const result of job.results) {
      counts.set(result.status, (counts.get(result.status) ?? 0) + 1);
    }
    return counts;
  }

  private _nameOf(identity: string): string {
    return this._devices.find((device) => device.identity === identity)?.name ?? identity;
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
      const [jobs, devices, snapshots] = await Promise.all([
        this.api.listJobs(),
        this.api.listDevices(),
        this.api.listSnapshots(),
      ]);
      this._jobs = jobs.jobs ?? [];
      this._running = jobs.running ?? null;
      this._devices = devices ?? [];
      this._snapshots = snapshots ?? [];
      this._error = null;
      if (this._selectedId === null && !this.narrow) {
        const first = this._jobs[0];
        if (first !== undefined) {
          this._select(first.id);
        }
      }
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._loading = false;
    }
  }

  private _select(id: string): void {
    this._selectedId = id;
    this._detail = this._jobs.find((job) => job.id === id) ?? null;
    if (!this.api) {
      return;
    }
    // The list already carries every field, so this is a refresh rather than a fetch: it
    // costs one command and means a job that finished while the list was on screen shows
    // its final results rather than the ones it had when the list was built.
    void this.api
      .getJob(id)
      .then((job) => {
        if (this._selectedId === id) {
          this._detail = job;
        }
      })
      .catch((error: unknown) => {
        this._error = describeError(this.hass, DeviceLinksApiError.from(error));
      });
  }

  private _clear(): void {
    this._selectedId = null;
    this._detail = null;
  }

  private _subscribe(): void {
    if (!this.api || this._subscription !== null) {
      return;
    }
    this._subscription = this.api.subscribeJobs(
      (event) => {
        if (event.type === "progress") {
          this._running = event.job;
          this._cancelling = false;
          return;
        }
        this._running = null;
        void this._load();
      },
      (error) => {
        this._error = describeError(this.hass, error);
      },
    );
  }

  private async _cancel(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._cancelling = true;
    try {
      await this.api.cancelJob();
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
      this._cancelling = false;
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-activity": DeviceLinksActivity;
  }
}
