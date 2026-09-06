/**
 * Profiles: the sets of rules, and which one is in force.
 *
 * **Activating a profile writes to nothing.** FR-E1 makes activating a decision about what
 * should be true and applying it a separate act, and the backend answers `profiles/activate`
 * with the plan that activation opened. That plan is handed straight to the plan dialog
 * rather than being asked for again, so the token the user confirms belongs to the plan
 * they were shown.
 */

import { html, nothing, type TemplateResult } from "lit";
import { customElement, state } from "lit/decorators.js";

import { DeviceLinksApiError, describeError } from "../api";
import "../components/dialog";
import "../dialogs/plan-dialog";
import { plural } from "../format";
import { sharedStyles } from "../styles";
import type { Plan, ProfileRow } from "../types";
import { DeviceLinksView } from "./view-base";

/** Which of the three small dialogs this view can open is open. */
type Sheet = "none" | "create" | "import" | "export" | "delete";

@customElement("device-links-profiles")
export class DeviceLinksProfiles extends DeviceLinksView {
  static override styles = sharedStyles;

  @state() private _profiles: ProfileRow[] = [];

  @state() private _loading = true;

  @state() private _busy = false;

  @state() private _error: string | null = null;

  @state() private _sheet: Sheet = "none";

  @state() private _subject: ProfileRow | null = null;

  @state() private _text = "";

  @state() private _exported = "";

  @state() private _planOpen = false;

