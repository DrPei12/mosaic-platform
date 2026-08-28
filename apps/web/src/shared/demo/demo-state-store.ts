import type { ApiErrorResponse, ConversationMessage } from "@mosaic/contracts";
import type {
  DemoChatRequestState,
  DemoConversationCreateState,
  DemoConversationState,
} from "@/entities/chat/conversation";
import { DEMO_SCENARIO, DEMO_SEED } from "./demo-scenario";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface DemoState {
  schemaVersion: 2;
  seed: typeof DEMO_SEED;
  authenticated: boolean;
  passwordChangeRequired: boolean;
  favorites: string[];
  selectedModelId: string | null;
  conversations: Record<string, DemoConversationState>;
  chatRequests: Record<string, DemoChatRequestState>;
  /** Optional v2 metadata for idempotent conversation creation. */
  conversationCreates?: Record<string, DemoConversationCreateState>;
  drafts: Record<string, string>;
  updatedAt: string;
}

export interface DemoStateStore {
  read(): DemoState;
  write(state: DemoState): DemoState;
  update(mutator: (state: DemoState) => DemoState): DemoState;
  reset(): DemoState;
}

export const DEMO_STATE_STORAGE_KEY = "mosaic.demo-state.v2";
export const LEGACY_DEMO_STATE_STORAGE_KEY = "mosaic.demo-state.v1";

/** Demo storage is intentionally single-tab/session scoped; cross-tab CAS is unsupported. */
export const DEMO_STATE_CROSS_TAB_SUPPORTED = false as const;
/** Generous fail-closed bounds for the browser-only demo state. */
export const MAX_DEMO_CONVERSATIONS = 32;
export const MAX_DEMO_MESSAGES_PER_CONVERSATION = 128;
export const MAX_DEMO_CHAT_REQUESTS = 64;
export const MAX_DEMO_DRAFT_LENGTH = 8_192;
export const MAX_DEMO_STATE_BYTES = 512 * 1024;

type LegacyDemoState = {
  schemaVersion: 1;
  seed: typeof DEMO_SEED;
  authenticated: boolean;
  passwordChangeRequired: boolean;
  updatedAt: string;
};

const MESSAGE_STATUSES = new Set<ConversationMessage["status"]>([
  "streaming",
  "complete",
  "stopped",
  "failed",
]);
const REQUEST_STATUSES = new Set<DemoChatRequestState["status"]>([
  "streaming",
  "completed",
  "stopped",
  "failed",
  "timeout",
  "content_rejected",
]);
const CANONICAL_MODEL_IDS = new Set(
  DEMO_SCENARIO.models.map((model) => model.product_model_id),
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isJsonValue(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return true;
  }
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  if (!isRecord(value)) return false;
  return Object.values(value).every(isJsonValue);
}

function serializedByteLength(value: unknown): number {
  try {
    const serialized = JSON.stringify(value);
    if (typeof serialized !== "string") return Number.POSITIVE_INFINITY;
    if (typeof TextEncoder !== "undefined") {
      return new TextEncoder().encode(serialized).byteLength;
    }
    return encodeURIComponent(serialized).replace(/%[0-9A-F]{2}/g, "x").length;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

export function isCanonicalTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;

  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return false;

    const canonical = date.toISOString();
    return canonical === value || canonical.replace(".000Z", "Z") === value;
  } catch {
    return false;
  }
}

function isErrorBody(value: unknown): value is ApiErrorResponse["error"] {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.code) &&
    isNonEmptyString(value.message) &&
    isNonEmptyString(value.request_id) &&
    typeof value.retryable === "boolean" &&
    (value.details === undefined ||
      value.details === null ||
      (isRecord(value.details) && isJsonValue(value.details)))
  );
}

function isConversationMessage(value: unknown): value is ConversationMessage {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.message_id) &&
    (value.role === "user" || value.role === "assistant") &&
    typeof value.content === "string" &&
    typeof value.status === "string" &&
    MESSAGE_STATUSES.has(value.status as ConversationMessage["status"]) &&
    isCanonicalTimestamp(value.created_at) &&
    (value.request_id === undefined || isNonEmptyString(value.request_id))
  );
}

