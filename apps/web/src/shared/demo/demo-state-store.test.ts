import { describe, expect, it } from "vitest";
import {
  createDemoStateStore,
  DEMO_STATE_STORAGE_KEY,
  LEGACY_DEMO_STATE_STORAGE_KEY,
  MAX_DEMO_CHAT_REQUESTS,
  MAX_DEMO_CONVERSATIONS,
  MAX_DEMO_DRAFT_LENGTH,
  MAX_DEMO_MESSAGES_PER_CONVERSATION,
  MAX_DEMO_STATE_BYTES,
  type DemoState,
  type StorageLike,
} from "./demo-state-store";
import { DEMO_SCENARIO } from "./demo-scenario";

const NOW = "2026-08-20T12:00:00.000Z";

function memoryStorage(initial: Record<string, string> = {}): StorageLike & {
  values: Map<string, string>;
} {
  const values = new Map(Object.entries(initial));
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, next) => {
      values.set(key, next);
    },
    removeItem: (key) => {
      values.delete(key);
    },
  };
}

function legacyState(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    schemaVersion: 1,
    seed: 8202026,
    authenticated: true,
    passwordChangeRequired: false,
    updatedAt: NOW,
    ...overrides,
  };
}

function storedState(overrides: Partial<DemoState> = {}): DemoState {
  return {
    ...createDemoStateStore({ storage: memoryStorage(), now: () => NOW }).read(),
    ...overrides,
  };
}

function expectInvalidPersistedState(state: unknown) {
  const initial = createDemoStateStore({ storage: memoryStorage(), now: () => NOW }).read();
  const store = createDemoStateStore({
    storage: memoryStorage({ [DEMO_STATE_STORAGE_KEY]: JSON.stringify(state) }),
    now: () => NOW,
  });
  expect(store.read()).toEqual(initial);
}

function expectValidPersistedState(state: DemoState) {
  const store = createDemoStateStore({
    storage: memoryStorage({ [DEMO_STATE_STORAGE_KEY]: JSON.stringify(state) }),
    now: () => NOW,
  });
  expect(store.read()).toEqual(state);
}

