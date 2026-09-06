/**
 * Stand-ins for the Home Assistant elements the shell renders, for the harness only.
 *
 * Nothing in `src/` imports this. The panel asks `ha-components.ts` which elements
 * resolved and branches on the answer, so outside a Home Assistant every branch would take
 * the plain fallback and the version a user actually sees would never be looked at. These
 * define just enough of each element for the shell's Home Assistant branch to render: a
 * fixed app bar, a tab strip, an icon, an alert.
 *
 * They are stand-ins and they prove nothing about the real ones. Open item R1 is closed by
 * a deploy and a restart, not by this file.
 */

class HaTopAppBar extends HTMLElement {
  connectedCallback(): void {
    if (this.shadowRoot) {
      return;
    }
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: block; }
        header {
          display: flex; align-items: center; gap: 12px;
          padding: 12px 16px; min-height: 40px;
          background: var(--app-header-background-color, var(--primary-color, #03a9f4));
          color: var(--app-header-text-color, #fff);
          font-size: 20px;
        }
        .tabs { border-bottom: 1px solid var(--divider-color, #e0e0e0); background: var(--card-background-color, #fff); }
      </style>
      <header><slot name="navigationIcon"></slot><slot name="title"></slot></header>
      <div class="tabs"><slot name="tabs"></slot></div>
      <slot></slot>
    `;
  }
}

class HaMenuButton extends HTMLElement {
  connectedCallback(): void {
    this.textContent = "☰";
    this.style.cursor = "pointer";
  }
}

class HaTabGroup extends HTMLElement {
  connectedCallback(): void {
    if (this.shadowRoot) {
      return;
    }
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: flex; gap: 4px; padding: 0 8px; overflow-x: auto; }
      </style>
      <slot name="nav"></slot>
    `;
  }
}

class HaTabGroupTab extends HTMLElement {
  static observedAttributes = ["active"];

  connectedCallback(): void {
    this.setAttribute("role", "tab");
    this.style.cssText =
      "display: inline-flex; align-items: center; padding: 12px 16px; cursor: pointer; white-space: nowrap; border-bottom: 2px solid transparent; color: var(--primary-text-color, #212121);";
    this._paint();
  }

  set active(value: boolean) {
    this.toggleAttribute("active", value);
    this._paint();
  }

  private _paint(): void {
    const active = this.hasAttribute("active");
    this.style.borderBottomColor = active ? "var(--primary-color, #03a9f4)" : "transparent";
    this.style.color = active
      ? "var(--primary-color, #03a9f4)"
      : "var(--secondary-text-color, #727272)";
  }
}

/**
 * An icon, drawn as a dot.
 *
 * The real one renders an MDI path. What the panel needs to be looked at for is whether
 * an icon beside a chip's text throws the layout out, and a dot of the right size answers
 * that without shipping an icon font into a harness.
 */
class HaIcon extends HTMLElement {
  set icon(value: string) {
    this.title = value;
    this.textContent = "●";
  }

  connectedCallback(): void {
    this.style.cssText = "display: inline-block; width: 16px; font-size: 10px; line-height: 16px;";
  }
}

class HaAlert extends HTMLElement {
  connectedCallback(): void {
    this.style.cssText =
      "display: block; padding: 12px 16px; border-radius: 8px; border: 1px solid var(--info-color, #039be5); background: var(--card-background-color, #fff);";
  }
}

export function defineHaStubs(): void {
  const stubs: [string, CustomElementConstructor][] = [
    ["ha-top-app-bar-fixed", HaTopAppBar],
    ["ha-menu-button", HaMenuButton],
    ["ha-tab-group", HaTabGroup],
    ["ha-tab-group-tab", HaTabGroupTab],
    ["ha-icon", HaIcon],
    ["ha-alert", HaAlert],
  ];
  for (const [tag, element] of stubs) {
    if (!customElements.get(tag)) {
      customElements.define(tag, element);
    }
  }
}