function isConversation(value: unknown): value is DemoConversationState {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.conversation_id) &&
    isNonEmptyString(value.product_model_id) &&
    isNonEmptyString(value.title) &&
    Array.isArray(value.messages) &&
    value.messages.every(isConversationMessage) &&
    isCanonicalTimestamp(value.updated_at) &&
    (value.active_request_id === null || isNonEmptyString(value.active_request_id)) &&
    (value.active_request_cursor === null || (
      Number.isInteger(value.active_request_cursor) &&
      (value.active_request_cursor as number) >= -1
    )) &&
    ((value.active_request_id === null && value.active_request_cursor === null) ||
      (value.active_request_id !== null && value.active_request_cursor !== null))
  );
}

function isChatRequest(value: unknown): value is DemoChatRequestState {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.request_id) &&
    isNonEmptyString(value.conversation_id) &&
    isNonEmptyString(value.message_id) &&
    typeof value.status === "string" &&
    REQUEST_STATUSES.has(value.status as DemoChatRequestState["status"]) &&
    Number.isInteger(value.next_chunk_index) &&
    (value.next_chunk_index as number) >= 0 &&
    Number.isInteger(value.turn_index) &&
    (value.turn_index as number) >= 0 &&
    (value.operation === undefined || value.operation === "send" || value.operation === "resume" || value.operation === "regenerate") &&
    (value.client_request_id === undefined || isNonEmptyString(value.client_request_id)) &&
    (value.payload_fingerprint === undefined || isNonEmptyString(value.payload_fingerprint)) &&
    (value.prompt === undefined || typeof value.prompt === "string") &&
    (value.script_id === undefined || isNonEmptyString(value.script_id)) &&
    (value.error === undefined || isErrorBody(value.error))
  );
}

function isConversationCreate(value: unknown): value is DemoConversationCreateState {
  if (!isRecord(value)) return false;
  return (
    isNonEmptyString(value.client_request_id) &&
    isNonEmptyString(value.product_model_id) &&
    isNonEmptyString(value.conversation_id) &&
    isNonEmptyString(value.payload_fingerprint)
  );
}

function isLegacyDemoState(value: unknown): value is LegacyDemoState {
  if (!isRecord(value)) return false;
  return (
    value.schemaVersion === 1 &&
    value.seed === DEMO_SEED &&
    typeof value.authenticated === "boolean" &&
    typeof value.passwordChangeRequired === "boolean" &&
    isCanonicalTimestamp(value.updatedAt)
  );
}

