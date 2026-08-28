# MOSAIC Foundation and Product Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable, testable MOSAIC monorepo foundation with one-source design tokens, public contracts, replaceable Demo/API services, a responsive and accessible product shell, and FastAPI live/ready endpoints.

**Architecture:** Use a pnpm workspace with a Next.js App Router web app, neutral JSON Schema contracts, and a token package generated from one JSON source. The web app depends on service interfaces selected only in a composition root. A modular FastAPI skeleton owns health and readiness behavior; PostgreSQL is the only local infrastructure in this plan.

**Tech Stack:** Node.js 24, pnpm 11, Next.js App Router, TypeScript strict, Tailwind CSS v4, Radix Dialog/Slot, Motion, Phosphor Icons, Vitest, Testing Library, Playwright, axe, Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, pytest, Ruff, mypy.

**Worker configuration:** Any implementation subagent must use `gpt-5.6-luna` with `max` reasoning, per user instruction.

---

## Scope and evidence boundary

This plan implements only the first approved subproject:

- repository and dependency foundation;
- `docs/DESIGN.md` and one-source design tokens;
- neutral public contracts and boundary checks;
- centralized MOSAIC brand configuration;
- minimal versioned `DemoStateStore` and service registry;
- shared feedback and form primitives used by the shell;
- public, auth, and console route skeletons;
- responsive `AppShell`, navigation, top bar, offline/demo indicators;
- FastAPI `live` and database-backed `ready` endpoints;
- unit, integration, accessibility, browser, and screenshot gates.

This plan does not implement real authentication, model catalog data, chat streaming, media jobs, assets, usage ledger, Provider adapters, Ollama access, workers, queues, object storage, payment, or production deployment. Route skeletons must say `demo_scaffolding`; they must not display fabricated successful calls.

The current repository contains user-owned untracked documents and assets. Preserve them. Every commit in this plan must stage only the files named by the task.

## Target file map

```text
apps/
  web/
    e2e/
    scripts/
    src/app/
    src/services/
    src/shared/config/
    src/shared/demo/
    src/shared/layout/
    src/shared/ui/
  api/
    app/api/
    app/contracts/
    app/core/
    app/infrastructure/
    tests/api/
    tests/contracts/
packages/
  contracts/
    schemas/
    src/
  design-tokens/
    scripts/
    src/
infra/compose/
docs/DESIGN.md
```

## Task 1: Bootstrap the workspace and lock the toolchain

**Files:**

- Create: `.editorconfig`
- Create: `.gitattributes`
- Create: `.gitignore`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `tsconfig.base.json`
- Create: `apps/web/**` via `create-next-app`
- Create: `apps/web/.env.example`
- Modify: `apps/web/package.json`
- Modify: `apps/web/next.config.ts`

- [ ] **Step 1: Verify the approved runtime and clean staging state**

Run:

```powershell
node --version
pnpm --version
python --version
uv --version
git status --short --branch
```

Expected: Node 24.x, pnpm 11.x, Python 3.12.x, uv 0.11.x, branch `main`; existing `docs/assets`, `docs/product-design.md`, and old plan files may be untracked and must remain untouched.

- [ ] **Step 2: Scaffold the Next.js application without creating a nested Git repository**

Run:

```powershell
pnpm dlx create-next-app@latest apps/web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm --disable-git --yes
```

Expected: `apps/web/src/app/layout.tsx`, `apps/web/src/app/page.tsx`, `apps/web/next.config.ts`, and `apps/web/package.json` exist; no `apps/web/.git` exists.

- [ ] **Step 3: Create the root workspace files**

Create `package.json`:

```json
{
  "name": "mosaic-platform",
  "private": true,
  "packageManager": "pnpm@11.19.0",
  "scripts": {
    "dev:web": "pnpm --filter @mosaic/web dev",
    "build:web": "pnpm --filter @mosaic/web build",
    "lint:web": "pnpm --filter @mosaic/web lint",
    "typecheck:web": "pnpm --filter @mosaic/web typecheck",
    "test:web": "pnpm --filter @mosaic/web test",
    "test:e2e": "pnpm --filter @mosaic/web test:e2e",
    "check:web-boundaries": "pnpm --filter @mosaic/web check:brand && pnpm --filter @mosaic/web check:boundaries",
    "test:packages": "pnpm --filter @mosaic/contracts test && pnpm --filter @mosaic/design-tokens test",
    "verify:web": "pnpm lint:web && pnpm typecheck:web && pnpm check:web-boundaries && pnpm test:packages && pnpm test:web && pnpm build:web"
  }
}
```

Create `pnpm-workspace.yaml`:

```yaml
packages:
  - apps/*
  - packages/*
```

Create `tsconfig.base.json`:

```json
{
  "compilerOptions": {
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "skipLibCheck": true
  }
}
```

Create `.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 2
trim_trailing_whitespace = true

[*.py]
indent_size = 4

[*.md]
trim_trailing_whitespace = false
```

Create `.gitattributes`:

```gitattributes
* text=auto eol=lf
*.ps1 text eol=crlf
```

Create `.gitignore`:

```gitignore
node_modules/
.next/
coverage/
playwright-report/
test-results/
*.tsbuildinfo
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.pyc
.env
.env.*
!.env.example
```

Create `apps/web/.env.example`:

```dotenv
MOSAIC_API_ORIGIN=http://127.0.0.1:8000
```

- [ ] **Step 4: Configure the web package and install only the first-plan dependencies**

Run:

```powershell
pnpm --dir apps/web pkg set name=@mosaic/web scripts.typecheck="tsc --noEmit" scripts.test="vitest run" scripts.test:watch="vitest" scripts.test:e2e="playwright test" scripts.check:brand="node scripts/check-brand-centralization.mjs" scripts.check:boundaries="node scripts/check-boundaries.mjs"
pnpm --dir apps/web add motion @phosphor-icons/react @radix-ui/react-dialog @radix-ui/react-slot class-variance-authority clsx tailwind-merge geist @fontsource-variable/noto-sans-sc
pnpm --dir apps/web add -D vitest @vitejs/plugin-react vite-tsconfig-paths jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @playwright/test @axe-core/playwright
pnpm install
```

Expected: `pnpm-lock.yaml` is created; `apps/web/package.json` is named `@mosaic/web`; no Provider SDK, state framework, Redis, queue, or object-storage dependency appears.

- [ ] **Step 5: Make workspace packages transpile through Next.js**

Replace `apps/web/next.config.ts` with:

```ts
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.MOSAIC_API_ORIGIN ?? "http://127.0.0.1:8000"}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 6: Verify the untouched scaffold**

Run:

```powershell
pnpm --filter @mosaic/web lint
pnpm --filter @mosaic/web typecheck
pnpm --filter @mosaic/web build
```

Expected: all three commands exit 0.

- [ ] **Step 7: Commit the workspace foundation**

Run:

```powershell
git add -- .editorconfig .gitattributes .gitignore package.json pnpm-workspace.yaml pnpm-lock.yaml tsconfig.base.json apps/web
git commit -m "chore: bootstrap mosaic workspace"
```

Expected: commit succeeds; pre-existing untracked documents remain untracked.

## Task 2: Establish neutral public contracts

**Files:**

- Create: `packages/contracts/package.json`
- Create: `packages/contracts/tsconfig.json`
- Create: `packages/contracts/schemas/health.schema.json`
- Create: `packages/contracts/schemas/api-error.schema.json`
- Create: `packages/contracts/schemas/public-product-model.schema.json`
- Create: `packages/contracts/src/index.ts`
- Create: `packages/contracts/src/contracts.test.ts`

- [ ] **Step 1: Write the failing contract tests**

Create `packages/contracts/src/contracts.test.ts`:

```ts
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import apiErrorSchema from "../schemas/api-error.schema.json";
import healthSchema from "../schemas/health.schema.json";
import productSchema from "../schemas/public-product-model.schema.json";

const ajv = new Ajv2020({ allErrors: true });