  @state() private _plan: Plan | null = null;

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
        <div class="card">
          <div class="spread">
            <div class="grow">
              <h2>Profiles</h2>
              <p class="secondary">
                One profile is in force at a time. The others are kept as they are, and
                nothing they say reaches a device until you activate them and apply.
              </p>
            </div>
            <div class="row">
              <button type="button" class="outlined" @click=${() => this._open("import")}>
                Import
              </button>
              <button type="button" class="primary" @click=${() => this._open("create")}>
                New profile
              </button>
            </div>
          </div>
          ${this._renderList()}
        </div>
      </div>
      ${this._renderSheets()}
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .initialPlan=${this._plan}
        .heading=${this._planHeading}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
  }

  private _renderList(): TemplateResult {
    if (this._loading) {
      return html`<p class="secondary">Loading.</p>`;
    }
    if (this._profiles.length === 0) {
      return html`<p class="empty">No profiles yet.</p>`;
    }
    return html`
      <ul class="list">
        ${this._profiles.map((profile) => this._renderRow(profile))}
      </ul>
    `;
  }

  private _renderRow(profile: ProfileRow): TemplateResult {
    return html`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <strong>${profile.name}</strong>
              ${profile.is_active ? html`<span class="chip ok">Active</span>` : nothing}
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${plural(profile.rules, "rule")}, ${profile.enabled_rules} enabled.
            </p>
          </div>
          <div class="row">
            ${
              profile.is_active
                ? html`<button type="button" class="outlined" @click=${() => this.goTo("rules")}>
                  Open rules
                </button>`
                : html`<button
                  type="button"
                  class="primary"
                  ?disabled=${this._busy}
                  @click=${() => this._activate(profile)}
                >
                  Activate
                </button>`
            }
            <button
              type="button"
              class="outlined"
              ?disabled=${this._busy}
              @click=${() => this._duplicate(profile)}
            >
              Duplicate
            </button>
            <button
              type="button"
              class="outlined"
              ?disabled=${this._busy}
              @click=${() => this._export(profile)}
            >
              Export
            </button>
            <button type="button" class="danger" @click=${() => this._open("delete", profile)}>
              Delete
            </button>
          </div>
        </div>
      </li>
    `;
  }

  private _renderSheets(): TemplateResult {
    return html`
      <dl-dialog
        .open=${this._sheet === "create"}
        .narrow=${this.narrow}
        heading="New profile"
        @dl-dialog-closed=${this._closeSheet}
      >
        <label class="field">
          <span>Name</span>
          <input
            type="text"
            .value=${this._text}
            @input=${(event: Event) => {
              this._text = (event.target as HTMLInputElement).value;
            }}
          />
        </label>
        <p class="secondary">
          A new profile starts empty and is not activated. Nothing changes on any device.
        </p>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Cancel</button>
          <button
            type="button"
            class="primary"
            ?disabled=${this._text.trim() === "" || this._busy}
            @click=${this._create}
          >
            Create
          </button>
        </div>
      </dl-dialog>

      <dl-dialog
        .open=${this._sheet === "import"}
        .narrow=${this.narrow}
        heading="Import a profile"
        @dl-dialog-closed=${this._closeSheet}
      >
        <p class="secondary">
          Paste the YAML of a profile. It is stored and nothing is written to a device. If
          it names devices this network does not have, the import is refused whole rather
          than half done.
        </p>
        <textarea
          .value=${this._text}
          aria-label="Profile YAML"
          @input=${(event: Event) => {
            this._text = (event.target as HTMLTextAreaElement).value;
          }}
        ></textarea>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Cancel</button>
          <button
            type="button"
            class="primary"
            ?disabled=${this._text.trim() === "" || this._busy}
            @click=${this._import}
          >
            Import
          </button>
        </div>
      </dl-dialog>

      <dl-dialog
        .open=${this._sheet === "export"}
        .narrow=${this.narrow}
        .heading=${`Export ${this._subject?.name ?? ""}`}
        @dl-dialog-closed=${this._closeSheet}
      >
        <p class="secondary">This is the file this profile would be kept as.</p>
        <textarea readonly aria-label="Exported YAML" .value=${this._exported}></textarea>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Close</button>
          <button type="button" class="primary" @click=${this._copyExport}>Copy</button>
        </div>
      </dl-dialog>

      <dl-dialog
        .open=${this._sheet === "delete"}
        .narrow=${this.narrow}
        .heading=${`Delete ${this._subject?.name ?? ""}?`}
        @dl-dialog-closed=${this._closeSheet}
      >
        <p>
          The profile and its rules are removed from Device Links. Whatever those rules
          already wrote stays on the devices and becomes unmanaged, so nothing in your house
          changes when you press this.
        </p>
        <div slot="actions">
          <button type="button" class="outlined" @click=${this._closeSheet}>Cancel</button>
          <button type="button" class="danger" @click=${this._delete}>Delete the profile</button>
        </div>
      </dl-dialog>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Data and actions.
  // ------------------------------------------------------------------------------------

  private async _load(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._loading = true;
    try {
      this._profiles = (await this.api.listProfiles()).profiles ?? [];
      this._error = null;
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._loading = false;
    }
  }

  private _open(sheet: Sheet, subject: ProfileRow | null = null): void {
    this._sheet = sheet;
    this._subject = subject;
    this._text = "";
  }

  private _closeSheet(): void {
    this._sheet = "none";
    this._subject = null;
    this._text = "";
  }

  private async _run(action: () => Promise<void>): Promise<void> {
    this._busy = true;
    this._error = null;
    try {
      await action();
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._busy = false;
    }
  }

  private async _create(): Promise<void> {
    const name = this._text.trim();
    await this._run(async () => {
      await this.api.createProfile({ id: newProfileId(), name, rules: [] });
      this._closeSheet();
      await this._load();
    });
  }

  private async _duplicate(profile: ProfileRow): Promise<void> {
    await this._run(async () => {
      await this.api.duplicateProfile(profile.id);
      await this._load();
    });
  }

  private async _export(profile: ProfileRow): Promise<void> {
    await this._run(async () => {
      const exported = await this.api.exportProfile(profile.id);
      this._exported = exported.yaml;
      this._subject = profile;
      this._sheet = "export";
    });
  }

  private _copyExport(): void {
    void navigator.clipboard?.writeText(this._exported).catch(() => undefined);
  }

  private async _import(): Promise<void> {
    const yaml = this._text;
    await this._run(async () => {
      const result = await this.api.importProfile(yaml);
      this._closeSheet();
      await this._load();
      // An import into the active profile answers with the plan it opened. Showing it is
      // the difference between "stored" and "and here is what that would change".
      if (result.plan !== undefined) {
        this._plan = result.plan;
        this._planHeading = `Plan and apply: ${result.profile.name}`;
        this._planOpen = true;
      }
    });
  }

  private async _activate(profile: ProfileRow): Promise<void> {
    await this._run(async () => {
      const result = await this.api.activateProfile(profile.id);
      await this._load();
      this._plan = result.plan;
      this._planHeading = `Plan and apply: ${profile.name}`;
      this._planOpen = true;
    });
  }

  private async _delete(): Promise<void> {
    const profile = this._subject;
    if (profile === null) {
      return;
    }
    await this._run(async () => {
      await this.api.deleteProfile(profile.id);
      this._closeSheet();
      await this._load();
    });
  }

  private _closePlan(): void {
    this._planOpen = false;
    this._plan = null;
    void this._load();
  }

  private _afterApply(): void {
    void this._load();
  }
}

/** A profile id, which the user never sees and the storage keys on. */
function newProfileId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? uuid.replace(/-/g, "") : `profile${Date.now().toString(36)}`;
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-profiles": DeviceLinksProfiles;
  }
}
