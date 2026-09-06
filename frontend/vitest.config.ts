/**
 * The test run, which sees the same compile-time constants the bundle does.
 *
 * Separate from `vite.config.ts` so nothing a test needs (a DOM, a reporter) can change
 * the bytes that get committed. `define` is repeated here rather than shared through the
 * build config for the same reason, from the one function that produces it.
 */

import { defineConfig } from "vitest/config";

import { buildDefines } from "./build-defines.ts";

export default defineConfig({
  define: buildDefines(),
  test: {
    environment: "happy-dom",
    include: ["test/**/*.test.ts"],
    restoreMocks: true,
  },
});