function isDemoState(value: unknown): value is DemoState {
  if (!isRecord(value)) return false;
  if (
    value.schemaVersion !== 2 ||
    value.seed !== DEMO_SEED ||
    typeof value.authenticated !== "boolean" ||
    typeof value.passwordChangeRequired !== "boolean" ||
    !Array.isArray(value.favorites) ||
    !value.favorites.every(isNonEmptyString) ||
    new Set(value.favorites).size !== value.favorites.length ||
    !value.favorites.every((modelId) => CANONICAL_MODEL_IDS.has(modelId)) ||
    (value.selectedModelId !== null &&
      (!isNonEmptyString(value.selectedModelId) ||
        !CANONICAL_MODEL_IDS.has(value.selectedModelId))) ||
    !isRecord(value.conversations) ||
    !isRecord(value.chatRequests) ||
    (value.conversationCreates !== undefined && !isRecord(value.conversationCreates)) ||
    !isRecord(value.drafts) ||
    !Object.values(value.drafts).every((draft) => typeof draft === "string") ||
    !isCanonicalTimestamp(value.updatedAt) ||
    Object.keys(value.conversations).length > MAX_DEMO_CONVERSATIONS ||
    Object.keys(value.chatRequests).length > MAX_DEMO_CHAT_REQUESTS ||
    serializedByteLength(value) > MAX_DEMO_STATE_BYTES
  ) {
    return false;
  }

  const conversationIds = new Set(Object.keys(value.conversations));
  const messageIdsByConversation = new Map<string, Set<string>>();
  const allMessageIds = new Set<string>();
  for (const [id, conversation] of Object.entries(value.conversations)) {
    if (
      id.length === 0 ||
      !isConversation(conversation) ||
      (conversation as DemoConversationState).conversation_id !== id ||
      !CANONICAL_MODEL_IDS.has((conversation as DemoConversationState).product_model_id) ||
      (conversation as DemoConversationState).messages.length > MAX_DEMO_MESSAGES_PER_CONVERSATION
    ) {
      return false;
    }

    const canonicalConversation = conversation as DemoConversationState;

    const messageIds = new Set<string>();
    for (const message of canonicalConversation.messages) {
      if (messageIds.has(message.message_id) || allMessageIds.has(message.message_id)) {
        return false;
      }
      messageIds.add(message.message_id);
      allMessageIds.add(message.message_id);
    }
    messageIdsByConversation.set(id, messageIds);
  }
  for (const [id, request] of Object.entries(value.chatRequests)) {
    if (
      id.length === 0 ||
      !isChatRequest(request) ||
      request.request_id !== id ||
      !conversationIds.has(request.conversation_id) ||
      !messageIdsByConversation.get(request.conversation_id)?.has(request.message_id) ||
      (request.error !== undefined && request.error.request_id !== request.request_id)
    ) {
      return false;
    }
  }
  if (value.conversationCreates !== undefined) {
    for (const [id, create] of Object.entries(value.conversationCreates)) {
      if (
        id.length === 0 ||
        !isConversationCreate(create) ||
        create.client_request_id !== id ||
        !conversationIds.has(create.conversation_id) ||
        !CANONICAL_MODEL_IDS.has(create.product_model_id)
      ) {
        return false;
      }
    }
  }
  for (const [id, conversation] of Object.entries(value.conversations)) {
    const canonicalConversation = conversation as DemoConversationState;
    if (canonicalConversation.active_request_id === null) continue;
    const request = value.chatRequests[canonicalConversation.active_request_id];
    if (
      !request ||
      (request as DemoChatRequestState).conversation_id !== id ||
      (request as DemoChatRequestState).request_id !== canonicalConversation.active_request_id ||
      canonicalConversation.active_request_cursor !==
        ((request as DemoChatRequestState).next_chunk_index > 0
          ? (request as DemoChatRequestState).next_chunk_index
          : -1)
    ) {
      return false;
    }
  }
  for (const [id, draft] of Object.entries(value.drafts)) {
    if (
      !conversationIds.has(id) ||
      SENSITIVE_KEY.test(id) ||
      (draft as string).length > MAX_DEMO_DRAFT_LENGTH
    ) {
      return false;
    }
  }
  return true;
}

/** Add the cursor field when upgrading an existing v2 demo snapshot. */
function migrateConversationCursors(value: unknown): unknown {
  if (!isRecord(value) || value.schemaVersion !== 2 || !isRecord(value.conversations)) return value;
  if (!isRecord(value.chatRequests)) return value;
  const requests = value.chatRequests;
  const conversations = Object.fromEntries(
    Object.entries(value.conversations).map(([id, candidate]) => {
      if (!isRecord(candidate) || Object.prototype.hasOwnProperty.call(candidate, "active_request_cursor")) {
        return [id, candidate];
      }
      const requestId = candidate.active_request_id;
      const request = typeof requestId === "string" ? requests[requestId] : undefined;
      const nextChunkIndex = isRecord(request) && Number.isInteger(request.next_chunk_index)
        ? Number(request.next_chunk_index)
        : 0;
      return [id, {
        ...candidate,
        active_request_cursor: requestId === null
          ? null
          : nextChunkIndex > 0 ? nextChunkIndex : -1,
      }];
    }),
  );
  return { ...value, conversations };
}

function cloneValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const SENSITIVE_KEY = /password|credential|secret|token|authorization|api[_-]?key/i;

function sanitizeJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizeJson);
  if (!isRecord(value)) return value;

  const result: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(value)) {
    if (SENSITIVE_KEY.test(key)) continue;
    result[key] = sanitizeJson(nested);
  }
  return result;
}

function sanitizeDetails(value: Record<string, unknown>): Record<string, unknown> {
  const sanitized = sanitizeJson(value);
  return isRecord(sanitized) ? sanitized : {};
}

