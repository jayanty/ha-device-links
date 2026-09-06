/**
 * Devices: what is actually on each device, rule or no rule.
 *
 * This is the view that answers "what does my house really hold", so it shows what was
 * read rather than what was intended: every entry on every control, including the ones no
 * rule of ours claims and the ones the device needs to work at all.
 *
 * **A lifeline offers no Remove control at all.** Not a disabled one, not a greyed one:
 * none. The backend refuses lifeline removal in three places already, and the UI should
 * not invite the click. The same is true of any link the backend marks `is_system`.
 *
 * **A device that cannot be read says so before it says anything else.** The coordinator
 * marks a device from an unavailable backend as unavailable and keeps its cached links, so
 * the honest reading of this screen is "this is what was last seen", and the difference
 * between that and "this is what is there" is the difference between a tool somebody
 * trusts and one they learn to double-check.
 *
 * **Removing an unmanaged link goes through the plan dialog**, like every other write in
 * this panel. There is a WebSocket command that would remove one directly; using it here
 * would be the shortcut Decision D18 exists to refuse.
 */

import { html, nothing, type TemplateResult } from "lit";
import { customElement, state } from "lit/decorators.js";

import { DeviceLinksApiError, describeError, type PlanScope } from "../api";
import "../components/two-pane";
import "../dialogs/plan-dialog";
import { renderIcon } from "../components/icon";
import {
  backendLabel,
  emitterUsage,
  endpointName,
  featureIcon,
  featureLabel,
  plural,
} from "../format";
import { sharedStyles } from "../styles";
import type { DeviceDetail, DeviceRow, Emitter, Feature, LinkRow } from "../types";
import { DeviceLinksView } from "./view-base";

/** How sure we are that what is on screen is what is on the device. */
type Confidence = "cached" | "confirmed" | "unconfirmed";

@customElement("device-links-devices")
export class DeviceLinksDevices extends DeviceLinksView {
  static override styles = sharedStyles;

  @state() private _devices: DeviceRow[] = [];

  @state() private _detail: DeviceDetail | null = null;

  @state() private _selectedId: string | null = null;

  @state() private _search = "";

  @state() private _loading = true;

  @state() private _busy = false;

  @state() private _error: string | null = null;

  @state() private _confidence: Confidence = "cached";

  @state() private _incoming: LinkRow[] | null = null;

  @state() private _incomingState: "idle" | "loading" | "ready" | "error" = "idle";

  @state() private _planOpen = false;

  @state() private _planScope: PlanScope | undefined;

  @state() private _planRemove: string[] = [];

  @state() private _planHeading = "Plan and apply";

  /** Every device's links, read once so "what controls this device" can be answered. */
  private _linkIndex: LinkRow[] = [];