describe("public contracts", () => {
  it("accepts the health fixture", () => {
    expect(ajv.validate(healthSchema, { service: "mosaic-api", status: "ready", version: "0.1.0" })).toBe(true);
  });

  it("requires a stable error code and request id", () => {
    expect(
      ajv.validate(apiErrorSchema, {
        error: { code: "SERVICE_UNAVAILABLE", message: "服务暂不可用", request_id: "req_demo_001", retryable: true },
      }),
    ).toBe(true);
  });

  it.each(["provider", "provider_model_id", "quantization", "license", "snapshot_date", "deployment_id"])(
    "rejects internal field %s from public product models",
    (field) => {
      const payload = {
        product_model_id: "qwen-3-5",
        display_name: "Qwen 3.5",
        category: "text",
        task_type: "chat",
        description: "适合复杂推理与多轮对话",
        capabilities: ["多轮对话"],
        availability: "available",
        pricing_summary: "演示点数",
        [field]: "must-not-leak",
      };
      expect(ajv.validate(productSchema, payload)).toBe(false);
    },
  );
});
```

Create `packages/contracts/package.json`:

```json
{
  "name": "@mosaic/contracts",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./src/index.ts",
    "./schemas/*": "./schemas/*"
  },
  "scripts": {
    "test": "vitest run"
  },
  "devDependencies": {
    "ajv": "^8.17.1",
    "typescript": "^5.9.0",
    "vitest": "^3.2.0"
  }
}
```

Create `packages/contracts/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "types": ["vitest/globals"]
  },
  "include": ["src/**/*.ts", "schemas/**/*.json"]
}
```

- [ ] **Step 2: Run the tests and verify the schemas are missing**

Run:

```powershell
pnpm install
pnpm --filter @mosaic/contracts test
```

Expected: FAIL because the three schema files and `src/index.ts` do not exist.

- [ ] **Step 3: Add the complete JSON Schemas**

Create `packages/contracts/schemas/health.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://mosaic.internal/schemas/health.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["service", "status", "version"],
  "properties": {
    "service": { "const": "mosaic-api" },
    "status": { "enum": ["ok", "ready"] },
    "version": { "type": "string", "minLength": 1 }
  }
}
```

Create `packages/contracts/schemas/api-error.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://mosaic.internal/schemas/api-error.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["error"],
  "properties": {
    "error": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "message", "request_id", "retryable"],
      "properties": {
        "code": { "type": "string", "pattern": "^[A-Z0-9_]+$" },
        "message": { "type": "string", "minLength": 1 },
        "request_id": { "type": "string", "minLength": 1 },
        "retryable": { "type": "boolean" },
        "details": { "type": ["object", "null"] }
      }
    }
  }
}
```

Create `packages/contracts/schemas/public-product-model.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://mosaic.internal/schemas/public-product-model.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["product_model_id", "display_name", "category", "task_type", "description", "capabilities", "availability", "pricing_summary"],
  "properties": {
    "product_model_id": { "type": "string", "pattern": "^[a-z0-9-]+$" },
    "display_name": { "type": "string", "minLength": 1 },
    "category": { "enum": ["text", "image", "video", "audio"] },
    "task_type": { "enum": ["chat", "text_to_image", "image_to_video", "tts"] },
    "description": { "type": "string", "minLength": 1 },
    "capabilities": { "type": "array", "items": { "type": "string", "minLength": 1 }, "uniqueItems": true },
    "input_schema": { "type": "object" },
    "availability": { "enum": ["available", "maintenance", "unavailable", "demo"] },
    "pricing_summary": { "type": "string", "minLength": 1 }
  }
}
```

- [ ] **Step 4: Add the TypeScript public types**

Create `packages/contracts/src/index.ts`:

```ts
export type EvidenceStatus = "demo_scaffolding" | "provider_unverified" | "observed_accepted";
export type ModelCategory = "text" | "image" | "video" | "audio";
export type TaskType = "chat" | "text_to_image" | "image_to_video" | "tts";
export type Availability = "available" | "maintenance" | "unavailable" | "demo";

export interface HealthResponse {
  service: "mosaic-api";
  status: "ok" | "ready";
  version: string;
}

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    request_id: string;
    retryable: boolean;
    details?: Record<string, unknown> | null;
  };
}

export interface PublicProductModel {
  product_model_id: string;
  display_name: string;
  category: ModelCategory;
  task_type: TaskType;
  description: string;
  capabilities: string[];
  input_schema?: Record<string, unknown>;
  availability: Availability;
  pricing_summary: string;
}
```

- [ ] **Step 5: Run the contract tests**

Run:

```powershell
pnpm --filter @mosaic/web add @mosaic/contracts@workspace:*
pnpm --filter @mosaic/contracts test
```

Expected: PASS, including all six forbidden-field cases.

- [ ] **Step 6: Commit the public contract boundary**

Run:

```powershell
git add -- packages/contracts apps/web/package.json pnpm-lock.yaml
git commit -m "feat: define public platform contracts"
```

## Task 3: Create one-source design tokens and DESIGN.md

**Files:**

- Create: `packages/design-tokens/package.json`
- Create: `packages/design-tokens/tsconfig.json`
- Create: `packages/design-tokens/src/tokens.json`
- Create: `packages/design-tokens/src/index.ts`
- Create: `packages/design-tokens/src/tokens.css`
- Create: `packages/design-tokens/scripts/generate-css.mjs`
- Create: `packages/design-tokens/src/tokens.test.ts`
- Create: `docs/DESIGN.md`

- [ ] **Step 1: Write the failing drift tests**

Create `packages/design-tokens/src/tokens.test.ts`:

```ts
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import tokens from "./tokens.json";

describe("Editorial Instrument tokens", () => {
  it("locks the approved palette and shape system", () => {
    expect(tokens.color).toEqual({
      canvas: "#F5F6F8",
      surface: "#FFFFFF",
      surfaceMuted: "#ECEFF3",
      ink: "#15171A",
      inkMuted: "#667085",
      line: "#D7DCE3",
      accent: "#2F5BEA",
      danger: "#C63C45",
      warning: "#A66616",
      success: "#227A53"
    });
    expect(tokens.radius).toEqual({ control: "8px", surface: "12px", media: "10px", pill: "999px" });
  });

  it("keeps generated CSS in sync with tokens.json", () => {
    execFileSync(process.execPath, [resolve("scripts/generate-css.mjs"), "--check"], { stdio: "pipe" });
    const css = readFileSync(resolve("src/tokens.css"), "utf8");
    expect(css).toContain("--mosaic-color-accent: #2F5BEA;");
    expect(css).toContain("prefers-reduced-motion: reduce");
  });
});
```

Create `packages/design-tokens/package.json`:

```json
{
  "name": "@mosaic/design-tokens",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./src/index.ts",
    "./tokens.css": "./src/tokens.css"
  },
  "scripts": {
    "generate": "node scripts/generate-css.mjs",
    "check": "node scripts/generate-css.mjs --check",
    "test": "vitest run"
  },
  "devDependencies": {
    "typescript": "^5.9.0",
    "vitest": "^3.2.0"
  }
}
```

Create `packages/design-tokens/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "types": ["vitest/globals"]
  },
  "include": ["src/**/*.ts", "src/**/*.json"]
}
```

- [ ] **Step 2: Run the test and verify the source is missing**

Run:

```powershell
pnpm install
pnpm --filter @mosaic/design-tokens test
```

Expected: FAIL because `tokens.json`, the generator, and generated CSS do not exist.

- [ ] **Step 3: Add the single token source**

Create `packages/design-tokens/src/tokens.json`:

```json
{
  "color": {
    "canvas": "#F5F6F8",
    "surface": "#FFFFFF",
    "surfaceMuted": "#ECEFF3",
    "ink": "#15171A",
    "inkMuted": "#667085",
    "line": "#D7DCE3",
    "accent": "#2F5BEA",
    "danger": "#C63C45",
    "warning": "#A66616",
    "success": "#227A53"
  },
  "radius": { "control": "8px", "surface": "12px", "media": "10px", "pill": "999px" },
  "motion": { "fast": "180ms", "normal": "240ms", "page": "360ms", "ease": "cubic-bezier(0.16, 1, 0.3, 1)" },
  "layout": { "content": "1280px", "workspace": "1440px", "nav": "240px", "compactBreakpoint": "1024px", "singleColumnBreakpoint": "768px" }
}
```

Create `packages/design-tokens/src/index.ts`:

```ts
import tokens from "./tokens.json";

export { tokens };
export type MosaicTokens = typeof tokens;
```

- [ ] **Step 4: Add the deterministic CSS generator**

Create `packages/design-tokens/scripts/generate-css.mjs`:

```js
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tokens = JSON.parse(readFileSync(resolve(root, "src/tokens.json"), "utf8"));
const css = `:root {
  --mosaic-color-canvas: ${tokens.color.canvas};
  --mosaic-color-surface: ${tokens.color.surface};
  --mosaic-color-surface-muted: ${tokens.color.surfaceMuted};
  --mosaic-color-ink: ${tokens.color.ink};
  --mosaic-color-ink-muted: ${tokens.color.inkMuted};
  --mosaic-color-line: ${tokens.color.line};
  --mosaic-color-accent: ${tokens.color.accent};
  --mosaic-color-danger: ${tokens.color.danger};
  --mosaic-color-warning: ${tokens.color.warning};
  --mosaic-color-success: ${tokens.color.success};
  --mosaic-radius-control: ${tokens.radius.control};
  --mosaic-radius-surface: ${tokens.radius.surface};
  --mosaic-radius-media: ${tokens.radius.media};
  --mosaic-radius-pill: ${tokens.radius.pill};
  --mosaic-motion-fast: ${tokens.motion.fast};
  --mosaic-motion-normal: ${tokens.motion.normal};
  --mosaic-motion-page: ${tokens.motion.page};
  --mosaic-motion-ease: ${tokens.motion.ease};
  --mosaic-layout-content: ${tokens.layout.content};
  --mosaic-layout-workspace: ${tokens.layout.workspace};
  --mosaic-layout-nav: ${tokens.layout.nav};
}

@media (prefers-reduced-motion: reduce) {
  :root {
    --mosaic-motion-fast: 0ms;
    --mosaic-motion-normal: 0ms;
    --mosaic-motion-page: 0ms;
  }
}
`;
const output = resolve(root, "src/tokens.css");
if (process.argv.includes("--check")) {
  if (readFileSync(output, "utf8") !== css) {
    throw new Error("tokens.css is out of date; run pnpm generate");
  }
} else {
  writeFileSync(output, css, "utf8");
}
```

Run:

```powershell
pnpm --filter @mosaic/design-tokens generate
```

Expected: `packages/design-tokens/src/tokens.css` is generated.

- [ ] **Step 5: Create the human-readable design contract**

Create `docs/DESIGN.md` with these exact decisions:

```markdown
# MOSAIC Design System

