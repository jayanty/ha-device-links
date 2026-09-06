/**
 * The few styles every view shares.
 *
 * Colour, spacing and typography come from Home Assistant's own CSS custom properties, so
 * the panel follows the user's theme and their dark mode without knowing anything about
 * either. Every variable has a fallback, because a theme that does not define one should
 * make the panel plainer rather than invisible.
 *
 * The classes below are the whole vocabulary of the panel: a card, a row, a chip in one
 * of five tones, a table, an empty state. They are here rather than in each view so that
 * two screens showing the same kind of thing look the same, and so that a contrast
 * problem in dark mode is fixed once.
 */

import { css } from "lit";

export const sharedStyles = css`
  :host {
    display: block;
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    font-size: 14px;
  }

  .content {
    padding: 16px;
    max-width: 1400px;
    margin: 0 auto;
    box-sizing: border-box;
  }

  .card {
    background: var(--card-background-color, #fff);
    border-radius: var(--ha-card-border-radius, 12px);
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0, 0, 0, 0.12));
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    padding: 16px;
    box-sizing: border-box;
  }

  .card + .card {
    margin-top: 16px;
  }

  h2 {
    font-size: 20px;
    font-weight: 500;
    margin: 0 0 8px;
  }

  h3 {
    font-size: 16px;
    font-weight: 500;
    margin: 0 0 8px;
  }

  h4 {
    font-size: 14px;
    font-weight: 500;
    margin: 0 0 4px;
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

  /* Layout helpers. */

  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .row.nowrap {
    flex-wrap: nowrap;
    white-space: nowrap;
  }

  .spread {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  .grow {
    flex: 1 1 200px;
    min-width: 0;
  }

  .stack {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .toolbar {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }

  .truncate {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Chips: a small piece of state, in one of five tones. */

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 10px;
    border-radius: 14px;
    font-size: 12px;
    line-height: 20px;
    white-space: nowrap;
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    background: var(--secondary-background-color, #f5f5f5);
    color: var(--primary-text-color, #212121);
  }

  .chip.ok {
    border-color: var(--success-color, #43a047);
    color: var(--success-color, #43a047);
    background: transparent;
  }

  .chip.warn {
    border-color: var(--warning-color, #ffa600);
    color: var(--warning-color, #ffa600);
    background: transparent;
  }

  .chip.error {
    border-color: var(--error-color, #db4437);
    color: var(--error-color, #db4437);
    background: transparent;
  }

  .chip.info {
    border-color: var(--info-color, #039be5);
    color: var(--info-color, #039be5);
    background: transparent;
  }

  .chip.muted {
    color: var(--secondary-text-color, #727272);
  }

  /* Buttons. Home Assistant's own when it has them, these when it does not. */

  button {
    font: inherit;
    color: var(--primary-color, #03a9f4);
    background: none;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 12px;
    cursor: pointer;
    min-height: 36px;
  }

  button:hover:not(:disabled) {
    background: var(--secondary-background-color, #f5f5f5);
  }

  button:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }

  button:disabled {
    color: var(--disabled-text-color, #bdbdbd);
    cursor: default;
  }

  button.primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }

  button.primary:hover:not(:disabled) {
    filter: brightness(1.08);
  }

  button.primary:disabled {
    background: var(--disabled-text-color, #bdbdbd);
    color: var(--card-background-color, #fff);
  }

  button.outlined {
    border-color: var(--divider-color, rgba(0, 0, 0, 0.12));
  }

  button.danger {
    color: var(--error-color, #db4437);
  }

  button.link {
    padding: 0;
    min-height: 0;
    text-decoration: underline;
  }

  /* Form controls. ha-textfield does not exist on the target frontend, so these are
     plain elements styled to sit beside Home Assistant's own. */

  input[type="text"],
  input[type="search"],
  select,
  textarea {
    font: inherit;
    color: var(--primary-text-color, #212121);
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.38));
    border-radius: 8px;
    padding: 8px 10px;
    min-height: 36px;
    box-sizing: border-box;
    max-width: 100%;
  }

  textarea {
    width: 100%;
    min-height: 160px;
    font-family: var(--code-font-family, ui-monospace, monospace);
    font-size: 13px;
  }

  input:focus-visible,
  select:focus-visible,
  textarea:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 1px;
  }

  label.field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
  }

  label.choice {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 6px 0;
    cursor: pointer;
  }

  label.choice.disabled {
    cursor: default;
    color: var(--disabled-text-color, #bdbdbd);
  }

  /* Lists and tables. Every table scrolls inside its own box rather than pushing the
     page sideways, because a rules table on a phone is wider than the phone. */

  .scroll-x {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 14px;
  }

  th {
    text-align: left;
    font-weight: 500;
    color: var(--secondary-text-color, #727272);
    padding: 8px;
    border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    white-space: nowrap;
  }

  td.actions {
    white-space: nowrap;
  }

  td {
    padding: 8px;
    border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    vertical-align: top;
  }

  tbody tr:hover td {
    background: var(--secondary-background-color, #f5f5f5);
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .list > li {
    padding: 10px 0;
    border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
  }

  .list > li:last-child {
    border-bottom: none;
  }

  .selectable {
    display: block;
    width: 100%;
    text-align: left;
    border-radius: 8px;
    padding: 8px 10px;
    border: 1px solid transparent;
    color: inherit;
  }

  .selectable[aria-current="true"] {
    background: var(--secondary-background-color, #f5f5f5);
    border-color: var(--primary-color, #03a9f4);
  }

  .empty {
    padding: 24px 8px;
    text-align: center;
    color: var(--secondary-text-color, #727272);
  }

  .unavailable {
    opacity: 0.72;
  }

  .mono {
    font-family: var(--code-font-family, ui-monospace, monospace);
    font-size: 12px;
    color: var(--secondary-text-color, #727272);
    overflow-wrap: anywhere;
  }

  .notice {
    border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
    border-left: 4px solid var(--info-color, #039be5);
    border-radius: 8px;
    padding: 10px 12px;
    background: var(--secondary-background-color, #f5f5f5);
    margin-bottom: 12px;
  }

  .notice.warn {
    border-left-color: var(--warning-color, #ffa600);
  }

  .notice.error {
    border-left-color: var(--error-color, #db4437);
  }
`;