describe("DemoStateStore v2", () => {
  it("hydrates a fresh state from the immutable scenario", () => {
    const storage = memoryStorage();
    const store = createDemoStateStore({ storage, now: () => NOW });
    const state = store.read();

    expect(state).toMatchObject({
      schemaVersion: 2,
      seed: 8202026,
      authenticated: false,
      passwordChangeRequired: true,
      favorites: [],
      selectedModelId: "qwen-3-5",
      chatRequests: {},
      drafts: {},
      updatedAt: NOW,
    });
    expect(Object.keys(state.conversations)).toEqual(
      DEMO_SCENARIO.conversations.map((conversation) => conversation.conversation_id),
    );
  });

  it("round-trips favorites, selected model, conversations, requests and drafts", () => {
    const storage = memoryStorage();
    const store = createDemoStateStore({ storage, now: () => NOW });
    const initial = store.read();
    const conversationId = Object.keys(initial.conversations)[0]!;
    const next: DemoState = {
      ...initial,
      favorites: ["qwen-image", "qwen-3-5"],
      selectedModelId: "qwen-image",
      conversations: {
        ...initial.conversations,
        [conversationId]: {
          ...initial.conversations[conversationId]!,
          title: "已修改会话",
        },
      },
      chatRequests: {
        request_demo_001: {
          request_id: "request_demo_001",
          conversation_id: conversationId,
          message_id: initial.conversations[conversationId]!.messages[0]!.message_id,
          status: "streaming",
          next_chunk_index: 1,
          turn_index: 0,
        },
      },
      drafts: { [conversationId]: "离线草稿" },
      updatedAt: NOW,
    };

    const written = store.write(next);
    expect(written).toEqual({ ...next, updatedAt: NOW });
    expect(store.read()).toEqual(written);
    expect(JSON.parse(storage.values.get(DEMO_STATE_STORAGE_KEY) ?? "{}")).toEqual(written);
  });

  it("composes sequential updates without losing the previous update", () => {
    const store = createDemoStateStore({ storage: memoryStorage(), now: () => NOW });
    store.update((state) => ({ ...state, favorites: ["qwen-image"] }));
    const updated = store.update((state) => ({ ...state, selectedModelId: "deepseek-v4" }));

    expect(updated.favorites).toEqual(["qwen-image"]);
    expect(updated.selectedModelId).toBe("deepseek-v4");
  });

  it("does not destroy a valid state when a mutator returns an invalid value", () => {
    const storage = memoryStorage();
    const store = createDemoStateStore({ storage, now: () => NOW });
    const valid = store.update((state) => ({ ...state, favorites: ["qwen-image"] }));
    const invalid = store.update(
      () => ({ ...valid, favorites: "not-an-array" } as unknown as DemoState),
    );

    expect(invalid).toEqual(valid);
    expect(store.read()).toEqual(valid);
  });

  it("migrates a valid v1 state only when v2 is absent and keeps the legacy key", () => {
    const legacy = JSON.stringify(legacyState());
    const storage = memoryStorage({ [LEGACY_DEMO_STATE_STORAGE_KEY]: legacy });
    const store = createDemoStateStore({ storage, now: () => NOW });
    const migrated = store.read();

    expect(migrated.authenticated).toBe(true);
    expect(migrated.passwordChangeRequired).toBe(false);
    expect(migrated.favorites).toEqual([]);
    expect(migrated.selectedModelId).toBe("qwen-3-5");
    expect(Object.keys(migrated.conversations)).toHaveLength(DEMO_SCENARIO.conversations.length);
    expect(storage.values.has(LEGACY_DEMO_STATE_STORAGE_KEY)).toBe(true);
    expect(JSON.parse(storage.values.get(DEMO_STATE_STORAGE_KEY) ?? "{}").schemaVersion).toBe(2);
  });

  it("adds cursor -1 when hydrating a pre-cursor v2 active request with no chunks", () => {
    const state = storedState();
    const conversationId = Object.keys(state.conversations)[0]!;
    const conversation = state.conversations[conversationId]!;
    const requestId = "request-pre-cursor-v2";
    const legacyConversation: Record<string, unknown> = {
      ...conversation,
      active_request_id: requestId,
    };
    delete legacyConversation.active_request_cursor;
    const legacyV2 = {
      ...state,
      conversations: {
        ...state.conversations,
        [conversationId]: legacyConversation,
      },
      chatRequests: {
        [requestId]: {
          request_id: requestId,
          conversation_id: conversationId,
          message_id: conversation.messages[0]!.message_id,
          status: "streaming",
          next_chunk_index: 0,
          turn_index: 0,
        },
      },
    };
    const storage = memoryStorage({
      [DEMO_STATE_STORAGE_KEY]: JSON.stringify(legacyV2),
    });
    const migrated = createDemoStateStore({ storage, now: () => NOW }).read();

    expect(migrated.chatRequests[requestId]?.next_chunk_index).toBe(0);
    expect(migrated.conversations[conversationId]?.active_request_id).toBe(requestId);
    expect(migrated.conversations[conversationId]?.active_request_cursor).toBe(-1);
  });

  it("uses v2 when both v2 and v1 are present", () => {
    const storage = memoryStorage({
      [LEGACY_DEMO_STATE_STORAGE_KEY]: JSON.stringify(legacyState()),
    });
    const setup = createDemoStateStore({ storage, now: () => NOW });
    const v2 = setup.write({ ...setup.read(), authenticated: false, passwordChangeRequired: true });
    const store = createDemoStateStore({ storage, now: () => NOW });

    expect(store.read()).toEqual(v2);
    expect(store.read().authenticated).toBe(false);
  });

  it.each([
    "not-json",
    JSON.stringify({ schemaVersion: 99, seed: 8202026 }),
    JSON.stringify({ schemaVersion: 3, seed: 8202026 }),
  ])("recovers corrupt, unknown, and future v2 values to stable initial state", (raw) => {
    const store = createDemoStateStore({
      storage: memoryStorage({ [DEMO_STATE_STORAGE_KEY]: raw }),
      now: () => NOW,
    });

    expect(store.read()).toMatchObject({
      schemaVersion: 2,
      seed: 8202026,
      authenticated: false,
      passwordChangeRequired: true,
      favorites: [],
      selectedModelId: "qwen-3-5",
      updatedAt: NOW,
    });
  });

  it.each(["", "yesterday", "2026-02-30T12:00:00.000Z"])(
    "recovers a non-canonical updatedAt timestamp (%s)",
    (updatedAt) => {
      const valid = createDemoStateStore({ storage: memoryStorage(), now: () => NOW }).read();
      const store = createDemoStateStore({
        storage: memoryStorage({
          [DEMO_STATE_STORAGE_KEY]: JSON.stringify({ ...valid, updatedAt }),
        }),
        now: () => NOW,
      });

      expect(store.read().updatedAt).toBe(NOW);
      expect(store.read().authenticated).toBe(false);
    },
  );

  it("preserves a valid UTC timestamp without fractional milliseconds", () => {
    const store = createDemoStateStore({ storage: memoryStorage(), now: () => "2026-08-20T12:00:00Z" });
    const written = store.write({ ...store.read(), authenticated: true });

    expect(written.authenticated).toBe(true);
    expect(written.updatedAt).toBe("2026-08-20T12:00:00Z");
    expect(store.read()).toEqual(written);
  });

  it("persists authentication state and reset returns a fresh initial state", () => {
    const storage = memoryStorage();
    const store = createDemoStateStore({ storage, now: () => NOW });

    const authenticated = store.write({
      ...store.read(),
      authenticated: true,
      passwordChangeRequired: false,
    });

    expect(authenticated.authenticated).toBe(true);
    expect(store.read()).toEqual(authenticated);
    expect(store.reset()).toMatchObject({
      schemaVersion: 2,
      seed: 8202026,
      authenticated: false,
      passwordChangeRequired: true,
      favorites: [],
      selectedModelId: "qwen-3-5",
      updatedAt: NOW,
    });
    expect(store.read().authenticated).toBe(false);
  });

  it("keeps a session-local fallback when storage operations throw", () => {
    let getCalls = 0;
    const unavailableStorage: StorageLike = {
      getItem: () => {
        getCalls += 1;
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    const store = createDemoStateStore({ storage: unavailableStorage, now: () => NOW });

    expect(() => store.read()).not.toThrow();
    expect(() => store.write({ ...store.read(), authenticated: true })).not.toThrow();
    expect(store.read().authenticated).toBe(true);
    expect(() => store.reset()).not.toThrow();
    expect(store.read().authenticated).toBe(false);
    expect(getCalls).toBeGreaterThan(0);
  });

  it("keeps a written state when reads fail but writes succeed", () => {
    let persisted: string | null = null;
    const storage: StorageLike = {
      getItem: () => {
        throw new Error("blocked reads");
      },
      setItem: (_key, next) => {
        persisted = next;
      },
      removeItem: () => {
        persisted = null;
      },
    };
    const store = createDemoStateStore({ storage, now: () => NOW });
    const written = store.write({ ...store.read(), authenticated: true });

    expect(persisted).not.toBeNull();
    expect(store.read()).toEqual(written);
  });

  it("preserves a direct first write when the next read fails", () => {
    const storage: StorageLike = {
      getItem: () => {
        throw new Error("blocked reads");
      },
      setItem: () => undefined,
      removeItem: () => undefined,
    };
    const store = createDemoStateStore({ storage, now: () => NOW });

    const written = store.write({
      schemaVersion: 1,
      seed: 8202026,
      authenticated: true,
      passwordChangeRequired: false,
      updatedAt: "2026-08-19T12:00:00.000Z",
    } as unknown as DemoState);

    expect(store.read()).toEqual(written);
  });

  it("keeps a written state when writes fail but reads work", () => {
    let persisted: string | null = null;
    const storage: StorageLike = {
      getItem: () => persisted,
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => {
        persisted = null;
      },
    };
    const store = createDemoStateStore({ storage, now: () => NOW });
    const written = store.write({ ...store.read(), authenticated: true });

    expect(store.read()).toEqual(written);
  });

  it("keeps reset state when removal fails", () => {
    const storage: StorageLike = {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => {
        throw new Error("blocked removal");
      },
    };
    const store = createDemoStateStore({ storage, now: () => NOW });

    const reset = store.reset();

    expect(reset).toMatchObject({
      schemaVersion: 2,
      seed: 8202026,
      authenticated: false,
      passwordChangeRequired: true,
      updatedAt: NOW,
    });
    expect(store.read()).toEqual(reset);
  });

  it("keeps reset state when every storage method fails", () => {
    const storage: StorageLike = {
      getItem: () => {
        throw new Error("blocked reads");
      },
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => {
        throw new Error("blocked removal");
      },
    };
    const store = createDemoStateStore({ storage, now: () => NOW });

    expect(() => store.read()).not.toThrow();
    expect(() => store.write({ ...store.read(), authenticated: true })).not.toThrow();
    const reset = store.reset();

    expect(reset.authenticated).toBe(false);
    expect(reset.passwordChangeRequired).toBe(true);
    expect(store.read()).toEqual(reset);
  });

  it("resets only demo state and never persists credentials", () => {
    const storage = memoryStorage({ unrelated: "keep", [LEGACY_DEMO_STATE_STORAGE_KEY]: JSON.stringify(legacyState()) });
    const store = createDemoStateStore({ storage, now: () => NOW });
    store.write({
      ...store.read(),
      password: "top-secret",
      credential: "secret-token",
    } as DemoState & { password: string; credential: string });

    const reset = store.reset();
    expect(reset.authenticated).toBe(false);
    expect(storage.values.get("unrelated")).toBe("keep");
    expect(storage.values.has(LEGACY_DEMO_STATE_STORAGE_KEY)).toBe(true);
    expect(storage.values.get(DEMO_STATE_STORAGE_KEY)).not.toContain("top-secret");
    expect(storage.values.get(DEMO_STATE_STORAGE_KEY)).not.toContain("secret-token");
  });

  it("never serializes a password or nested credential detail", () => {
    const storage = memoryStorage();
    const store = createDemoStateStore({ storage, now: () => NOW });
    const conversationId = Object.keys(store.read().conversations)[0]!;

    store.write({
      ...store.read(),
      chatRequests: {
        request_demo_credential: {
          request_id: "request_demo_credential",
          conversation_id: conversationId,
          message_id: store.read().conversations[conversationId]!.messages[0]!.message_id,
          status: "failed",
          next_chunk_index: 0,
          turn_index: 0,
          error: {
            code: "DEMO_ERROR",
            message: "safe message",
            request_id: "request_demo_credential",
            retryable: false,
            details: { reason: "demo", password: "top-secret" },
          },
        },
      },
      password: "top-secret",
    } as DemoState & { password: string });

    const persisted = storage.values.get(DEMO_STATE_STORAGE_KEY) ?? "";
    expect(persisted).not.toContain("top-secret");
    expect(persisted).toContain('"reason":"demo"');
  });

  it("sanitizes sensitive keys through arbitrarily nested JSON arrays", () => {
    const storage = memoryStorage();
    const store = createDemoStateStore({ storage, now: () => NOW });
    const conversationId = Object.keys(store.read().conversations)[0]!;
    const messageId = store.read().conversations[conversationId]!.messages[0]!.message_id;

    store.write({
      ...store.read(),
      chatRequests: {
        request_nested_credentials: {
          request_id: "request_nested_credentials",
          conversation_id: conversationId,
          message_id: messageId,
          status: "failed",
          next_chunk_index: 0,
          turn_index: 0,
          error: {
            code: "DEMO_ERROR",
            message: "safe message",
            request_id: "request_nested_credentials",
            retryable: false,
            details: {
              levels: [
                { nested: [{ token: "secret-token" }, { message: "my password is a topic" }] },
                [[{ api_key: "secret-key" }]],
              ],
            },
          },
        },
      },
    });

    const persisted = storage.values.get(DEMO_STATE_STORAGE_KEY) ?? "";
    expect(persisted).not.toContain("secret-token");
    expect(persisted).not.toContain("secret-key");
    expect(persisted).toContain("my password is a topic");
  });

  it.each([
    ["unknown selected model", (state: DemoState) => ({ ...state, selectedModelId: "unknown-model" })],
    ["unknown favorite", (state: DemoState) => ({ ...state, favorites: ["unknown-model"] })],
    ["duplicate favorite", (state: DemoState) => ({ ...state, favorites: ["qwen-image", "qwen-image"] })],
    [
      "conversation key mismatch",
      (state: DemoState) => ({
        ...state,
        conversations: { renamed: Object.values(state.conversations)[0] },
      }),
    ],
    [
      "unknown conversation model",
      (state: DemoState) => ({
        ...state,
        conversations: {
          ...state.conversations,
          [Object.keys(state.conversations)[0]!]: {
            ...Object.values(state.conversations)[0]!,
            product_model_id: "unknown-model",
          },
        },
      }),
    ],
    [
      "duplicate message id",
      (state: DemoState) => {
        const conversation = Object.values(state.conversations)[0]!;
        return {
          ...state,
          conversations: {
            ...state.conversations,
            [conversation.conversation_id]: {
              ...conversation,
              messages: [conversation.messages[0]!, ...conversation.messages],
            },
          },
        };
      },
    ],
    [
      "non-canonical message timestamp",
      (state: DemoState) => {
        const conversation = Object.values(state.conversations)[0]!;
        return {
          ...state,
          conversations: {
            ...state.conversations,
            [conversation.conversation_id]: {
              ...conversation,
              messages: [{ ...conversation.messages[0]!, created_at: "yesterday" }, ...conversation.messages.slice(1)],
            },
          },
        };
      },
    ],
  ])("rejects relationally invalid %s state", (_label, mutate) => {
    expectInvalidPersistedState(mutate(storedState()));
  });

  it("rejects orphan and mismatched request references", () => {
    const state = storedState();
    const conversationId = Object.keys(state.conversations)[0]!;
    const conversation = state.conversations[conversationId]!;
    const request = {
      request_id: "request-invalid",
      conversation_id: conversationId,
      message_id: conversation.messages[0]!.message_id,
      status: "streaming" as const,
      next_chunk_index: 0,
      turn_index: 0,
    };

    expectInvalidPersistedState({
      ...state,
      chatRequests: { [request.request_id]: { ...request, conversation_id: "missing" } },
    });
    expectInvalidPersistedState({
      ...state,
      chatRequests: { [request.request_id]: { ...request, message_id: "missing" } },
    });
    expectInvalidPersistedState({
      ...state,
      chatRequests: { [request.request_id]: request },
      conversations: {
        ...state.conversations,
        [conversationId]: { ...conversation, active_request_id: "missing" },
      },
    });
    expectValidPersistedState({
      ...state,
      chatRequests: { [request.request_id]: request },
      conversations: {
        ...state.conversations,
        [conversationId]: { ...conversation, active_request_id: request.request_id, active_request_cursor: -1 },
      },
    });
  });

  it("rejects arbitrary, sensitive, and oversized draft keys while preserving ordinary text", () => {
    const state = storedState();
    expectInvalidPersistedState({ ...state, drafts: { arbitrary: "draft" } });
    expectInvalidPersistedState({ ...state, drafts: { password: "draft" } });
    expectInvalidPersistedState({
      ...state,
      drafts: { [Object.keys(state.conversations)[0]!]: "x".repeat(MAX_DEMO_DRAFT_LENGTH + 1) },
    });

    const conversationId = Object.keys(state.conversations)[0]!;
    const store = createDemoStateStore({ storage: memoryStorage(), now: () => NOW });
    const written = store.update((current) => ({
      ...current,
      drafts: { [conversationId]: "A legitimate draft mentions password policy." },
    }));
    expect(written.drafts[conversationId]).toContain("password policy");
  });

  it("rejects oversized state, conversation, message, and request collections", () => {
    const state = storedState();
    const conversationEntries = Object.fromEntries(
      Array.from({ length: MAX_DEMO_CONVERSATIONS + 1 }, (_, index) => {
        const source = Object.values(state.conversations)[0]!;
        const id = `conversation-extra-${index}`;
        return [id, { ...source, conversation_id: id }];
      }),
    );
    expectInvalidPersistedState({ ...state, conversations: conversationEntries });

    const sourceConversation = Object.values(state.conversations)[0]!;
    expectInvalidPersistedState({
      ...state,
      conversations: {
        ...state.conversations,
        [sourceConversation.conversation_id]: {
          ...sourceConversation,
          messages: Array.from({ length: MAX_DEMO_MESSAGES_PER_CONVERSATION + 1 }, (_, index) => ({
            ...sourceConversation.messages[0]!,
            message_id: `message-extra-${index}`,
          })),
        },
      },
    });

    const requestConversation = sourceConversation.conversation_id;
    const requestMessage = sourceConversation.messages[0]!.message_id;
    const requests = Object.fromEntries(
      Array.from({ length: MAX_DEMO_CHAT_REQUESTS + 1 }, (_, index) => {
        const requestId = `request-extra-${index}`;
        return [requestId, {
          request_id: requestId,
          conversation_id: requestConversation,
          message_id: requestMessage,
          status: "streaming",
          next_chunk_index: 0,
          turn_index: 0,
        }];
      }),
    );
    expectInvalidPersistedState({ ...state, chatRequests: requests });

    expectInvalidPersistedState({
      ...state,
      extra: "x".repeat(MAX_DEMO_STATE_BYTES + 1),
    });
  });
});
