/**
 * The device swap wizard: a switch failed, a new one is in the wall, every rule follows it.
 *
 * FR-S2 and open item T59. The backend has had `swap/candidates`, `swap/preview` and
 * `swap/apply` since Phase 2B; this is the screen that makes them reachable by somebody
 * who is not writing a script.
 *
 * Four steps, and the order is the order the decisions actually depend on each other:
 * which device has gone, what replaces it, which control on the replacement takes over from
 * which, and then what all of that costs. The last one is the one this wizard exists for.
 *
 * **The review step is not a summary.** A swap rewrites a user's whole configuration in one
 * move, so every rule is shown before and after, every feature the replacement will not
 * carry is named, and every change the rewrite had to make that nobody asked for (a target
 * merged away, an endpoint moved) is on the screen. When any of that is a loss, the confirm
 * button is behind a tick box: `accept_lossy` exists on the backend precisely so that a
 * lossy swap cannot be silent, and a UI that set it automatically would be defeating the
 * flag rather than using it.
 *
 * **The apply goes through the plan dialog, like every other write.** The wizard hands it a
 * `PlanFlow` whose two calls are `swap/preview` and `swap/apply`, so the token confirmed is
 * the token of the plan on screen and Decision D18 holds here as everywhere else.
 */

import { css, html, LitElement, nothing, type TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { type DeviceLinksApi, DeviceLinksApiError, describeError } from "../api";
import "../components/dialog";
import "./plan-dialog";
import { backendLabel, featureLabel, plural } from "../format";
import type { ComponentSet } from "../ha-components";
import type { HomeAssistant } from "../hass";
import { localizeDiagnostic } from "../messages";
import { sharedStyles } from "../styles";
import type {
  DeviceRow,
  Emitter,
  JobStarted,
  MappingBasis,
  Plan,
  SwapMapping,
  SwapPreview,
  SwapReplacement,
  SwapRewrite,
} from "../types";
import type { PlanFlow } from "./plan-dialog";

/** The steps, in order. Choosing the old device is skipped when the caller named one. */
const STEPS = ["old", "new", "mapping", "review"] as const;

type Step = (typeof STEPS)[number];

const STEP_TITLES: Record<Step, string> = {
  old: "Which device has gone?",
  new: "What has replaced it?",
  mapping: "Which control takes over from which?",
  review: "What this would do",
};

/**
 * How each pre-fill describes itself.
 *
 * The two confident answers are deliberately different sentences. "The ids agree" is a
 * claim about which physical control this is; "this is the only control that fits" is a
 * claim about what happens to work. Presenting them identically would invite somebody to
 * accept the second as casually as the first.
 */
const BASIS_TEXT: Record<MappingBasis, string> = {
  same_emitter_id: "The replacement has a control with the same id, so this is the same button.",
  same_features: "The only control on the replacement that carries everything the rules ask for.",
  chosen: "You chose this one.",
  unmapped: "Nothing on the replacement was an obvious match, so this is yours to pick.",
};

@customElement("dl-swap-wizard")
export class DeviceLinksSwapWizard extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;

  @property({ attribute: false }) api!: DeviceLinksApi;

  @property({ attribute: false }) components: ComponentSet | null = null;

  @property({ type: Boolean }) narrow = false;

  @property({ type: Boolean }) open = false;

  /** Every device the backends can see, loaded once by the view that owns this. */
  @property({ attribute: false }) devices: DeviceRow[] = [];

  /**
   * The device to swap away from, when the caller already knows.
   *
   * The Devices tab's Replace control sets this, because the user is standing on that
   * device's page. Opened from the toolbar it is null, and the first step asks.
   */
  @property({ attribute: false }) oldIdentity: string | null = null;

  @state() private _step: Step = "old";

  @state() private _replacements: SwapReplacement[] = [];

  @state() private _old: string | null = null;

  @state() private _new: DeviceRow | null = null;

  @state() private _newEmitters: Emitter[] = [];

  @state() private _mapping: Record<string, string> = {};

  @state() private _preview: SwapPreview | null = null;

  @state() private _accepted = false;

  @state() private _busy = false;

  @state() private _error: string | null = null;

  @state() private _planOpen = false;

  @state() private _search = "";

  static override styles = [
    sharedStyles,
    css`
      .picker {
        max-height: 320px;
        overflow-y: auto;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 4px;
      }

      .rewrite {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
      }

      .rewrite h4 {
        margin: 0 0 4px;
        overflow-wrap: anywhere;
      }

      .mapping {
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
      }
    `,
  ];

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("open") && this.open) {
      this._begin();
    }
  }

  protected override render(): TemplateResult {
    return html`
      <dl-dialog
        .open=${this.open && !this._planOpen}
        .narrow=${this.narrow}
        heading="Replace a device"
        @dl-dialog-closed=${this._close}
      >
        ${this._renderStep()}
        <div slot="actions">${this._renderActions()}</div>
      </dl-dialog>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .heading=${"Replace a device"}
        .flow=${this._flow()}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
  }

  private _renderStep(): TemplateResult {
    return html`
      <p class="secondary">
        Step ${STEPS.indexOf(this._step) + 1} of ${STEPS.length}: ${STEP_TITLES[this._step]}
      </p>
      ${
        this._error === null
          ? nothing
          : html`<div class="notice error" role="alert">${this._error}</div>`
      }
      ${
        this._step === "old"
          ? this._renderOldStep()
          : this._step === "new"
            ? this._renderNewStep()
            : this._step === "mapping"
              ? this._renderMappingStep()
              : this._renderReviewStep()
      }
    `;
  }

  // ------------------------------------------------------------------------------------
  // Step 1: which device has gone.
  // ------------------------------------------------------------------------------------

  private _renderOldStep(): TemplateResult {
    if (this._busy) {
      return html`<p class="secondary">Looking for devices your rules name that are not there.</p>`;
    }
    if (this._replacements.length === 0) {
      return html`
        <p class="empty">
          Every device your rules name is on the network. Nothing needs replacing.
        </p>
      `;
    }
    return html`
      <p class="secondary">
        These are devices the active profile's rules name that are not on the network, or
        that have come back answering as a different model.
      </p>
      <ul class="list">
        ${this._replacements.map(
          (replacement) => html`
            <li>
              <button
                type="button"
                class="selectable"
                aria-current=${replacement.old.identity === this._old ? "true" : "false"}
                @click=${() => this._chooseOld(replacement)}
              >
                <span class="row">
                  <span class="grow">${replacement.old.name}</span>
                  <span class="chip muted">${backendLabel(replacement.old.backend)}</span>
                </span>
                <span class="chips" style="margin-top: 4px">
                  <span class="chip warn">
                    ${
                      replacement.changed_in_place
                        ? "Answering as a different model"
                        : "Not on the network"
                    }
                  </span>
                  <span class="chip muted">
                    ${plural(replacement.rule_ids.length, "rule")} name it
                  </span>
                </span>
              </button>
            </li>
          `,
        )}
      </ul>
    `;
  }

  private _chooseOld(replacement: SwapReplacement): void {
    this._old = replacement.old.identity;
    this._forget();
    this._step = "new";
  }

  /**
   * Drop everything that was about the previous pair.
   *
   * A preview, a mapping and an acknowledged loss all belong to one old device and one
   * replacement. Carrying any of them into a different pair would put the wrong rewrites
   * on the review step and, worse, would carry a tick about losses the user has not seen.
   */
  private _forget(): void {
    this._new = null;
    this._newEmitters = [];
    this._mapping = {};
    this._preview = null;
    this._accepted = false;
  }

  // ------------------------------------------------------------------------------------
  // Step 2: what replaces it.
  // ------------------------------------------------------------------------------------

  private _renderNewStep(): TemplateResult {
    const suggested = this._replacements.find(
      (replacement) => replacement.old.identity === this._old,
    );
    const candidates = suggested?.candidates ?? [];
    const others = this._filtered(
      this.devices.filter(
        (device) =>
          device.identity !== this._old &&
          device.device_id !== null &&
          !candidates.some((candidate) => candidate.identity === device.identity),
      ),
    );
    return html`
      ${
        candidates.length === 0
          ? html`<p class="secondary">
            Nothing on the network looks like the device that has gone, so pick the
            replacement yourself. A different model is fine: the next step asks which of
            its controls takes over from which.
          </p>`
          : html`<p class="secondary">
            Same model as the device that has gone, and not named by any rule.
          </p>`
      }
      ${
        candidates.length === 0
          ? nothing
          : html`<ul class="list">
            ${candidates.map((device) => this._renderCandidate(device))}
          </ul>`
      }
      <label class="field" style="margin: 8px 0">
        <span>Any other device</span>
        <input
          type="search"
          .value=${this._search}
          placeholder="Name or address"
          @input=${(event: Event) => {
            this._search = (event.target as HTMLInputElement).value;
          }}
        />
      </label>
      <div class="picker">
        <ul class="list">${others.map((device) => this._renderCandidate(device))}</ul>
        ${others.length === 0 ? html`<p class="empty">No device matches that search.</p>` : nothing}
      </div>
    `;
  }

  private _renderCandidate(device: DeviceRow): TemplateResult {
    return html`
      <li>
        <button
          type="button"
          class="selectable"
          aria-current=${device.identity === this._new?.identity ? "true" : "false"}
          @click=${() => this._chooseNew(device)}
        >
          <span class="row">
            <span class="grow">${device.name}</span>
            <span class="chip muted">${backendLabel(device.backend)}</span>
            ${device.available ? nothing : html`<span class="chip warn">Not answering</span>`}
          </span>
        </button>
      </li>
    `;
  }

  private _chooseNew(device: DeviceRow): void {
    this._new = device;
    this._mapping = {};
    this._accepted = false;
    void this._loadReplacement(device);
  }

  // ------------------------------------------------------------------------------------
  // Step 3: which control takes over from which.
  // ------------------------------------------------------------------------------------

  private _renderMappingStep(): TemplateResult {
    const proposal = this._preview?.proposal;
    if (this._busy || proposal === undefined) {
      return html`<p class="secondary">Working out what would take over from what.</p>`;
    }
    if (proposal.errors.length > 0) {
      return html`
        ${proposal.errors.map(
          (error) => html`<div class="notice error" role="alert">
            ${localizeDiagnostic(this.hass, error)}
          </div>`,
        )}
      `;
    }
    if (proposal.mappings.length === 0) {
      return html`
        <p>
          No rule drives anything <em>from</em> ${proposal.old.name}, so there are no
          controls to map. The swap only has to re-point the rules that target it.
        </p>
      `;
    }
    return html`
      ${
        proposal.same_model
          ? html`<p class="secondary">
            The replacement is the same model, so every control maps across on its own.
            Change any of them if this device is wired differently.
          </p>`
          : html`<p class="secondary">
            The replacement is a different model, so each control the rules use has to be
            matched to one on the new device.
          </p>`
      }
      ${proposal.mappings.map((mapping) => this._renderMapping(mapping))}
    `;
  }

  private _renderMapping(mapping: SwapMapping): TemplateResult {
    const lost = mapping.features_needed.filter(
      (feature) => !mapping.features_carried.includes(feature),
    );
    return html`
      <div class="mapping">
        <div class="row">
          <strong class="grow">${mapping.old_emitter_id}</strong>
          <span class="chip muted">
            ${mapping.features_needed.map((feature) => featureLabel(feature)).join(", ")}
          </span>
        </div>
        <label class="field" style="margin-top: 6px">
          <span>Takes over from it</span>
          <select
            @change=${(event: Event) =>
              this._chooseMapping(mapping, (event.target as HTMLSelectElement).value)}
          >
            <option value="" ?selected=${mapping.new_emitter_id === null}>
              Choose a control
            </option>
            ${this._newEmitters
              .filter((emitter) => !emitter.is_lifeline)
              .map(
                (emitter) => html`
                  <option
                    value=${emitter.emitter_id}
                    ?selected=${emitter.emitter_id === mapping.new_emitter_id}
                  >
                    ${emitter.label}
                  </option>
                `,
              )}
          </select>
        </label>
        <p class="secondary" style="margin: 6px 0 0">${BASIS_TEXT[mapping.basis]}</p>
        ${
          lost.length === 0
            ? nothing
            : html`<p class="secondary">
              This control does not carry
              ${lost.map((feature) => featureLabel(feature)).join(", ")}, so those parts of
              the rules using it stop working.
            </p>`
        }
      </div>
    `;
  }

  private _chooseMapping(mapping: SwapMapping, emitterId: string): void {
    const next = { ...this._mapping };
    if (emitterId === "") {
      delete next[mapping.old_emitter_id];
    } else {
      next[mapping.old_emitter_id] = emitterId;
    }
    this._mapping = next;
    this._accepted = false;
    void this._loadPreview();
  }

  // ------------------------------------------------------------------------------------
  // Step 4: what it costs.
  // ------------------------------------------------------------------------------------

  private _renderReviewStep(): TemplateResult {
    const preview = this._preview;
    if (this._busy || preview === null) {
      return html`<p class="secondary">Working out what this would do.</p>`;
    }
    const proposal = preview.proposal;
    return html`
      <p>
        <strong>${proposal.old.name}</strong> becomes
        <strong>${proposal.new.name}</strong> in
        ${plural(proposal.rewrites.length, "rule")}.
      </p>
      ${this._renderReachability(preview)}
      ${
        // A swap the backend has refused outright: a device on another protocol, a
        // replacement nothing can read, a device no rule names. The button is disabled
        // either way, and a disabled button with no reason beside it is a dead end.
        proposal.errors.map(
          (error) => html`<div class="notice error" role="alert">
            <p>${localizeDiagnostic(this.hass, error)}</p>
          </div>`,
        )
      }
      ${
        proposal.unmapped.length === 0
          ? nothing
          : html`<div class="notice error" role="alert">
            <p>
              ${proposal.unmapped.join(", ")} still has nothing chosen to take over from it,
              so this swap cannot be applied. Go back and pick a control.
            </p>
          </div>`
      }
      ${proposal.rewrites.map((rewrite) => this._renderRewrite(rewrite))}
      ${this._renderLossGate(preview)}
    `;
  }

  /**
   * The two questions the plan cannot answer, said before anybody presses anything.
   *
   * A device that is gone has no work in the plan, which reads as a swap with nothing to
   * clean up; a device that cannot be read has nothing planned for it either, which would
   * strip the old switch and write nothing to the new. Both are silences that look like
   * good news.
   */
  private _renderReachability(preview: SwapPreview): TemplateResult | typeof nothing {
    const notices: string[] = [];
    if (!preview.new_reachable) {
      notices.push(
        `${preview.proposal.new.name} is not answering. Nothing can be written to it, so this swap would take the links off the old device and put none on the new one. It is refused until the replacement answers.`,
      );
    }
    if (!preview.old_reachable) {
      notices.push(
        preview.old_listed
          ? `${preview.proposal.old.name} is not answering, so the entries it still holds cannot be taken off. They stay on it until it comes back or is excluded from the network.`
          : `${preview.proposal.old.name} has left the network, so nothing can be removed from it. Whatever it still holds stays there.`,
      );
    }
    if (notices.length === 0) {
      return nothing;
    }
    return html`
      <div class="notice warn" role="status">${notices.map((notice) => html`<p>${notice}</p>`)}</div>
    `;
  }

  private _renderRewrite(rewrite: SwapRewrite): TemplateResult {
    return html`
      <section class="rewrite">
        <h4>${rewrite.name}</h4>
        ${
          rewrite.is_lossy
            ? html`<span class="chip warn">Does less than it did</span>`
            : html`<span class="chip ok">Carried across whole</span>`
        }
        ${rewrite.losses.map(
          (loss) => html`<p class="secondary">${localizeDiagnostic(this.hass, loss)}</p>`,
        )}
        ${rewrite.notes.map(
          (note) => html`<p class="secondary">${localizeDiagnostic(this.hass, note)}</p>`,
        )}
        ${rewrite.errors.map(
          (error) => html`<p class="secondary">${localizeDiagnostic(this.hass, error)}</p>`,
        )}
      </section>
    `;
  }

  /**
   * The tick box a lossy swap cannot be applied without.
   *
   * `accept_lossy` exists on the backend so a swap that leaves rules doing less than they
   * were asked to cannot happen quietly. Setting it from here without a person having
   * ticked something would use the flag to defeat itself, so this is the only thing that
   * sets it, and it sits directly under the list of what is lost.
   */
  private _renderLossGate(preview: SwapPreview): TemplateResult | typeof nothing {
    if (!preview.proposal.is_lossy) {
      return nothing;
    }
    return html`
      <label class="choice">
        <input
          type="checkbox"
          .checked=${this._accepted}
          @change=${(event: Event) => {
            this._accepted = (event.target as HTMLInputElement).checked;
          }}
        />
        <span>
          I have read what these rules will no longer do, and I want to swap anyway.
        </span>
      </label>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Moving between steps.
  // ------------------------------------------------------------------------------------

  private _renderActions(): TemplateResult {
    const index = STEPS.indexOf(this._step);
    const back =
      index === 0 || (index === 1 && this.oldIdentity !== null)
        ? nothing
        : html`<button type="button" class="outlined" @click=${() => this._goTo(index - 1)}>
          Back
        </button>`;
    if (this._step === "review") {
      return html`
        <button type="button" class="outlined" @click=${this._close}>Cancel</button>
        ${back}
        <button
          type="button"
          class="primary"
          ?disabled=${!this._canApply()}
          @click=${() => {
            this._planOpen = true;
          }}
        >
          Show the plan
        </button>
      `;
    }
    return html`
      <button type="button" class="outlined" @click=${this._close}>Cancel</button>
      ${back}
      <button
        type="button"
        class="primary"
        ?disabled=${!this._canLeave()}
        @click=${() => this._goTo(index + 1)}
      >
        Next
      </button>
    `;
  }

  private _canLeave(): boolean {
    if (this._step === "old") {
      return this._old !== null;
    }
    if (this._step === "new") {
      return this._new !== null;
    }
    return this._preview !== null && this._preview.proposal.unmapped.length === 0;
  }

  /** Everything the backend will check, checked here so the button is honest. */
  private _canApply(): boolean {
    const preview = this._preview;
    if (preview === null || !preview.proposal.is_applicable || !preview.new_reachable) {
      return false;
    }
    return !preview.proposal.is_lossy || this._accepted;
  }

  private _goTo(index: number): void {
    const step = STEPS[Math.min(Math.max(index, 0), STEPS.length - 1)];
    if (step === undefined) {
      return;
    }
    this._step = step;
    if (step === "mapping" || step === "review") {
      void this._loadPreview();
    }
  }

  private _begin(): void {
    this._error = null;
    this._preview = null;
    this._new = null;
    this._newEmitters = [];
    this._mapping = {};
    this._accepted = false;
    this._search = "";
    this._old = this.oldIdentity;
    this._step = this.oldIdentity === null ? "old" : "new";
    void this._loadCandidates();
  }

  // ------------------------------------------------------------------------------------
  // Data.
  // ------------------------------------------------------------------------------------

  private async _loadCandidates(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._busy = true;
    try {
      this._replacements = await this.api.swapCandidates();
      this._error = null;
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._busy = false;
    }
  }

  /** Read the replacement's controls, which the mapping step's pickers are built from. */
  private async _loadReplacement(device: DeviceRow): Promise<void> {
    if (!this.api || device.device_id === null) {
      return;
    }
    this._busy = true;
    try {
      this._newEmitters = (await this.api.getDevice(device.device_id)).emitters;
      this._error = null;
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._busy = false;
    }
  }

  private async _loadPreview(): Promise<void> {
    const oldIdentity = this._old;
    const replacement = this._new;
    if (!this.api || oldIdentity === null || replacement?.device_id == null) {
      return;
    }
    this._busy = true;
    try {
      this._preview = await this.api.swapPreview({
        oldIdentity,
        newDeviceId: replacement.device_id,
        mapping: this._mapping,
      });
      this._error = null;
    } catch (error) {
      // Dropped rather than kept: a preview that failed is not a preview of anything, and
      // leaving the previous one would let Next stay enabled and the review step render
      // the wrong device's rewrites, the wrong reachability and the wrong loss gate.
      this._preview = null;
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._busy = false;
    }
  }

  /**
   * How the plan dialog plans and applies a swap.
   *
   * `removeUnmanaged` is deliberately ignored, and the dialog is told so rather than left
   * to render tick boxes that do nothing: a swap already carries the exact links it would
   * take off the old device, computed from the rules it is rewriting, and letting the ticks
   * add to that list would let a swap remove associations nobody connected it to. The token
   * rule is unchanged, which is the part that matters.
   */
  private _flow(): PlanFlow | null {
    const api = this.api;
    const oldIdentity = this._old;
    const replacement = this._new;
    if (!api || oldIdentity === null || replacement?.device_id == null) {
      return null;
    }
    const newDeviceId = replacement.device_id;
    const mapping = this._mapping;
    return {
      plan: async (): Promise<Plan> => {
        const preview = await api.swapPreview({ oldIdentity, newDeviceId, mapping });
        // Re-planning can find losses that were not there when the box was ticked: a
        // target that has since gone unreadable makes a rule lose what it used to carry.
        // The tick is about a list the user read, so a longer list needs a new tick.
        if (this._losses(preview) !== this._losses(this._preview)) {
          this._accepted = false;
        }
        this._preview = preview;
        return preview.plan;
      },
      apply: async (planToken: string): Promise<JobStarted> => {
        const applied = await api.swapApply({
          oldIdentity,
          newDeviceId,
          planToken,
          mapping,
          // Read now rather than captured when this flow was built, so a tick that was
          // withdrawn between the plan and the press is a tick that was withdrawn.
          acceptLossy: this._accepted,
        });
        return { job_id: applied.job_id, status: applied.status };
      },
      notices: () => this._planNotices(),
      // See `PlanFlow.acceptsUnmanaged`. A swap removes exactly the links its own rewrite
      // orphans, so the dialog reports the rest and offers no tick box for them.
      acceptsUnmanaged: false,
    };
  }

  /** Return what a preview says would be lost, as one comparable string. */
  private _losses(preview: SwapPreview | null): string {
    return (preview?.proposal.rewrites ?? [])
      .flatMap((rewrite) => rewrite.losses.map((loss) => loss.translation_key))
      .sort()
      .join("|");
  }

  /** What a user has to weigh alongside the plan, in the plan rather than behind it. */
  private _planNotices(): string[] {
    const preview = this._preview;
    if (preview === null) {
      return [];
    }
    const notices: string[] = [];
    if (preview.removes.length > 0 && !preview.old_reachable) {
      notices.push(
        `${plural(preview.removes.length, "link")} on ${preview.proposal.old.name} cannot be removed, because it is not answering. The rules are re-pointed either way.`,
      );
    }
    if (preview.proposal.is_lossy) {
      notices.push(
        "Some of these rules will do less than they did. You confirmed that on the previous screen.",
      );
    }
    return notices;
  }

  private _filtered(devices: DeviceRow[]): DeviceRow[] {
    const needle = this._search.trim().toLowerCase();
    if (!needle) {
      return devices;
    }
    return devices.filter((device) =>
      `${device.name} ${device.protocol_id}`.toLowerCase().includes(needle),
    );
  }

  private _closePlan(): void {
    this._planOpen = false;
  }

  private _afterApply(): void {
    this._planOpen = false;
    this.dispatchEvent(new CustomEvent("dl-swap-applied", { bubbles: true, composed: true }));
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("dl-swap-closed", { bubbles: true, composed: true }));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dl-swap-wizard": DeviceLinksSwapWizard;
  }
}
