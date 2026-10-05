import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // verification-record/ holds COPIES of test files from several projects,
    // published as a record of what was run and when. They are evidence, not
    // this package's suite: they import paths that do not exist here, so
    // collecting them turns a green suite red for no reason.
    //
    // Excluded rather than renamed, so the copies stay byte-comparable with
    // the originals they are a record of.
    exclude: ["node_modules/**", "dist/**", "verification-record/**"],
  },
});
