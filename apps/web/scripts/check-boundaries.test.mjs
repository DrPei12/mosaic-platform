import { afterEach, describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { scanBoundaries } from "./check-boundaries.mjs";

const temporaryRoots = [];

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function fixture(files = {}) {
  const root = mkdtempSync(join(tmpdir(), "mosaic-boundaries-"));
  temporaryRoots.push(root);

  for (const relativePath of [
    "src/app",
    "src/features",
    "src/shared/ui",
    "src/shared/layout",
  ]) {
    mkdirSync(join(root, relativePath), { recursive: true });
  }
  for (const [relativePath, contents] of Object.entries(files)) {
    const path = join(root, relativePath);
    mkdirSync(join(path, ".."), { recursive: true });
    writeFileSync(path, contents, "utf8");
  }
  return root;
}

describe("check-boundaries scanner", () => {
  it("detects imports, exports, dynamic imports, require, and fetch calls", () => {
    const root = fixture({
      "src/app/import.ts": 'import { create } from "@/services/demo-auth-service";',
      "src/app/export.ts": 'export { health } from "../services/api-health-service";',
      "src/app/nested/dynamic.ts": 'const service = import("@/services/demo-health-service");',
      "src/app/require.ts": 'const service = require("../services/api-auth-service");',
      "src/app/fetch.ts": 'const result = fetch("/api/v1/health/ready");',
      "src/app/alias.ts":
        'const alias = fetch; let target; target = fetch; const pass = (value) => value; pass(fetch);',
      "src/app/global-alias.ts": "const alias = globalThis.fetch; const browser = window.fetch;",
      "src/app/element-alias.ts":
        'const request = globalThis["fetch"]; request("/health"); const browserRequest = window[\'fetch\']; browserRequest("/health");',
    });

    const result = scanBoundaries({ projectRoot: root });

    assert.equal(result.violations.length, 8);
    assert.deepEqual(
      result.violations.map((path) => basename(path)).sort(),
      [
        "alias.ts",
        "dynamic.ts",
        "element-alias.ts",
        "export.ts",
        "fetch.ts",
        "global-alias.ts",
        "import.ts",
        "require.ts",
      ],
    );
  });

  it("does not inspect skipped generated or dependency directories", () => {
    const root = fixture({
      "src/app/clean.ts": '// fetch("/comment-only");\nconst text = "fetch(\\\"/not-a-call\\\")";',
      "src/app/export-local.ts": "const local = 1; export { local };",
      "src/app/node_modules/dependency.ts": 'fetch("/ignored");',
      "src/app/.next/generated.ts": 'fetch("/ignored");',
      "src/app/dist/generated.ts": 'fetch("/ignored");',
    });

    const result = scanBoundaries({ projectRoot: root });

    assert.deepEqual(result.violations, []);
    assert.deepEqual(result.sourceFiles.map((path) => basename(path)), ["clean.ts", "export-local.ts"]);
  });

  it("forbids every consumer root from importing demo scenario or state directly", () => {
    const root = fixture({
      "src/features/scenario.ts":
        'import { DEMO_SCENARIO } from "@/shared/demo/demo-scenario";',
      "src/features/store.ts":
        'const store = require("../shared/demo/demo-state-store");',
      "src/features/dynamic.ts":
        'const store = import("@/shared/demo/demo-state-store");',
      "src/features/clean.ts": "export const feature = true;",
      "src/app/scenario.ts":
        'export { DEMO_SCENARIO } from "../shared/demo/demo-scenario";',
      "src/shared/ui/store.ts":
        'const store = require("@/shared/demo/demo-state-store");',
      "src/shared/layout/dynamic.ts":
        'const scenario = import("@/shared/demo/demo-scenario");',
    });

    const result = scanBoundaries({ projectRoot: root });

    assert.deepEqual(
      result.violations.map((path) => basename(path)).sort(),
      [
        "dynamic.ts",
        "dynamic.ts",
        "scenario.ts",
        "scenario.ts",
        "store.ts",
        "store.ts",
      ],
    );
  });

  it("returns deterministic paths and fails when an expected root is absent", () => {
    const root = fixture({
      "src/app/z.ts": "export const z = 1;",
      "src/app/a.ts": "export const a = 1;",
    });

    const first = scanBoundaries({ projectRoot: root });
    const second = scanBoundaries({ projectRoot: root });

    assert.deepEqual(first, second);
    assert.deepEqual(first.sourceFiles.map((path) => basename(path)), ["a.ts", "z.ts"]);

    rmSync(join(root, "src/shared/layout"), { recursive: true, force: true });
    assert.throws(
      () => scanBoundaries({ projectRoot: root }),
      /expected consumer root is missing \(src\/shared\/layout\)/,
    );
  });
});
