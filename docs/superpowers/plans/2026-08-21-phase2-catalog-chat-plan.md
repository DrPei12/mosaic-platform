# MOSAIC Phase 2 Catalog and Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Foundation Shell placeholders with a high-fidelity, reference-matched model marketplace and deterministic text-chat demo that survives refresh and preserves strict Provider/API boundaries.

**Architecture:** Extend the neutral contracts and migrate the single DemoStateStore from schema v1 to v2. Model and conversation features depend only on new service ports selected in the existing composition root. UI presentation metadata and project media remain frontend-owned; public API contracts never expose Provider or deployment fields.

**Tech Stack:** Existing Next.js 16 App Router, React 19, TypeScript strict, Tailwind CSS v4, Radix Dialog, Motion, Phosphor Icons, Vitest/Testing Library, Playwright/axe, JSON Schema Draft 2020-12.

**Worker configuration:** Every implementation and review subagent uses `gpt-5.6-luna` with `max` reasoning.

---

## Scope

In scope:

- 12 canonical demo models and public-only contracts;
- category, search, collection and favorite behavior;
- reference-matched desktop/mobile marketplace;
- model detail drawer and correct route actions;
- versioned DemoScenario and DemoState v1→v2 migration;
- deterministic text conversations, streaming events, stop, regenerate and refresh resume;
- reference-matched desktop/mobile chat workspace;
- mobile bottom navigation and chat-specific responsive behavior;
- unit, contract, E2E, axe, geometry and visual evidence.

Out of scope:

- real Provider/model calls;
- server-side authentication or protected data;
- real balance, reservations, ledger or billing;
- image/video/audio job submission or results;
- uploads, object storage or PostgreSQL business persistence;
- Ollama public access.

## Canonical model IDs

```text
qwen-3-5                         Qwen 3.5                         text   chat
deepseek-v4                      DeepSeek V4                      text   chat
glm-5-2                          GLM 5.2                          text   chat
kimi-k2-7-code                   Kimi K2.7 Code                   text   chat
gpt-oss                          GPT-OSS                          text   chat
gemma-4                          Gemma 4                          text   chat
qwen-image                       Qwen Image                       image  text_to_image
flux-2                           FLUX 2                           image  text_to_image
hunyuan-video-1-5                HunyuanVideo 1.5                 video  image_to_video
qwen3-tts-voice-design           Qwen3-TTS 1.7B VoiceDesign      audio  tts
qwen3-tts-custom-voice           Qwen3-TTS 1.7B CustomVoice      audio  tts
qwen3-tts-base                   Qwen3-TTS 1.7B Base             audio  tts
```

All use `availability: "demo"`. No public object contains Provider, revision, deployment, quantization, precision, license, snapshot or hidden parameter variants.

## Task 1: Extend neutral Phase 2 contracts

**Files:**

- Create: `packages/contracts/schemas/model-catalog.schema.json`
- Create: `packages/contracts/schemas/conversation.schema.json`
- Create: `packages/contracts/schemas/chat-stream-event.schema.json`
- Create: `packages/contracts/src/phase2-contracts.test.ts`
- Modify: `packages/contracts/src/index.ts`

- [ ] **Step 1: Write failing contract tests**

Create tests that validate one exact catalog fixture, one conversation fixture and all five event variants. Tests must reject Provider/deployment fields, unknown event types, non-monotonic-invalid sequence values, empty IDs and missing required fields.

Use Ajv 2020 and the existing forbidden-field list. The first run must fail because the schemas and exported types do not exist.

Run:

```powershell
pnpm --filter @mosaic/contracts exec vitest run src/phase2-contracts.test.ts
```

Expected: FAIL with missing schema/module evidence.

- [ ] **Step 2: Add the catalog contract**

`model-catalog.schema.json` must use Draft 2020-12, `additionalProperties: false`, and this shape:

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["items"],
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["model", "collections"],
        "properties": {
          "model": { "$ref": "./public-product-model.schema.json" },
          "collections": {
            "type": "array",
            "uniqueItems": true,
            "items": { "enum": ["featured", "popular", "new"] }
          }
        }
      }
    }
  }
}
```

Register the referenced public schema with Ajv in tests rather than weakening `$ref` resolution.

- [ ] **Step 3: Add conversation and stream schemas**

Conversation message fields:

```text
message_id, role, content, status, created_at, optional request_id
```

Conversation fields:

```text
conversation_id, product_model_id, title, messages, updated_at, active_request_id
```

`active_request_id` is string or null. Message status is `streaming|complete|stopped|failed`.

Stream schema uses `oneOf` with discriminator `type`: `started`, `delta`, `completed`, `stopped`, `failed`. Every variant requires request/conversation/message IDs and integer sequence ≥0. `started.sequence` is const 0; delta requires nonempty `delta`; completed requires `content`; failed requires the existing error body shape.

- [ ] **Step 4: Export exact TypeScript types**

Add to `packages/contracts/src/index.ts`:

```ts
export type CatalogCollection = "featured" | "popular" | "new";