MOSAIC uses the approved Editorial Instrument direction: a bright, editorial, professional-tool interface for B2B AIGC workflows.

## Source of truth

`packages/design-tokens/src/tokens.json` is the only machine-readable token source. `tokens.css` is generated and must pass the drift test. This document explains usage and must not introduce different values.

## Color

- Canvas `#F5F6F8`
- Surface `#FFFFFF`
- Muted surface `#ECEFF3`
- Ink `#15171A`
- Muted ink `#667085`
- Line `#D7DCE3`
- Accent `#2F5BEA`
- Danger `#C63C45`
- Warning `#A66616`
- Success `#227A53`

Accent is the only brand action color. Semantic colors only communicate real state. Do not use AI-purple gradients, neon glow, dark-universe backgrounds, or decorative status colors.

## Typography

Geist Sans is used for Latin text and numbers, Geist Mono for identifiers and tabular numbers, and Noto Sans SC for Chinese with system sans-serif fallback. Public hero text stays within two lines. Product headings use restrained scale.

## Shape and material

Controls and buttons use 8px radius, surfaces 12px, media 10px, and filter chips full radius. Prefer whitespace and 1px rules to unnecessary cards. Shadows are reserved for overlays.

## Layout

Public content max width is 1280px. Product workspace max width is 1440px. Full navigation is 240px. Navigation compacts at 1024px; workspaces become single-column below 768px. Interactive targets are at least 44x44px.

## Motion

Fast feedback is 180ms, normal transitions 240ms, and page orchestration 360ms with `cubic-bezier(0.16, 1, 0.3, 1)`. Animate transform and opacity only. Reduced-motion mode resolves all three durations to 0ms.

## Accessibility

Use visible labels, semantic landmarks, visible focus rings, textual state labels, WCAG AA contrast, keyboard-operable dialogs, and a skip link. Status cannot rely on color alone.

## Forbidden patterns

Do not use NEXUS AI, Provider IDs, license labels, parameter-size badges, quantization, snapshot dates, fake success data, three equal feature cards, universal glassmorphism, or div-built fake screenshots. The approved product names `Qwen3-TTS 1.7B VoiceDesign`, `Qwen3-TTS 1.7B CustomVoice`, and `Qwen3-TTS 1.7B Base` retain `1.7B` as part of their names.
```

- [ ] **Step 6: Run token generation and drift tests**

Update `apps/web/next.config.ts` by adding this property beside `reactStrictMode` now that both workspace packages exist:

```ts
transpilePackages: ["@mosaic/contracts", "@mosaic/design-tokens"],
```

Run:

```powershell
pnpm --filter @mosaic/web add @mosaic/design-tokens@workspace:*
pnpm --filter @mosaic/design-tokens generate
pnpm --filter @mosaic/design-tokens test
pnpm --filter @mosaic/design-tokens check
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit the design source of truth**

Run:

```powershell
git add -- docs/DESIGN.md packages/design-tokens apps/web/package.json apps/web/next.config.ts pnpm-lock.yaml
git commit -m "feat: establish mosaic design tokens"
```

## Task 4: Configure the web test harness and centralized brand

**Files:**

- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/shared/config/brand.ts`
- Create: `apps/web/src/shared/config/brand.test.ts`
- Create: `apps/web/scripts/check-brand-centralization.mjs`
- Modify: `apps/web/src/app/layout.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Add the failing brand test**

Create `apps/web/src/shared/config/brand.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { BRAND } from "./brand";

describe("brand configuration", () => {
  it("exposes the approved centralized identity", () => {
    expect(BRAND).toEqual({ name: "MOSAIC", environmentLabel: "内部演示", defaultTitle: "MOSAIC 多模态模型工作台" });
  });
});
```

Create `apps/web/vitest.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: true,
  },
});
```

Create `apps/web/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/config/brand.test.ts
```

Expected: FAIL because `brand.ts` does not exist.

- [ ] **Step 3: Implement the centralized brand object**

Create `apps/web/src/shared/config/brand.ts`:

```ts
export const BRAND = Object.freeze({
  name: "MOSAIC",
  environmentLabel: "内部演示",
  defaultTitle: "MOSAIC 多模态模型工作台",
});
```

Create `apps/web/scripts/check-brand-centralization.mjs`:

```js
import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve("src");
const allowed = new Set([
  resolve("src/shared/config/brand.ts"),
  resolve("src/shared/config/brand.test.ts"),
]);
const violations = [];
function visit(path) {
  for (const entry of readdirSync(path)) {
    const full = resolve(path, entry);
    if (statSync(full).isDirectory()) visit(full);
    else if (/\.(ts|tsx)$/.test(entry) && !allowed.has(full)) {
      const text = readFileSync(full, "utf8");
      if (text.includes("MOSAIC") || text.includes("NEXUS AI")) violations.push(full);
    }
  }
}
visit(root);
if (violations.length) throw new Error(`Brand literals outside config:\n${violations.join("\n")}`);
```

- [ ] **Step 4: Wire the fonts, metadata, and token package**

Replace `apps/web/src/app/layout.tsx` with:

```tsx
import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import "@fontsource-variable/noto-sans-sc";
import "@mosaic/design-tokens/tokens.css";
import { BRAND } from "@/shared/config/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: BRAND.defaultTitle,
  description: "面向专业创作团队的多模态模型工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
```

Replace `apps/web/src/app/globals.css` with:

```css
@import "tailwindcss";

@theme inline {
  --color-canvas: var(--mosaic-color-canvas);
  --color-surface: var(--mosaic-color-surface);
  --color-surface-muted: var(--mosaic-color-surface-muted);
  --color-ink: var(--mosaic-color-ink);
  --color-ink-muted: var(--mosaic-color-ink-muted);
  --color-line: var(--mosaic-color-line);
  --color-accent: var(--mosaic-color-accent);
  --font-sans: var(--font-geist-sans), "Noto Sans SC Variable", "Microsoft YaHei", sans-serif;
  --font-mono: var(--font-geist-mono), ui-monospace, monospace;
}

* { box-sizing: border-box; }
html { background: var(--mosaic-color-canvas); color: var(--mosaic-color-ink); }
body { margin: 0; min-height: 100dvh; background: var(--mosaic-color-canvas); font-family: var(--font-sans); }
button, input, textarea, select { font: inherit; }
:focus-visible { outline: 3px solid color-mix(in srgb, var(--mosaic-color-accent) 45%, transparent); outline-offset: 2px; }
```

- [ ] **Step 5: Run brand, type, and build checks**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/config/brand.test.ts
pnpm --filter @mosaic/web check:brand
pnpm --filter @mosaic/web typecheck
pnpm --filter @mosaic/web build
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit brand and test infrastructure**

Run:

```powershell
git add -- apps/web pnpm-lock.yaml
git commit -m "feat: centralize mosaic brand and web test setup"
```

## Task 5: Implement DemoStateStore and the service composition root

**Files:**

- Create: `apps/web/src/shared/demo/demo-state-store.ts`
- Create: `apps/web/src/shared/demo/demo-state-store.test.ts`
- Create: `apps/web/src/services/interfaces.ts`
- Create: `apps/web/src/services/demo-auth-service.ts`
- Create: `apps/web/src/services/api-auth-service.ts`
- Create: `apps/web/src/services/demo-health-service.ts`
- Create: `apps/web/src/services/api-health-service.ts`
- Create: `apps/web/src/services/create-service-registry.ts`
- Create: `apps/web/src/services/create-service-registry.test.ts`
- Create: `apps/web/scripts/check-boundaries.mjs`

- [ ] **Step 1: Write the failing store and registry tests**

Create `apps/web/src/shared/demo/demo-state-store.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createDemoStateStore, type StorageLike } from "./demo-state-store";

function memoryStorage(initial?: string): StorageLike {
  let value = initial ?? null;
  return {
    getItem: () => value,
    setItem: (_key, next) => { value = next; },
    removeItem: () => { value = null; },
  };
}

describe("DemoStateStore", () => {
  it("recovers from corrupt persisted JSON", () => {
    const store = createDemoStateStore({ storage: memoryStorage("not-json"), now: () => "2026-08-20T12:00:00Z" });
    expect(store.read()).toEqual({ schemaVersion: 1, seed: 8202026, authenticated: false, passwordChangeRequired: true, updatedAt: "2026-08-20T12:00:00Z" });
  });

  it("persists and resets only the demo state", () => {
    const storage = memoryStorage();
    const store = createDemoStateStore({ storage, now: () => "2026-08-20T12:00:00Z" });
    store.write({ ...store.read(), authenticated: true });
    expect(store.read().authenticated).toBe(true);
    expect(store.reset().authenticated).toBe(false);
  });

  it("does not crash when browser storage is unavailable", () => {
    const storage: StorageLike = { getItem: () => null, setItem: () => { throw new Error("quota"); }, removeItem: () => { throw new Error("blocked"); } };
    const store = createDemoStateStore({ storage, now: () => "2026-08-20T12:00:00Z" });
    expect(() => store.write({ ...store.read(), authenticated: true })).not.toThrow();
    expect(() => store.reset()).not.toThrow();
  });
});
```

