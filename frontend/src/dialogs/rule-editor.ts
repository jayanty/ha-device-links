/**
 * The rule editor: a stepper from an intent to a rule somebody can save.
 *
 * Five steps, in the order the decisions actually depend on each other: what kind of
 * thing this is, which control drives it, what it drives, how it behaves, and then what
 * that compiles to. The last step is the one that matters most, because it is where the
 * compiler gets to answer before anything is stored.
 *
 * **Capacity is shown while choosing, not after applying.** A Z-Wave association group
 * holds a fixed number of entries, and the planner refuses an add that would not fit with
 * a `group_full` diagnostic. Learning that from an apply is learning it too late, so the
 * emitter picker shows "2 of 5 used in group 7" from the device's own capabilities and
 * its observed links, and the targets step says plainly when the chosen targets will not
 * all fit.
 *
 * **The Z7 warning reaches the user before they save.** An Off-all rule on a Zooz scene
 * button compiles with `button_semantics_unknown`: nobody has observed whether those
 * buttons send a fixed OFF or toggle, and if they toggle the button turns the lights back
 * on every second press. `rules/validate` returns it as a warning and the review step
 * shows every warning as a sentence, above the save buttons, where it is read rather than
 * logged. Open item J3 and issue #7 track closing it for real.
 *
 * **An error does not trap the work.** A rule the compiler refuses produces no link at
 * all, so applying it is meaningless and "Save and apply" is not offered. Saving is,
 * because the alternative is a dialog that will not let go of a rule the user cannot
 * finish yet: a target that is asleep, a device that is not answering, an emitter that
 * turned out to be wrong. A saved rule with a visible problem shows as `blocked` in the
 * rules table and in Needs attention, which is a place it can be found and fixed. A rule
 * that could not be saved is only lost.
 */