export interface PublicModelCatalogItem {
  model: PublicProductModel;
  collections: CatalogCollection[];
}

export interface PublicModelCatalogResponse {
  items: PublicModelCatalogItem[];
}

export type ConversationRole = "user" | "assistant";
export type ConversationMessageStatus = "streaming" | "complete" | "stopped" | "failed";

export interface ConversationMessage {
  message_id: string;
  role: ConversationRole;
  content: string;
  status: ConversationMessageStatus;
  created_at: string;
  request_id?: string;
}

export interface ConversationSummary {
  conversation_id: string;
  product_model_id: string;
  title: string;
  preview: string;
  updated_at: string;
}

export interface Conversation {
  conversation_id: string;
  product_model_id: string;
  title: string;
  messages: ConversationMessage[];
  updated_at: string;
  active_request_id: string | null;
}

export type ChatStreamEvent =
  | { type: "started"; request_id: string; conversation_id: string; message_id: string; sequence: 0 }
  | { type: "delta"; request_id: string; conversation_id: string; message_id: string; sequence: number; delta: string }
  | { type: "completed"; request_id: string; conversation_id: string; message_id: string; sequence: number; content: string }
  | { type: "stopped"; request_id: string; conversation_id: string; message_id: string; sequence: number }
  | { type: "failed"; request_id: string; conversation_id: string; message_id: string; sequence: number; error: ApiErrorResponse["error"] };
```

- [ ] **Step 5: Run contract gates and commit**

```powershell
pnpm --filter @mosaic/contracts test
pnpm --filter @mosaic/contracts exec tsc --noEmit
pnpm verify:web
git add -- packages/contracts
git commit -m "feat: define phase two public contracts"
```

Expected: all contract tests and existing gates pass.

## Task 2: Add DemoScenario and migrate DemoState to v2

**Files:**

- Create: `apps/web/src/entities/models/catalog.ts`
- Create: `apps/web/src/entities/chat/conversation.ts`
- Create: `apps/web/src/shared/demo/demo-scenario.ts`
- Create: `apps/web/src/shared/demo/demo-scenario.test.ts`
- Modify: `apps/web/src/shared/demo/demo-state-store.ts`
- Modify: `apps/web/src/shared/demo/demo-state-store.test.ts`

- [ ] **Step 1: Write failing scenario and migration tests**

Tests must assert:

- exact model set and category counts 6/2/1/3;
- all availability values equal `demo`;
- only approved TTS names contain `1.7B`;
- at least two seeded Qwen 3.5 conversations and two-turn scripts;
- v2 round-trips favorites, selected model, conversations, requests and drafts;
- valid v1 migrates only auth fields and hydrates scenario data;
- corrupt v2, unknown version and future version recover initial state;
- storage get/set/remove fallbacks from Phase 1 still pass;
- no password/credential field is persisted;
- `update()` composes consecutive writes without lost updates.

Run focused tests and record RED before implementation.

- [ ] **Step 2: Define frontend presentation metadata**

`entities/models/catalog.ts` owns local visual metadata, never public API fields:

```ts
export type ModelCardMedia =
  | { kind: "abstract"; src: string; alt: string }
  | { kind: "gallery"; sources: readonly { src: string; alt: string }[] }
  | { kind: "video"; src: string; alt: string }
  | { kind: "audio"; waveform: readonly number[]; durationLabel: string }
  | { kind: "none" };

