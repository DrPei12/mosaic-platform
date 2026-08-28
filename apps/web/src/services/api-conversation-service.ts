import type {
  ApiErrorResponse,
  ChatStreamEvent,
  Conversation,
  ConversationMessage,
  ConversationSummary,
} from "@mosaic/contracts";
import {
  ConversationServiceError,
  type ConversationService,
  type ConversationStream,
} from "./interfaces";
import { csrfRequestHeaders } from "./csrf";

export class ApiConversationServiceError extends ConversationServiceError {
  constructor(options: ConstructorParameters<typeof ConversationServiceError>[0]) {
    super(options);
    this.name = "ApiConversationServiceError";
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

const MESSAGE_STATUSES = new Set(["streaming", "complete", "stopped", "failed"]);
const EVENT_TYPES = new Set(["started", "delta", "completed", "stopped", "failed"]);
const ERROR_CODES = new Set([
  "CONVERSATION_NOT_FOUND",
  "MESSAGE_NOT_LATEST",
  "MODEL_NOT_FOUND",
  "MESSAGE_EMPTY",
  "CONVERSATION_BUSY",
  "IDEMPOTENCY_KEY_REUSED",
  "PROVIDER_TIMEOUT",
  "CONTENT_REJECTED",
  "CHAT_SUBMISSION_DISABLED",
  "IDEMPOTENCY_IN_PROGRESS",
  "STREAM_CURSOR_INVALID",
  "STREAM_RESPONSE_INVALID",
  "CONVERSATION_UNAVAILABLE",
]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  return (
    Object.keys(value).every((key) => allowed.has(key)) &&
    required.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

const RFC3339_DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/;
const PUBLIC_ERROR_CODE = /^[A-Z0-9_]+$/;

function isoTimestamp(value: unknown): value is string {
  if (!nonEmptyString(value) || !RFC3339_DATE_TIME.test(value)) return false;
  const parts = value.match(RFC3339_DATE_TIME);
  if (!parts) return false;
  const year = Number(parts[1]);
  const month = Number(parts[2]);
  const day = Number(parts[3]);
  const hour = Number(parts[4]);
  const minute = Number(parts[5]);
  const second = Number(parts[6]);
  const timezone = parts[7]!;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > monthDays[month - 1]! ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) return false;
  if (timezone !== "Z") {
    const offset = timezone.match(/^[+-](\d{2}):(\d{2})$/);
    if (!offset || Number(offset[1]) > 23 || Number(offset[2]) > 59) return false;
  }
  const date = new Date(value);
  return !Number.isNaN(date.getTime());
}

function isErrorBody(value: unknown): value is ApiErrorResponse["error"] {
  if (!isPlainObject(value)) return false;
  if (
    !exactKeys(value, ["code", "message", "request_id", "retryable"], ["details"]) ||
    !nonEmptyString(value.code) ||
    !PUBLIC_ERROR_CODE.test(value.code) ||
    !nonEmptyString(value.message) ||
    !nonEmptyString(value.request_id) ||
    typeof value.retryable !== "boolean"
  ) return false;
  return (
    value.details === undefined ||
    value.details === null ||
    isPlainObject(value.details)
  );
}

function isConversationMessage(value: unknown): value is ConversationMessage {
  if (!isPlainObject(value)) return false;
  return (
    exactKeys(value, ["message_id", "role", "content", "status", "created_at"], ["request_id"]) &&
    nonEmptyString(value.message_id) &&
    (value.role === "user" || value.role === "assistant") &&
    typeof value.content === "string" &&
    typeof value.status === "string" &&
    MESSAGE_STATUSES.has(value.status) &&
    isoTimestamp(value.created_at) &&
    (value.request_id === undefined || value.request_id === null || nonEmptyString(value.request_id))
  );
}

function isConversation(value: unknown): value is Conversation {
  if (!isPlainObject(value)) return false;
  return (
    exactKeys(value, [
      "conversation_id",
      "product_model_id",
      "title",
      "messages",
      "updated_at",
      "active_request_id",
      "active_request_cursor",
    ]) &&
    nonEmptyString(value.conversation_id) &&
    nonEmptyString(value.product_model_id) &&
    nonEmptyString(value.title) &&
    Array.isArray(value.messages) &&
    value.messages.every(isConversationMessage) &&
    isoTimestamp(value.updated_at) &&
    (value.active_request_id === null || nonEmptyString(value.active_request_id)) &&
    (value.active_request_cursor === null || (
      Number.isInteger(value.active_request_cursor) &&
      (value.active_request_cursor as number) >= -1
    )) &&
    ((value.active_request_id === null && value.active_request_cursor === null) ||
      (value.active_request_id !== null && value.active_request_cursor !== null))
  );
}

function isConversationSummary(value: unknown): value is ConversationSummary {
  if (!isPlainObject(value)) return false;
  return (
    exactKeys(value, ["conversation_id", "product_model_id", "title", "preview", "updated_at"]) &&
    nonEmptyString(value.conversation_id) &&
    nonEmptyString(value.product_model_id) &&
    nonEmptyString(value.title) &&
    typeof value.preview === "string" &&
    isoTimestamp(value.updated_at)
  );
}

function isChatStreamEvent(value: unknown): value is ChatStreamEvent {
  if (!isPlainObject(value) || typeof value.type !== "string" || !EVENT_TYPES.has(value.type)) return false;
  const common =
    nonEmptyString(value.request_id) &&
    nonEmptyString(value.conversation_id) &&
    nonEmptyString(value.message_id) &&
    Number.isInteger(value.sequence) &&
    (value.sequence as number) >= 0;
  if (!common) return false;
  switch (value.type) {
    case "started":
      return exactKeys(value, ["type", "request_id", "conversation_id", "message_id", "sequence"]) && value.sequence === 0;
    case "delta":
      return exactKeys(value, ["type", "request_id", "conversation_id", "message_id", "sequence", "delta"]) && nonEmptyString(value.delta);
    case "completed":
      return exactKeys(value, ["type", "request_id", "conversation_id", "message_id", "sequence", "content"]) && typeof value.content === "string";
    case "stopped":
      return exactKeys(value, ["type", "request_id", "conversation_id", "message_id", "sequence"]);
    case "failed":
      return exactKeys(value, ["type", "request_id", "conversation_id", "message_id", "sequence", "error"]) && isErrorBody(value.error);
  }
  return false;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

function statusOf(response: Response): number {
  return Number.isFinite(response.status) ? response.status : 0;
}

function errorFromBody(value: unknown, status: number, fallbackCode: "CONVERSATION_NOT_FOUND" | "CONVERSATION_UNAVAILABLE"): ApiConversationServiceError {
  if (isPlainObject(value) && isErrorBody(value.error)) {
    const candidate = value.error.code;
    const code = ERROR_CODES.has(candidate)
      ? (candidate as ConstructorParameters<typeof ConversationServiceError>[0]["code"])
      : fallbackCode;
    return new ApiConversationServiceError({
      code,
      status,
      retryable: value.error.retryable || status >= 500,
      requestId: value.error.request_id,
      message: value.error.message,
    });
  }
  return new ApiConversationServiceError({
    code: fallbackCode,
    status,
    retryable: status === 408 || status === 429 || status >= 500,
  });
}

async function httpError(
  response: Response,
  fallbackCode: "CONVERSATION_NOT_FOUND" | "CONVERSATION_UNAVAILABLE",
): Promise<ApiConversationServiceError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
  }
  return errorFromBody(body, statusOf(response), fallbackCode);
}

function invalidResponse(status: number, requestId?: string, message = "Invalid conversation response"): ApiConversationServiceError {
  return new ApiConversationServiceError({
    code: "STREAM_RESPONSE_INVALID",
    status,
    retryable: false,
    ...(requestId === undefined ? {} : { requestId }),
    message,
  });
}

function encode(value: string): string {
  return encodeURIComponent(value);
}

function headers(extra: Record<string, string> = {}): HeadersInit {
  return { accept: "application/json", ...extra };
}

function jsonRequest(
  method: "POST" | "GET",
  signal: AbortSignal | undefined,
  body?: unknown,
  idempotencyKey?: string,
  accept = "application/json",
): RequestInit {
  return {
    method,
    ...(signal === undefined ? {} : { signal }),
    headers: headers({
      accept,
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      ...(idempotencyKey === undefined ? {} : { "Idempotency-Key": idempotencyKey }),
      ...(method === "POST" ? csrfRequestHeaders() : {}),
    }),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw invalidResponse(statusOf(response));
  }
}

async function* parseSse(
  response: Response,
  stream: { requestId: string; messageId: string; cursor: number | null; lastSequence: number },
  conversationId: string,
  resumeCursor: number | null,
): AsyncIterable<ChatStreamEvent> {
  if (!response.body) throw invalidResponse(statusOf(response), stream.requestId, "Missing stream body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let dataLines: string[] = [];
  let eventId: string | undefined;
  let started = false;
  let terminal = false;
  let received = false;
  const resumed = resumeCursor !== null && resumeCursor >= 0;
  let expectedSequence = resumed ? resumeCursor + 1 : 0;

  const invalid = (message: string): ApiConversationServiceError =>
    invalidResponse(statusOf(response), stream.requestId, message);

  const dispatch = (payload: string): ChatStreamEvent => {
    if (eventId === undefined || !/^(?:0|[1-9]\d*)$/.test(eventId)) {
      throw invalid("SSE event id is missing or not an integer");
    }
    const id = Number(eventId);
    let value: unknown;
    try {
      value = JSON.parse(payload);
    } catch (error) {
      if (isAbortError(error)) throw error;
      throw invalid("Malformed stream JSON");
    }
    if (!isChatStreamEvent(value)) throw invalid("Invalid stream event");
    const event = value;
    if (id !== event.sequence) throw invalid("SSE event id does not match sequence");
    if (
      event.conversation_id !== conversationId ||
      (stream.requestId !== "" && event.request_id !== stream.requestId) ||
      (stream.messageId !== "" && event.message_id !== stream.messageId)
    ) {
      throw invalid("Stream IDs do not match request");
    }
    if (terminal) throw invalid("Stream emitted after terminal event");
    if (!received) {
      if (!resumed && (event.type !== "started" || event.sequence !== 0)) {
        throw invalid("Stream did not start with sequence zero");
      }
      if (resumed && event.type === "started") {
        throw invalid("Resumed stream repeated started event");
      }
      started = event.type === "started";
      received = true;
      stream.requestId = event.request_id;
      stream.messageId = event.message_id;
    } else if (event.type === "started") {
      throw invalid("Stream emitted started after its first event");
    }
    if (event.sequence !== expectedSequence) {
      throw invalid("Stream sequence is not consecutive");
    }
    if (!resumed && !started) {
      throw invalid("Stream did not start with sequence zero");
    }
    if (event.type === "failed" && event.error.request_id !== event.request_id) {
      throw invalid("Failure request ID does not match stream");
    }
    expectedSequence = event.sequence + 1;
    stream.lastSequence = event.sequence;
    if (event.type === "completed" || event.type === "stopped" || event.type === "failed") terminal = true;
    return event;
  };

  const consumeLine = (line: string): ChatStreamEvent | undefined => {
    if (line === "") {
      if (dataLines.length === 0) {
        if (eventId !== undefined) throw invalid("SSE event id has no data payload");
        eventId = undefined;
        return undefined;
      }
      const payload = dataLines.join("\n");
      dataLines = [];
      const event = dispatch(payload);
      eventId = undefined;
      return event;
    }
    if (line.startsWith(":")) return undefined;
    if (line.startsWith("id:")) {
      if (eventId !== undefined) throw invalid("Duplicate SSE event id");
      eventId = line.slice(3).replace(/^ /, "");
      return undefined;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
      return undefined;
    }
    throw invalid("Unsupported SSE field");
  };

  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      while (true) {
        const lfIndex = buffer.indexOf("\n");
        const crIndex = buffer.indexOf("\r");
        const separatorIndex =
          lfIndex < 0 ? crIndex : crIndex < 0 ? lfIndex : Math.min(lfIndex, crIndex);
        if (separatorIndex < 0) break;
        // A CR at the end of a network chunk may be the first half of CRLF.
        // Keep it until the next read so it cannot dispatch a partial event.
        if (buffer[separatorIndex] === "\r" && separatorIndex === buffer.length - 1) break;
        const separatorLength =
          buffer[separatorIndex] === "\r" && buffer[separatorIndex + 1] === "\n" ? 2 : 1;
        const line = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + separatorLength);
        const event = consumeLine(line);
        if (event) yield event;
      }
    }
    buffer += decoder.decode();
    if (buffer.endsWith("\r")) {
      const event = consumeLine(buffer.slice(0, -1));
      buffer = "";
      if (event) yield event;
    }
    if (buffer.length > 0 || dataLines.length > 0 || eventId !== undefined) {
      throw invalid("SSE stream ended with an incomplete event frame");
    }
    if (!received) throw invalid("Empty stream");
    if (!terminal) throw invalid("Stream ended before terminal event");
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw error;
  } finally {
    try {
      await reader.cancel();
    } catch (error) {
      if (isAbortError(error)) throw error;
    }
  }
}