Create `apps/web/src/services/create-service-registry.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { createServiceRegistry } from "./create-service-registry";

function memoryStorage() {
  let value: string | null = null;
  return { getItem: () => value, setItem: (_key: string, next: string) => { value = next; }, removeItem: () => { value = null; } };
}

describe("service registry", () => {
  it("selects demo services only in the composition root", async () => {
    const registry = createServiceRegistry({ mode: "demo", storage: memoryStorage(), now: () => "2026-08-20T12:00:00Z" });
    await expect(registry.health.getStatus()).resolves.toMatchObject({ evidence: "demo_scaffolding", status: "ready" });
    await expect(registry.auth.signIn({ account: "demo", password: "not-persisted" })).resolves.toMatchObject({ authenticated: true });
  });

  it("selects the API health adapter", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ service: "mosaic-api", status: "ready", version: "0.1.0" }) });
    const registry = createServiceRegistry({ mode: "api", fetcher });
    await registry.health.getStatus();
    expect(fetcher).toHaveBeenCalledWith("/api/v1/health/ready", expect.any(Object));
  });
});
```

- [ ] **Step 2: Run focused tests and verify missing implementations**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/demo/demo-state-store.test.ts src/services/create-service-registry.test.ts
```

Expected: FAIL because the store and services do not exist.

- [ ] **Step 3: Implement the versioned store**

Create `apps/web/src/shared/demo/demo-state-store.ts`:

```ts
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface DemoState {
  schemaVersion: 1;
  seed: number;
  authenticated: boolean;
  passwordChangeRequired: boolean;
  updatedAt: string;
}

const KEY = "mosaic.demo-state.v1";

export function createDemoStateStore(input: { storage: StorageLike; now: () => string }) {
  const initial = (): DemoState => ({
    schemaVersion: 1,
    seed: 8202026,
    authenticated: false,
    passwordChangeRequired: true,
    updatedAt: input.now(),
  });
  const read = (): DemoState => {
    try {
      const raw = input.storage.getItem(KEY);
      if (!raw) return initial();
      const value = JSON.parse(raw) as Partial<DemoState>;
      if (value.schemaVersion !== 1 || typeof value.authenticated !== "boolean") return initial();
      return value as DemoState;
    } catch {
      return initial();
    }
  };
  const write = (state: DemoState) => {
    const next = { ...state, updatedAt: input.now() };
    try { input.storage.setItem(KEY, JSON.stringify(next)); } catch { /* demo continues without persistence */ }
    return next;
  };
  const reset = () => {
    try { input.storage.removeItem(KEY); } catch { /* demo continues with a fresh in-memory view */ }
    return initial();
  };
  return { read, write, reset };
}

export type DemoStateStore = ReturnType<typeof createDemoStateStore>;
```

- [ ] **Step 4: Implement the service interfaces and adapters**

Create `apps/web/src/services/interfaces.ts`:

```ts
import type { EvidenceStatus, HealthResponse } from "@mosaic/contracts";

export interface PlatformHealth extends HealthResponse {
  evidence: EvidenceStatus;
}

export interface AuthSession {
  authenticated: boolean;
  passwordChangeRequired: boolean;
}

export interface AuthService {
  getSession(signal?: AbortSignal): Promise<AuthSession>;
  signIn(input: { account: string; password: string }, signal?: AbortSignal): Promise<AuthSession>;
  signOut(signal?: AbortSignal): Promise<void>;
}

export interface HealthService {
  getStatus(signal?: AbortSignal): Promise<PlatformHealth>;
}

export interface ServiceRegistry {
  health: HealthService;
  auth: AuthService;
}
```

Create `apps/web/src/services/demo-auth-service.ts`:

```ts
import type { DemoStateStore } from "@/shared/demo/demo-state-store";
import type { AuthService } from "./interfaces";

export function createDemoAuthService(store: DemoStateStore): AuthService {
  return {
    async getSession() {
      const state = store.read();
      return { authenticated: state.authenticated, passwordChangeRequired: state.passwordChangeRequired };
    },
    async signIn() {
      const state = store.write({ ...store.read(), authenticated: true, passwordChangeRequired: false });
      return { authenticated: state.authenticated, passwordChangeRequired: state.passwordChangeRequired };
    },
    async signOut() {
      store.write({ ...store.read(), authenticated: false });
    },
  };
}
```

Create `apps/web/src/services/api-auth-service.ts`:

```ts
import type { AuthService, AuthSession } from "./interfaces";