export interface ModelPresentation {
  productModelId: string;
  cardStyle: "hero" | "gallery" | "video" | "audio" | "compact";
  media: ModelCardMedia;
  actionLabel: string;
}
```

Presentation assets use `/media/models/*`; API adapters map by stable product ID.

- [ ] **Step 3: Create immutable DemoScenario**

The scenario exports `DEMO_SCENARIO` with `scenarioVersion: 1`, seed `8202026`, 12 public models, presentations, two seeded conversations and deterministic turn scripts. Freeze top-level arrays/objects in development or expose readonly types.

Capabilities are user-facing and nonnumeric unless verified. Do not include context-window or Provider claims.

- [ ] **Step 4: Implement DemoState v2 and v1 migration**

Use keys:

```ts
export const DEMO_STATE_STORAGE_KEY = "mosaic.demo-state.v2";
export const LEGACY_DEMO_STATE_STORAGE_KEY = "mosaic.demo-state.v1";
```

State shape:

```ts
export interface DemoState {
  schemaVersion: 2;
  seed: 8202026;
  authenticated: boolean;
  passwordChangeRequired: boolean;
  favorites: string[];
  selectedModelId: string | null;
  conversations: Record<string, DemoConversationState>;
  chatRequests: Record<string, DemoChatRequestState>;
  drafts: Record<string, string>;
  updatedAt: string;
}
```

Add `update(mutator)` that reads once, applies the pure mutator, validates and writes. Migrate v1 only when v2 is absent. Preserve the Phase 1 sticky in-memory fallback and canonical timestamp handling. Do not remove the v1 key as a prerequisite for success.

- [ ] **Step 5: Run state gates and commit**

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/demo/demo-scenario.test.ts src/shared/demo/demo-state-store.test.ts
pnpm verify:web
git add -- apps/web/src/entities apps/web/src/shared/demo
git commit -m "feat: add phase two demo scenario state"
```

## Task 3: Implement model catalog services and registry wiring

**Files:**

- Modify: `apps/web/src/services/interfaces.ts`
- Create: `apps/web/src/services/demo-model-catalog-service.ts`
- Create: `apps/web/src/services/demo-model-catalog-service.test.ts`
- Create: `apps/web/src/services/api-model-catalog-service.ts`
- Create: `apps/web/src/services/api-model-catalog-service.test.ts`
- Modify: `apps/web/src/services/create-service-registry.ts`
- Modify: `apps/web/src/services/create-service-registry.test.ts`

- [ ] **Step 1: Write failing service tests**

Demo tests:

- returns exactly 12 canonical entries;
- category and search are an intersection;
- search covers display name, description and capabilities;
- collection filter works;
- empty search does not mutate scenario;
- toggleFavorite is idempotent and persists;
- returned objects contain no forbidden internal fields.

API tests:

- builds encoded query parameters;
- validates exact catalog response against runtime rules;
- rejects extra Provider/deployment fields and malformed responses;
- maps 404 and 5xx to typed service errors;
- preserves AbortError.

- [ ] **Step 2: Extend service interfaces**

```ts
export interface ModelCatalogQuery {
  category?: ModelCategory;
  search?: string;
  collection?: CatalogCollection;
}

export interface CatalogModel {
  item: PublicModelCatalogItem;
  presentation: ModelPresentation;
  favorite: boolean;
}

export interface ModelCatalogService {
  list(query?: ModelCatalogQuery, signal?: AbortSignal): Promise<readonly CatalogModel[]>;
  get(productModelId: string, signal?: AbortSignal): Promise<CatalogModel>;
  toggleFavorite(productModelId: string, signal?: AbortSignal): Promise<boolean>;
}
```

Add `modelCatalog` to `ServiceRegistry`.

- [ ] **Step 3: Implement Demo and API adapters**

Demo adapter uses scenario + store, normalizes search with `trim().toLocaleLowerCase("zh-CN")`, sorts by scenario order and updates favorites only via store.update.

API adapter calls `/api/v1/models`, uses a strict runtime validator, then attaches local presentation by ID. `toggleFavorite` remains a frontend demo preference and uses the same store in Phase 2; do not invent a backend favorite endpoint.

- [ ] **Step 4: Wire composition root and boundary scan**

Both demo and API mode receive a ModelCatalogService. Extend `check-boundaries.mjs` expected roots to include `src/features`; tests prove feature code cannot call fetch, import concrete services or import DemoScenario/Store.

- [ ] **Step 5: Run gates and commit**

```powershell
pnpm --filter @mosaic/web exec vitest run src/services/demo-model-catalog-service.test.ts src/services/api-model-catalog-service.test.ts src/services/create-service-registry.test.ts
pnpm verify:web
git add -- apps/web/src/services apps/web/scripts
git commit -m "feat: add model catalog service adapters"
```

## Task 4: Build the reference-matched model marketplace

**Files:**

- Create: `apps/web/src/features/models/model-marketplace.tsx`
- Create: `apps/web/src/features/models/model-filter-bar.tsx`
- Create: `apps/web/src/features/models/model-card.tsx`
- Create: `apps/web/src/features/models/model-detail-drawer.tsx`
- Create: `apps/web/src/features/models/model-marketplace.test.tsx`
- Modify: `apps/web/src/app/(console)/models/page.tsx`
- Create: `apps/web/src/app/(console)/models/loading.tsx`

- [ ] **Step 1: Write failing RTL tests**

Cover canonical names, category tabs, combined search/category, empty recovery, favorite separation from navigation, drawer focus/Escape, correct CTA route per task type, loading/error/offline states and 44px targets.

- [ ] **Step 2: Implement filter and page state**

`ModelMarketplace` is the only service-aware component. It loads through `createBrowserServiceRegistry().modelCatalog`, keeps category/search/collection in URL search parameters, aborts stale requests and displays tokenized Loading/Error/Empty states.

`ModelFilterBar` is presentational and exposes accessible tabs/search/filter actions. No component imports scenario or concrete adapters.

- [ ] **Step 3: Implement differential model cards**

Use `next/image` for project assets with fixed aspect ratios. Desktop grid is `1.1fr 1fr`; mobile is one column. Implement hero/gallery/video/audio/compact variants without nested cards. Bookmark uses `aria-pressed`; card CTA is independent.

Text models route to a newly created conversation. Media models route to their existing studio route, which remains an honest future-stage page.

- [ ] **Step 4: Implement model detail drawer**

Radix Dialog/Drawer uses a real trigger, focus trap, Escape and focus restoration. It shows only public model information and action; no Provider or availability overclaim.

- [ ] **Step 5: Run gates and commit**

```powershell
pnpm --filter @mosaic/web exec vitest run src/features/models/model-marketplace.test.tsx
pnpm verify:web
git add -- apps/web/src/features/models apps/web/src/app/(console)/models
git commit -m "feat: build high fidelity model marketplace"
```

PowerShell execution must quote paths containing parentheses when staging.

## Task 5: Implement deterministic conversation services

**Files:**

- Create: `apps/web/src/shared/demo/demo-scheduler.ts`
- Create: `apps/web/src/shared/demo/demo-scheduler.test.ts`
- Create: `apps/web/src/features/chat/conversation-reducer.ts`
- Create: `apps/web/src/features/chat/conversation-reducer.test.ts`
- Create: `apps/web/src/services/demo-conversation-service.ts`
- Create: `apps/web/src/services/demo-conversation-service.test.ts`
- Create: `apps/web/src/services/api-conversation-service.ts`
- Create: `apps/web/src/services/api-conversation-service.test.ts`
- Modify: `apps/web/src/services/interfaces.ts`
- Modify: `apps/web/src/services/create-service-registry.ts`
- Modify: `apps/web/src/services/create-service-registry.test.ts`

- [ ] **Step 1: Write reducer and service RED tests**

Cover event ordering, stale request/sequence rejection, single terminal, two-turn context, deterministic chunks, stop, regenerate, duplicate key, conflicting payload, busy conversation, timeout, content rejection and refresh resume from nextChunkIndex.

- [ ] **Step 2: Implement scheduler and pure reducer**

```ts
export interface DemoScheduler {
  wait(delayMs: number, signal?: AbortSignal): Promise<void>;
}
```

Real scheduler uses `setTimeout` and AbortSignal cleanup. Tests inject controllable scheduler; no test uses `waitForTimeout`.

Reducer accepts current conversation + event and ignores old request IDs, duplicate sequence and any event after terminal state.

- [ ] **Step 3: Extend ConversationService**

```ts
export interface ConversationStream {
  requestId: string;
  messageId: string;
  events: AsyncIterable<ChatStreamEvent>;
}

export interface ConversationService {
  listConversations(signal?: AbortSignal): Promise<readonly ConversationSummary[]>;
  getConversation(conversationId: string, signal?: AbortSignal): Promise<Conversation>;
  createConversation(input: { productModelId: string; clientRequestId: string }, signal?: AbortSignal): Promise<Conversation>;
  sendMessage(input: { conversationId: string; content: string; clientRequestId: string }, signal?: AbortSignal): Promise<ConversationStream>;
  resumeMessage(input: { conversationId: string; requestId: string }, signal?: AbortSignal): Promise<ConversationStream>;
  regenerate(input: { conversationId: string; messageId: string; clientRequestId: string }, signal?: AbortSignal): Promise<ConversationStream>;
  stopMessage(input: { conversationId: string; requestId: string }, signal?: AbortSignal): Promise<void>;
}
```

- [ ] **Step 4: Implement Demo conversation semantics**

All writes use store.update. Stable request IDs derive from operation/conversation/client key. Canonical payload fingerprint is deterministic. Service persists the user message, one assistant placeholder, next chunk index, partial content and terminal state.

Subscription Abort does not change business status. stopMessage changes terminal state and aborts active scheduler. resumeMessage starts at persisted nextChunkIndex.

- [ ] **Step 5: Implement API adapter**

Implement strict endpoint calls and SSE parser for started/delta/completed/stopped/failed. Use `Idempotency-Key`, validate every event, propagate AbortError and reject malformed/extra fields as `STREAM_RESPONSE_INVALID`. No API endpoint is claimed operational.

- [ ] **Step 6: Wire registry, run and commit**

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/demo/demo-scheduler.test.ts src/features/chat/conversation-reducer.test.ts src/services/demo-conversation-service.test.ts src/services/api-conversation-service.test.ts
pnpm verify:web
git add -- apps/web/src/shared/demo apps/web/src/features/chat apps/web/src/services
git commit -m "feat: add deterministic conversation services"
```

## Task 6: Build the reference-matched chat workspace

**Files:**

- Create: `apps/web/src/features/chat/chat-workspace.tsx`
- Create: `apps/web/src/features/chat/conversation-list.tsx`
- Create: `apps/web/src/features/chat/message-list.tsx`
- Create: `apps/web/src/features/chat/composer.tsx`
- Create: `apps/web/src/features/chat/stream-response.tsx`
- Create: `apps/web/src/features/chat/chat-workspace.test.tsx`
- Modify: `apps/web/src/app/(console)/chat/[conversationId]/page.tsx`
- Create: `apps/web/src/app/(console)/chat/[conversationId]/loading.tsx`

- [ ] **Step 1: Write failing component tests**

Cover seeded list, active switch, new session, no cross-contamination, loading/error/unknown conversation, ordered stream, stop partial, regenerate without duplicate user message, offline draft, duplicate-submit prevention and refresh active-request resume.

- [ ] **Step 2: Build the three-column desktop workspace**

Global nav remains 240px. Chat feature adds a 320–336px conversation column and flexible main area. The message canvas uses flat editorial rows, 40px avatars, hairline dividers and no colored bubble spam.

Main header is 80px and displays stable model name. Composer is sticky at the chat-region bottom, approximately 104px high, and messages scroll independently.

- [ ] **Step 3: Implement stream consumption**

ChatWorkspace owns an AbortController for subscriptions, folds events through the reducer, refreshes persisted service state, and distinguishes subscription abort from failed business status. It resumes an active request on mount.

- [ ] **Step 4: Implement stop, regenerate and draft behavior**

Composer uses controlled local draft plus persisted draft update. Stop preserves partial content. Regenerate targets the latest assistant message and keeps user-message count unchanged. Copy uses Clipboard API with accessible confirmation.

- [ ] **Step 5: Implement responsive chat behavior**

Below 768px, conversation list becomes a Radix drawer/top switcher; global bottom nav hides; a clear return-to-models action remains. Composer includes safe-area padding and never overlaps content.

- [ ] **Step 6: Run gates and commit**

```powershell
pnpm --filter @mosaic/web exec vitest run src/features/chat/chat-workspace.test.tsx
pnpm verify:web
git add -- apps/web/src/features/chat "apps/web/src/app/(console)/chat"
git commit -m "feat: build high fidelity text chat workspace"
```

## Task 7: Integrate mobile bottom navigation and shell geometry

**Files:**

- Create: `apps/web/src/shared/layout/mobile-bottom-navigation.tsx`
- Create: `apps/web/src/shared/layout/mobile-bottom-navigation.test.tsx`
- Modify: `apps/web/src/shared/layout/app-shell.tsx`
- Modify: `apps/web/src/shared/layout/top-bar.tsx`
- Modify: `apps/web/src/shared/layout/app-shell.test.tsx`

- [ ] **Step 1: Add failing layout tests**

Test TopBar desktop/mobile heights, bottom-nav items/active state/safe area, chat route bottom-nav hiding, main bottom padding and no duplicate navigation landmarks.

- [ ] **Step 2: Implement reference geometry**

TopBar uses 80px on desktop and 64px mobile. Bottom nav is fixed under 768px, three equal items, 76px plus safe-area. AppShell adds content padding only when bottom nav is present. Chat routes hide it.

Desktop navigation remains 240px and existing mobile drawer remains available for account/security routes.

- [ ] **Step 3: Run gates and commit**

```powershell
pnpm --filter @mosaic/web exec vitest run src/shared/layout
pnpm verify:web
git add -- apps/web/src/shared/layout
git commit -m "feat: align shell with phase two references"
```

## Task 8: Add Phase 2 browser, geometry, accessibility and evidence gates

**Files:**

- Create: `apps/web/e2e/model-marketplace.spec.ts`
- Create: `apps/web/e2e/chat.spec.ts`
- Create: `apps/web/e2e/phase2-a11y.spec.ts`
- Create: `apps/web/e2e/phase2-geometry.spec.ts`
- Create: committed Phase 2 snapshots
- Modify: `apps/web/e2e/shell.spec.ts`
- Modify: `apps/web/playwright.config.ts`
- Create: `docs/evidence/phase2-catalog-chat.md`

- [ ] **Step 1: Update Foundation Shell assertions**

Remove old expectations that `/models` and `/chat` display `demo_scaffolding`. Keep route access, login, Foundation API and remaining media-stage routes honest.

- [ ] **Step 2: Add marketplace E2E**

Assert exact 12 models and 6/2/1/3 counts, forbidden-field absence, filter/search intersection, empty recovery, favorite persistence, drawer keyboard behavior and correct route per category.

- [ ] **Step 3: Add chat E2E**

Assert Qwen 3.5 entry, seeded sessions, two deterministic streamed turns, stop at an observable delta, regenerate without duplicate user message, refresh resume and offline draft preservation. Never use `waitForTimeout`; wait on status/events.

- [ ] **Step 4: Add axe and keyboard gates**

Marketplace and chat must have zero serious/critical issues in desktop/wide/mobile. Keyboard path covers tabs, search, favorite, drawer, conversation switch, composer, stop and regenerate. Reduced-motion remains functional.

- [ ] **Step 5: Add geometry and visual gates**

Geometry assertions:

```text
desktop nav 240px ±1
desktop marketplace two columns
mobile marketplace one column
mobile no horizontal overflow
H1 56/64 marketplace and 40/48 chat/login
card border 1px, radius 12px
control min target 44px
canvas/surface/line/accent computed tokens
chat conversation column 320–336px
composer visible and nonoverlapping
```

Add 426×923 project/viewport or a dedicated geometry test in addition to existing 390×844.

Create reviewed snapshots for marketplace desktop/wide/mobile and chat desktop/wide/mobile. Initial generation uses `--update-snapshots`; normal Gate must pass without it. Inspect every image against the three approved references.

- [ ] **Step 6: Run complete gates and record evidence**

```powershell
pnpm verify:web
uv run --project apps/api pytest -q
uv run --project apps/api ruff check apps/api/app apps/api/tests
uv run --project apps/api mypy apps/api/app apps/api/migrations
pnpm --filter @mosaic/web test:e2e
git diff --check
```

Evidence records observed counts and explicitly states:

```text
Design status: demo_scaffolding
Provider status: provider_unverified
Real model invocation: NOT_IMPLEMENTED_SCOPE
Server-side authorization: NOT_IMPLEMENTED_SCOPE
Real PostgreSQL business persistence: NOT_IMPLEMENTED_SCOPE
Balance/ledger: N/A_PHASE_3
```

- [ ] **Step 7: Commit Phase 2 evidence**

```powershell
git add -- apps/web/e2e apps/web/playwright.config.ts docs/evidence/phase2-catalog-chat.md
git commit -m "test: verify phase two catalog and chat"
```

## Final self-review

- [ ] Reference images are committed and never used as cropped production assets.
- [ ] Canonical model names are exact; fictitious reference names do not appear.
- [ ] Provider/internal fields are absent from public contracts, DOM and screenshots.
- [ ] Media models do not fabricate generation results.
- [ ] DemoState v1 migration preserves auth and hydrates stable Phase 2 state.
- [ ] Favorites, conversations, requests and drafts share one state source.
- [ ] stop/regenerate/idempotency/refresh semantics have deterministic tests.
- [ ] Pages/features do not call fetch or concrete adapters.
- [ ] Marketplace and chat match reference hierarchy on desktop/mobile.
- [ ] Geometry, axe and behavior gates supplement snapshots.
- [ ] Normal Playwright Gate passes without updating snapshots.
- [ ] Evidence makes no Provider, real auth, balance or database claims.
