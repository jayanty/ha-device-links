/**
 * The comparison dialog: what changes if this becomes that (FR-P4).
 *
 * One dialog for both comparisons, because the question is the same one asked of two
 * different right-hand sides. A profile against another profile is what a user asks before
 * activating one; a profile against a snapshot is what they ask before restoring it. Both
 * are somebody deciding whether to hand over their whole configuration, and both deserve
 * the same answer in the same shape.
 *
 * **Two levels, shown separately and in this order.** The rules first, because that is
 * where a person's own edits live and what they can recognise: a rule added, a rule gone, a
 * rule whose targets moved. Then the links, because that is what will actually be written,
 * and the two are not the same question: a rename changes a rule and writes nothing, and a
 * device swapped underneath an untouched rule writes everything.
 *
 * **It writes nothing and offers no button that does.** A diff is a thing you read before
 * you decide. Applying is the plan dialog's job, on its own token, and putting an Apply
 * here would be a second door into a device write with no plan behind it (Decision D18).
 */

import { css, html, LitElement, nothing, type TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { type DeviceLinksApi, DeviceLinksApiError, describeError } from "../api";
import "../components/dialog";
import { describeLink, plural } from "../format";
import type { HomeAssistant } from "../hass";
import { sharedStyles } from "../styles";
import type { ChangeKind, LinkChange, ProfileDiff, RuleDiffRow } from "../types";

/** Which right-hand side this dialog is comparing against. */
export type DiffAgainst = { profileId: string } | { snapshotId: string };

/** How each kind of change is labelled and toned, in one place for both levels. */
const KINDS: Record<ChangeKind, { label: string; tone: string }> = {
  added: { label: "Added", tone: "ok" },
  removed: { label: "Removed", tone: "warn" },
  changed: { label: "Changed", tone: "info" },
  unchanged: { label: "Unchanged", tone: "muted" },
};

@customElement("dl-diff-dialog")
export class DeviceLinksDiffDialog extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;

  @property({ attribute: false }) api!: DeviceLinksApi;

  @property({ type: Boolean }) narrow = false;

  @property({ type: Boolean }) open = false;

  /** The dialog's title, which is where the two sides are named. */
  @property({ type: String }) heading = "Compare";

  /** The profile on the left. Its rules are the ones the diff is expressed in terms of. */
  @property({ type: String }) profileId = "";

  /** What to compare it with: another profile, or a snapshot. */
  @property({ attribute: false }) against: DiffAgainst | null = null;

  @state() private _diff: ProfileDiff | null = null;

  @state() private _error: string | null = null;

  @state() private _loading = false;

  /** Whether the links that are the same on both sides are on screen. */
  @state() private _showUnchanged = false;

  static override styles = [
    sharedStyles,
    css`
      .rule {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
      }

      .rule header {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .rule h4 {
        margin: 0;
        flex: 1;
        overflow-wrap: anywhere;
      }

      .change {
        padding: 2px 0;
        overflow-wrap: anywhere;
      }
    `,
  ];

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (!changed.has("open")) {
      return;
    }
    if (this.open) {
      void this._load();
    } else {
      this._diff = null;
      this._error = null;
      this._showUnchanged = false;
    }
  }

  protected override render(): TemplateResult {
    return html`
      <dl-dialog
        .open=${this.open}
        .narrow=${this.narrow}
        .heading=${this.heading}
        @dl-dialog-closed=${this._close}
      >
        ${this._renderBody()}
        <div slot="actions">
          <button type="button" class="primary" @click=${this._close}>Close</button>
        </div>
      </dl-dialog>
    `;
  }

  private _renderBody(): TemplateResult {
    if (this._error !== null) {
      return html`<div class="notice error" role="alert">${this._error}</div>`;
    }
    if (this._loading) {
      return html`<p class="secondary">Working out what differs.</p>`;
    }
    const diff = this._diff;
    if (diff === null) {
      return html`<p class="secondary">Nothing compared yet.</p>`;
    }
    if (diff.is_empty) {
      return html`
        <p>These two describe the same thing. Nothing would change.</p>
        ${this._renderScope(diff)}
      `;
    }
    return html`
      ${this._renderSummary(diff)} ${this._renderScope(diff)} ${this._renderRules(diff)}
      ${this._renderLinks(diff)}
    `;
  }

  private _renderSummary(diff: ProfileDiff): TemplateResult {
    const counts = diff.counts;
    return html`
      <div class="chips" style="margin-bottom: 12px">
        ${this._chip("Rules added", counts.rules_added)}
        ${this._chip("Rules removed", counts.rules_removed)}
        ${this._chip("Rules changed", counts.rules_changed)}
        ${this._chip("Links added", counts.links_added)}
        ${this._chip("Links removed", counts.links_removed)}
      </div>
    `;
  }

  private _chip(label: string, count: number | undefined): TemplateResult | typeof nothing {
    if (!count) {
      return nothing;
    }
    return html`<span class="chip info">${label} ${count}</span>`;
  }

  /**
   * What the right-hand side can honestly speak for.
   *
   * A snapshot covers the devices it was taken of and no others, so a comparison against
   * one says nothing about the rest of the house. Leaving that out would let "no changes"
   * read as "nothing would change anywhere", which is a much larger claim.
   */
  private _renderScope(diff: ProfileDiff): TemplateResult | typeof nothing {
    if (diff.devices.length === 0) {
      return nothing;
    }
    return html`
      <p class="secondary">
        This snapshot covers ${plural(diff.devices.length, "device")}, so it is the whole
        of what this comparison can speak for. Nothing here says anything about the rest of
        your network.
      </p>
    `;
  }

  private _renderRules(diff: ProfileDiff): TemplateResult | typeof nothing {
    const rules = diff.rules.filter((rule) => rule.kind !== "unchanged");
    if (rules.length === 0) {
      return nothing;
    }
    return html`
      <h3>Rules</h3>
      ${rules.map((rule) => this._renderRule(rule))}
    `;
  }

  private _renderRule(rule: RuleDiffRow): TemplateResult {
    const kind = KINDS[rule.kind];
    return html`
      <section class="rule">
        <header>
          <h4>${rule.name}</h4>
          <span class="chip ${kind.tone}">${kind.label}</span>
          ${
            rule.writes_nothing_new && rule.kind === "changed"
              ? html`<span class="chip muted" title="Nothing would be written to a device">
                No device change
              </span>`
              : nothing
          }
        </header>
        ${
          rule.fields.length === 0
            ? nothing
            : html`<p class="secondary">Different: ${rule.fields.join(", ")}.</p>`
        }
        ${rule.links_added.map(
          (link) => html`<div class="change">
            <span class="chip ok">Add</span> ${describeLink(link)}
          </div>`,
        )}
        ${rule.links_removed.map(
          (link) => html`<div class="change">
            <span class="chip warn">Remove</span> ${describeLink(link)}
          </div>`,
        )}
        ${
          rule.links_unchanged > 0
            ? html`<p class="secondary">
              ${plural(rule.links_unchanged, "link")} the same on both sides.
            </p>`
            : nothing
        }
      </section>
    `;
  }

  private _renderLinks(diff: ProfileDiff): TemplateResult | typeof nothing {
    const shown = diff.links.filter((change) => this._showUnchanged || change.kind !== "unchanged");
    if (diff.links.length === 0) {
      return nothing;
    }
    const unchanged = diff.links.length - diff.links.filter((c) => c.kind !== "unchanged").length;
    return html`
      <h3 style="margin-top: 12px">Links</h3>
      <p class="secondary">What would actually be written to the devices.</p>
      ${shown.map((change) => this._renderLink(change))}
      ${
        unchanged === 0
          ? nothing
          : html`<button
            type="button"
            class="link"
            @click=${() => {
              this._showUnchanged = !this._showUnchanged;
            }}
          >
            ${
              this._showUnchanged
                ? "Hide the links that are the same"
                : `Show ${plural(unchanged, "link")} that are the same`
            }
          </button>`
      }
    `;
  }

  private _renderLink(change: LinkChange): TemplateResult {
    const kind = KINDS[change.kind];
    return html`
      <div class="change">
        <span class="chip ${kind.tone}">${kind.label}</span> ${describeLink(change.link)}
      </div>
    `;
  }

  private async _load(): Promise<void> {
    const against = this.against;
    if (!this.api || this.profileId === "" || against === null) {
      return;
    }
    this._loading = true;
    this._error = null;
    try {
      this._diff = await this.api.diffProfile(this.profileId, against);
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._loading = false;
    }
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("dl-diff-closed", { bubbles: true, composed: true }));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dl-diff-dialog": DeviceLinksDiffDialog;
  }
}
