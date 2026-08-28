import type {
  ApiErrorResponse,
  ChatStreamEvent,
  Conversation,
  ConversationMessage,
  ConversationSummary,
} from "@mosaic/contracts";
import type {
  DemoChatRequestState,
  DemoConversationState,
} from "@/entities/chat/conversation";
import type { DemoScenario, DemoTurnScript } from "@/shared/demo/demo-scenario";
import { createDemoScheduler, type DemoScheduler } from "@/shared/demo/demo-scheduler";
import type { DemoState, DemoStateStore } from "@/shared/demo/demo-state-store";
import {
  ConversationServiceError,
  type ConversationService,
  type ConversationStream,
} from "./interfaces";

export { ConversationServiceError };

const DEFAULT_DELAY_MS = 180;
const NON_EMPTY = /\S/;

interface StreamControl {
  readonly requestId: string;
  readonly controller: AbortController;
  stoppedByBusiness: boolean;
  terminalEmitted: boolean;
}

interface SharedProducer {
  readonly requestId: string;
  readonly messageId: string;
  readonly conversationId: string;
  readonly source: AsyncIterator<ChatStreamEvent>;
  readonly events: ChatStreamEvent[];
  readonly waiters: Set<() => void>;
  pumping: boolean;
  done: boolean;
  error: unknown;
}