function persistedError(error: ApiErrorResponse["error"]): ApiErrorResponse["error"] {
  return {
    code: error.code,
    message: error.message,
    request_id: error.request_id,
    retryable: error.retryable,
    ...(error.details === undefined
      ? {}
      : { details: error.details === null ? null : sanitizeDetails(error.details) }),
  };
}

function persistedMessage(message: ConversationMessage): ConversationMessage {
  return {
    message_id: message.message_id,
    role: message.role,
    content: message.content,
    status: message.status,
    created_at: message.created_at,
    ...(message.request_id === undefined ? {} : { request_id: message.request_id }),
  };
}

function persistedConversation(conversation: DemoConversationState): DemoConversationState {
  return {
    conversation_id: conversation.conversation_id,
    product_model_id: conversation.product_model_id,
    title: conversation.title,
    messages: conversation.messages.map(persistedMessage),
    updated_at: conversation.updated_at,
    active_request_id: conversation.active_request_id,
    active_request_cursor: conversation.active_request_cursor,
  };
}

function persistedChatRequest(request: DemoChatRequestState): DemoChatRequestState {
  return {
    request_id: request.request_id,
    conversation_id: request.conversation_id,
    message_id: request.message_id,
    status: request.status,
    next_chunk_index: request.next_chunk_index,
    turn_index: request.turn_index,
    ...(request.operation === undefined ? {} : { operation: request.operation }),
    ...(request.client_request_id === undefined
      ? {}
      : { client_request_id: request.client_request_id }),
    ...(request.payload_fingerprint === undefined
      ? {}
      : { payload_fingerprint: request.payload_fingerprint }),
    ...(request.prompt === undefined ? {} : { prompt: request.prompt }),
    ...(request.script_id === undefined ? {} : { script_id: request.script_id }),
    ...(request.error === undefined ? {} : { error: persistedError(request.error) }),
  };
}

function persistedConversationCreate(
  create: DemoConversationCreateState,
): DemoConversationCreateState {
  return {
    client_request_id: create.client_request_id,
    product_model_id: create.product_model_id,
    conversation_id: create.conversation_id,
    payload_fingerprint: create.payload_fingerprint,
  };
}

function toPersistedState(state: DemoState): DemoState {
  return {
    schemaVersion: 2,
    seed: DEMO_SEED,
    authenticated: state.authenticated,
    passwordChangeRequired: state.passwordChangeRequired,
    favorites: [...state.favorites],
    selectedModelId: state.selectedModelId,
    conversations: Object.fromEntries(
      Object.entries(state.conversations).map(([id, conversation]) => [
        id,
        persistedConversation(conversation),
      ]),
    ),
    chatRequests: Object.fromEntries(
      Object.entries(state.chatRequests).map(([id, request]) => [
        id,
        persistedChatRequest(request),
      ]),
    ),
    ...(state.conversationCreates === undefined
      ? {}
      : {
          conversationCreates: Object.fromEntries(
            Object.entries(state.conversationCreates).map(([id, create]) => [
              id,
              persistedConversationCreate(create),
            ]),
          ),
        }),
    drafts: { ...state.drafts },
    updatedAt: state.updatedAt,
  };
}

