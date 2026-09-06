/**
 * The modal every dialog in this panel is built inside.
 *
 * Deliberately not `ha-dialog`. Open item R1 says nobody has yet confirmed that Home
 * Assistant's lazily defined elements resolve inside this panel at all, and the two
 * dialogs here are the ones a user cannot work without: the plan they confirm before a
 * write, and the editor they author a rule in. A dialog that renders as an empty inline
 * box on a frontend we did not anticipate would take the product with it, so this one is
 * built out of a div, a scrim and the theme's own custom properties. It looks like Home
 * Assistant because it uses Home Assistant's colours, and it works whatever resolved.
 *
 * What it still owes a user is dialog behaviour rather than dialog appearance: Escape
 * closes it, focus moves into it when it opens and back to whatever had it when it
 * closes, the scrim is a click target, and on a narrow screen it fills the screen rather
 * than floating in the middle of it with 8 pixels of margin.
 */

import { css, html, LitElement, nothing, type TemplateResult } from "lit";
import { customElement, property, query } from "lit/decorators.js";

@customElement("dl-dialog")
export class DeviceLinksDialog extends LitElement {
  /** Whether the dialog is on screen. Setting it to false is what closes it. */
  @property({ type: Boolean, reflect: true }) open = false;

  /** The dialog's title, which is also its accessible name. */
  @property({ type: String }) heading = "";

  /** True on a narrow screen, where the dialog fills it. */
  @property({ type: Boolean, reflect: true }) narrow = false;

  /**
   * Whether Escape and the scrim close this dialog.
   *
   * False while an apply is running: a job that is writing to devices should not be
   * dismissed by a stray click on the background, because the dialog is the only place
   * its progress and its result are shown.
   */
  @property({ type: Boolean }) dismissible = true;

  @query(".dialog") private _surface?: HTMLElement;

  private _returnFocusTo: Element | null = null;

  static override styles = css`
    :host {
      display: contents;
    }

    .scrim {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      z-index: 8;
    }

    .dialog {
      position: fixed;
      z-index: 9;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      display: flex;
      flex-direction: column;
      width: min(720px, calc(100vw - 32px));
      max-height: calc(100vh - 64px);
      box-sizing: border-box;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #212121);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.32);
      font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
      font-size: 14px;
    }

    :host([narrow]) .dialog {
      top: 0;
      left: 0;
      transform: none;
      width: 100vw;
      height: 100dvh;
      max-height: none;
      border-radius: 0;
    }

    .dialog:focus-visible {
      outline: none;
    }

    header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 16px 16px 8px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }

    h2 {
      margin: 0;
      flex: 1;
      font-size: 20px;
      font-weight: 500;
      overflow-wrap: anywhere;
    }

    .body {
      padding: 16px;
      overflow-y: auto;
      overflow-x: hidden;
      flex: 1;
    }

    footer {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      padding: 8px 16px 16px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    }

    footer:empty {
      display: none;
    }

    button.close {
      font: inherit;
      color: inherit;
      background: none;
      border: none;
      border-radius: 50%;
      width: 36px;
      height: 36px;
      cursor: pointer;
      font-size: 18px;
      line-height: 1;
    }

    button.close:hover {
      background: var(--secondary-background-color, #f5f5f5);
    }

    button.close:focus-visible {
      outline: 2px solid var(--primary-color, #03a9f4);
      outline-offset: 2px;
    }
  `;

  override connectedCallback(): void {
    super.connectedCallback();
    // On the document rather than on the host: the host renders into a shadow root and
    // the focused element inside it does not bubble a keydown out to the panel, while a
    // click on the scrim of a dialog that has not been focused yet reaches neither.
    document.addEventListener("keydown", this._onKeyDown);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    document.removeEventListener("keydown", this._onKeyDown);
  }

  protected override updated(changed: Map<string, unknown>): void {
    if (!changed.has("open")) {
      return;
    }
    if (this.open) {
      this._returnFocusTo = document.activeElement;
      this._surface?.focus();
    } else if (this._returnFocusTo instanceof HTMLElement) {
      this._returnFocusTo.focus();
      this._returnFocusTo = null;
    }
  }

  protected override render(): TemplateResult | typeof nothing {
    if (!this.open) {
      return nothing;
    }
    return html`
      <div class="scrim" @click=${this._onScrim}></div>
      <div class="dialog" role="dialog" aria-modal="true" aria-label=${this.heading} tabindex="-1">
        <header>
          <h2>${this.heading}</h2>
          ${
            this.dismissible
              ? html`<button
                class="close"
                type="button"
                aria-label="Close"
                title="Close"
                @click=${this._close}
              >
                &#10005;
              </button>`
              : nothing
          }
        </header>
        <div class="body"><slot></slot></div>
        <footer><slot name="actions"></slot></footer>
      </div>
    `;
  }

  private readonly _onKeyDown = (event: KeyboardEvent): void => {
    if (this.open && this.dismissible && event.key === "Escape") {
      event.stopPropagation();
      this._close();
    }
  };

  private _onScrim(): void {
    if (this.dismissible) {
      this._close();
    }
  }

  /**
   * Ask to be closed.
   *
   * The dialog does not close itself: it tells its owner, which owns whether it is open
   * and often has to do something else first (drop the plan it was showing, stop
   * following a job). One owner of one piece of state is what stops a dialog reopening
   * itself on the next render.
   */
  private _close(): void {
    this.dispatchEvent(new CustomEvent("dl-dialog-closed", { bubbles: true, composed: true }));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dl-dialog": DeviceLinksDialog;
  }
}
