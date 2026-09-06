/**
 * Mount the panel outside Home Assistant, so somebody can look at it.
 *
 * Everything before this task was proved with assertions, and an assertion cannot see that
 * a table pushes the page sideways on a phone, that a chip's text is unreadable on the dark
 * theme's card colour, or that a dialog is taller than the screen it opens on. This page
 * exists to be looked at, in both themes and at both widths, with the plan dialog and the
 * rule editor open.
 *
 * The theme variables below are the subset of Home Assistant's own that the panel reads,
 * with the values its default light and dark themes use. That is the whole coupling: the
 * panel never names a colour, so setting these is the same act as a user picking a theme.
 */

import { componentSet, HA_COMPONENTS } from "../src/ha-components";
import type { HomeAssistant } from "../src/hass";
import { BUNDLE_VERSION, type DeviceLinksPanel } from "../src/panel";
import "../src/panel";
import { HarnessBackend } from "./backend";
import { defineHaStubs } from "./ha-stubs";

const backend = new HarnessBackend();

const hass: HomeAssistant = {
  connection: {
    sendMessagePromise<T>(message: Record<string, unknown>): Promise<T> {
      return backend.send(message) as Promise<T>;
    },
    async subscribeMessage<T>(callback: (event: T) => void): Promise<() => void> {
      return backend.subscribe(callback as (event: unknown) => void);
    },
  },
  language: "en",
  localize: () => "",
  themes: { darkMode: false },
  user: { id: "u1", name: "Jayant", is_admin: true },
};

/** Where this page lives, so the panel's own navigation can be put back after it. */
const HARNESS_PATH = "/harness/index.html";

const stage = document.querySelector("#stage");

/** Which Home Assistant elements this mount should pretend resolved. */
let withHaComponents = true;

/** Whether to pretend the integration was updated under this page (E33). */
let staleBackend = false;

let narrow = false;

let panel = document.createElement("device-links-panel") as DeviceLinksPanel;

/**
 * Build a fresh panel and put it on the page.
 *
 * A new element each time rather than a reused one, because the shell loads its Home
 * Assistant components once per element and keeps the answer. Toggling the components
 * control on the element that already has an answer would change nothing, and the point
 * of that control is to look at the fallback rendering.
 */
function mount(): void {
  if (!(stage instanceof HTMLElement)) {
    return;
  }
  defineHaStubs();
  panel = document.createElement("device-links-panel") as DeviceLinksPanel;
  panel.componentLoader = () =>
    Promise.resolve(componentSet(withHaComponents ? [...HA_COMPONENTS] : []));
  panel.hass = hass;
  panel.narrow = narrow;
  panel.route = { prefix: "/device_links", path: `/${location.hash.slice(1) || "overview"}` };
  // The version the running backend reports. Matching the bundle keeps the E33 banner off
  // the screen; the third control flips it so the banner itself can be looked at.
  panel.panel = { config: { version: staleBackend ? "99.0.0" : BUNDLE_VERSION } };
  stage.replaceChildren(panel);
}

function setTheme(dark: boolean): void {
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  hass.themes.darkMode = dark;
  panel.hass = { ...hass };
}

function setNarrow(isNarrow: boolean): void {
  narrow = isNarrow;
  if (stage instanceof HTMLElement) {
    stage.classList.toggle("narrow", isNarrow);
  }
  panel.narrow = isNarrow;
}

/** One toolbar toggle, which relabels itself so the page says which state it is in. */
function toggle(
  label: (on: boolean) => string,
  onChange: (on: boolean) => void,
): HTMLButtonElement {
  const button = document.createElement("button");
  let on = false;
  button.type = "button";
  button.textContent = label(on);
  button.addEventListener("click", () => {
    on = !on;
    button.textContent = label(on);
    onChange(on);
  });
  return button;
}

const bar = document.querySelector("#controls");
if (bar instanceof HTMLElement) {
  bar.append(
    toggle(
      (on) => `Theme: ${on ? "dark" : "light"}`,
      (on) => setTheme(on),
    ),
    toggle(
      (on) => `Width: ${on ? "narrow" : "desktop"}`,
      (on) => setNarrow(on),
    ),
    toggle(
      (on) => `Version banner: ${on ? "on" : "off"}`,
      (on) => {
        staleBackend = on;
        mount();
      },
    ),
    toggle(
      (on) => `Home Assistant components: ${on ? "off" : "on"}`,
      (on) => {
        withHaComponents = !on;
        mount();
      },
    ),
  );
}

/**
 * Keep the address bar on the harness page.
 *
 * The panel navigates the way it does inside Home Assistant: it pushes
 * `/device_links/<tab>` and announces it. There is no such path on a dev server, so a
 * reload after clicking a tab would land on a blank page. The tab is taken out of the URL
 * the panel pushed, the address is put back to this page with the tab in the fragment, and
 * the panel is told the route it asked for.
 */
window.addEventListener("location-changed", () => {
  const tab = location.pathname.split("/").filter(Boolean).pop() ?? "overview";
  history.replaceState(null, "", `${HARNESS_PATH}#${tab}`);
  panel.route = { prefix: "/device_links", path: `/${tab}` };
});

mount();
setTheme(false);