export function createDemoStateStore(input: {
  storage: StorageLike;
  now: () => string;
}): DemoStateStore {
  const timestamp = (): string => {
    try {
      const candidate = input.now();
      return isCanonicalTimestamp(candidate) ? candidate : new Date().toISOString();
    } catch {
      return new Date().toISOString();
    }
  };

  const initial = (): DemoState => ({
    schemaVersion: 2,
    seed: DEMO_SEED,
    authenticated: false,
    passwordChangeRequired: true,
    favorites: [...DEMO_SCENARIO.favorites],
    selectedModelId: DEMO_SCENARIO.selectedModelId,
    conversations: Object.fromEntries(
      DEMO_SCENARIO.conversations.map((conversation) => [
        conversation.conversation_id,
        cloneValue(conversation),
      ]),
    ),
    chatRequests: cloneValue(DEMO_SCENARIO.chatRequests),
    drafts: { ...DEMO_SCENARIO.drafts },
    updatedAt: timestamp(),
  });

  // Once a storage operation fails, keep serving this session-local value. This
  // makes a demo login usable even when localStorage is blocked or full.
  let fallbackState: DemoState | undefined;
  let useFallback = false;
  let readUnavailable = false;

  const recoverInitial = (storageReadFailed = false): DemoState => {
    const state = storageReadFailed && fallbackState ? fallbackState : initial();
    fallbackState = toPersistedState(state);
    useFallback = true;
    if (storageReadFailed) readUnavailable = true;
    return cloneValue(fallbackState);
  };

  const persist = (state: DemoState): DemoState => {
    const next = toPersistedState(state);
    fallbackState = next;

    try {
      input.storage.setItem(DEMO_STATE_STORAGE_KEY, JSON.stringify(next));
      // A successful write cannot prove that a previously unavailable read is
      // now reliable. Keep the in-memory state authoritative for this session.
      useFallback = readUnavailable;
    } catch {
      useFallback = true;
    }

    return cloneValue(next);
  };

  const read = (): DemoState => {
    if (useFallback && fallbackState) return cloneValue(fallbackState);

    let v2Raw: string | null;
    try {
      v2Raw = input.storage.getItem(DEMO_STATE_STORAGE_KEY);
    } catch {
      return recoverInitial(true);
    }

    // A present but corrupt/unknown/future v2 must win over the legacy key.
    if (v2Raw !== null) {
      try {
        const parsed: unknown = migrateConversationCursors(JSON.parse(v2Raw));
        if (!isDemoState(parsed)) return recoverInitial();
        const state = toPersistedState(parsed);
        fallbackState = state;
        return cloneValue(state);
      } catch {
        return recoverInitial();
      }
    }

    let legacyRaw: string | null;
    try {
      legacyRaw = input.storage.getItem(LEGACY_DEMO_STATE_STORAGE_KEY);
    } catch {
      return recoverInitial(true);
    }

    if (legacyRaw !== null) {
      try {
        const parsed: unknown = JSON.parse(legacyRaw);
        if (!isLegacyDemoState(parsed)) return recoverInitial();
        const migrated = initial();
        migrated.authenticated = parsed.authenticated;
        migrated.passwordChangeRequired = parsed.passwordChangeRequired;
        // Keep the legacy key untouched; writing the v2 copy is best effort.
        return persist(migrated);
      } catch {
        return recoverInitial();
      }
    }

    const state = initial();
    fallbackState = toPersistedState(state);
    return cloneValue(fallbackState);
  };

  const write = (state: DemoState): DemoState => {
    let base: DemoState;
    if (isDemoState(state)) {
      base = toPersistedState(state);
    } else if (isLegacyDemoState(state as unknown)) {
      // Accept a v1-shaped direct write for callers that still hold a legacy
      // snapshot while always persisting the v2 shape.
      base = initial();
      base.authenticated = (state as unknown as LegacyDemoState).authenticated;
      base.passwordChangeRequired = (state as unknown as LegacyDemoState).passwordChangeRequired;
    } else {
      base = read();
    }
    return persist({ ...base, updatedAt: timestamp() });
  };

  const update = (mutator: (state: DemoState) => DemoState): DemoState => {
    const current = read();
    let candidate: unknown;
    try {
      candidate = mutator(cloneValue(current));
    } catch {
      return cloneValue(current);
    }

    // Never send an invalid mutator result to persistence: the previous valid
    // state remains the source of truth for this session and storage.
    if (!isDemoState(candidate)) return cloneValue(current);
    return persist({ ...toPersistedState(candidate), updatedAt: timestamp() });
  };

  const reset = (): DemoState => {
    const state = initial();
    fallbackState = toPersistedState(state);

    try {
      input.storage.removeItem(DEMO_STATE_STORAGE_KEY);
    } catch {
      useFallback = true;
    }

    // Persisting the fresh v2 state prevents a retained legacy key from
    // resurrecting the authenticated session on the next read.
    try {
      input.storage.setItem(DEMO_STATE_STORAGE_KEY, JSON.stringify(fallbackState));
      useFallback = readUnavailable;
    } catch {
      useFallback = true;
    }

    return cloneValue(fallbackState);
  };

  return { read, write, update, reset };
}