export function createApiAuthService(fetcher: typeof fetch): AuthService {
  async function readSession(response: Response): Promise<AuthSession> {
    if (!response.ok) return { authenticated: false, passwordChangeRequired: false };
    return response.json() as Promise<AuthSession>;
  }
  return {
    async getSession(signal) { return readSession(await fetcher("/api/v1/auth/me", { signal })); },
    async signIn(input, signal) { return readSession(await fetcher("/api/v1/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input), signal })); },
    async signOut(signal) { await fetcher("/api/v1/auth/logout", { method: "POST", signal }); },
  };
}
```

Create `apps/web/src/services/demo-health-service.ts`:

```ts
import type { HealthService } from "./interfaces";

export const demoHealthService: HealthService = {
  async getStatus() {
    return { service: "mosaic-api", status: "ready", version: "demo", evidence: "demo_scaffolding" };
  },
};
```

Create `apps/web/src/services/api-health-service.ts`:

```ts
import type { HealthResponse } from "@mosaic/contracts";
import type { HealthService } from "./interfaces";

export function createApiHealthService(fetcher: typeof fetch): HealthService {
  return {
    async getStatus(signal) {
      const response = await fetcher("/api/v1/health/ready", { headers: { accept: "application/json" }, signal });
      if (!response.ok) throw new Error("API_NOT_READY");
      const value = (await response.json()) as HealthResponse;
      return { ...value, evidence: "provider_unverified" };
    },
  };
}
```

Create `apps/web/src/services/create-service-registry.ts`:

```ts
import { createApiHealthService } from "./api-health-service";
import { createApiAuthService } from "./api-auth-service";
import { createDemoAuthService } from "./demo-auth-service";
import { demoHealthService } from "./demo-health-service";
import { createDemoStateStore, type StorageLike } from "@/shared/demo/demo-state-store";
import type { ServiceRegistry } from "./interfaces";

export function createServiceRegistry(input: { mode: "demo" | "api"; fetcher?: typeof fetch; storage?: StorageLike; now?: () => string }): ServiceRegistry {
  if (input.mode === "demo") {
    if (!input.storage || !input.now) throw new Error("Demo mode requires storage and clock");
    const store = createDemoStateStore({ storage: input.storage, now: input.now });
    return { health: demoHealthService, auth: createDemoAuthService(store) };
  }
  const fetcher = input.fetcher ?? fetch;
  return { health: createApiHealthService(fetcher), auth: createApiAuthService(fetcher) };
}

export function createBrowserServiceRegistry(): ServiceRegistry {
  const mode = process.env.NEXT_PUBLIC_MOSAIC_SERVICE_MODE === "api" ? "api" : "demo";
  return createServiceRegistry({ mode, storage: window.localStorage, now: () => new Date().toISOString() });
}
```

- [ ] **Step 5: Enforce import boundaries**

Create `apps/web/scripts/check-boundaries.mjs`:

```js
import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const roots = ["src/app", "src/shared/ui", "src/shared/layout"];
const violations = [];
function visit(path) {
  for (const entry of readdirSync(path)) {
    const full = resolve(path, entry);
    if (statSync(full).isDirectory()) visit(full);
    else if (/\.(ts|tsx)$/.test(entry)) {
      const text = readFileSync(full, "utf8");
      if (/\bfetch\s*\(/.test(text) || /from ["']@\/services\/(demo|api)-/.test(text)) violations.push(full);
    }
  }
}
roots.forEach((root) => visit(resolve(root)));
if (violations.length) throw new Error(`Boundary violations:\n${violations.join("\n")}`);
```

- [ ] **Step 6: Run store, registry, and boundary tests**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/demo/demo-state-store.test.ts src/services/create-service-registry.test.ts
pnpm --filter @mosaic/web check:boundaries
```

Expected: PASS; no component or route calls `fetch` or imports concrete adapters.

- [ ] **Step 7: Commit the replaceable service foundation**

Run:

```powershell
git add -- apps/web/src/shared/demo apps/web/src/services apps/web/scripts/check-boundaries.mjs
git commit -m "feat: add demo state and service composition root"
```

## Task 6: Implement accessible shared UI primitives

**Files:**

- Create: `apps/web/src/shared/ui/cn.ts`
- Create: `apps/web/src/shared/ui/button.tsx`
- Create: `apps/web/src/shared/ui/input-field.tsx`
- Create: `apps/web/src/shared/ui/feedback-state.tsx`
- Create: `apps/web/src/shared/ui/status-badge.tsx`
- Create: `apps/web/src/shared/ui/shared-ui.test.tsx`

- [ ] **Step 1: Write failing accessibility behavior tests**

Create `apps/web/src/shared/ui/shared-ui.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./button";
import { ErrorState, Skeleton } from "./feedback-state";
import { InputField } from "./input-field";
import { StatusBadge } from "./status-badge";

describe("shared UI", () => {
  it("prevents duplicate button activation while loading", () => {
    const action = vi.fn();
    render(<Button loading onClick={action}>保存</Button>);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
  });

  it("associates input label, help, and error text", () => {
    render(<InputField id="email" label="邮箱" description="仅用于演示登录" error="请输入有效邮箱" />);
    const input = screen.getByLabelText("邮箱");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("仅用于演示登录 请输入有效邮箱");
  });

  it("provides recovery actions and textual status", () => {
    render(<ErrorState title="加载失败" description="请重试" action={<button>重试</button>} />);
    expect(screen.getByRole("button", { name: "重试" })).toBeVisible();
    const { rerender } = render(<StatusBadge tone="warning">正在确认</StatusBadge>);
    expect(screen.getByText("正在确认")).toBeVisible();
    rerender(<Skeleton label="正在加载模型" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });
});
```

- [ ] **Step 2: Run the test and verify missing components**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/ui/shared-ui.test.tsx
```

Expected: FAIL because the UI modules do not exist.

- [ ] **Step 3: Implement the utility, Button, and InputField**

Create `apps/web/src/shared/ui/cn.ts`:

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...values: ClassValue[]) { return twMerge(clsx(values)); }
```

Create `apps/web/src/shared/ui/button.tsx`:

```tsx
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

const styles = cva("inline-flex min-h-11 items-center justify-center gap-2 rounded-[var(--mosaic-radius-control)] px-4 text-sm font-semibold transition-[transform,background-color,border-color] duration-[var(--mosaic-motion-fast)] active:translate-y-px disabled:pointer-events-none disabled:opacity-50", {
  variants: {
    variant: {
      primary: "bg-accent text-white hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,black)]",
      secondary: "border border-line bg-surface text-ink hover:bg-surface-muted",
      danger: "bg-[var(--mosaic-color-danger)] text-white",
      ghost: "text-ink hover:bg-surface-muted",
    },
  },
  defaultVariants: { variant: "primary" },
});

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof styles> {
  asChild?: boolean;
  loading?: boolean;
}

export function Button({ asChild, loading = false, variant, className, disabled, children, ...props }: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(styles({ variant }), className)} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>{children}</Component>;
}
```

Create `apps/web/src/shared/ui/input-field.tsx`:

```tsx
import type { InputHTMLAttributes } from "react";
import { cn } from "./cn";

export interface InputFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  description?: string;
  error?: string;
}

export function InputField({ id, label, description, error, className, ...props }: InputFieldProps) {
  const describedBy = [description ? `${id}-description` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
  return <div className="grid gap-2"><label htmlFor={id} className="text-sm font-semibold text-ink">{label}</label><input id={id} aria-describedby={describedBy} aria-invalid={error ? true : undefined} className={cn("min-h-11 rounded-[var(--mosaic-radius-control)] border border-line bg-surface px-3 text-ink placeholder:text-ink-muted", className)} {...props} />{description && <p id={`${id}-description`} className="text-sm text-ink-muted">{description}</p>}{error && <p id={`${id}-error`} className="text-sm text-[var(--mosaic-color-danger)]">{error}</p>}</div>;
}
```

- [ ] **Step 4: Implement generic feedback and status components**

Create `apps/web/src/shared/ui/feedback-state.tsx`:

```tsx
import type { ReactNode } from "react";

export function ErrorState({ title, description, action }: { title: string; description: string; action: ReactNode }) {
  return <section role="alert" className="grid gap-3 rounded-[var(--mosaic-radius-surface)] border border-line bg-surface p-6"><h2 className="text-xl font-semibold">{title}</h2><p className="text-ink-muted">{description}</p><div>{action}</div></section>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <section className="grid justify-items-start gap-3 border-t border-line py-10"><h2 className="text-xl font-semibold">{title}</h2><p className="max-w-[60ch] text-ink-muted">{description}</p>{action}</section>;
}

export function Skeleton({ label }: { label: string }) {
  return <div role="status" aria-busy="true" aria-label={label} className="h-20 animate-pulse rounded-[var(--mosaic-radius-surface)] bg-surface-muted motion-reduce:animate-none" />;
}
```

Create `apps/web/src/shared/ui/status-badge.tsx`:

```tsx
import type { ReactNode } from "react";
import { cn } from "./cn";

const tones = {
  neutral: "border-line bg-surface-muted text-ink",
  info: "border-[color-mix(in_srgb,var(--mosaic-color-accent)_35%,white)] bg-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,white)] text-accent",
  success: "border-[color-mix(in_srgb,var(--mosaic-color-success)_35%,white)] bg-[color-mix(in_srgb,var(--mosaic-color-success)_10%,white)] text-[var(--mosaic-color-success)]",
  warning: "border-[color-mix(in_srgb,var(--mosaic-color-warning)_35%,white)] bg-[color-mix(in_srgb,var(--mosaic-color-warning)_10%,white)] text-[var(--mosaic-color-warning)]",
  danger: "border-[color-mix(in_srgb,var(--mosaic-color-danger)_35%,white)] bg-[color-mix(in_srgb,var(--mosaic-color-danger)_10%,white)] text-[var(--mosaic-color-danger)]",
} as const;

export function StatusBadge({ tone = "neutral", children }: { tone?: keyof typeof tones; children: ReactNode }) {
  return <span className={cn("inline-flex min-h-7 items-center rounded-[var(--mosaic-radius-pill)] border px-2.5 text-xs font-semibold", tones[tone])}>{children}</span>;
}
```

- [ ] **Step 5: Run shared UI tests and checks**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/ui/shared-ui.test.tsx
pnpm --filter @mosaic/web typecheck
pnpm --filter @mosaic/web lint
```

Expected: PASS with no accessibility assertion or type failure.

- [ ] **Step 6: Commit the shared primitives**

Run:

```powershell
git add -- apps/web/src/shared/ui
git commit -m "feat: add accessible shared ui primitives"
```

## Task 7: Build the responsive Product Shell and complete route skeleton

**Files:**

- Create: `apps/web/src/shared/config/routes.ts`
- Create: `apps/web/src/shared/layout/navigation-rail.tsx`
- Create: `apps/web/src/shared/layout/top-bar.tsx`
- Create: `apps/web/src/shared/layout/network-status.tsx`
- Create: `apps/web/src/shared/layout/app-shell.tsx`
- Create: `apps/web/src/shared/layout/app-shell.test.tsx`
- Create: `apps/web/src/shared/ui/route-state.tsx`
- Create: `apps/web/src/features/auth/demo-auth-gate.tsx`
- Create: `apps/web/src/features/auth/demo-login-form.tsx`
- Create: `apps/web/src/app/(marketing)/page.tsx`
- Create: `apps/web/src/app/(auth)/login/page.tsx`
- Create: `apps/web/src/app/(console)/layout.tsx`
- Create: route skeleton pages under `apps/web/src/app/(console)/**`
- Create: `apps/web/src/app/not-found.tsx`
- Create: `apps/web/src/app/loading.tsx`
- Create: `apps/web/src/app/error.tsx`
- Delete: `apps/web/src/app/page.tsx`

- [ ] **Step 1: Write the failing shell test**

Create `apps/web/src/shared/layout/app-shell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppShell } from "./app-shell";

describe("AppShell", () => {
  it("renders semantic navigation, demo status, and main content", () => {
    render(<AppShell pathname="/models"><h1>模型广场</h1></AppShell>);
    expect(screen.getByRole("navigation", { name: "主导航" })).toBeVisible();
    expect(screen.getByText("内部演示")).toBeVisible();
    expect(screen.getByRole("main")).toContainElement(screen.getByRole("heading", { name: "模型广场" }));
    expect(screen.getByRole("link", { name: "跳到主要内容" })).toHaveAttribute("href", "#main-content");
  });

  it("opens and closes the compact navigation with keyboard", async () => {
    const user = userEvent.setup();
    render(<AppShell pathname="/models"><h1>模型广场</h1></AppShell>);
    await user.click(screen.getByRole("button", { name: "打开导航" }));
    expect(screen.getByRole("dialog", { name: "移动导航" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "移动导航" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test and verify missing shell modules**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/layout/app-shell.test.tsx
```

Expected: FAIL because the shell does not exist.

- [ ] **Step 3: Create one route manifest**

Create `apps/web/src/shared/config/routes.ts`:

```ts
export const CONSOLE_ROUTES = [
  { href: "/models", label: "模型广场" },
  { href: "/generations", label: "生成记录" },
  { href: "/usage", label: "用量中心" },
  { href: "/account/security", label: "账户安全" },
] as const;

export const ROUTE_ACCESS = {
  public: ["/", "/login"],
  protectedPrefixes: ["/models", "/chat", "/studio", "/generations", "/usage", "/account"],
} as const;
```

- [ ] **Step 4: Implement NavigationRail and TopBar**

Create `apps/web/src/shared/layout/navigation-rail.tsx`:

```tsx
import { ClockCounterClockwise, GridFour, ShieldCheck, Wallet } from "@phosphor-icons/react";
import Link from "next/link";
import { BRAND } from "@/shared/config/brand";
import { CONSOLE_ROUTES } from "@/shared/config/routes";
import { cn } from "@/shared/ui/cn";

const icons = [GridFour, ClockCounterClockwise, Wallet, ShieldCheck];
export function NavigationRail({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return <nav aria-label="主导航" className="flex h-full flex-col bg-surface px-3 py-5"><Link href="/models" className="mb-8 px-3 text-xl font-bold tracking-[0.16em]">{BRAND.name}</Link><div className="grid gap-1">{CONSOLE_ROUTES.map((route, index) => { const Icon = icons[index] ?? GridFour; const active = pathname === route.href || pathname.startsWith(`${route.href}/`); return <Link key={route.href} href={route.href} onClick={onNavigate} aria-current={active ? "page" : undefined} className={cn("flex min-h-11 items-center gap-3 rounded-[var(--mosaic-radius-control)] px-3 text-sm font-medium text-ink-muted", active && "bg-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,white)] text-accent")}><Icon size={20} aria-hidden />{route.label}</Link>; })}</div></nav>;
}
```

Create `apps/web/src/shared/layout/top-bar.tsx`:

```tsx
import { BRAND } from "@/shared/config/brand";
import { StatusBadge } from "@/shared/ui/status-badge";
export function TopBar({ onOpenNavigation }: { onOpenNavigation: () => void }) {
  return <header className="flex min-h-16 items-center justify-between border-b border-line bg-surface px-4 md:px-6"><button type="button" onClick={onOpenNavigation} className="min-h-11 rounded-[var(--mosaic-radius-control)] border border-line px-3 lg:hidden" aria-label="打开导航">菜单</button><div className="ml-auto flex items-center gap-3"><StatusBadge tone="info">{BRAND.environmentLabel}</StatusBadge><span className="text-sm text-ink-muted">体验账户</span></div></header>;
}
```

Create `apps/web/src/shared/layout/network-status.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";

export function NetworkStatus() {
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => { window.removeEventListener("online", update); window.removeEventListener("offline", update); };
  }, []);
  return online ? null : <div role="status" className="border-b border-[var(--mosaic-color-warning)] bg-[color-mix(in_srgb,var(--mosaic-color-warning)_10%,white)] px-4 py-2 text-sm text-[var(--mosaic-color-warning)]">网络已断开。未提交的演示内容会保留在当前页面。</div>;
}
```

- [ ] **Step 5: Implement the responsive AppShell**

Create `apps/web/src/shared/layout/app-shell.tsx`:

```tsx
"use client";
import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { useState } from "react";
import { NavigationRail } from "./navigation-rail";
import { NetworkStatus } from "./network-status";
import { TopBar } from "./top-bar";

export function AppShell({ pathname, children }: { pathname: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <div className="min-h-[100dvh] bg-canvas"><a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-surface focus:p-3">跳到主要内容</a><aside className="fixed inset-y-0 left-0 hidden w-[var(--mosaic-layout-nav)] border-r border-line lg:block"><NavigationRail pathname={pathname} /></aside><div className="lg:pl-[var(--mosaic-layout-nav)]"><TopBar onOpenNavigation={() => setOpen(true)} /><NetworkStatus /><main id="main-content" className="mx-auto w-full max-w-[var(--mosaic-layout-workspace)] p-4 md:p-6 lg:p-8">{children}</main></div><Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-40 bg-black/25" /><Dialog.Content aria-label="移动导航" className="fixed inset-y-0 left-0 z-50 w-[min(86vw,320px)] bg-surface"><Dialog.Title className="sr-only">移动导航</Dialog.Title><NavigationRail pathname={pathname} onNavigate={() => setOpen(false)} /><Dialog.Close className="absolute right-3 top-3 min-h-11 px-3" aria-label="关闭导航">关闭</Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root></div>;
}
```

- [ ] **Step 6: Implement the centralized Demo access boundary**

Create `apps/web/src/features/auth/demo-auth-gate.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import { Skeleton } from "@/shared/ui/feedback-state";

export function DemoAuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);
  useEffect(() => {
    let active = true;
    createBrowserServiceRegistry().auth.getSession().then((session) => {
      if (!active) return;
      if (!session.authenticated) router.replace("/login");
      else setAllowed(true);
    });
    return () => { active = false; };
  }, [router]);
  return allowed ? children : <Skeleton label="正在验证演示会话" />;
}
```

Create `apps/web/src/features/auth/demo-login-form.tsx`:

```tsx
"use client";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import { Button } from "@/shared/ui/button";
import { InputField } from "@/shared/ui/input-field";

export function DemoLoginForm() {
  const router = useRouter();
  const [account, setAccount] = useState("demo@mosaic.internal");
  const [password, setPassword] = useState("internal-demo");
  const [submitting, setSubmitting] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    await createBrowserServiceRegistry().auth.signIn({ account, password });
    router.push("/models");
  }
  return <form className="grid gap-5" onSubmit={submit}><InputField id="account" label="账户" autoComplete="username" value={account} onChange={(event) => setAccount(event.target.value)} /><InputField id="password" label="密码" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /><Button type="submit" loading={submitting}>进入内部演示</Button></form>;
}
```

- [ ] **Step 7: Add route-state content and all route skeletons**

Create `apps/web/src/shared/ui/route-state.tsx`:

```tsx
import { StatusBadge } from "./status-badge";
export function RouteState({ title, description }: { title: string; description: string }) {
  return <section className="grid gap-6"><StatusBadge tone="info">demo_scaffolding</StatusBadge><div className="max-w-3xl"><h1 className="text-4xl font-semibold tracking-[-0.04em] text-ink">{title}</h1><p className="mt-3 max-w-[65ch] text-ink-muted">{description}</p></div><div className="border-t border-line pt-8 text-sm text-ink-muted">此阶段只验证产品 Shell 与访问边界，不代表模型或业务链路已接入。</div></section>;
}
```

Use it in the following complete route modules:

```tsx
// apps/web/src/app/(marketing)/page.tsx
import Link from "next/link";
import { BRAND } from "@/shared/config/brand";
import { Button } from "@/shared/ui/button";
export default function MarketingPage() { return <main className="mx-auto grid min-h-[100dvh] max-w-[1280px] content-center gap-10 px-6 py-20"><p className="font-semibold tracking-[0.16em]">{BRAND.name}</p><h1 className="max-w-4xl text-6xl font-semibold tracking-[-0.055em]">一个入口，进入专业多模态创作。</h1><p className="max-w-[60ch] text-lg text-ink-muted">选择模型和任务，进入与文本、图像、视频或声音匹配的专业工作台。</p><Button asChild><Link href="/login">进入演示</Link></Button></main>; }

// apps/web/src/app/(auth)/login/page.tsx
import { BRAND } from "@/shared/config/brand";
import { DemoLoginForm } from "@/features/auth/demo-login-form";
export default function LoginPage() { return <main className="mx-auto grid min-h-[100dvh] max-w-md content-center gap-8 px-6"><div><p className="font-semibold tracking-[0.16em]">{BRAND.name}</p><h1 className="mt-4 text-4xl font-semibold">邀请账户登录</h1><p className="mt-2 text-ink-muted">当前为内部演示，不连接真实认证服务。</p></div><DemoLoginForm /></main>; }
```

Create `apps/web/src/app/(console)/layout.tsx`:

```tsx
"use client";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { AppShell } from "@/shared/layout/app-shell";
import { DemoAuthGate } from "@/features/auth/demo-auth-gate";
export default function ConsoleLayout({ children }: { children: ReactNode }) { return <DemoAuthGate><AppShell pathname={usePathname()}>{children}</AppShell></DemoAuthGate>; }
```

Create `apps/web/src/app/(console)/models/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function ModelsPage() { return <RouteState title="模型广场" description="模型目录与筛选将在第二计划实现。" />; }
```

Create `apps/web/src/app/(console)/chat/[conversationId]/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function ChatPage() { return <RouteState title="文本对话" description="流式会话将在第二计划实现。" />; }
```

Create `apps/web/src/app/(console)/studio/image/[modelId]/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function ImageStudioPage() { return <RouteState title="图片工作台" description="图片任务将在第三计划实现。" />; }
```

Create `apps/web/src/app/(console)/studio/video/[modelId]/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function VideoStudioPage() { return <RouteState title="视频工作台" description="视频任务将在第三计划实现。" />; }
```

Create `apps/web/src/app/(console)/studio/audio/[modelId]/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function AudioStudioPage() { return <RouteState title="音频工作台" description="音频任务将在第三计划实现。" />; }
```

Create `apps/web/src/app/(console)/generations/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function GenerationsPage() { return <RouteState title="生成记录" description="统一任务记录将在第三计划实现。" />; }
```

Create `apps/web/src/app/(console)/generations/[jobId]/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function GenerationDetailPage() { return <RouteState title="任务详情" description="状态时间线将在第三计划实现。" />; }
```

Create `apps/web/src/app/(console)/usage/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function UsagePage() { return <RouteState title="用量中心" description="演示账本将在第三计划实现。" />; }
```

Create `apps/web/src/app/(console)/account/security/page.tsx`:

```tsx
import { RouteState } from "@/shared/ui/route-state";
export default function AccountSecurityPage() { return <RouteState title="账户安全" description="当前阶段只验证账户访问边界。" />; }
```

Do not add fake balances, successful generations, model output, or Provider claims.

- [ ] **Step 8: Add route-level Loading, Error, and Not Found states**

Create `apps/web/src/app/loading.tsx`:

```tsx
import { Skeleton } from "@/shared/ui/feedback-state";
export default function Loading() { return <main className="mx-auto max-w-[1440px] p-6"><Skeleton label="正在加载页面" /></main>; }
```

Create `apps/web/src/app/error.tsx`:

```tsx
"use client";
import { Button } from "@/shared/ui/button";
import { ErrorState } from "@/shared/ui/feedback-state";
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) { return <main className="mx-auto max-w-[1440px] p-6"><ErrorState title="页面加载失败" description="当前页面没有完成加载，请重试。" action={<Button onClick={reset}>重试</Button>} /></main>; }
```

Create `apps/web/src/app/not-found.tsx`:

```tsx
import Link from "next/link";
import { Button } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/feedback-state";
export default function NotFound() { return <main className="mx-auto max-w-[1440px] p-6"><EmptyState title="页面不存在" description="返回模型广场继续浏览演示内容。" action={<Button asChild><Link href="/models">返回模型广场</Link></Button>} /></main>; }
```

- [ ] **Step 9: Run shell unit, boundary, brand, type, and build checks**

Run:

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/layout/app-shell.test.tsx
pnpm --filter @mosaic/web check:brand
pnpm --filter @mosaic/web check:boundaries
pnpm --filter @mosaic/web typecheck
pnpm --filter @mosaic/web lint
pnpm --filter @mosaic/web build
```

Expected: PASS; build output includes `/`, `/login`, `/models`, all dynamic route skeletons, `/usage`, and `/account/security`.

- [ ] **Step 10: Commit the complete shell**

Run:

```powershell
git add -- apps/web/src/app apps/web/src/features/auth apps/web/src/shared/config/routes.ts apps/web/src/shared/layout apps/web/src/shared/ui/route-state.tsx
git commit -m "feat: build responsive product shell"
```

## Task 8: Add FastAPI live/ready and PostgreSQL readiness

**Files:**

- Create: `apps/api/pyproject.toml`
- Create: `apps/api/.env.example`
- Create: `apps/api/app/__init__.py`
- Create: `apps/api/app/main.py`
- Create: `apps/api/app/api/health.py`
- Create: `apps/api/app/contracts/health.py`
- Create: `apps/api/app/contracts/errors.py`
- Create: `apps/api/app/core/settings.py`
- Create: `apps/api/app/infrastructure/database.py`
- Create: `apps/api/alembic.ini`
- Create: `apps/api/migrations/env.py`
- Create: `apps/api/migrations/script.py.mako`
- Create: `apps/api/migrations/versions/20260820_0001_bootstrap.py`
- Create: `apps/api/tests/api/test_health.py`
- Create: `apps/api/tests/contracts/test_schema_parity.py`
- Create: `apps/api/tests/contracts/test_migration_head.py`
- Create: `infra/compose/docker-compose.yml`

- [ ] **Step 1: Create the Python project and failing API tests**

Create `apps/api/pyproject.toml`:

```toml
[project]
name = "mosaic-api"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "alembic>=1.16,<2",
  "asyncpg>=0.30,<1",
  "fastapi>=0.116,<1",
  "pydantic-settings>=2.10,<3",
  "sqlalchemy>=2.0,<3",
  "uvicorn[standard]>=0.35,<1"
]

[dependency-groups]
dev = [
  "httpx>=0.28,<1",
  "jsonschema>=4.25,<5",
  "mypy>=1.17,<2",
  "pytest>=8.4,<9",
  "pytest-asyncio>=1.1,<2",
  "ruff>=0.12,<1"
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
```

Create `apps/api/tests/api/test_health.py`:

```py
from collections.abc import AsyncIterator

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.health import database_ready
from app.main import create_app


async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_live_returns_200_without_database_probe() -> None:
    app = create_app()
    async for client in client_for(app):
        response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"service": "mosaic-api", "status": "ok", "version": "0.1.0"}


@pytest.mark.asyncio
async def test_ready_success_and_failure_use_stable_contracts() -> None:
    app = create_app()
    app.dependency_overrides[database_ready] = lambda: True
    async for client in client_for(app):
        ready = await client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    app.dependency_overrides[database_ready] = lambda: False
    async for client in client_for(app):
        failed = await client.get("/api/v1/health/ready")
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "DATABASE_NOT_READY"
    assert "postgresql" not in str(failed.json()).lower()
```

- [ ] **Step 2: Sync dependencies and verify tests fail**

Run:

```powershell
uv sync --project apps/api --dev
uv run --project apps/api pytest -q
```

Expected: FAIL because application modules do not exist.

- [ ] **Step 3: Implement settings, contracts, and database probe**

Create `apps/api/app/core/settings.py`:

```py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_version: str = "0.1.0"
    database_url: str = "postgresql+asyncpg://mosaic:mosaic@127.0.0.1:5432/mosaic"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
```

Create `apps/api/app/contracts/health.py`:

```py
from typing import Literal
from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: Literal["mosaic-api"] = "mosaic-api"
    status: Literal["ok", "ready"]
    version: str
```

Create `apps/api/app/contracts/errors.py`:

```py
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
```

Create `apps/api/app/infrastructure/database.py`:

```py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.settings import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)


async def probe_database() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Implement health routes and the application factory**

Create `apps/api/app/api/health.py`:

```py
from typing import Annotated
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.contracts.errors import ErrorBody, ErrorResponse
from app.contracts.health import HealthResponse
from app.core.settings import settings
from app.infrastructure.database import probe_database

router = APIRouter(prefix="/api/v1/health", tags=["health"])


async def database_ready() -> bool:
    return await probe_database()


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version)


@router.get("/ready", response_model=HealthResponse, responses={503: {"model": ErrorResponse}})
async def ready(is_ready: Annotated[bool, Depends(database_ready)]) -> HealthResponse | JSONResponse:
    if is_ready:
        return HealthResponse(status="ready", version=settings.app_version)
    body = ErrorResponse(error=ErrorBody(code="DATABASE_NOT_READY", message="服务尚未准备好", request_id="health-ready", retryable=True))
    return JSONResponse(status_code=503, content=body.model_dump())
```

Create `apps/api/app/main.py`:

```py
from fastapi import FastAPI
from app.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="MOSAIC Platform API", version="0.1.0")
    app.include_router(health_router)
    return app


app = create_app()
```

Create empty `__init__.py` files in `app`, `app/api`, `app/contracts`, `app/core`, and `app/infrastructure`.

- [ ] **Step 5: Verify Python responses against the neutral schemas**

Create `apps/api/tests/contracts/test_schema_parity.py`:

```py
import json
from pathlib import Path
from jsonschema import validate
from app.contracts.errors import ErrorBody, ErrorResponse
from app.contracts.health import HealthResponse

SCHEMAS = Path(__file__).parents[4] / "packages" / "contracts" / "schemas"


def test_python_contracts_match_neutral_schemas() -> None:
    health = HealthResponse(status="ready", version="0.1.0").model_dump()
    validate(health, json.loads((SCHEMAS / "health.schema.json").read_text(encoding="utf-8")))
    error = ErrorResponse(error=ErrorBody(code="DATABASE_NOT_READY", message="服务尚未准备好", request_id="health-ready", retryable=True)).model_dump()
    validate(error, json.loads((SCHEMAS / "api-error.schema.json").read_text(encoding="utf-8")))
```

- [ ] **Step 6: Add PostgreSQL Compose and safe environment example**

Create `infra/compose/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: mosaic
      POSTGRES_USER: mosaic
      POSTGRES_PASSWORD: mosaic
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mosaic -d mosaic"]
      interval: 5s
      timeout: 3s
      retries: 10
    volumes:
      - mosaic_postgres:/var/lib/postgresql/data

volumes:
  mosaic_postgres:
```

Create `apps/api/.env.example`:

```dotenv
DATABASE_URL=postgresql+asyncpg://mosaic:mosaic@127.0.0.1:5432/mosaic
```

No Provider or production credentials belong in this file.

Create `apps/api/alembic.ini`:

```ini
[alembic]
script_location = %(here)s/migrations
prepend_sys_path = %(here)s
sqlalchemy.url = postgresql+asyncpg://mosaic:mosaic@127.0.0.1:5432/mosaic
```

Create `apps/api/migrations/env.py`:

```py
import asyncio
from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool
from app.core.settings import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
```

Create `apps/api/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

Create `apps/api/migrations/versions/20260820_0001_bootstrap.py`:

```py
"""Bootstrap the migration chain without introducing business tables."""
from collections.abc import Sequence

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

Create `apps/api/tests/contracts/test_migration_head.py`:

```py
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_bootstrap_revision_is_the_single_migration_head() -> None:
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260820_0001"]
```

- [ ] **Step 7: Run API tests and static checks**

Run:

```powershell
uv run --project apps/api pytest -q
uv run --project apps/api ruff check apps/api/app apps/api/tests
uv run --project apps/api mypy apps/api/app
uv run --project apps/api alembic -c apps/api/alembic.ini heads
```

Expected: all commands exit 0; Alembic prints `20260820_0001 (head)`.

- [ ] **Step 8: Prove live and unavailable-ready semantics in the current environment**

Docker is not installed in the current checkout environment. Do not install it implicitly and do not claim a real PostgreSQL readiness pass. Start only the API:

```powershell
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

In a second terminal run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live
try { Invoke-WebRequest http://127.0.0.1:8000/api/v1/health/ready -ErrorAction Stop } catch { $_.Exception.Response.StatusCode.value__ }
```

Expected: live returns `status=ok`; ready returns HTTP 503 because PostgreSQL is unavailable. This proves the endpoint does not report false readiness. Record real PostgreSQL readiness as `NOT_RUN_ENVIRONMENT` until Docker or an approved PostgreSQL instance is provided. Stop uvicorn after the check.

- [ ] **Step 9: Commit the backend skeleton**

Run:

```powershell
git add -- apps/api infra/compose apps/api/uv.lock
git commit -m "feat: add platform api health skeleton"
```

## Task 9: Add browser, accessibility, and visual evidence gates

**Files:**

- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/e2e/shell.spec.ts`
- Create: `apps/web/e2e/a11y.spec.ts`
- Create: `apps/web/e2e/api-smoke.spec.ts`
- Modify: `package.json`

- [ ] **Step 1: Add Playwright configuration**

Create `apps/web/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    {
      command: "pnpm dev",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: true,
      timeout: 120000,
    },
    {
      command: "uv run --project ../api uvicorn app.main:app --app-dir ../api --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/v1/health/live",
      reuseExistingServer: true,
      timeout: 120000,
    },
  ],
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "wide", use: { ...devices["Desktop Chrome"], viewport: { width: 1728, height: 1117 } } },
    { name: "mobile", use: { ...devices["iPhone 13"], viewport: { width: 390, height: 844 } } },
  ],
});
```

- [ ] **Step 2: Write route, responsive, and screenshot tests**

Create `apps/web/e2e/shell.spec.ts`:

```ts
import { expect, test, type Page } from "@playwright/test";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "进入内部演示" }).click();
  await expect(page).toHaveURL(/\/models$/);
}

test("public, auth, and console routes render honest shell evidence", async ({ page }, testInfo) => {
  for (const [path, heading] of [["/", "一个入口，进入专业多模态创作。"], ["/login", "邀请账户登录"]] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
  await signIn(page);
  await expect(page.getByRole("heading", { name: "模型广场" })).toBeVisible();
  if (testInfo.project.name !== "mobile") {
    await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  } else {
    await page.getByRole("button", { name: "打开导航" }).click();
    await expect(page.getByRole("dialog", { name: "移动导航" })).toBeVisible();
  }
  await expect(page).toHaveScreenshot(`shell-${testInfo.project.name}.png`, { fullPage: true });
});

test("all approved route skeletons are reachable", async ({ page }) => {
  await signIn(page);
  const routes = ["/models", "/chat/demo-conversation", "/studio/image/qwen-image", "/studio/video/hunyuan-video-1-5", "/studio/audio/qwen3-tts-voice-design", "/generations", "/generations/demo-job", "/usage", "/account/security"];
  for (const route of routes) {
    await page.goto(route);
    await expect(page.getByText("demo_scaffolding")).toBeVisible();
  }
});

test("protected routes redirect an unauthenticated demo session", async ({ page }) => {
  await page.goto("/models");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "邀请账户登录" })).toBeVisible();
});
```

- [ ] **Step 3: Add axe gates**

Create `apps/web/e2e/a11y.spec.ts`:

```ts
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

for (const path of ["/", "/login", "/models"] as const) {
  test(`${path} has no serious accessibility violations`, async ({ page }) => {
    if (path === "/models") {
      await page.goto("/login");
      await page.getByRole("button", { name: "进入内部演示" }).click();
      await expect(page).toHaveURL(/\/models$/);
    }
    await page.goto(path);
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter((item) => item.impact === "serious" || item.impact === "critical");
    expect(serious).toEqual([]);
  });
}
```

- [ ] **Step 4: Prove the browser-to-API rewrite**

Create `apps/web/e2e/api-smoke.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("browser reaches FastAPI live and unavailable-ready through the Next rewrite", async ({ request }) => {
  const live = await request.get("/api/v1/health/live");
  expect(live.status()).toBe(200);
  await expect(live.json()).resolves.toEqual({ service: "mosaic-api", status: "ok", version: "0.1.0" });
  const ready = await request.get("/api/v1/health/ready");
  expect(ready.status()).toBe(503);
  await expect(ready.json()).resolves.toMatchObject({ error: { code: "DATABASE_NOT_READY" } });
});
```

This test requires FastAPI on `127.0.0.1:8000`. It proves the browser path and honest readiness failure without pretending PostgreSQL was exercised.

- [ ] **Step 5: Install the browser and establish the approved screenshot baseline**

Run:

```powershell
pnpm --filter @mosaic/web exec playwright install chromium
pnpm --filter @mosaic/web test:e2e -- --update-snapshots
```

Expected: the first run creates reviewed baselines for `desktop`, `wide`, and `mobile`. Inspect every image before committing; confirm no overflow, old brand, dark-universe design, fake success data, or generic three-card layout.

- [ ] **Step 6: Run the complete first-plan gate without updating evidence**

Run:

```powershell
pnpm verify:web
uv run --project apps/api pytest -q
uv run --project apps/api ruff check apps/api/app apps/api/tests
uv run --project apps/api mypy apps/api/app
pnpm --filter @mosaic/web test:e2e
git diff --check
```

Expected: every command exits 0. The normal Playwright gate must pass without `--update-snapshots`.

- [ ] **Step 7: Record exact first-plan evidence**

Create `docs/evidence/foundation-shell.md` containing:

```markdown
# Foundation and Product Shell Evidence

- Design status: demo_scaffolding
- Provider status: provider_unverified
- Web lint: PASS
- Web typecheck: PASS
- Contracts tests: PASS
- Design-token drift: PASS
- Web unit tests: PASS
- Next build: PASS
- API pytest: PASS
- Ruff: PASS
- mypy: PASS
- Playwright desktop: PASS
- Playwright wide: PASS
- Playwright mobile: PASS
- axe serious/critical: 0
- Browser to API live path: PASS
- Browser to API unavailable-ready path: PASS
- Real PostgreSQL readiness: NOT_RUN_ENVIRONMENT

This evidence proves only the foundation and product shell. It does not prove authentication, model invocation, task execution, asset storage, billing, or data-center deployment.
```

Replace each `PASS` only after observing the corresponding command in the same checkout. If any command fails, record `FAIL` and do not commit a success claim.

- [ ] **Step 8: Commit the verified first-plan evidence**

Run:

```powershell
git add -- apps/web/e2e apps/web/playwright.config.ts apps/web/package.json package.json docs/evidence/foundation-shell.md
git commit -m "test: verify mosaic foundation shell"
git status --short --branch
```

Expected: commit succeeds; status shows only the user-owned pre-existing untracked documents and no generated test debris.

## Final self-review checklist

Before calling this plan complete, verify:

- [ ] Every approved route exists and displays `demo_scaffolding`, never fake success.
- [ ] `MOSAIC` appears in product code only in centralized brand configuration and its test.
- [ ] `NEXUS AI`, `Qwen2.5`, Provider IDs, parameter-size badges, quantization, license, and snapshot dates do not appear in product UI.
- [ ] JSON Schema rejects Provider and deployment fields from public model payloads.
- [ ] `tokens.json` is the only machine-readable design-token source and the drift test passes.
- [ ] Shared UI has no model, job, ledger, or Provider knowledge.
- [ ] Routes and UI do not call `fetch` or import concrete Demo/API services.
- [ ] DemoStateStore is versioned, SSR-safe through dependency injection, resettable, and tolerant of corrupt data.
- [ ] `live` does not depend on PostgreSQL; `ready` returns 503 when PostgreSQL is unavailable.
- [ ] Next rewrite proves a browser can reach FastAPI without a separate CORS policy.
- [ ] Real PostgreSQL readiness remains explicitly `NOT_RUN_ENVIRONMENT` while Docker and PostgreSQL are unavailable.
- [ ] Desktop, wide, and mobile screenshot baselines are reviewed and stable.
- [ ] axe reports zero serious or critical issues on public, login, and console shells.
- [ ] No real Provider, Ollama, authentication, ledger, Worker, object storage, payment, or production deployment work entered this plan.
- [ ] Existing user documents and assets were preserved and were not silently committed.
