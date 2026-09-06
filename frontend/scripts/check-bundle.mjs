/**
 * Assert that the committed bundle is what this source builds.
 *
 * The bundle is committed (PRD Section 16 and CLAUDE.md Section 4) because a HACS install
 * has no build step: whatever is in `custom_components/device_links/frontend/` is what
 * every user runs. So the one thing that must never happen is source and bundle drifting
 * apart, and the only way to know is to build and compare.
 *
 * It compares bytes, not a normalised form. There is nothing to normalise: `vite.config.ts`
 * reads no clock, no environment and no absolute path, so the output is a pure function of
 * the repository and the pinned toolchain in `package-lock.json`. If this check ever starts
 * failing for a reason that is not a real change, that is worth finding rather than
 * papering over, because a check people learn to force past is worse than no check.
 *
 * Run through `npm run check:bundle`. CI runs the build and then asserts the working tree
 * is clean, which catches the same drift and also catches a file the build stopped writing.
 */

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "..");
const bundle = resolve(
  frontend,
  "../custom_components/device_links/frontend/device-links-panel.js",
);

const digest = (path) =>
  existsSync(path) ? createHash("sha256").update(readFileSync(path)).digest("hex") : null;

const committed = digest(bundle);
if (committed === null) {
  console.error(`No committed bundle at ${bundle}. Run "npm run build" and commit the result.`);
  process.exit(1);
}

const build = spawnSync("npx", ["vite", "build"], { cwd: frontend, stdio: "inherit" });
if (build.status !== 0) {
  process.exit(build.status ?? 1);
}

const fresh = digest(bundle);
if (fresh !== committed) {
  console.error("");
  console.error("The committed bundle does not match a fresh build.");
  console.error(`  committed: sha256 ${committed}`);
  console.error(`  rebuilt:   sha256 ${fresh}`);
  console.error("");
  console.error("The fresh build is now in the working tree. Commit it with the source change.");
  process.exit(1);
}

console.error(`The committed bundle matches a fresh build (sha256 ${fresh}).`);