  override connectedCallback(): void {
    super.connectedCallback();
    void this._load();
  }

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("selected") && this.selected !== null) {
      void this._select(this.selected);
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
        <dl-two-pane .narrow=${this.narrow} ?show-detail=${this._selectedId !== null}>
          <div slot="list" class="card">${this._renderList()}</div>
          <div slot="detail" class="card">${this._renderDetail()}</div>
        </dl-two-pane>
      </div>
      <dl-plan-dialog
        .hass=${this.hass}
        .api=${this.api}
        .components=${this.components}
        .narrow=${this.narrow}
        .open=${this._planOpen}
        .scope=${this._planScope}
        .initialRemoveUnmanaged=${this._planRemove}
        .heading=${this._planHeading}
        @dl-plan-closed=${this._closePlan}
        @dl-plan-applied=${this._afterApply}
      ></dl-plan-dialog>
    `;
  }

  // ------------------------------------------------------------------------------------
  // The list.
  // ------------------------------------------------------------------------------------

  private _renderList(): TemplateResult {
    const devices = this._filtered();
    return html`
      <label class="field" style="margin-bottom: 8px">
        <span>Search</span>
        <input
          type="search"
          .value=${this._search}
          placeholder="Name or address"
          @input=${(event: Event) => {
            this._search = (event.target as HTMLInputElement).value;
          }}
        />
      </label>
      ${
        this._loading
          ? html`<p class="secondary">Loading.</p>`
          : devices.length === 0
            ? html`<p class="empty">No device matches that search.</p>`
            : html`
              <ul class="list">
                ${devices.map((device) => this._renderListRow(device))}
              </ul>
            `
      }
    `;
  }

  private _renderListRow(device: DeviceRow): TemplateResult {
    return html`
      <li>
        <button
          type="button"
          class="selectable ${device.available ? "" : "unavailable"}"
          aria-current=${device.device_id === this._selectedId ? "true" : "false"}
          ?disabled=${device.device_id === null}
          @click=${() => this._selectRow(device)}
        >
          <span class="row">
            <span class="grow">${device.name}</span>
            <span class="chip muted">${backendLabel(device.backend)}</span>
          </span>
          <span class="chips" style="margin-top: 4px">
            <span class="chip muted">${plural(device.links, "link")}</span>
            <span class="chip muted">${plural(device.emitters, "control")}</span>
            ${device.available ? nothing : html`<span class="chip warn">Not answering</span>`}
            ${device.is_long_range ? html`<span class="chip error">Long Range</span>` : nothing}
            ${
              device.device_id === null
                ? html`<span class="chip muted">No Home Assistant device</span>`
                : nothing
            }
          </span>
        </button>
      </li>
    `;
  }

  // ------------------------------------------------------------------------------------
  // The detail.
  // ------------------------------------------------------------------------------------

  private _renderDetail(): TemplateResult {
    const detail = this._detail;
    if (detail === null) {
      return html`<p class="empty">Choose a device to see what is on it.</p>`;
    }
    const device = detail.device;
    return html`
      ${
        this.narrow
          ? html`<button type="button" class="link" @click=${this._clear}>Back to the list</button>`
          : nothing
      }
      <div class="spread" style="margin-top: 8px">
        <div class="grow">
          <h2>${device.name}</h2>
          <div class="chips">
            <span class="chip muted">${backendLabel(device.backend)}</span>
            <span class="chip muted">${device.protocol_id}</span>
            ${device.available ? nothing : html`<span class="chip warn">Not answering</span>`}
            ${device.is_long_range ? html`<span class="chip error">Long Range</span>` : nothing}
          </div>
        </div>
        <div class="row">
          <button type="button" class="outlined" ?disabled=${this._busy} @click=${() => this._refresh(false)}>
            Refresh
          </button>
          <button type="button" class="outlined" ?disabled=${this._busy} @click=${() => this._refresh(true)}>
            Deep verify
          </button>
        </div>
      </div>
      ${this._renderConfidence(device)}
      ${this._renderOutgoing(detail)}
      ${this._renderIncoming(detail)}
      ${this._renderSettings(detail)}
    `;
  }

  /**
   * How much of what is on this screen is confirmed, in the three states there really are.
   *
   * A deep verify asks the device rather than the driver's cache, and it can end in one of
   * two places: the device answered, or it did not. Neither is the same as never having
   * asked, which is what a page shows when it is first opened, so all three are said in
   * different words. A green tick for "we asked and heard nothing back" is the one answer
   * this view will not give.
   */
  private _renderConfidence(device: DeviceRow): TemplateResult {
    if (!device.available) {
      return html`
        <div class="notice warn">
          <p>
            This device is not answering. What follows is what Device Links last read from
            it, kept so you can see what it holds; it cannot be confirmed right now, and
            nothing can be planned for it until it answers again.
          </p>
        </div>
      `;
    }
    if (this._confidence === "confirmed") {
      return html`
        <div class="notice">
          <p>Read from the device itself just now.</p>
        </div>
      `;
    }
    if (this._confidence === "unconfirmed") {
      return html`
        <div class="notice warn">
          <p>
            The deep verify did not come back confirmed. The device may have been asleep or
            simply did not report a value, so what follows is still the last known state
            rather than a fresh reading. It is not evidence that anything is wrong.
          </p>
        </div>
      `;
    }
    return html`
      <p class="secondary">
        From the driver's cache. Deep verify reads the device itself.
      </p>
    `;
  }

  private _renderOutgoing(detail: DeviceDetail): TemplateResult {
    const claimed = new Set<string>();
    return html`
      <h3 style="margin-top: 16px">Outgoing</h3>
      <p class="secondary">What this device sends, and to whom.</p>
      ${
        detail.emitters.length === 0
          ? html`<p class="secondary">This device offers no controls that reach another device.</p>`
          : detail.emitters.map((emitter) => this._renderEmitter(detail, emitter, claimed))
      }
      ${this._renderOrphans(detail, claimed)}
    `;
  }

  private _renderEmitter(
    detail: DeviceDetail,
    emitter: Emitter,
    claimed: Set<string>,
  ): TemplateResult {
    const groups = new Set(
      emitter.group_ids.length
        ? emitter.group_ids
        : Object.values(emitter.actions).filter((group): group is string => group !== undefined),
    );
    const entries = detail.links.filter((link) => groups.has(link.emitter_group));
    for (const entry of entries) {
      claimed.add(entry.fingerprint);
    }
    const usage = emitterUsage(emitter, detail.links);
    const features = Object.keys(emitter.actions) as Feature[];
    return html`
      <div class="card" style="margin-top: 8px">
        <div class="row">
          <strong class="grow">${emitter.label}</strong>
          ${
            emitter.is_lifeline
              ? html`<span class="chip muted" title="Device Links never writes to a lifeline">
                System link
              </span>`
              : nothing
          }
          ${
            usage === null
              ? nothing
              : html`<span class="chip ${usage.free === 0 ? "warn" : "muted"}">
                ${usage.used} of ${usage.capacity} used in group ${usage.group}
              </span>`
          }
        </div>
        <div class="chips" style="margin: 6px 0">
          ${features.map(
            (feature) =>
              html`<span class="chip">
                ${renderIcon(this.components, featureIcon(feature))}${featureLabel(feature)}
              </span>`,
          )}
          ${
            emitter.semantics === "unknown"
              ? html`<span class="chip warn" title="What this control sends has not been observed">
                Unverified
              </span>`
              : nothing
          }
        </div>
        ${
          entries.length === 0
            ? html`<p class="secondary">Nothing on it.</p>`
            : html`<ul class="list">${entries.map((link) => this._renderEntry(link))}</ul>`
        }
      </div>
    `;
  }

  /** Entries on groups no control claims, which would otherwise be invisible. */
  private _renderOrphans(
    detail: DeviceDetail,
    claimed: Set<string>,
  ): TemplateResult | typeof nothing {
    const orphans = detail.links.filter((link) => !claimed.has(link.fingerprint));
    if (orphans.length === 0) {
      return nothing;
    }
    return html`
      <div class="card" style="margin-top: 8px">
        <div class="row">
          <strong class="grow">Other groups</strong>
          <span class="chip muted">${plural(orphans.length, "entry", "entries")}</span>
        </div>
        <p class="secondary">
          These are on groups no control of this device claims, so Device Links cannot say
          which button they belong to.
        </p>
        <ul class="list">${orphans.map((link) => this._renderEntry(link))}</ul>
      </div>
    `;
  }

  private _renderEntry(link: LinkRow): TemplateResult {
    const unmanaged = !link.is_system && link.rule_id === null;
    return html`
      <li>
        <div class="spread">
          <div class="grow">
            <div class="row">
              <span>${endpointName(link.target)}</span>
              <span class="chip muted">${featureLabel(link.feature)}</span>
              <span class="chip muted">group ${link.emitter_group}</span>
            </div>
            <p class="secondary" style="margin: 4px 0 0">
              ${
                link.is_system
                  ? "System link. Device Links never removes this."
                  : link.rule_name !== null
                    ? `Managed by ${link.rule_name}`
                    : link.rule_id !== null
                      ? "Managed by a rule that is no longer in the active profile"
                      : "Not managed by any rule. Somebody added this by hand, or a rule that used to own it changed."
              }
            </p>
          </div>
          ${this._renderEntryActions(link, unmanaged)}
        </div>
      </li>
    `;
  }

  /**
   * The controls one entry offers.
   *
   * A system link is given none at all. That is the point: the backend refuses to remove a
   * lifeline in three places, and a disabled button here would still be a button, which is
   * an invitation to try.
   */
  private _renderEntryActions(link: LinkRow, unmanaged: boolean): TemplateResult | typeof nothing {
    if (link.is_system || !unmanaged) {
      return nothing;
    }
    return html`
      <div class="row">
        <button
          type="button"
          class="outlined"
          ?disabled=${this._busy}
          @click=${() => this._setIgnored(link, !this._isIgnored(link))}
        >
          ${this._isIgnored(link) ? "Stop ignoring" : "Ignore"}
        </button>
        <button type="button" class="danger" @click=${() => this._planRemoval(link)}>
          Remove
        </button>
      </div>
    `;
  }

  private _renderIncoming(detail: DeviceDetail): TemplateResult {
    const identity = detail.device.identity;
    return html`
      <h3 style="margin-top: 16px">Incoming</h3>
      <p class="secondary">What reaches this device from somewhere else.</p>
      ${
        this._incomingState === "loading"
          ? html`<p class="secondary">Reading every device to find what controls this one.</p>`
          : this._incomingState === "error"
            ? html`<p class="secondary">
              The other devices could not all be read, so this list may be short.
            </p>`
            : nothing
      }
      ${this._renderIncomingList(identity)}
    `;
  }

  private _renderIncomingList(identity: string): TemplateResult {
    const incoming = (this._incoming ?? []).filter((link) => link.target.identity === identity);
    if (this._incomingState === "loading") {
      return html``;
    }
    if (incoming.length === 0) {
      return html`<p class="secondary">Nothing controls this device over the radio.</p>`;
    }
    return html`
      <ul class="list">
        ${incoming.map(
          (link) => html`
            <li>
              <div class="row">
                <span class="grow">${endpointName(link.source)}</span>
                <span class="chip muted">group ${link.emitter_group}</span>
                <span class="chip muted">${featureLabel(link.feature)}</span>
                ${link.is_system ? html`<span class="chip muted">System link</span>` : nothing}
              </div>
              <p class="secondary" style="margin: 4px 0 0">
                ${link.rule_name ?? (link.is_system ? "System link" : "Not managed by any rule")}
              </p>
            </li>
          `,
        )}
      </ul>
    `;
  }

  private _renderSettings(detail: DeviceDetail): TemplateResult | typeof nothing {
    const entries = Object.entries(detail.settings);
    if (entries.length === 0) {
      return nothing;
    }
    return html`
      <h3 style="margin-top: 16px">Association settings</h3>
      <p class="secondary">
        The device settings a rule can write. The value is what was last read from the device.
      </p>
      <div class="scroll-x">
        <table>
          <thead>
            <tr>
              <th>Setting</th>
              <th>Current value</th>
            </tr>
          </thead>
          <tbody>
            ${entries.map(
              ([name, value]) => html`
                <tr>
                  <td>${name}</td>
                  <td class="mono">${String(value)}</td>
                </tr>
              `,
            )}
          </tbody>
        </table>
      </div>
    `;
  }

  // ------------------------------------------------------------------------------------
  // Data.
  // ------------------------------------------------------------------------------------

  private _filtered(): DeviceRow[] {
    const needle = this._search.trim().toLowerCase();
    if (!needle) {
      return this._devices;
    }
    return this._devices.filter((device) =>
      `${device.name} ${device.protocol_id}`.toLowerCase().includes(needle),
    );
  }

  private async _load(): Promise<void> {
    if (!this.api) {
      return;
    }
    this._loading = true;
    try {
      this._devices = (await this.api.listDevices()) ?? [];
      this._error = null;
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._loading = false;
    }
  }

  private _selectRow(device: DeviceRow): void {
    if (device.device_id === null) {
      return;
    }
    void this._select(device.device_id);
  }

  private async _select(deviceId: string): Promise<void> {
    if (!this.api) {
      return;
    }
    this._selectedId = deviceId;
    this._confidence = "cached";
    this._busy = true;
    try {
      this._detail = await this.api.getDevice(deviceId);
      this._error = null;
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._busy = false;
    }
    void this._loadIncoming();
  }

  private _clear(): void {
    this._selectedId = null;
    this._detail = null;
  }

  private async _refresh(deep: boolean): Promise<void> {
    const deviceId = this._selectedId;
    if (!this.api || deviceId === null) {
      return;
    }
    this._busy = true;
    try {
      const detail = await this.api.refreshDevice(deviceId, deep);
      this._detail = detail;
      this._confidence = !deep ? "cached" : detail.deep_verified ? "confirmed" : "unconfirmed";
      this._error = null;
      // The links this device holds may have changed, so the index other devices' incoming
      // lists were built from is stale.
      this._linkIndex = [];
      this._incomingState = "idle";
      void this._loadIncoming();
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._busy = false;
    }
  }

  /**
   * Read every device once, so "what controls this one" can be answered.
   *
   * The API answers with the links stored *on* a device, which is the outgoing half. The
   * incoming half is every other device's outgoing half, and there is no command that
   * asks the question directly, so it is assembled here and kept for the life of the
   * view. That is one command per device, once (open item T35 asks the backend for a
   * cheaper answer).
   */
  private async _loadIncoming(): Promise<void> {
    if (!this.api || this._incomingState === "loading") {
      return;
    }
    if (this._linkIndex.length > 0 || this._incomingState === "ready") {
      this._incoming = this._linkIndex;
      return;
    }
    this._incomingState = "loading";
    const ids = this._devices
      .map((device) => device.device_id)
      .filter((id): id is string => id !== null);
    const results = await Promise.allSettled(ids.map((id) => this.api.getDevice(id)));
    const links: LinkRow[] = [];
    let failed = false;
    for (const result of results) {
      if (result.status === "fulfilled") {
        links.push(...result.value.links);
      } else {
        failed = true;
      }
    }
    this._linkIndex = links;
    this._incoming = links;
    this._incomingState = failed ? "error" : "ready";
  }

  private _isIgnored(link: LinkRow): boolean {
    // The ignored flag lives on a plan's unmanaged entries rather than on a device's links,
    // so what this view knows is what it has been told by an action it took itself.
    return this._ignored.has(link.fingerprint);
  }

  private readonly _ignored = new Set<string>();

  private async _setIgnored(link: LinkRow, ignored: boolean): Promise<void> {
    if (!this.api) {
      return;
    }
    this._busy = true;
    try {
      await this.api.setUnmanagedIgnored([link.fingerprint], ignored);
      if (ignored) {
        this._ignored.add(link.fingerprint);
      } else {
        this._ignored.delete(link.fingerprint);
      }
      this.requestUpdate();
      this._error = null;
    } catch (error) {
      this._error = describeError(this.hass, DeviceLinksApiError.from(error));
    } finally {
      this._busy = false;
    }
  }

  /**
   * Take one unmanaged link off, through the plan dialog like everything else.
   *
   * The plan opens scoped to this device with the link already ticked, so what the user
   * confirms is a plan that says exactly this one removal, and the token that authorises
   * it is the token of that plan.
   */
  private _planRemoval(link: LinkRow): void {
    const deviceId = this._detail?.device.device_id;
    this._planScope =
      deviceId === null || deviceId === undefined ? undefined : { device_ids: [deviceId] };
    this._planRemove = [link.fingerprint];
    this._planHeading = `Remove a link from ${this._detail?.device.name ?? "this device"}`;
    this._planOpen = true;
  }

  private _closePlan(): void {
    this._planOpen = false;
    this._planRemove = [];
  }

  private _afterApply(): void {
    void this._load();
    if (this._selectedId !== null) {
      void this._select(this._selectedId);
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-devices": DeviceLinksDevices;
  }
}
