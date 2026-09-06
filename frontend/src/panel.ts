/**
 * The Device Links panel: the element Home Assistant loads, and the shell every view
 * lives inside.
 *
 * Home Assistant sets four properties on a custom panel: `hass`, `narrow`, `route` and
 * `panel`. This element turns the third into a tab, hands the first to whichever view that
 * tab names, and owns the two things no view should have to own.
 *
 * **One API client, closed when the panel goes.** Every view shares it, so there is one
 * place that knows what is subscribed, and `disconnectedCallback` ends all of it. A panel
 * is a page somebody leaves open for hours; a subscription that outlives it fires into
 * detached components until the tab is closed.
 *
 * **One component load, before anything renders with them.** Home Assistant's elements are
 * defined lazily and a custom panel is loaded on its own, so they have to be pulled in
 * (see `ha-components.ts`). Until that finishes the panel shows a loading line, and
 * whatever does not resolve is rendered as a plain element rather than as nothing.
 *
 * **The version handshake (E33).** The bundle knows the version it was built from and the
 * backend puts its own in the panel config, so an integration updated underneath an open
 * tab produces a banner asking for a reload rather than an error that reads like a broken
 * configuration.
 */

import { css, html, LitElement, nothing, type TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { html as staticHtml, unsafeStatic } from "lit/static-html.js";

import { DeviceLinksApi } from "./api";
import "./components/two-pane";
import { type ComponentSet, loadHaComponents } from "./ha-components";
import type { HomeAssistant, PanelInfo, Route } from "./hass";
import { TABS, tabFromPath } from "./tabs";
import "./views/activity";
import "./views/devices";
import "./views/overview";
import "./views/profiles";
import "./views/rules";

/** The version this bundle was built from, substituted by vite from `manifest.json`. */
export const BUNDLE_VERSION = __DL_BUNDLE_VERSION__;

@customElement("device-links-panel")
export class DeviceLinksPanel extends LitElement {
  @property({ attribute: false }) hass!: HomeAssistant;

  @property({ type: Boolean, reflect: true }) narrow = false;

  @property({ attribute: false }) route?: Route;

  @property({ attribute: false }) panel?: PanelInfo;

  /**
   * How the shell gets its Home Assistant components.
   *
   * A property rather than a direct call so the static harness and the unit tests can
   * mount the panel with a known set, outside a Home Assistant where none of the elements
   * would ever resolve and every one of them would wait out its timeout. Home Assistant
   * never sets it, so the default is what runs for a user.
   */
  @property({ attribute: false }) componentLoader: () => Promise<ComponentSet> = () =>
    loadHaComponents();

  @state() private _components: ComponentSet | null = null;

  /**
   * What the tab being opened should select, when another view asked for it.
   *
   * Held here rather than in the URL because it is a hand-off between two views rather
   * than an address: a rule id in the path would be a link somebody could bookmark, and
   * it would then have to survive that rule being deleted. It is cleared as soon as the
   * receiving view has been given it once, so going back to a tab by hand opens it plain.
   */
  @state() private _selected: string | null = null;

  private _api: DeviceLinksApi | null = null;

  static override styles = css`
    :host {
      display: block;
      height: 100%;
      background: var(--primary-background-color, #fafafa);
      color: var(--primary-text-color, #212121);
      font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    }

    .plain-bar {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 16px;
      background: var(--app-header-background-color, var(--primary-color, #03a9f4));
      color: var(--app-header-text-color, #fff);
      font-size: 20px;
    }

    .plain-tabs {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
      padding: 8px 16px;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }

    .plain-tabs button {
      font: inherit;
      color: inherit;
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      padding: 8px 12px;
      cursor: pointer;
    }

    .plain-tabs button[aria-current="page"] {
      border-bottom-color: var(--primary-color, #03a9f4);
      font-weight: 500;
    }

    .plain-tabs button:focus-visible {
      outline: 2px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
    }

    .banner {
      margin: 16px;
    }

    .banner-plain {
      margin: 16px;
      padding: 12px 16px;
      border-radius: 8px;
      border: 1px solid var(--warning-color, #ffa600);
      background: var(--card-background-color, #fff);
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }

    .loading {
      padding: 32px 16px;
      text-align: center;
      color: var(--secondary-text-color, #727272);
    }

    .view {
      display: block;
    }
  `;

  /** The current tab, taken from the URL Home Assistant gave us. */
  get tab(): string {
    return tabFromPath(this.route?.path);
  }

  /** The one API client, built when `hass` first arrives and shared with every view. */
  get api(): DeviceLinksApi | null {
    return this._api;
  }

  override connectedCallback(): void {
    super.connectedCallback();
    void this._loadComponents();
    // Rebuilt here as well as in `willUpdate`, because a panel that is detached and
    // re-attached (moved in the DOM rather than recreated) comes back with the same
    // `hass` it had, so no property change would rebuild the client `disconnectedCallback`
    // closed, and every view would be handed a null one.
    this._openClient();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    // Everything subscribed through the shared client ends here. A job subscription that
    // outlived the panel would keep firing into views that are no longer in the document.
    this._api?.close();
    this._api = null;
  }

  protected override willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("hass")) {
      this._openClient();
    }
  }

  /** Build the shared client, or point the one that exists at the current `hass`. */
  private _openClient(): void {
    if (!this.hass) {
      return;
    }
    if (this._api === null) {
      this._api = new DeviceLinksApi(this.hass);
    } else {
      this._api.hass = this.hass;
    }
  }

  private async _loadComponents(): Promise<void> {
    if (this._components === null) {
      this._components = await this.componentLoader();
    }
  }

  protected override render(): TemplateResult {
    return html`
      ${this._renderBar()}
      ${this._renderVersionBanner()}
      ${
        this._components === null
          ? html`<div class="loading">Loading Home Assistant components</div>`
          : this._renderView()
      }
    `;
  }

  // ------------------------------------------------------------------------------------
  // The bar and the tabs, with a plain fallback for a frontend that has neither.
  // ------------------------------------------------------------------------------------

  private _renderBar(): TemplateResult {
    const components = this._components;
    if (!components?.has("ha-top-app-bar-fixed")) {
      return html`
        <header class="plain-bar">
          <span>Device Links</span>
        </header>
        ${this._renderTabs()}
      `;
    }
    return html`
      <ha-top-app-bar-fixed>
        ${
          components.has("ha-menu-button")
            ? html`<ha-menu-button
              slot="navigationIcon"
              .hass=${this.hass}
              .narrow=${this.narrow}
            ></ha-menu-button>`
            : nothing
        }
        <div slot="title">Device Links</div>
        ${this._renderTabs()}
      </ha-top-app-bar-fixed>
    `;
  }

  private _renderTabs(): TemplateResult {
    const components = this._components;
    // The strip needs both elements to work as one. With either missing, a plain nav of
    // buttons is the honest substitute: it looks unlike Home Assistant and it navigates,
    // which is the right way round.
    if (!components?.has("ha-tab-group") || !components.has("ha-tab-group-tab")) {
      return html`
        <nav class="plain-tabs" aria-label="Device Links sections">
          ${TABS.map(
            (tab) => html`
              <button
                type="button"
                aria-current=${tab.id === this.tab ? "page" : "false"}
                @click=${() => this._selectTab(tab.id)}
              >
                ${tab.label}
              </button>
            `,
          )}
        </nav>
      `;
    }
    return html`
      <ha-tab-group slot="tabs" aria-label="Device Links sections">
        ${TABS.map(
          (tab) => html`
            <ha-tab-group-tab
              slot="nav"
              panel=${tab.id}
              .active=${tab.id === this.tab}
              @click=${() => this._selectTab(tab.id)}
            >
              ${
                this.narrow && components.has("ha-icon")
                  ? html`<ha-icon .icon=${tab.icon} aria-label=${tab.label}></ha-icon>`
                  : tab.label
              }
            </ha-tab-group-tab>
          `,
        )}
      </ha-tab-group>
    `;
  }

  /**
   * Navigate to a tab.
   *
   * Home Assistant's router owns the address bar, so the way to move inside a panel is to
   * push the URL and tell it that the location changed. It answers by setting `route`
   * back on this element, which is what actually changes the tab.
   */
  private _selectTab(id: string, select: string | null = null): void {
    this._selected = select;
    if (id === this.tab) {
      return;
    }
    const prefix = this.route?.prefix ?? "/device_links";
    history.pushState(null, "", `${prefix}/${id}`);
    this.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
    // Set locally as well, rather than waiting to be told. Home Assistant's router answers
    // a location change by setting `route` back to exactly this, so nothing is being
    // second-guessed; what this avoids is a tab strip that does not move in whatever
    // context the router does not answer, which would look like a dead control.
    this.route = { prefix, path: `/${id}` };
  }

  // ------------------------------------------------------------------------------------
  // The version handshake (E33).
  // ------------------------------------------------------------------------------------

  /**
   * The backend version, or null when this frontend did not send one.
   *
   * Null is the normal answer on an older backend rather than a fault, and it produces no
   * banner: a handshake that fails open is right here, because the cost of a false banner
   * is telling somebody to reload a page that is already correct.
   */
  get backendVersion(): string | null {
    const version = this.panel?.config?.version;
    return typeof version === "string" && version ? version : null;
  }

  /** True when the running integration is not the one this bundle was built from. */
  get versionMismatch(): boolean {
    const backend = this.backendVersion;
    return backend !== null && backend !== BUNDLE_VERSION;
  }

  private _renderVersionBanner(): TemplateResult | typeof nothing {
    if (!this.versionMismatch) {
      return nothing;
    }
    const message = `Device Links was updated to ${this.backendVersion} while this page was open. This panel is still running version ${BUNDLE_VERSION}. Reload the page to pick up the new one.`;
    if (this._components?.has("ha-alert")) {
      return html`
        <ha-alert class="banner" alert-type="info" title="A newer version is installed">
          ${message}
          <button type="button" slot="action" @click=${() => this._reload()}>Reload</button>
        </ha-alert>
      `;
    }
    return html`
      <div class="banner-plain" role="status">
        <span>${message}</span>
        <button type="button" @click=${() => this._reload()}>Reload</button>
      </div>
    `;
  }

  /** Overridable so a test can assert the button without navigating the test runner. */
  protected _reload(): void {
    location.reload();
  }

  // ------------------------------------------------------------------------------------
  // The content area.
  // ------------------------------------------------------------------------------------

  private _renderView(): TemplateResult {
    const definition = TABS.find((tab) => tab.id === this.tab) ?? TABS[0];
    if (!definition) {
      return html`<div class="loading">No view is registered.</div>`;
    }
    return staticHtml`
      <${unsafeStatic(definition.tagName)}
        class="view"
        .hass=${this.hass}
        .api=${this._api}
        .components=${this._components}
        .narrow=${this.narrow}
        .selected=${this._selected}
        @dl-navigate=${this._onNavigate}
      ></${unsafeStatic(definition.tagName)}>
    `;
  }

  /**
   * Follow a view's request to open something in another tab.
   *
   * The Overview's "Needs attention" rows are only worth having if they lead to the thing
   * that fixes them, and the Activity view's job rows lead back to the devices a job
   * touched. Both go through here so that the shell stays the only thing that knows what
   * a tab is.
   */
  private _onNavigate(event: Event): void {
    const detail = (event as CustomEvent<{ tab: string; select?: string }>).detail;
    if (!detail?.tab) {
      return;
    }
    this._selectTab(detail.tab, detail.select ?? null);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "device-links-panel": DeviceLinksPanel;
  }
}