export interface DemoConversationServiceOptions {
  scenario: DemoScenario;
  store: DemoStateStore;
  scheduler?: DemoScheduler;
  now?: () => string;
  delayMs?: number;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function abortIfNeeded(signal?: AbortSignal): void {
  if (!signal?.aborted) return;
  throw signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

function hash(value: string): string {
  // FNV-1a is deliberately small and deterministic across browser sessions.
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return (result >>> 0).toString(36);
}

function stableId(prefix: string, ...parts: string[]): string {
  return `${prefix}-${hash(JSON.stringify(parts))}`;
}

function fingerprint(operation: string, payload: Record<string, string>): string {
  const canonical = Object.keys(payload)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${JSON.stringify(payload[key])}`)
    .join(",");
  return `${operation}:{${canonical}}`;
}

function isoNow(now: () => string): string {
  try {
    const candidate = now();
    const parsed = new Date(candidate);
    if (!Number.isNaN(parsed.getTime())) return parsed.toISOString();
  } catch {
    // Fall through to a stable platform timestamp.
  }
  return new Date().toISOString();
}

function serviceError(
  code: ConstructorParameters<typeof ConversationServiceError>[0]["code"],
  status: number,
  retryable = false,
  requestId?: string,
  message?: string,
): ConversationServiceError {
  const options: ConstructorParameters<typeof ConversationServiceError>[0] = {
    code,
    status,
    retryable,
    ...(requestId === undefined ? {} : { requestId }),
    ...(message === undefined ? {} : { message }),
  };
  return new ConversationServiceError(options);
}

function summaryOf(conversation: Conversation): ConversationSummary {
  const last = conversation.messages.at(-1);
  return {
    conversation_id: conversation.conversation_id,
    product_model_id: conversation.product_model_id,
    title: conversation.title,
    preview: last?.content ?? "",
    updated_at: conversation.updated_at,
  };
}

function currentMessage(
  state: DemoState,
  request: DemoChatRequestState,
): ConversationMessage | undefined {
  return state.conversations[request.conversation_id]?.messages.find(
    (message) => message.message_id === request.message_id,
  );
}

function remapError(
  error: ApiErrorResponse["error"] | undefined,
  requestId: string,
  fallbackCode: "PROVIDER_TIMEOUT" | "CONTENT_REJECTED",
): ApiErrorResponse["error"] {
  return {
    code: fallbackCode,
    message: error?.message ?? (fallbackCode === "PROVIDER_TIMEOUT"
      ? "演示响应超时，请稍后重试。"
      : "该请求无法在演示环境中处理。"),
    request_id: requestId,
    retryable: error?.retryable ?? fallbackCode === "PROVIDER_TIMEOUT",
    ...(error?.details === undefined ? {} : { details: clone(error.details) }),
  };
}

function fallbackChunks(content: string, context: readonly ConversationMessage[]): readonly string[] {
  const previousTurn = context.filter((message) => message.role === "user").length;
  if (previousTurn > 1) {
    return ["基于前面的讨论，", "我会把这个问题拆成可执行的下一步。"];
  }
  return ["已收到你的问题：", `${content.trim()}。`];
}

  function scriptFor(
  scenario: DemoScenario,
  conversationId: string,
  prompt: string,
): DemoTurnScript | undefined {
  const all = [
    ...scenario.scripts.twoTurn,
    ...scenario.scripts.timeout,
    ...scenario.scripts.contentRejected,
    ...scenario.scripts.stop,
  ];
  return all.find(
    (script) =>
      script.conversation_id === conversationId &&
      script.prompt === prompt,
  ) ?? all.find(
    (script) =>
      script.prompt === prompt &&
      script.terminal !== "completed",
  );
}

function requestMatches(
  request: DemoChatRequestState | undefined,
  operation: string,
  requestFingerprint: string,
): "missing" | "same" | "conflict" {
  if (!request) return "missing";
  if (
    request.operation === operation &&
    request.payload_fingerprint === requestFingerprint
  ) {
    return "same";
  }
  return "conflict";
}

export function createDemoConversationService(
  options: DemoConversationServiceOptions,
): ConversationService {
  const scheduler = options.scheduler ?? createDemoScheduler();
  const now = options.now ?? (() => new Date().toISOString());
  const delayMs = options.delayMs ?? DEFAULT_DELAY_MS;
  const controls = new Map<string, Set<StreamControl>>();
  const producers = new Map<string, SharedProducer>();

  function addControl(control: StreamControl): void {
    const active = controls.get(control.requestId) ?? new Set<StreamControl>();
    active.add(control);
    controls.set(control.requestId, active);
  }

  function removeControl(control: StreamControl): void {
    const active = controls.get(control.requestId);
    if (!active) return;
    active.delete(control);
    if (active.size === 0) controls.delete(control.requestId);
  }

  function getConversationOrThrow(
    state: DemoState,
    conversationId: string,
  ): DemoConversationState {
    const conversation = state.conversations[conversationId];
    if (!conversation) throw serviceError("CONVERSATION_NOT_FOUND", 404);
    return conversation;
  }

  function getRequestOrThrow(state: DemoState, requestId: string): DemoChatRequestState {
    const request = state.chatRequests[requestId];
    if (!request) throw serviceError("CONVERSATION_NOT_FOUND", 404, false, requestId);
    return request;
  }

  function modelExists(productModelId: string): boolean {
    return options.scenario.models.some(
      (model) =>
        model.product_model_id === productModelId &&
        model.category === "text" &&
        model.task_type === "chat",
    );
  }

  function initializeRequest(
    operation: "send" | "regenerate",
    conversationId: string,
    clientRequestId: string,
    requestFingerprint: string,
    messageId: string,
    turnIndex: number,
    signal?: AbortSignal,
  ): ConversationStream {
    const requestId = stableId("request", operation, conversationId, clientRequestId);
    const state = options.store.read();
    const existing = state.chatRequests[requestId];
    const match = requestMatches(existing, operation, requestFingerprint);
    if (match === "conflict") {
      throw serviceError("IDEMPOTENCY_KEY_REUSED", 409, false, requestId);
    }
    if (match === "same") return streamFor(requestId, signal);

    const conversation = getConversationOrThrow(state, conversationId);
    if (conversation.active_request_id !== null) {
      throw serviceError("CONVERSATION_BUSY", 409, true, conversation.active_request_id);
    }

    const timestamp = isoNow(now);
    options.store.update((current) => {
      const currentConversation = current.conversations[conversationId];
      if (!currentConversation || currentConversation.active_request_id !== null) return current;

      const nextConversation: DemoConversationState = {
        ...currentConversation,
        messages: currentConversation.messages.map((item) => ({ ...item })),
        updated_at: timestamp,
        active_request_id: requestId,
        active_request_cursor: -1,
      };

      if (operation === "send") {
        nextConversation.messages.push({
          message_id: messageId.replace(/^message-assistant-/, "message-user-"),
          role: "user",
          content: requestFingerprintPayload(requestFingerprint, "content"),
          status: "complete",
          created_at: timestamp,
          request_id: requestId,
        });
      }
      nextConversation.messages.push({
        message_id: messageId,
        role: "assistant",
        content: "",
        status: "streaming",
        created_at: timestamp,
        request_id: requestId,
      });

      const nextRequest: DemoChatRequestState = {
        request_id: requestId,
        conversation_id: conversationId,
        message_id: messageId,
        status: "streaming",
        next_chunk_index: 0,
        turn_index: turnIndex,
        operation,
        client_request_id: clientRequestId,
        payload_fingerprint: requestFingerprint,
        prompt: requestFingerprintPayload(requestFingerprint, "content"),
      };
      return {
        ...current,
        conversations: { ...current.conversations, [conversationId]: nextConversation },
        chatRequests: { ...current.chatRequests, [requestId]: nextRequest },
      };
    });
    return streamFor(requestId, signal);
  }

  function requestFingerprintPayload(value: string, field: "content"): string {
    const match = value.match(/"content":"((?:\\.|[^"\\])*)"/);
    if (match?.[1] !== undefined) {
      try {
        return JSON.parse(`"${match[1]}"`) as string;
      } catch {
        // Use the original canonical string if a malformed caller somehow
        // bypassed the local fingerprint helper.
      }
    }
    void field;
    return value;
  }

  function notifyProducer(producer: SharedProducer): void {
    for (const wake of producer.waiters) wake();
    producer.waiters.clear();
  }

  function ensureProducerPump(producer: SharedProducer): void {
    if (producer.pumping || producer.done) return;
    producer.pumping = true;
    void (async () => {
      try {
        while (true) {
          const next = await producer.source.next();
          if (next.done) break;
          producer.events.push(next.value);
          notifyProducer(producer);
        }
      } catch (error) {
        producer.error = error;
      } finally {
        producer.done = true;
        producer.pumping = false;
        notifyProducer(producer);
      }
    })();
  }

  async function waitForProducer(
    producer: SharedProducer,
    signal?: AbortSignal,
  ): Promise<boolean> {
    let wake: (() => void) | undefined;
    const producerWake = new Promise<void>((resolve) => {
      wake = resolve;
      producer.waiters.add(resolve);
    });
    let removeAbort: (() => void) | undefined;
    let aborted = false;
    const abortWake = signal === undefined
      ? undefined
      : new Promise<void>((resolve) => {
          const onAbort = (): void => {
            aborted = true;
            resolve();
          };
          if (signal.aborted) {
            onAbort();
          } else {
            signal.addEventListener("abort", onAbort, { once: true });
            removeAbort = () => signal.removeEventListener("abort", onAbort);
          }
        });
    ensureProducerPump(producer);
    await (abortWake === undefined
      ? producerWake
      : Promise.race([producerWake, abortWake]));
    removeAbort?.();
    if (wake) producer.waiters.delete(wake);
    return aborted || signal?.aborted === true;
  }

  async function* subscribe(
    producer: SharedProducer,
    signal?: AbortSignal,
    resumeFromCursor?: number | null,
  ): AsyncIterable<ChatStreamEvent> {
    const firstSequence = resumeFromCursor === undefined
      ? 0
      : Math.max(0, (resumeFromCursor ?? -1) + 1);
    let eventIndex = 0;
    while (true) {
      if (signal?.aborted) return;
      if (eventIndex < producer.events.length) {
        const event = producer.events[eventIndex]!;
        eventIndex += 1;
        if (event.sequence < firstSequence) continue;
        yield event;
        continue;
      }
      if (producer.done) {
        if (producer.error !== undefined) throw producer.error;
        return;
      }
      if (await waitForProducer(producer, signal)) return;
    }
  }

  function streamFor(
    requestId: string,
    subscriptionSignal?: AbortSignal,
    resumeCursor?: number | null,
  ): ConversationStream {
    const initial = options.store.read();
    const request = getRequestOrThrow(initial, requestId);
    const message = currentMessage(initial, request);
    if (!message) throw serviceError("CONVERSATION_NOT_FOUND", 404, false, requestId);

    const existingProducer = producers.get(requestId);
    if (existingProducer) {
      const cursor = resumeCursor === undefined
        ? null
        : resumeCursor ?? -1;
      let lastSequence = cursor ?? -1;
      const streamEvents = (async function* (): AsyncIterable<ChatStreamEvent> {
        for await (const event of subscribe(
          existingProducer,
          subscriptionSignal,
          resumeCursor === undefined ? undefined : cursor,
        )) {
          lastSequence = event.sequence;
          yield event;
        }
      })();
      return {
        requestId: existingProducer.requestId,
        messageId: existingProducer.messageId,
        cursor,
        get lastSequence() {
          return lastSequence;
        },
        events: streamEvents,
      };
    }

    const control: StreamControl = {
      requestId,
      controller: new AbortController(),
      stoppedByBusiness: false,
      terminalEmitted: false,
    };
    addControl(control);

    const scheduleWait = (): Promise<void> => {
      const pending = scheduler.wait(delayMs, control.controller.signal);
      // A stop can abort a pre-scheduled wait before the generator asks for
      // its next value. Attach a handling branch now to avoid an unhandled
      // rejection while preserving the original promise for the generator.
      void pending.catch(() => undefined);
      return pending;
    };

    async function* events(): AsyncIterable<ChatStreamEvent> {
      try {
        const current = options.store.read();
        const currentRequest = current.chatRequests[requestId];
        const currentMessageValue = currentRequest ? currentMessage(current, currentRequest) : undefined;
        if (!currentRequest || !currentMessageValue) return;
        const conversation = current.conversations[currentRequest.conversation_id];
        if (!conversation) return;

        const sourceScript =
          currentRequest.operation === "regenerate"
            ? scriptFor(options.scenario, conversation.conversation_id, findPromptForAssistant(conversation, currentRequest.message_id))
            : scriptFor(options.scenario, conversation.conversation_id, currentRequest.prompt ?? requestFingerprintPayload(currentRequest.payload_fingerprint ?? "", "content"));
        const requestPrompt = currentRequest.prompt ?? requestFingerprintPayload(currentRequest.payload_fingerprint ?? "", "content");
        const chunks = sourceScript?.chunks ?? fallbackChunks(
          requestPrompt,
          conversation.messages,
        );

        if (currentRequest.status !== "streaming") {
          yield {
            type: "started",
            request_id: requestId,
            conversation_id: currentRequest.conversation_id,
            message_id: currentRequest.message_id,
            sequence: 0,
          };
          for (let index = 0; index < Math.min(currentRequest.next_chunk_index, chunks.length); index += 1) {
            yield {
              type: "delta",
              request_id: requestId,
              conversation_id: currentRequest.conversation_id,
              message_id: currentRequest.message_id,
              sequence: index + 1,
              delta: chunks[index]!,
            };
          }
          control.terminalEmitted = true;
          const replay = replayTerminal(current, requestId, currentRequest.next_chunk_index + 1);
          if (replay) yield replay;
          return;
        }

        let nextIndex = currentRequest.next_chunk_index;
        // Sequence is global. A resumed producer starts from the first chunk
        // that is not represented by the persisted next-chunk cursor.
        let sequence = nextIndex + 1;

        // Start the first controllable wait before exposing started/0. This
        // gives injected schedulers a deterministic hand-off point and keeps
        // tests/event consumers free of wall-clock sleeps.
        let pendingWait: Promise<void> | undefined =
          nextIndex < chunks.length ? scheduleWait() : undefined;

        yield {
          type: "started",
          request_id: requestId,
          conversation_id: currentRequest.conversation_id,
          message_id: currentRequest.message_id,
          sequence: 0,
        };
        for (let index = 0; index < Math.min(nextIndex, chunks.length); index += 1) {
          yield {
            type: "delta",
            request_id: requestId,
            conversation_id: currentRequest.conversation_id,
            message_id: currentRequest.message_id,
            sequence: index + 1,
            delta: chunks[index]!,
          };
        }

        while (nextIndex < chunks.length) {
          try {
            await (pendingWait ?? scheduleWait());
            pendingWait = undefined;
          } catch (error) {
            if (control.stoppedByBusiness) {
              if (!control.terminalEmitted) {
                control.terminalEmitted = true;
                yield stoppedEvent(currentRequest, sequence);
              }
              return;
            }
            if (isAbortError(error)) return;
            throw error;
          }

          const beforeAppend = options.store.read();
          const requestBeforeAppend = beforeAppend.chatRequests[requestId];
          if (!requestBeforeAppend || requestBeforeAppend.status !== "streaming") {
            const replay = replayTerminal(beforeAppend, requestId, sequence);
            if (replay && !control.terminalEmitted) {
              control.terminalEmitted = true;
              yield replay;
            }
            return;
          }
          const chunk = chunks[nextIndex]!;
          const timestamp = isoNow(now);
          let applied = false;
          const persistedState = options.store.update((currentState) => {
            const storedRequest = currentState.chatRequests[requestId];
            const storedConversation = currentState.conversations[requestBeforeAppend.conversation_id];
            if (
              !storedRequest ||
              storedRequest.status !== "streaming" ||
              storedRequest.next_chunk_index !== nextIndex ||
              !storedConversation ||
              storedConversation.active_request_id !== requestId
            ) return currentState;
            const messages = storedConversation.messages.map((item) => ({ ...item }));
            const index = messages.findIndex((item) => item.message_id === storedRequest.message_id);
            if (index < 0) return currentState;
            applied = true;
            messages[index] = {
              ...messages[index]!,
              content: `${messages[index]!.content}${chunk}`,
              status: "streaming",
            };
            return {
              ...currentState,
              conversations: {
                ...currentState.conversations,
                [storedConversation.conversation_id]: {
                  ...storedConversation,
                  messages,
                  updated_at: timestamp,
                  active_request_cursor: sequence,
                },
              },
              chatRequests: {
                ...currentState.chatRequests,
                [requestId]: { ...storedRequest, next_chunk_index: nextIndex + 1 },
              },
            };
          });
          const persistedRequest = persistedState.chatRequests[requestId];
          const persistedMessage = persistedRequest
            ? currentMessage(persistedState, persistedRequest)
            : undefined;
          if (
            !applied ||
            !persistedRequest ||
            persistedRequest.next_chunk_index !== nextIndex + 1 ||
            persistedMessage?.content !== `${requestBeforeAppend ? currentMessage(beforeAppend, requestBeforeAppend)?.content ?? "" : ""}${chunk}`
          ) {
            // A separate service instance may have atomically claimed this
            // cursor first. Its producer owns the remaining stream; this
            // producer must stop without emitting a stale delta or replacing
            // the winning request with a synthetic failure.
            if (
              !applied &&
              persistedRequest?.status === "streaming" &&
              persistedRequest.next_chunk_index > nextIndex
            ) {
              return;
            }
            const error: ApiErrorResponse["error"] = {
              code: "DEMO_STATE_UPDATE_FAILED",
              message: "演示状态无法保存，请重试。",
              request_id: requestId,
              retryable: true,
            };
            if (!finishRequest(requestId, "failed", error)) {
              const replay = replayTerminal(options.store.read(), requestId, sequence);
              if (replay) yield replay;
              return;
            }
            control.terminalEmitted = true;
            yield {
              type: "failed",
              request_id: requestId,
              conversation_id: requestBeforeAppend.conversation_id,
              message_id: requestBeforeAppend.message_id,
              sequence,
              error,
            };
            return;
          }
          const deltaEvent: ChatStreamEvent = {
            type: "delta",
            request_id: requestId,
            conversation_id: requestBeforeAppend.conversation_id,
            message_id: requestBeforeAppend.message_id,
            sequence,
            delta: chunk,
          };
          nextIndex += 1;
          sequence += 1;
          if (nextIndex < chunks.length) {
            pendingWait = scheduleWait();
          }
          yield deltaEvent;
        }

        const finalState = options.store.read();
        const finalRequest = finalState.chatRequests[requestId];
        if (!finalRequest || finalRequest.status !== "streaming") {
          const replay = replayTerminal(finalState, requestId, sequence);
          if (replay && !control.terminalEmitted) {
            control.terminalEmitted = true;
            yield replay;
          }
          return;
        }
        const finalConversation = finalState.conversations[finalRequest.conversation_id];
        const finalMessage = finalConversation && currentMessage(finalState, finalRequest);
        if (!finalConversation || !finalMessage) return;

        const terminal = sourceScript?.terminal ?? "completed";
        if (terminal === "timeout" || terminal === "content_rejected") {
          const code = terminal === "timeout" ? "PROVIDER_TIMEOUT" : "CONTENT_REJECTED";
          const error = remapError(sourceScript?.error, requestId, code);
          const terminalStatus = terminal === "timeout" ? "timeout" : "content_rejected";
          if (!finishRequest(requestId, terminalStatus, error)) {
            const replay = replayTerminal(options.store.read(), requestId, sequence);
            if (replay) yield replay;
            return;
          }
          control.terminalEmitted = true;
          yield {
            type: "failed",
            request_id: requestId,
            conversation_id: finalRequest.conversation_id,
            message_id: finalRequest.message_id,
            sequence,
            error,
          };
          return;
        }
        if (terminal === "stopped") {
          if (!finishRequest(requestId, "stopped")) {
            const replay = replayTerminal(options.store.read(), requestId, sequence);
            if (replay) yield replay;
            return;
          }
          control.terminalEmitted = true;
          yield stoppedEvent(finalRequest, sequence);
          return;
        }

        if (!finishRequest(requestId, "completed")) {
          const replay = replayTerminal(options.store.read(), requestId, sequence);
          if (replay) yield replay;
          return;
        }
        control.terminalEmitted = true;
        const completedState = options.store.read();
        const completedRequest = completedState.chatRequests[requestId] ?? finalRequest;
        yield {
          type: "completed",
          request_id: requestId,
          conversation_id: completedRequest.conversation_id,
          message_id: completedRequest.message_id,
          sequence,
          content: currentMessage(completedState, completedRequest)?.content ?? finalMessage.content,
        };
      } finally {
        removeControl(control);
      }
    }

    const producer: SharedProducer = {
      requestId,
      messageId: message.message_id,
      conversationId: request.conversation_id,
      source: events()[Symbol.asyncIterator](),
      events: [],
      waiters: new Set(),
      pumping: false,
      done: false,
      error: undefined,
    };
    producers.set(requestId, producer);

    const cursor = resumeCursor === undefined
      ? null
      : resumeCursor ?? -1;
    let lastSequence = cursor ?? -1;
    const streamEvents = (async function* (): AsyncIterable<ChatStreamEvent> {
      for await (const event of subscribe(
        producer,
        subscriptionSignal,
        resumeCursor === undefined ? undefined : cursor,
      )) {
        lastSequence = event.sequence;
        yield event;
      }
    })();

    return {
      requestId,
      messageId: message.message_id,
      cursor,
      get lastSequence() {
        return lastSequence;
      },
      events: streamEvents,
    };
  }

  function findPromptForAssistant(conversation: Conversation, messageId: string): string {
    const index = conversation.messages.findIndex((message) => message.message_id === messageId);
    for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
      const message = conversation.messages[cursor]!;
      if (message.role === "user") return message.content;
    }
    return "";
  }

  function stoppedEvent(request: DemoChatRequestState, sequence: number): ChatStreamEvent {
    return {
      type: "stopped",
      request_id: request.request_id,
      conversation_id: request.conversation_id,
      message_id: request.message_id,
      sequence,
    };
  }

  function replayTerminal(
    state: DemoState,
    requestId: string,
    sequence: number,
  ): ChatStreamEvent | undefined {
    const request = state.chatRequests[requestId];
    if (!request || request.status === "streaming") return undefined;
    const message = currentMessage(state, request);
    if (!message) return undefined;
    const terminalSequence = request.next_chunk_index + 1;
    void sequence;
    if (request.status === "completed") {
      return {
        type: "completed",
        request_id: request.request_id,
        conversation_id: request.conversation_id,
        message_id: request.message_id,
        sequence: terminalSequence,
        content: message.content,
      };
    }
    if (request.status === "stopped") return stoppedEvent(request, terminalSequence);
    return {
      type: "failed",
      request_id: request.request_id,
      conversation_id: request.conversation_id,
      message_id: request.message_id,
      sequence: terminalSequence,
      error: request.error ?? {
        code: request.status === "timeout" ? "PROVIDER_TIMEOUT" : "DEMO_REQUEST_FAILED",
        message: "演示请求未完成。",
        request_id: request.request_id,
        retryable: request.status === "timeout",
      },
    };
  }

  function finishRequest(
    requestId: string,
    status: DemoChatRequestState["status"],
    error?: ApiErrorResponse["error"],
  ): boolean {
    const timestamp = isoNow(now);
    const persisted = options.store.update((state) => {
      const request = state.chatRequests[requestId];
      if (!request || request.status !== "streaming") return state;
      const conversation = state.conversations[request.conversation_id];
      if (!conversation || conversation.active_request_id !== requestId) return state;
      const messages = conversation.messages.map((item) => ({ ...item }));
      const messageIndex = messages.findIndex((item) => item.message_id === request.message_id);
      if (messageIndex < 0) return state;
      const terminalMessageStatus = status === "completed" ? "complete" : status === "stopped" ? "stopped" : "failed";
      messages[messageIndex] = {
        ...messages[messageIndex]!,
        status: terminalMessageStatus,
      };
      return {
        ...state,
        conversations: {
          ...state.conversations,
          [conversation.conversation_id]: {
            ...conversation,
            messages,
            active_request_id: null,
            active_request_cursor: null,
            updated_at: timestamp,
          },
        },
        chatRequests: {
          ...state.chatRequests,
          [requestId]: {
            ...request,
            status,
            next_chunk_index: request.next_chunk_index,
            ...(error === undefined ? {} : { error }),
          },
        },
      };
    });
    const request = persisted.chatRequests[requestId];
    const conversation = persisted.conversations[request?.conversation_id ?? ""];
    return request?.status === status && conversation?.active_request_id === null;
  }

  function send(
    input: { conversationId: string; content: string; clientRequestId: string },
    signal?: AbortSignal,
  ): Promise<ConversationStream> {
    abortIfNeeded(signal);
    if (!NON_EMPTY.test(input.content) || !NON_EMPTY.test(input.clientRequestId)) {
      return Promise.reject(serviceError("MESSAGE_EMPTY", 400));
    }
    const requestFingerprint = fingerprint("send", {
      conversation_id: input.conversationId,
      content: input.content,
    });
    const requestId = stableId("request", "send", input.conversationId, input.clientRequestId);
    const state = options.store.read();
    const existing = state.chatRequests[requestId];
    const match = requestMatches(existing, "send", requestFingerprint);
    if (match === "conflict") return Promise.reject(serviceError("IDEMPOTENCY_KEY_REUSED", 409, false, requestId));
    if (match === "same") return Promise.resolve(streamFor(requestId, signal));
    const conversation = state.conversations[input.conversationId];
    if (!conversation) return Promise.reject(serviceError("CONVERSATION_NOT_FOUND", 404));
    if (conversation.active_request_id !== null) return Promise.reject(serviceError("CONVERSATION_BUSY", 409, true, conversation.active_request_id));
    const messageId = stableId("message-assistant", "send", input.conversationId, input.clientRequestId);
    return Promise.resolve(initializeRequest("send", input.conversationId, input.clientRequestId, requestFingerprint, messageId, conversation.messages.filter((message) => message.role === "user").length, signal));
  }

  return {
    async listConversations(signal) {
      abortIfNeeded(signal);
      const conversations = Object.values(options.store.read().conversations)
        .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
      return conversations.map(summaryOf).map(clone);
    },

    async getConversation(conversationId, signal) {
      abortIfNeeded(signal);
      const conversation = getConversationOrThrow(options.store.read(), conversationId);
      return clone(conversation);
    },

    async getDraft(conversationId, signal) {
      abortIfNeeded(signal);
      const state = options.store.read();
      getConversationOrThrow(state, conversationId);
      return state.drafts[conversationId] ?? "";
    },

    async saveDraft(input, signal) {
      abortIfNeeded(signal);
      getConversationOrThrow(options.store.read(), input.conversationId);
      if (input.content.length > 8192) {
        throw serviceError(
          "CONVERSATION_UNAVAILABLE",
          413,
          false,
          undefined,
          "草稿长度超过演示环境限制。",
        );
      }
      options.store.update((current) => {
        if (!current.conversations[input.conversationId]) return current;
        return {
          ...current,
          drafts: {
            ...current.drafts,
            [input.conversationId]: input.content,
          },
        };
      });
    },

    async createConversation(input, signal) {
      abortIfNeeded(signal);
      if (!modelExists(input.productModelId)) throw serviceError("MODEL_NOT_FOUND", 404);
      if (!NON_EMPTY.test(input.clientRequestId)) throw serviceError("IDEMPOTENCY_KEY_REUSED", 400);
      const conversationId = stableId("conversation", "create", input.clientRequestId);
      const createFingerprint = fingerprint("create", {
        product_model_id: input.productModelId,
      });
      const state = options.store.read();
      const existingCreate = state.conversationCreates?.[input.clientRequestId];
      if (existingCreate) {
        if (
          existingCreate.payload_fingerprint !== createFingerprint ||
          existingCreate.product_model_id !== input.productModelId
        ) {
          throw serviceError("IDEMPOTENCY_KEY_REUSED", 409);
        }
        const created = state.conversations[existingCreate.conversation_id];
        if (created) return clone(created);
      }
      const existing = state.conversations[conversationId];
      if (existing) {
        if (existing.product_model_id !== input.productModelId) throw serviceError("IDEMPOTENCY_KEY_REUSED", 409);
        return clone(existing);
      }
      const model = options.scenario.models.find((item) => item.product_model_id === input.productModelId)!;
      const timestamp = isoNow(now);
      options.store.update((current) => {
        if (current.conversations[conversationId]) return current;
        const conversation: DemoConversationState = {
          conversation_id: conversationId,
          product_model_id: input.productModelId,
          title: `${model.display_name} 对话`,
          messages: [],
          updated_at: timestamp,
          active_request_id: null,
          active_request_cursor: null,
        };
        return {
          ...current,
          conversations: { ...current.conversations, [conversationId]: conversation },
          conversationCreates: {
            ...(current.conversationCreates ?? {}),
            [input.clientRequestId]: {
              client_request_id: input.clientRequestId,
              product_model_id: input.productModelId,
              conversation_id: conversationId,
              payload_fingerprint: createFingerprint,
            },
          },
        };
      });
      return clone(options.store.read().conversations[conversationId]!);
    },

    sendMessage: send,

    async resumeMessage(input, signal) {
      abortIfNeeded(signal);
      const state = options.store.read();
      const request = state.chatRequests[input.requestId];
      if (!request || request.conversation_id !== input.conversationId) {
        throw serviceError("CONVERSATION_NOT_FOUND", 404, false, input.requestId);
      }
      return streamFor(request.request_id, signal, input.cursor);
    },

    async regenerate(input, signal) {
      abortIfNeeded(signal);
      if (!NON_EMPTY.test(input.clientRequestId)) throw serviceError("IDEMPOTENCY_KEY_REUSED", 400);
      const state = options.store.read();
      const conversation = state.conversations[input.conversationId];
      if (!conversation) throw serviceError("CONVERSATION_NOT_FOUND", 404);
      const target = conversation.messages.find((message) => message.message_id === input.messageId);
      if (!target || target.role !== "assistant") throw serviceError("CONVERSATION_NOT_FOUND", 404);
      const latestAssistant = [...conversation.messages]
        .reverse()
        .find((message) => message.role === "assistant");
      if (latestAssistant?.message_id !== input.messageId) {
        throw serviceError("MESSAGE_NOT_LATEST", 409);
      }
      const requestFingerprint = fingerprint("regenerate", {
        conversation_id: input.conversationId,
        message_id: input.messageId,
      });
      const requestId = stableId("request", "regenerate", input.conversationId, input.clientRequestId);
      const existing = state.chatRequests[requestId];
      const match = requestMatches(existing, "regenerate", requestFingerprint);
      if (match === "conflict") throw serviceError("IDEMPOTENCY_KEY_REUSED", 409, false, requestId);
      if (match === "same") return streamFor(requestId, signal);
      if (conversation.active_request_id !== null) throw serviceError("CONVERSATION_BUSY", 409, true, conversation.active_request_id);
      options.store.update((current) => {
        const currentConversation = current.conversations[input.conversationId];
        if (!currentConversation || currentConversation.active_request_id !== null) return current;
        const timestamp = isoNow(now);
        const messages = currentConversation.messages.map((message) =>
          message.message_id === input.messageId
            ? { ...message, content: "", status: "streaming" as const, request_id: requestId }
            : { ...message },
        );
        return {
          ...current,
          conversations: {
            ...current.conversations,
            [input.conversationId]: {
              ...currentConversation,
              messages,
              updated_at: timestamp,
              active_request_id: requestId,
              active_request_cursor: -1,
            },
          },
          chatRequests: {
            ...current.chatRequests,
            [requestId]: {
              request_id: requestId,
              conversation_id: input.conversationId,
              message_id: input.messageId,
              status: "streaming",
              next_chunk_index: 0,
              turn_index: currentConversation.messages.filter((message) => message.role === "user").length - 1,
              operation: "regenerate",
              client_request_id: input.clientRequestId,
              payload_fingerprint: requestFingerprint,
              prompt: findPromptForAssistant(currentConversation, input.messageId),
            },
          },
        };
      });
      return streamFor(requestId, signal);
    },

    async stopMessage(input, signal) {
      abortIfNeeded(signal);
      const state = options.store.read();
      const request = state.chatRequests[input.requestId];
      if (!request || request.conversation_id !== input.conversationId) {
        throw serviceError("CONVERSATION_NOT_FOUND", 404, false, input.requestId);
      }
      if (request.status !== "streaming") return;
      const active = controls.get(request.request_id);
      if (!finishRequest(request.request_id, "stopped")) return;
      if (active) {
        for (const control of active) control.stoppedByBusiness = true;
      }
      if (active) {
        for (const control of active) control.controller.abort();
      }
    },
  };
}