import { css, html, LitElement, nothing, type TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";

import { type DeviceLinksApi, DeviceLinksApiError, describeError } from "../api";
import "../components/dialog";
import { renderIcon } from "../components/icon";
import {
  backendLabel,
  describeHybridLeg,
  describeLink,
  emitterUsage,
  featureIcon,
  featureLabel,
  plural,
  templateLabel,
  templateSummary,
  type Usage,
} from "../format";
import type { ComponentSet } from "../ha-components";
import type { HomeAssistant } from "../hass";
import { localizeDiagnostic } from "../messages";
import { sharedStyles } from "../styles";
import type {
  CompiledRule,
  DeviceDetail,
  DeviceRow,
  Emitter,
  Feature,
  HybridKind,
  MirrorChoice,
  RuleData,
  TemplateId,
} from "../types";

/** The steps, in order. The stepper never skips one, so the order is the whole router. */
const STEPS = ["template", "source", "targets", "behaviour", "review"] as const;

type Step = (typeof STEPS)[number];

const STEP_TITLES: Record<Step, string> = {
  template: "What should this do?",
  source: "Which control drives it?",
  targets: "What should it control?",
  behaviour: "How should it behave?",
  review: "What this will do",
};

/** Every feature, in the order the behaviour step lists them. */
const ALL_FEATURES: readonly Feature[] = [
  "on_off",
  "level_set",
  "level_hold",
  "scene",
  "color",
  "status_report",
];

/**
 * What choosing a template pre-fills.
 *
 * The compiler branches on the template in exactly one place (the Off-all semantics
 * warning), so a template is mostly an intent that picks sensible defaults here. They are
 * defaults rather than constraints: every one of them is editable in the behaviour step,
 * because a template that silently forced a choice would be a rule the user did not write.
 */
const TEMPLATE_DEFAULTS: Record<
  TemplateId,
  { features: Feature[]; direction: "one_way" | "two_way"; mirror: MirrorChoice }
> = {
  remote: {
    features: ["on_off", "level_set", "level_hold"],
    direction: "one_way",
    mirror: "leave",
  },
  virtual_3way: {
    features: ["on_off", "level_set", "level_hold"],
    direction: "two_way",
    mirror: "leave",
  },
  scene_button: { features: ["on_off"], direction: "one_way", mirror: "leave" },
  off_all: { features: ["on_off"], direction: "one_way", mirror: "off" },
  status_feedback: { features: ["status_report"], direction: "one_way", mirror: "leave" },
  custom: { features: ["on_off"], direction: "one_way", mirror: "leave" },
};

/**
 * The three HA-executed opt-ins, in the words the user meets them in (PRD Section 6.7).
 *
 * `needs` is what the chosen control must report before an opt-in can be offered at all: a
 * scene number for the two that react to a press, an indicator id for the one that lights a
 * button. Offering a tick box the compiler would refuse is worse than offering none, so a
 * control that cannot carry a leg does not get the choice.
 *
 * Every label says what it does and every help line says the cost, in the same sentence,
 * because the cost is the whole point of Decision D3: this part runs in Home Assistant, and
 * it stops when Home Assistant stops.
 */
const HYBRID_CHOICES: {
  value: HybridKind;
  needs: "scene_id" | "indicator_id";
  label: string;
  help: string;
}[] = [
  {
    value: "on_only",
    needs: "scene_id",
    label: "Only pass on, never off",
    help: "An association carries on and off together, so Home Assistant does this part: it hears the button press and turns the targets on.",
  },
  {
    value: "off_only",
    needs: "scene_id",
    label: "Only pass off, never on",
    help: "The same the other way round. Home Assistant hears the press and turns the targets off.",
  },
  {
    value: "self_load",
    needs: "scene_id",
    label: "Also turn off this device's own load",
    help: "A device cannot be in its own association group, so Home Assistant turns this device's own load off when the button is pressed. Add the device to the targets as well.",
  },
  {
    value: "button_led",
    needs: "indicator_id",
    label: "Keep this button's LED in sync with the target",
    help: "Nothing on the radio can address one button's LED, so Home Assistant watches the target and lights the button to match.",
  },
];

const MIRROR_CHOICES: { value: MirrorChoice; label: string; help: string }[] = [
  {
    value: "leave",
    label: "Leave the device's own setting alone",
    help: "Device Links writes no parameter. Choose this unless you know you want the other two.",
  },
  {
    value: "on",
    label: "Make the control's own load follow the press",
    help: "Writes the device's mirror setting so its own load responds as well as the targets.",
  },
  {
    value: "off",
    label: "Leave the control's own load out of it",
    help: "Writes the device's mirror setting so only the targets respond.",
  },
];

/**
 * A rule while it is being written, which is not yet a rule that could be saved.
 *
 * The one difference from `RuleData` is the source endpoint, which is null until a control
 * is chosen and is that control's own `endpoint` afterwards. A draft is what the steps
 * edit; `payloadOf` is the only way one becomes something the backend is sent, and it
 * answers null while the draft is still missing a piece, so the difference cannot be
 * forgotten at the one call site that matters (open item T50).
 */
export interface RuleDraft extends Omit<RuleData, "source"> {
  source: { device: string; endpoint: number | null; emitter_id: string };
}

/**
 * Return the rule this draft describes, or null while it does not describe one yet.
 *
 * Both the compile-as-you-type call and the save go through here, so what the user was
 * shown in the review step is exactly what is stored: two paths building the payload
 * separately is how a rule gets validated in one shape and saved in another.
 */
export function payloadOf(draft: RuleDraft): RuleData | null {
  const { device, endpoint, emitter_id } = draft.source;
  if (device === "" || emitter_id === "" || endpoint === null || draft.targets.length === 0) {
    return null;
  }
  return { ...draft, source: { device, endpoint, emitter_id } };
}

/** What the owner is told when a rule was stored. */
export interface RuleSavedDetail {
  rule: RuleData;
  /** True when the user asked to apply it, which opens the plan dialog. */
  apply: boolean;
}

@customElement("dl-rule-editor")
export class DeviceLinksRuleEditor extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;

  @property({ attribute: false }) api!: DeviceLinksApi;

  @property({ attribute: false }) components: ComponentSet | null = null;

  @property({ type: Boolean }) narrow = false;

  @property({ type: Boolean }) open = false;

  /** Every device the backends can see, loaded once by the view that owns this. */
  @property({ attribute: false }) devices: DeviceRow[] = [];

  /** The rule being edited, or null to start a new one. */
  @property({ attribute: false }) rule: RuleData | null = null;

  /** Which profile to save into. Undefined means the active one. */
  @property({ type: String }) profileId: string | undefined;

  /**
   * The template a new rule starts on, when the user came in through a template card.
   *
   * The first step is still shown rather than skipped: the card said what they wanted and
   * the step says what that means, and one of the six is now chosen for them.
   */
  @property({ attribute: false }) initialTemplate: TemplateId | null = null;

  /**
   * Whether this Home Assistant allows HA-executed legs at all (FR-H1).
   *
   * The global half of Decision D3's two gates, from the panel config. False hides the
   * whole section rather than greying it: an opt-in nothing would ever register is not a
   * choice, it is a promise the product does not keep.
   */
  @property({ type: Boolean }) hybridAllowed = false;

  @state() private _draft: RuleDraft | null = null;

  @state() private _step: Step = "template";

  @state() private _sourceDetail: DeviceDetail | null = null;

  @state() private _loadingSource = false;

  @state() private _compiled: CompiledRule | null = null;

  @state() private _validating = false;

  @state() private _saving = false;

  @state() private _error: string | null = null;

  @state() private _search = "";

  private _validateTimer: ReturnType<typeof setTimeout> | undefined;

  static override styles = [
    sharedStyles,
    css`
      .steps {
        display: flex;
        gap: 4px;
        flex-wrap: wrap;
        margin-bottom: 12px;
      }

      .steps > li {
        list-style: none;
        font-size: 12px;
        color: var(--secondary-text-color, #727272);
        padding: 2px 8px;
        border-radius: 12px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      }

      .steps > li[aria-current="step"] {
        color: var(--primary-color, #03a9f4);
        border-color: var(--primary-color, #03a9f4);
      }

      .template-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 8px;
      }

      .template-card {
        text-align: left;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 12px;
        color: inherit;
        min-height: 0;
      }

      .template-card[aria-pressed="true"] {
        border-color: var(--primary-color, #03a9f4);
        background: var(--secondary-background-color, #f5f5f5);
      }

      .template-card strong {
        display: block;
        margin-bottom: 4px;
      }

      .picker {
        max-height: 320px;
        overflow-y: auto;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 4px;
      }

      .emitter {
        color: var(--primary-text-color, #212121);
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 8px;
        padding: 8px 10px;
        margin-bottom: 6px;
      }

      .emitter[aria-pressed="true"] {
        border-color: var(--primary-color, #03a9f4);
        background: var(--secondary-background-color, #f5f5f5);
      }

      ha-icon {
        --mdc-icon-size: 16px;
      }
    `,
  ];

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("open") && this.open) {
      this._begin();
    }
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    clearTimeout(this._validateTimer);
  }

  protected override render(): TemplateResult {
    return html`
      <dl-dialog
        .open=${this.open}
        .narrow=${this.narrow}
        .heading=${this.rule === null ? "New rule" : `Edit ${this.rule.name}`}
        @dl-dialog-closed=${this._close}
      >
        ${this._renderStepper()}
        <div slot="actions">${this._renderActions()}</div>
      </dl-dialog>
    `;
  }

  private _renderStepper(): TemplateResult {
    const draft = this._draft;
    if (draft === null) {
      return html`<p class="secondary">Loading.</p>`;
    }
    const current = STEPS.indexOf(this._step);
    return html`
      ${
        // Five step chips take three lines on a phone, which is a third of the screen
        // spent on where you are rather than on what you are doing.
        this.narrow
          ? html`<p class="secondary">
            Step ${current + 1} of ${STEPS.length}: ${STEP_TITLES[this._step]}
          </p>`
          : html`<ol class="steps">
            ${STEPS.map(
              (step, index) => html`
                <li aria-current=${step === this._step ? "step" : "false"}>
                  ${index + 1}. ${STEP_TITLES[step]}
                </li>
              `,
            )}
          </ol>`
      }
      ${
        this._error === null
          ? nothing
          : html`<div class="notice error" role="alert">${this._error}</div>`
      }
      ${this._renderStep(draft)}
    `;
  }

  private _renderStep(draft: RuleDraft): TemplateResult {
    switch (this._step) {
      case "template":
        return this._renderTemplateStep(draft);
      case "source":
        return this._renderSourceStep(draft);
      case "targets":
        return this._renderTargetsStep(draft);
      case "behaviour":
        return this._renderBehaviourStep(draft);
      default:
        return this._renderReviewStep(draft);
    }
  }

  // ------------------------------------------------------------------------------------
  // Step 1: the intent.
  // ------------------------------------------------------------------------------------

  private _renderTemplateStep(draft: RuleDraft): TemplateResult {
    const templates = Object.keys(TEMPLATE_DEFAULTS) as TemplateId[];
    return html`
      <div class="template-grid">
        ${templates.map(
          (template) => html`
            <button
              type="button"
              class="template-card"
              aria-pressed=${draft.template === template ? "true" : "false"}
              @click=${() => this._chooseTemplate(template)}
            >
              <strong>${templateLabel(template)}</strong>
              <span class="secondary">${templateSummary(template)}</span>
            </button>
          `,
        )}
      </div>
    `;
  }

  private _chooseTemplate(template: TemplateId): void {
    const defaults = TEMPLATE_DEFAULTS[template];
    this._update({
      template,
      features: [...defaults.features],
      direction: defaults.direction,
      mirror_source: defaults.mirror,
      name: this._draft?.name || templateLabel(template),
    });
    this._step = "source";
  }

  // ------------------------------------------------------------------------------------
  // Step 2: the control, and its headroom.
  // ------------------------------------------------------------------------------------

  private _renderSourceStep(draft: RuleDraft): TemplateResult {
    const chosen = this._deviceFor(draft.source.device);
    if (chosen === null) {
      return html`
        ${this._renderSearch()}
        <div class="picker">${this._renderDeviceList(this._sourceCandidates(), (device) =>
          this._chooseSource(device),
        )}</div>
      `;
    }
    return html`
      <div class="row" style="margin-bottom: 12px">
        <strong>${chosen.name}</strong>
        <span class="chip muted">${backendLabel(chosen.backend)}</span>
        <button type="button" class="link" @click=${() => this._clearSource()}>
          Choose a different device
        </button>
      </div>
      ${
        this._loadingSource
          ? html`<p class="secondary">Reading what this device offers.</p>`
          : this._renderEmitters(draft)
      }
    `;
  }

  private _renderEmitters(draft: RuleDraft): TemplateResult {
    const emitters = this._sourceDetail?.emitters ?? [];
    if (emitters.length === 0) {
      return html`<p class="secondary">
        This device reports no controls that can drive another device.
      </p>`;
    }
    return html`
      <div>
        ${emitters.map((emitter) => this._renderEmitter(draft, emitter))}
      </div>
    `;
  }

  private _renderEmitter(draft: RuleDraft, emitter: Emitter): TemplateResult {
    // A lifeline is how the device reports to Home Assistant at all. It is shown, so the
    // user can see the group is accounted for, and it is not selectable and offers no
    // control: Device Links never writes to it.
    if (emitter.is_lifeline) {
      return html`
        <div class="emitter unavailable">
          <div class="row">
            <strong>${emitter.label}</strong>
            <span class="chip muted">System link</span>
          </div>
          <p class="secondary" style="margin: 4px 0 0">
            This is the device's lifeline, which is how it reports to Home Assistant.
            Device Links never writes to it.
          </p>
        </div>
      `;
    }
    const usage = this._usage(emitter);
    const selected = draft.source.emitter_id === emitter.emitter_id;
    const features = Object.keys(emitter.actions) as Feature[];
    return html`
      <button
        type="button"
        class="emitter"
        aria-pressed=${selected ? "true" : "false"}
        @click=${() => this._chooseEmitter(emitter)}
      >
        <div class="row">
          <strong>${emitter.label}</strong>
          ${
            usage === null
              ? nothing
              : html`<span class="chip ${usage.free === 0 ? "warn" : "muted"}">
                ${usage.used} of ${usage.capacity} used in group ${usage.group}
              </span>`
          }
          ${emitter.semantics === "unknown" ? html`<span class="chip warn">Unverified</span>` : nothing}
        </div>
        <div class="chips" style="margin-top: 6px">
          ${features.map(
            (feature) => html`<span class="chip">
              ${renderIcon(this.components, featureIcon(feature))}${featureLabel(feature)}
            </span>`,
          )}
        </div>
        ${
          usage !== null && usage.free === 0
            ? html`<p class="secondary" style="margin: 6px 0 0">
              This group is full. Anything added here is blocked until an entry comes off it.
            </p>`
            : nothing
        }
      </button>
    `;
  }

  /** How much room the chosen control has left, from the device's own capabilities. */
  private _usage(emitter: Emitter): Usage | null {
    return emitterUsage(emitter, this._sourceDetail?.links ?? []);
  }

  private _sourceCandidates(): DeviceRow[] {
    return this._filtered(
      this.devices.filter((device) => device.emitters > 0 && device.device_id !== null),
    );
  }

  private _chooseSource(device: DeviceRow): void {
    this._update({
      backend: device.backend,
      source: { device: device.identity, endpoint: null, emitter_id: "" },
    });
    this._sourceDetail = null;
    void this._loadSource(device);
  }

  private _clearSource(): void {
    this._update({ source: { device: "", endpoint: null, emitter_id: "" } });
    this._sourceDetail = null;
  }

  private async _loadSource(device: DeviceRow): Promise<void> {
    if (!this.api || device.device_id === null) {
      return;
    }
    this._loadingSource = true;
    try {
      this._sourceDetail = await this.api.getDevice(device.device_id);
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._loadingSource = false;
    }
  }

  private _chooseEmitter(emitter: Emitter): void {
    const draft = this._draft;
    if (draft === null) {
      return;
    }
    const available = Object.keys(emitter.actions) as Feature[];
    const kept = draft.features.filter((feature) => available.includes(feature));
    this._update({
      // The endpoint comes with the control, because it is a property of the control: the
      // Z-Wave root is 0 and an Inovelli Blue's paddle is Zigbee endpoint 2, and a rule
      // that named neither was refused by `rules/upsert` on every protocol (T50).
      source: {
        ...draft.source,
        endpoint: emitter.endpoint,
        emitter_id: emitter.emitter_id,
      },
      // A feature the chosen control cannot carry is dropped rather than left to compile
      // into a warning the user did not cause. If that empties the set, the template's
      // intent is kept as far as the control allows.
      features: kept.length ? kept : available.slice(0, 1),
    });
  }

  // ------------------------------------------------------------------------------------
  // Step 3: the targets.
  // ------------------------------------------------------------------------------------

  private _renderTargetsStep(draft: RuleDraft): TemplateResult {
    const chosen = new Set(draft.targets.map((target) => target.device));
    const candidates = this._filtered(
      this.devices.filter((device) => device.identity !== draft.source.device),
    );
    const emitter = this._selectedEmitter(draft);
    const usage = emitter === null ? null : this._usage(emitter);
    return html`
      ${
        usage !== null && chosen.size > usage.free
          ? html`<div class="notice warn">
            <p>
              ${plural(usage.free, "entry", "entries")} free in group ${usage.group}, and
              ${plural(chosen.size, "target")} chosen. The ones that do not fit are blocked
              rather than written, and the plan will say which.
            </p>
          </div>`
          : nothing
      }
      ${this._renderSearch()}
      <div class="picker">
        <ul class="list">
          ${candidates.map(
            (device) => html`
              <li>
                <label class="choice">
                  <input
                    type="checkbox"
                    .checked=${chosen.has(device.identity)}
                    @change=${(event: Event) => this._toggleTarget(device, event)}
                  />
                  <span class="grow">
                    <span>${device.name}</span>
                    <span class="chip muted">${backendLabel(device.backend)}</span>
                    ${
                      // Which endpoint the link will land on, shown rather than only sent.
                      // It is the device's own answer to "where does a link land when
                      // nobody chose", and a device with more than one is open item T56.
                      device.receiving_endpoint === null
                        ? nothing
                        : html`<span class="chip muted">
                          Endpoint ${device.receiving_endpoint}
                        </span>`
                    }
                    ${
                      device.available
                        ? nothing
                        : html`<span class="chip warn">Not answering</span>`
                    }
                    ${device.is_long_range ? html`<span class="chip error">Long Range</span>` : nothing}
                  </span>
                </label>
              </li>
            `,
          )}
        </ul>
        ${
          candidates.length === 0
            ? html`<p class="empty">No device matches that search.</p>`
            : nothing
        }
      </div>
    `;
  }

  private _toggleTarget(device: DeviceRow, event: Event): void {
    const draft = this._draft;
    if (draft === null) {
      return;
    }
    const checked = (event.target as HTMLInputElement).checked;
    const targets = draft.targets.filter((target) => target.device !== device.identity);
    if (checked) {
      // Where a link lands on this device when nobody was offered the choice. Null on
      // Z-Wave, which is a node association on the whole device and is what the compiler
      // expects; the endpoint the load is on for a Zigbee device, whose binding is refused
      // outright without one (T50). An endpoint picker for a target with several is T56.
      targets.push({ device: device.identity, endpoint: device.receiving_endpoint });
    }
    this._update({ targets });
  }

  // ------------------------------------------------------------------------------------
  // Step 4: behaviour.
  // ------------------------------------------------------------------------------------

  private _renderBehaviourStep(draft: RuleDraft): TemplateResult {
    const emitter = this._selectedEmitter(draft);
    const actions = emitter?.actions ?? {};
    return html`
      <label class="field" style="margin-bottom: 16px">
        <span>Name</span>
        <input
          type="text"
          .value=${draft.name}
          @input=${(event: Event) => this._update({ name: (event.target as HTMLInputElement).value })}
        />
      </label>

      <h3>What it sends</h3>
      ${ALL_FEATURES.map((feature) => {
        const group = actions[feature];
        const supported = group !== undefined;
        return html`
          <label class="choice ${supported ? "" : "disabled"}">
            <input
              type="checkbox"
              .checked=${draft.features.includes(feature)}
              ?disabled=${!supported}
              @change=${(event: Event) => this._toggleFeature(feature, event)}
            />
            <span>
              <span>${featureLabel(feature)}</span>
              ${
                supported
                  ? html`<span class="secondary"> (group ${group})</span>`
                  : html`<span class="secondary">
                    ${
                      emitter === null
                        ? " (choose a control first)"
                        : ` (${emitter.label} does not send this)`
                    }
                  </span>`
              }
            </span>
          </label>
        `;
      })}

      <h3 style="margin-top: 16px">Direction</h3>
      <label class="choice">
        <input
          type="radio"
          name="direction"
          .checked=${draft.direction === "one_way"}
          @change=${() => this._update({ direction: "one_way" })}
        />
        <span>One way. The control drives the targets.</span>
      </label>
      <label class="choice">
        <input
          type="radio"
          name="direction"
          .checked=${draft.direction === "two_way"}
          @change=${() => this._update({ direction: "two_way" })}
        />
        <span>
          Two way. Each target also drives the control, using the first control on it that
          carries the same features.
        </span>
      </label>

      <h3 style="margin-top: 16px">The control's own load</h3>
      ${MIRROR_CHOICES.map(
        (choice) => html`
          <label class="choice">
            <input
              type="radio"
              name="mirror"
              .checked=${draft.mirror_source === choice.value}
              @change=${() => this._update({ mirror_source: choice.value })}
            />
            <span>
              <span>${choice.label}</span>
              <span class="secondary" style="display: block">${choice.help}</span>
            </span>
          </label>
        `,
      )}
      ${this._renderSettingPreview()}
      ${this._renderHybridSection(draft)}
    `;
  }

  /**
   * The HA-executed opt-ins, which are the one place this product bends local-first.
   *
   * Hidden entirely unless the integration's own option is on, and hidden per choice unless
   * the chosen control can carry it. What is never hidden is the label: every leg is called
   * HA-executed here, in the review step, and in the plan, so nobody has to work out which
   * half of their rule stops when Home Assistant does.
   */
  private _renderHybridSection(draft: RuleDraft): TemplateResult | typeof nothing {
    if (!this.hybridAllowed) {
      return nothing;
    }
    const emitter = this._selectedEmitter(draft);
    const offered = HYBRID_CHOICES.filter(
      (choice) => emitter !== null && emitter[choice.needs] !== null,
    );
    return html`
      <h3 style="margin-top: 16px">
        Run in Home Assistant <span class="chip warn">HA-executed</span>
      </h3>
      <p class="secondary">
        These are the parts no radio can carry. Home Assistant does them, so they stop
        working while Home Assistant is off or restarting. The rest of this rule is written
        into the devices and keeps working either way.
      </p>
      ${
        offered.length === 0
          ? html`<p class="secondary">
            ${
              emitter === null
                ? "Choose a control first."
                : `${emitter.label} does not report a scene number or a button LED that Device Links knows how to use, so none of these can be offered for it.`
            }
          </p>`
          : offered.map((choice) => this._renderHybridChoice(draft, choice))
      }
    `;
  }

  private _renderHybridChoice(
    draft: RuleDraft,
    choice: (typeof HYBRID_CHOICES)[number],
  ): TemplateResult {
    // On-only and off-only are opposite intents rather than one option with a direction,
    // and the backend refuses a rule that asks for both, so ticking one unticks the other
    // here rather than letting a save be refused for a reason nobody can see.
    const opposite: Partial<Record<HybridKind, HybridKind>> = {
      on_only: "off_only",
      off_only: "on_only",
    };
    return html`
      <label class="choice">
        <input
          type="checkbox"
          .checked=${draft.hybrid.includes(choice.value)}
          @change=${(event: Event) =>
            this._toggleHybrid(choice.value, opposite[choice.value], event)}
        />
        <span>
          <span>${choice.label}</span>
          <span class="chip warn">HA-executed</span>
          <span class="secondary" style="display: block">${choice.help}</span>
        </span>
      </label>
    `;
  }

  private _toggleHybrid(kind: HybridKind, opposite: HybridKind | undefined, event: Event): void {
    const draft = this._draft;
    if (draft === null) {
      return;
    }
    const checked = (event.target as HTMLInputElement).checked;
    const hybrid = draft.hybrid.filter((existing) => existing !== kind && existing !== opposite);
    if (checked) {
      hybrid.push(kind);
    }
    this._update({ hybrid });
  }

  /** The exact parameter a mirror choice writes, taken from the compiler rather than guessed. */
  private _renderSettingPreview(): TemplateResult | typeof nothing {
    const settings = this._compiled?.settings ?? [];
    if (settings.length === 0) {
      return nothing;
    }
    return html`
      <div class="notice">
        ${settings.map(
          (setting) => html`<p>
            This writes parameter ${setting.parameter}
            ${setting.bitmask === null ? "" : `(bitmask ${setting.bitmask})`} on the control
            to ${setting.value}.
          </p>`,
        )}
      </div>
    `;
  }

  private _toggleFeature(feature: Feature, event: Event): void {
    const draft = this._draft;
    if (draft === null) {
      return;
    }
    const checked = (event.target as HTMLInputElement).checked;
    const features = draft.features.filter((existing) => existing !== feature);
    if (checked) {
      features.push(feature);
    }
    this._update({ features });
  }

  // ------------------------------------------------------------------------------------
  // Step 5: review, which is where the compiler gets the last word.
  // ------------------------------------------------------------------------------------

  private _renderReviewStep(draft: RuleDraft): TemplateResult {
    const compiled = this._compiled;
    return html`
      <div class="notice">
        <p>
          <strong>${draft.name}</strong>, ${templateLabel(draft.template)}, from
          ${this._nameOf(draft.source.device)} to
          ${draft.targets.map((target) => this._nameOf(target.device)).join(", ") || "nothing yet"}.
        </p>
      </div>
      ${this._validating ? html`<p class="secondary">Compiling.</p>` : nothing}
      ${compiled === null ? nothing : this._renderDiagnostics(compiled)}
      ${compiled === null ? nothing : this._renderCompiled(compiled)}
    `;
  }

  private _renderDiagnostics(compiled: CompiledRule): TemplateResult {
    return html`
      ${compiled.errors.map(
        (error) => html`<div class="notice error" role="alert">
          <p><strong>Problem.</strong> ${localizeDiagnostic(this.hass, error)}</p>
        </div>`,
      )}
      ${compiled.warnings.map(
        (warning) => html`<div class="notice warn" role="status">
          <p><strong>Warning.</strong> ${localizeDiagnostic(this.hass, warning)}</p>
        </div>`,
      )}
      ${
        compiled.errors.length > 0
          ? html`<p class="secondary">
            This rule compiles to no links, so there is nothing to apply. You can still save
            it: it will show as blocked in the rules table until whatever is wrong is fixed.
          </p>`
          : nothing
      }
    `;
  }

  private _renderCompiled(compiled: CompiledRule): TemplateResult {
    if (compiled.links.length === 0) {
      return html`
        <p>No links written to devices.</p>
        ${this._renderHybridLegs(compiled)}
      `;
    }
    return html`
      <h3>${plural(compiled.links.length, "link")}</h3>
      <ul class="list">
        ${compiled.links.map((link) => html`<li>${describeLink(link)}</li>`)}
      </ul>
      ${
        compiled.settings.length === 0
          ? nothing
          : html`
            <h3 style="margin-top: 12px">Device settings</h3>
            <ul class="list">
              ${compiled.settings.map(
                (setting) => html`<li>
                  ${setting.capability}: parameter ${setting.parameter}
                  ${setting.bitmask === null ? "" : `(bitmask ${setting.bitmask})`} set to
                  ${setting.value}
                </li>`,
              )}
            </ul>
          `
      }
      ${this._renderHybridLegs(compiled)}
    `;
  }

  /**
   * What Home Assistant will carry for this rule, under its own heading and its own label.
   *
   * Never mixed into the link list. A link is written into a device and survives Home
   * Assistant being off; a leg is a listener that does not. Showing them in one list would
   * be exactly the blurring Decision D3 says must not happen quietly.
   */
  private _renderHybridLegs(compiled: CompiledRule): TemplateResult | typeof nothing {
    if (compiled.hybrid_legs.length === 0) {
      return nothing;
    }
    return html`
      <h3 style="margin-top: 12px">
        ${plural(compiled.hybrid_legs.length, "HA-executed leg")}
      </h3>
      <p class="secondary">
        Run by Home Assistant, not written to a device. These stop working while Home
        Assistant is off; everything above keeps working.
      </p>
      <ul class="list">
        ${compiled.hybrid_legs.map(
          (leg) => html`<li>
            <span class="chip warn">HA-executed</span> ${describeHybridLeg(leg)}
          </li>`,
        )}
      </ul>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Shared bits of the steps.
  // ------------------------------------------------------------------------------------

  private _renderSearch(): TemplateResult {
    return html`
      <label class="field" style="margin-bottom: 8px">
        <span>Search devices</span>
        <input
          type="search"
          .value=${this._search}
          @input=${(event: Event) => {
            this._search = (event.target as HTMLInputElement).value;
          }}
        />
      </label>
    `;
  }

  private _renderDeviceList(
    devices: DeviceRow[],
    choose: (device: DeviceRow) => void,
  ): TemplateResult {
    if (devices.length === 0) {
      return html`<p class="empty">No device matches that search.</p>`;
    }
    return html`
      <ul class="list">
        ${devices.map(
          (device) => html`
            <li>
              <button type="button" class="selectable" @click=${() => choose(device)}>
                <span class="row">
                  <span class="grow">${device.name}</span>
                  <span class="chip muted">${backendLabel(device.backend)}</span>
                  <span class="chip muted">${plural(device.emitters, "control")}</span>
                  ${device.available ? nothing : html`<span class="chip warn">Not answering</span>`}
                </span>
              </button>
            </li>
          `,
        )}
      </ul>
    `;
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

  private _deviceFor(identity: string): DeviceRow | null {
    return this.devices.find((device) => device.identity === identity) ?? null;
  }

  private _nameOf(identity: string): string {
    return this._deviceFor(identity)?.name ?? identity;
  }

  private _selectedEmitter(draft: RuleDraft): Emitter | null {
    return (
      this._sourceDetail?.emitters.find(
        (emitter) => emitter.emitter_id === draft.source.emitter_id,
      ) ?? null
    );
  }

  // ------------------------------------------------------------------------------------
  // Moving between steps, and leaving.
  // ------------------------------------------------------------------------------------

  private _renderActions(): TemplateResult {
    const draft = this._draft;
    const index = STEPS.indexOf(this._step);
    if (draft === null) {
      return html`<button type="button" class="outlined" @click=${this._close}>Close</button>`;
    }
    if (this._step === "review") {
      const blocked = (this._compiled?.errors.length ?? 0) > 0;
      return html`
        <button type="button" class="outlined" @click=${() => this._goTo(index - 1)}>Back</button>
        <button type="button" class="outlined" ?disabled=${this._saving} @click=${() => this._save(false)}>
          ${blocked ? "Save anyway" : "Save"}
        </button>
        <button
          type="button"
          class="primary"
          ?disabled=${this._saving || blocked}
          title=${blocked ? "This rule compiles to no links, so there is nothing to apply." : ""}
          @click=${() => this._save(true)}
        >
          Save and apply
        </button>
      `;
    }
    return html`
      <button type="button" class="outlined" @click=${this._close}>Cancel</button>
      ${
        index === 0
          ? nothing
          : html`<button type="button" class="outlined" @click=${() => this._goTo(index - 1)}>
            Back
          </button>`
      }
      <button
        type="button"
        class="primary"
        ?disabled=${!this._canLeave(this._step, draft)}
        @click=${() => this._goTo(index + 1)}
      >
        Next
      </button>
    `;
  }

  /** What each step needs before it can be left. Nothing is guessed on the user's behalf. */
  private _canLeave(step: Step, draft: RuleDraft): boolean {
    switch (step) {
      case "template":
        return true;
      case "source":
        return draft.source.device !== "" && draft.source.emitter_id !== "";
      case "targets":
        return draft.targets.length > 0;
      case "behaviour":
        return draft.features.length > 0 && draft.name.trim() !== "";
      default:
        return true;
    }
  }

  private _goTo(index: number): void {
    const step = STEPS[Math.min(Math.max(index, 0), STEPS.length - 1)];
    if (step === undefined) {
      return;
    }
    this._step = step;
    if (step === "review") {
      this._validate();
    }
  }

  private _begin(): void {
    this._error = null;
    this._compiled = null;
    this._search = "";
    this._sourceDetail = null;
    if (this.rule === null) {
      const template = this.initialTemplate ?? "remote";
      const defaults = TEMPLATE_DEFAULTS[template];
      this._draft = {
        id: newRuleId(),
        name: this.initialTemplate === null ? "" : templateLabel(template),
        template,
        backend: "zwave",
        enabled: true,
        direction: defaults.direction,
        mirror_source: defaults.mirror,
        features: [...defaults.features],
        hybrid: [],
        source: { device: "", endpoint: null, emitter_id: "" },
        targets: [],
      };
      this._step = "template";
      return;
    }
    this._draft = {
      ...this.rule,
      features: [...this.rule.features],
      // Defaulted rather than assumed present: a rule stored before hybrid legs existed
      // arrives without the key, and a draft with an undefined list would throw on the
      // first render of the section rather than showing nothing ticked.
      hybrid: [...(this.rule.hybrid ?? [])],
      targets: [...this.rule.targets],
    };
    this._step = "template";
    const device = this._deviceFor(this.rule.source.device);
    if (device !== null) {
      // Compiled straight away rather than on the first edit, so the behaviour step can
      // show the exact parameter this rule writes without waiting for the user to change
      // something first.
      void this._loadSource(device).then(() => this._validate());
    }
  }

  private _update(patch: Partial<RuleDraft>): void {
    if (this._draft === null) {
      return;
    }
    this._draft = { ...this._draft, ...patch };
    this._scheduleValidate();
  }

  /**
   * Ask the compiler what this draft means, a moment after the typing stops.
   *
   * `rules/validate` stores nothing and writes to no device, so calling it while the user
   * is still editing is free of consequence; debouncing is about not sending a command
   * per keystroke, not about safety.
   */
  private _scheduleValidate(): void {
    clearTimeout(this._validateTimer);
    this._validateTimer = setTimeout(() => this._validate(), 300);
  }

  private _validate(): void {
    const draft = this._draft;
    if (!this.api || draft === null) {
      return;
    }
    const rule = payloadOf(draft);
    if (rule === null) {
      this._compiled = null;
      return;
    }
    this._validating = true;
    void this.api
      .validateRule(rule)
      .then((compiled) => {
        this._compiled = compiled;
        this._error = null;
      })
      .catch((error: unknown) => {
        this._error = describeError(this.hass, DeviceLinksApiError.from(error));
      })
      .finally(() => {
        this._validating = false;
      });
  }

  private async _save(apply: boolean): Promise<void> {
    const draft = this._draft;
    if (!this.api || draft === null) {
      return;
    }
    // Unreachable from the review step, which cannot be arrived at without a control and a
    // target, and cheaper than a save that would be refused for a reason the user cannot
    // see. The type is what makes it a check rather than a hope. It says so out loud rather
    // than returning quietly: a Save button that does nothing at all is the one outcome
    // worse than a refusal, and if this ever becomes reachable it has to be visible.
    const rule = payloadOf(draft);
    if (rule === null) {
      this._error = "This rule still needs a control and at least one target.";
      return;
    }
    this._saving = true;
    this._error = null;
    try {
      await this.api.upsertRule(rule, this.profileId);
      this.dispatchEvent(
        new CustomEvent<RuleSavedDetail>("dl-rule-saved", {
          detail: { rule, apply },
          bubbles: true,
          composed: true,
        }),
      );
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._saving = false;
    }
  }

  private _close(): void {
    this.dispatchEvent(new CustomEvent("dl-editor-closed", { bubbles: true, composed: true }));
  }
}

/**
 * A new rule id.
 *
 * `crypto.randomUUID` is not available on an insecure origin in every browser, and a
 * Home Assistant reached over plain http on a LAN is exactly that case, so there is a
 * fallback rather than an exception at the moment somebody presses New rule.
 */
function newRuleId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) {
    return uuid.replace(/-/g, "");
  }
  return `rule${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

declare global {
  interface HTMLElementTagNameMap {
    "dl-rule-editor": DeviceLinksRuleEditor;
  }
}
