/**
 * How the panel becomes one file.
 *
 * Three properties matter more than anything else here.
 *
 * **One ES module, no code splitting.** Home Assistant loads a custom panel by importing
 * exactly one URL. A second chunk would 404 rather than load, because nothing registers a
 * static path for it, and the panel would fail at the moment somebody opened it.
 *
 * **Nothing comes from a network.** `lit` is bundled in, and there is no `external` list
 * on purpose: an import left external would be resolved by the browser against a URL that
 * does not exist on an instance with no internet access, which is the premise this whole
 * integration is built on.
 *
 * **The output is a pure function of the repository.** No timestamp, no build id, no
 * environment variable, no absolute path: the same commit built on two machines produces
 * the same bytes, so CI can assert that the committed bundle matches a fresh build and
 * mean it.
 */

import { defineConfig } from "vite";

import { buildDefines, bundleDir, bundleName } from "./build-defines.ts";

export default defineConfig({
  define: buildDefines(),
  build: {
    target: "es2022",
    outDir: bundleDir,
    emptyOutDir: true,
    sourcemap: false,
    minify: "oxc",
    cssCodeSplit: false,
    // Reading the gzip size costs time and tells us nothing a check can act on.
    reportCompressedSize: false,
    lib: {
      entry: "src/panel.ts",
      formats: ["es"],
      fileName: () => bundleName,
    },
    rollupOptions: {
      output: {
        // Belt and braces with `formats: ["es"]` above: a dynamic import that crept in
        // would otherwise become a second chunk nobody serves.
        codeSplitting: false,
        entryFileNames: bundleName,
      },
    },
  },
});