async function* emptyTerminalStream(): AsyncIterable<ChatStreamEvent> {
  return;
}

export function createApiConversationService(fetcher: typeof fetch): ConversationService {
  async function requestJson<T>(
    path: string,
    init: RequestInit,
    validator: (value: unknown) => value is T,
    fallbackCode: "CONVERSATION_NOT_FOUND" | "CONVERSATION_UNAVAILABLE" = "CONVERSATION_UNAVAILABLE",
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetcher(path, init);
    } catch (error) {
      if (isAbortError(error)) throw error;
      throw error;
    }
    if (!response.ok) throw await httpError(response, fallbackCode);
    const body = await readJson(response);
    if (!validator(body)) throw invalidResponse(statusOf(response));
    return clone(body);
  }

  async function streamRequest(
    path: string,
    init: RequestInit,
    conversationId: string,
    fallbackCode: "CONVERSATION_NOT_FOUND" | "CONVERSATION_UNAVAILABLE" = "CONVERSATION_UNAVAILABLE",
    options: { cursor?: number | null; requestId?: string; messageId?: string } = {},
  ): Promise<ConversationStream> {
    let response: Response;
    try {
      response = await fetcher(path, init);
    } catch (error) {
      if (isAbortError(error)) throw error;
      throw error;
    }
    if (!response.ok) throw await httpError(response, fallbackCode);
    const cursor = options.cursor ?? null;
    const requestId = options.requestId ??
      response.headers?.get("x-chat-request-id") ??
      response.headers?.get("X-Chat-Request-ID") ??
      response.headers?.get("x-request-id") ??
      response.headers?.get("X-Request-Id") ??
      "";
    const messageId = options.messageId ?? response.headers?.get("x-message-id") ?? response.headers?.get("X-Message-Id") ?? "";
    const stream = { requestId, messageId, cursor, lastSequence: cursor ?? -1 };
    if (response.status === 204) {
      if (cursor === null || options.requestId === undefined) {
        throw invalidResponse(statusOf(response), requestId, "Unexpected empty stream response");
      }
      return {
        requestId,
        messageId,
        cursor,
        lastSequence: cursor,
        events: emptyTerminalStream(),
      };
    }
    return {
      get requestId() {
        return stream.requestId;
      },
      get messageId() {
        return stream.messageId;
      },
      cursor,
      get lastSequence() {
        return stream.lastSequence;
      },
      events: parseSse(response, stream, conversationId, cursor),
    };
  }

  return {
    async listConversations(signal) {
      return requestJson(
        "/api/v1/conversations",
        jsonRequest("GET", signal),
        (value): value is ConversationSummary[] => Array.isArray(value) && value.every(isConversationSummary),
      );
    },

    async getConversation(conversationId, signal) {
      return requestJson(
        `/api/v1/conversations/${encode(conversationId)}`,
        jsonRequest("GET", signal),
        isConversation,
        "CONVERSATION_NOT_FOUND",
      );
    },

    async getDraft(_conversationId, signal) {
      if (signal?.aborted) {
        throw signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
      }
      throw new ApiConversationServiceError({
        code: "CONVERSATION_UNAVAILABLE",
        status: 503,
        retryable: true,
        message: "服务器暂未提供草稿持久化能力。",
      });
    },

    async saveDraft(_input, signal) {
      if (signal?.aborted) {
        throw signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
      }
      throw new ApiConversationServiceError({
        code: "CONVERSATION_UNAVAILABLE",
        status: 503,
        retryable: true,
        message: "服务器暂未提供草稿持久化能力。",
      });
    },

    async createConversation(input, signal) {
      return requestJson(
        "/api/v1/conversations",
        jsonRequest("POST", signal, {
          product_model_id: input.productModelId,
          client_request_id: input.clientRequestId,
        }, input.clientRequestId),
        isConversation,
      );
    },

    async sendMessage(input, signal) {
      return streamRequest(
        `/api/v1/conversations/${encode(input.conversationId)}/messages`,
        jsonRequest("POST", signal, { content: input.content, client_request_id: input.clientRequestId }, input.clientRequestId, "text/event-stream"),
        input.conversationId,
        "CONVERSATION_NOT_FOUND",
        { cursor: null },
      );
    },

    async resumeMessage(input, signal) {
      const request = jsonRequest("GET", signal, undefined, undefined, "text/event-stream");
      if (input.cursor !== null && input.cursor >= 0) {
        request.headers = headers({ ...(request.headers as Record<string, string>), "Last-Event-ID": String(input.cursor) });
      }
      return streamRequest(
        `/api/v1/conversations/${encode(input.conversationId)}/requests/${encode(input.requestId)}/resume`,
        request,
        input.conversationId,
        "CONVERSATION_NOT_FOUND",
        { cursor: input.cursor, requestId: input.requestId },
      );
    },

    async regenerate(input, signal) {
      return streamRequest(
        `/api/v1/conversations/${encode(input.conversationId)}/messages/${encode(input.messageId)}/regenerate`,
        jsonRequest("POST", signal, { client_request_id: input.clientRequestId }, input.clientRequestId, "text/event-stream"),
        input.conversationId,
        "CONVERSATION_NOT_FOUND",
        { cursor: null },
      );
    },

    async stopMessage(input, signal) {
      let response: Response;
      try {
        response = await fetcher(
          `/api/v1/conversations/${encode(input.conversationId)}/requests/${encode(input.requestId)}/stop`,
          jsonRequest("POST", signal),
        );
      } catch (error) {
        if (isAbortError(error)) throw error;
        throw error;
      }
      if (!response.ok) throw await httpError(response, "CONVERSATION_NOT_FOUND");
    },
  };
}
