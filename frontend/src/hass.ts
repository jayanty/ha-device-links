/**
 * The bit of Home Assistant the panel actually touches, described structurally.
 *
 * Deliberately not a dependency on `home-assistant-js-websocket` or on
 * `custom-card-helpers`. Both would be bundled in for a handful of type signatures, both
 * carry their own idea of what `HomeAssistant` is, and both go stale against the running
 * frontend rather than against the version they were published for. What the panel needs
 * is small enough to write down, and writing it down is also the list of everything the
 * panel is coupled to, which is worth being able to read on one screen.
 *
 * The object itself is the real one Home Assistant sets on the panel element. Nothing
 * here constructs one.
 */

/** The error payload Home Assistant sends when a command handler raises. */
export interface HassErrorPayload {
  code: string;
  message: string;
  translation_key?: string | null;
  translation_domain?: string | null;
  translation_placeholders?: Record<string, string> | null;
}

/** What `hass.connection` offers, which is the panel's only route to the backend. */
export interface HassConnection {
  sendMessagePromise<T>(message: Record<string, unknown>): Promise<T>;
  subscribeMessage<T>(
    callback: (event: T) => void,
    message: Record<string, unknown>,
  ): Promise<() => void | Promise<void>>;
}

/** The signed-in user, which the panel reads only to say who it is refusing. */
export interface HassUser {
  id: string;
  name: string;
  is_admin: boolean;
}

/** Theme state, which decides nothing here beyond what a chart or an icon picks. */
export interface HassThemes {
  darkMode: boolean;
}

/**
 * The Home Assistant object handed to a custom panel.
 *
 * `localize` returns an empty string for a key it has no resource for, which is why
 * every call site has a fallback rather than trusting it.
 */
export interface HomeAssistant {
  connection: HassConnection;
  language: string;
  localize(key: string, values?: Record<string, string | number>): string;
  themes: HassThemes;
  user?: HassUser;
}

/**
 * The `panel` property Home Assistant sets alongside `hass`.
 *
 * `config` is what `panel.py` passed to `panel_custom.async_register_panel`, which is how
 * the running backend tells the panel its own version without the panel inventing a
 * command to ask (E33).
 */
export interface PanelInfo {
  config?: PanelConfig | null;
  title?: string | null;
  url_path?: string;
}

/** What `panel.py` puts in the panel's config. Keep this in step with that file. */
export interface PanelConfig {
  /** The integration's manifest version, as the running backend reports it. */
  version?: string | null;
  /** The path segment the bundle is served under, version and deployment included. */
  cache_key?: string | null;
  /** The URL the running backend serves the bundle from. */
  bundle_url?: string | null;
}

/** The route Home Assistant sets on a panel, which the shell turns into a tab. */
export interface Route {
  prefix: string;
  path: string;
}
