/**
 * A `hass` that records what was sent to it.
 *
 * Nothing in these tests reaches a Home Assistant. What is worth proving is that each
 * wrapper sends the command the backend registers, with the payload that command's schema
 * accepts, and reads the field the handler answers with. All three are visible from here.
 */

import type { HomeAssistant } from "../src/hass";

export interface SentMessage {
  type: string;
  [key: string]: unknown;
}

export interface MockHass extends HomeAssistant {
  sent: SentMessage[];
  subscriptions: SentMessage[];
  /** What the next `sendMessagePromise` resolves with, by command type. */
  results: Map<string, unknown>;
  /** What the next `sendMessagePromise` rejects with, by command type. */
  failures: Map<string, unknown>;
  /** Push an event into every live `jobs/subscribe` callback. */
  emit(event: unknown): void;
  /** How many subscriptions have been torn down. */
  unsubscribes: number;
  /** Resolve the pending subscribe promises, for the tests about that race. */
  settleSubscribe(): Promise<void>;
}

export interface MockOptions {
  /** Hold the subscribe promise open until `settleSubscribe` is called. */
  deferSubscribe?: boolean;
  /** Reject the subscribe promise instead of resolving it. */
  subscribeFails?: unknown;
  /** Translation resources, keyed exactly as `hass.localize` is called. */
  translations?: Record<string, string>;
}

export function mockHass(options: MockOptions = {}): MockHass {
  const listeners = new Set<(event: unknown) => void>();
  let releaseSubscribe: (() => void) | undefined;

  const hass: MockHass = {
    sent: [],
    subscriptions: [],
    results: new Map(),
    failures: new Map(),
    unsubscribes: 0,
    language: "en",
    themes: { darkMode: false },
    user: { id: "u1", name: "Jayant", is_admin: true },
    localize(key: string, values?: Record<string, string | number>): string {
      const text = options.translations?.[key];
      if (text === undefined) {
        return "";
      }
      return text.replace(/\{(\w+)\}/g, (whole, name: string) => {
        const value = values?.[name];
        return value === undefined ? whole : String(value);
      });
    },
    emit(event: unknown): void {
      for (const listener of listeners) {
        listener(event);
      }
    },
    async settleSubscribe(): Promise<void> {
      releaseSubscribe?.();
      await Promise.resolve();
      await Promise.resolve();
    },
    connection: {
      async sendMessagePromise<T>(message: Record<string, unknown>): Promise<T> {
        const sent = message as SentMessage;
        hass.sent.push(sent);
        if (hass.failures.has(sent.type)) {
          throw hass.failures.get(sent.type);
        }
        return (hass.results.get(sent.type) ?? {}) as T;
      },
      async subscribeMessage<T>(
        callback: (event: T) => void,
        message: Record<string, unknown>,
      ): Promise<() => void> {
        hass.subscriptions.push(message as SentMessage);
        const listener = (event: unknown) => callback(event as T);
        if (options.subscribeFails !== undefined) {
          throw options.subscribeFails;
        }
        if (options.deferSubscribe) {
          await new Promise<void>((resolve) => {
            releaseSubscribe = resolve;
          });
        }
        listeners.add(listener);
        return () => {
          hass.unsubscribes += 1;
          listeners.delete(listener);
        };
      },
    },
  };
  return hass;
}
