/**
 * The few styles every view shares.
 *
 * Colour, spacing and typography come from Home Assistant's own CSS custom properties, so
 * the panel follows the user's theme and their dark mode without knowing anything about
 * either. Every variable has a fallback, because a theme that does not define one should
 * make the panel plainer rather than invisible.
 */

import { css } from "lit";

export const sharedStyles = css`
  :host {
    display: block;
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
  }

  .content {
    padding: 16px;
    max-width: 1400px;
    margin: 0 auto;
  }

  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0, 0, 0, 0.12));
    padding: 16px;
  }

  h2 {
    font-size: 20px;
    font-weight: 500;
    margin: 0 0 8px;
  }

  p {
    margin: 0 0 8px;
    line-height: 1.5;
  }

  .secondary {
    color: var(--secondary-text-color, #727272);
  }

  a {
    color: var(--primary-color, #03a9f4);
  }
`;
