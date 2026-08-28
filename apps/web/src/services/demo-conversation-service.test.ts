import { describe, expect, it } from "vitest";
import type { ChatStreamEvent } from "@mosaic/contracts";
import { DEMO_SCENARIO } from "@/shared/demo/demo-scenario";
import {
  createDemoStateStore,
  type StorageLike,
} from "@/shared/demo/demo-state-store";
import type { DemoScheduler } from "@/shared/demo/demo-scheduler";
import {
  ConversationServiceError,
  createDemoConversationService,
} from "./demo-conversation-service";

const NOW = "2026-08-22T12:00:00.000Z";

function setup() {
  const values = new Map<string, string>();
  const storage: StorageLike = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const store = createDemoStateStore({ storage, now: () => NOW });
  const pending: Array<() => void> = [];
  const scheduler: DemoScheduler = {
    wait: (_delay, signal) =>
      new Promise<void>((resolve, reject) => {
        if (signal?.aborted) {
          reject(signal.reason ?? new DOMException("aborted", "AbortError"));
          return;
        }
        const onAbort = () => reject(signal?.reason ?? new DOMException("aborted", "AbortError"));
        signal?.addEventListener("abort", onAbort, { once: true });
        pending.push(() => {
          signal?.removeEventListener("abort", onAbort);
          resolve();
        });
      }),
  };
  return {
    storage,
    store,
    pending,
    service: createDemoConversationService({ scenario: DEMO_SCENARIO, store, scheduler }),
  };
}

describe("demo conversation service", () => {
  it("reads and persists drafts through the v2 state store", async () => {
    const { service, store } = setup();
    const conversation = await service.getConversation("conversation-qwen-3-5-001");
    expect(await service.getDraft(conversation.conversation_id)).toBe("");

    await service.saveDraft({
      conversationId: conversation.conversation_id,
      content: "保留到下一次打开的草稿",
    });
    expect(await service.getDraft(conversation.conversation_id)).toBe("保留到下一次打开的草稿");
    expect(store.read().drafts[conversation.conversation_id]).toBe("保留到下一次打开的草稿");

    await service.saveDraft({ conversationId: conversation.conversation_id, content: "" });
    expect(await service.getDraft(conversation.conversation_id)).toBe("");
  });

  it("does not save drafts for unknown conversations", async () => {
    const { service } = setup();
    await expect(service.getDraft("unknown-conversation")).rejects.toMatchObject({
      code: "CONVERSATION_NOT_FOUND",
    });
    await expect(service.saveDraft({ conversationId: "unknown-conversation", content: "x" })).rejects.toMatchObject({
      code: "CONVERSATION_NOT_FOUND",
    });
  });

  it("persists one user and assistant placeholder and emits deterministic chunks", async () => {
    const { service, store, pending } = setup();
    const conversation = await service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-1",
    });
    const stream = await service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "第一轮问题",
      clientRequestId: "send-1",
    });

    expect(store.read().conversations[conversation.conversation_id]?.messages).toHaveLength(2);
    expect(store.read().conversations[conversation.conversation_id]?.active_request_cursor).toBe(-1);
    expect(stream.cursor).toBeNull();
    expect(stream.lastSequence).toBe(-1);
    const iterator = stream.events[Symbol.asyncIterator]();
    const started = await iterator.next();
    expect(started.value).toMatchObject({ type: "started", sequence: 0 });
    pending.shift()?.();
    const delta = await iterator.next();
    expect(delta.value).toMatchObject({ type: "delta", sequence: 1 });
    expect(store.read().conversations[conversation.conversation_id]?.active_request_cursor).toBe(1);
    expect(stream.lastSequence).toBe(1);
    pending.shift()?.();
    const delta2 = await iterator.next();
    expect(delta2.value).toMatchObject({ type: "delta", sequence: 2 });
    pending.shift()?.();
    const terminal = await iterator.next();
    expect(terminal.value).toMatchObject({ type: "completed" });
    expect((await iterator.next()).done).toBe(true);

    const saved = store.read();
    expect(saved.conversations[conversation.conversation_id]?.active_request_id).toBeNull();
    expect(saved.conversations[conversation.conversation_id]?.active_request_cursor).toBeNull();
    expect(saved.chatRequests[stream.requestId]?.status).toBe("completed");
  });

  it("deduplicates same key, rejects conflicting key payload, and blocks concurrent requests", async () => {
    const { service } = setup();
    const conversation = await service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-2",
    });
    const first = await service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "相同请求",
      clientRequestId: "same-key",
    });
    const duplicate = await service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "相同请求",
      clientRequestId: "same-key",
    });
    expect(duplicate.requestId).toBe(first.requestId);
    await expect(
      service.sendMessage({
        conversationId: conversation.conversation_id,
        content: "不同请求",
        clientRequestId: "same-key",
      }),
    ).rejects.toMatchObject({ code: "IDEMPOTENCY_KEY_REUSED" });
    await expect(
      service.sendMessage({
        conversationId: conversation.conversation_id,
        content: "另一个并发请求",
        clientRequestId: "other-key",
      }),
    ).rejects.toMatchObject({ code: "CONVERSATION_BUSY" });
  });

  it("shares one producer for concurrent same-key stream subscriptions", async () => {
    const { service, store, pending } = setup();
    const conversation = await service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-shared",
    });
    const first = await service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "共享生产者",
      clientRequestId: "shared-key",
    });
    const second = await service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "共享生产者",
      clientRequestId: "shared-key",
    });
    expect(second.requestId).toBe(first.requestId);

    const firstIterator = first.events[Symbol.asyncIterator]();
    const secondIterator = second.events[Symbol.asyncIterator]();
    const firstEvents: ChatStreamEvent[] = [];
    const secondEvents: ChatStreamEvent[] = [];
    const firstNext = firstIterator.next();
    const secondNext = secondIterator.next();
    let firstResult = await firstNext;
    let secondResult = await secondNext;
    while (!firstResult.done && !secondResult.done) {
      firstEvents.push(firstResult.value);
      secondEvents.push(secondResult.value);
      if (firstResult.value.type === "completed") break;
      pending.shift()?.();
      [firstResult, secondResult] = await Promise.all([
        firstIterator.next(),
        secondIterator.next(),
      ]);
    }

    expect(firstEvents).toEqual(secondEvents);
    expect(firstEvents.at(-1)?.type).toBe("completed");
    expect(secondEvents.at(-1)?.type).toBe("completed");
    expect(firstEvents.filter((item) => item.type === "delta")).toHaveLength(2);
    const saved = store.read();
    const savedConversation = saved.conversations[conversation.conversation_id]!;
    expect(savedConversation.messages.filter((item) => item.role === "assistant")).toHaveLength(1);
    expect(saved.chatRequests[first.requestId]?.status).toBe("completed");
    expect(savedConversation.active_request_id).toBeNull();
  });

  it("stops without turning subscription abort into a business failure and resumes cursor", async () => {
    const first = setup();
    const conversation = await first.service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-3",
    });
    const stream = await first.service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "演示停止响应",
      clientRequestId: "stop-key",
    });
    const iterator = stream.events[Symbol.asyncIterator]();
    await iterator.next();
    first.pending.shift()?.();
    await iterator.next();
    const beforeStop = first.store.read().chatRequests[stream.requestId]?.next_chunk_index;
    await first.service.stopMessage({
      conversationId: conversation.conversation_id,
      requestId: stream.requestId,
    });
    expect(first.store.read().chatRequests[stream.requestId]?.status).toBe("stopped");
    expect(first.store.read().chatRequests[stream.requestId]?.next_chunk_index).toBe(beforeStop);

    const controller = new AbortController();
    controller.abort();
    await expect(
      first.service.resumeMessage({
        conversationId: conversation.conversation_id,
        requestId: stream.requestId,
        cursor: null,
      }, controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("does not emit or persist a delta when stop wins after the scheduler resolves", async () => {
    const { service, pending, store } = setup();
    const conversation = await service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-stop-race",
    });
    const stream = await service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "停止竞争",
      clientRequestId: "stop-race-key",
    });
    const iterator = stream.events[Symbol.asyncIterator]();
    await iterator.next();
    pending.shift()?.();
    await service.stopMessage({
      conversationId: conversation.conversation_id,
      requestId: stream.requestId,
    });

    const terminal = await iterator.next();
    expect(terminal.value).toMatchObject({ type: "stopped", sequence: 1 });
    const saved = store.read();
    expect(saved.conversations[conversation.conversation_id]?.messages.at(-1)?.content).toBe("");
    expect(saved.chatRequests[stream.requestId]?.status).toBe("stopped");
    expect(saved.conversations[conversation.conversation_id]?.active_request_id).toBeNull();
  });

  it("replays a completed terminal when another producer completes first", async () => {
    const first = setup();
    const conversation = await first.service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-cross-service",
    });
    const firstStream = await first.service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "跨服务恢复",
      clientRequestId: "cross-service-key",
    });
    const firstIterator = firstStream.events[Symbol.asyncIterator]();
    await firstIterator.next();
    first.pending.shift()?.();
    await firstIterator.next();
    expect(first.store.read().chatRequests[firstStream.requestId]?.next_chunk_index).toBe(1);

    const secondStore = createDemoStateStore({
      storage: first.storage,
      now: () => NOW,
    });
    const secondService = createDemoConversationService({
      scenario: DEMO_SCENARIO,
      store: secondStore,
      scheduler: { wait: async () => undefined },
    });
    const resumed = await secondService.resumeMessage({
      conversationId: conversation.conversation_id,
      requestId: firstStream.requestId,
      cursor: 0,
    });
    const resumedEvents: ChatStreamEvent[] = [];
    for await (const event of resumed.events) resumedEvents.push(event);

    expect(resumedEvents.map((event) => event.sequence)).toEqual([1, 2, 3]);
    expect(resumedEvents.at(-1)?.type).toBe("completed");
    expect(secondStore.read().chatRequests[firstStream.requestId]?.status).toBe("completed");
    first.pending.shift()?.();
    const firstRaceTerminal = await firstIterator.next();
    expect(firstRaceTerminal.value).toMatchObject({ type: "completed", sequence: 3 });
  });

  it("resumes the same producer after subscription abort without replaying persisted deltas", async () => {
    const controller = new AbortController();
    const { service, pending } = setup();
    const conversation = await service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-same-service-resume",
    });
    const first = await service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "同服务恢复",
      clientRequestId: "same-service-resume",
    }, controller.signal);
    const firstIterator = first.events[Symbol.asyncIterator]();
    await firstIterator.next();
    pending.shift()?.();
    const firstDelta = await firstIterator.next();
    expect(firstDelta.value).toMatchObject({ type: "delta", sequence: 1 });
    controller.abort();

    const resumed = await service.resumeMessage({
      conversationId: conversation.conversation_id,
      requestId: first.requestId,
      cursor: 1,
    });
    const resumedEvents: ChatStreamEvent[] = [];
    const resumedIterator = resumed.events[Symbol.asyncIterator]();
    pending.shift()?.();
    let next = await resumedIterator.next();
    while (!next.done) {
      resumedEvents.push(next.value);
      if (next.value.type === "completed") break;
      pending.shift()?.();
      next = await resumedIterator.next();
    }

    expect(resumedEvents.map((event) => event.sequence)).toEqual([2, 3]);
    expect(resumedEvents.filter((event) => event.type === "delta")).toHaveLength(1);
    expect(resumedEvents.find((event) => event.type === "delta")).not.toMatchObject({
      delta: "已收到你的问题：",
    });
    expect(resumedEvents.at(-1)?.type).toBe("completed");
  });

  it("replays a failed terminal when another producer completes the request first", async () => {
    const first = setup();
    const conversation = await first.service.createConversation({
      productModelId: "qwen-3-5",
      clientRequestId: "create-failed-race",
    });
    const stream = await first.service.sendMessage({
      conversationId: conversation.conversation_id,
      content: "演示内容拒绝响应",
      clientRequestId: "failed-race-key",
    });
    const firstIterator = stream.events[Symbol.asyncIterator]();
    await firstIterator.next();

    const secondStore = createDemoStateStore({ storage: first.storage, now: () => NOW });
    const secondService = createDemoConversationService({
      scenario: DEMO_SCENARIO,
      store: secondStore,
      scheduler: { wait: async () => undefined },
    });
    const secondStream = await secondService.resumeMessage({
      conversationId: conversation.conversation_id,
      requestId: stream.requestId,
      cursor: 0,
    });
    const secondEvents: ChatStreamEvent[] = [];
    for await (const event of secondStream.events) secondEvents.push(event);
    expect(secondEvents.at(-1)).toMatchObject({ type: "failed", sequence: 1 });

    const firstTerminal = await firstIterator.next();
    expect(firstTerminal.value).toMatchObject({
      type: "failed",
      sequence: 1,
      error: { code: "CONTENT_REJECTED", request_id: stream.requestId },
    });
  });

  it("maps timeout and content rejection to failed assistant events with actual request IDs", async () => {
    for (const [content, expectedCode] of [
      ["演示超时响应", "PROVIDER_TIMEOUT"],
      ["演示内容拒绝响应", "CONTENT_REJECTED"],
    ] as const) {
      const { service, pending, store } = setup();
      const conversation = await service.createConversation({
        productModelId: "qwen-3-5",
        clientRequestId: `create-${expectedCode}`,
      });
      const stream = await service.sendMessage({
        conversationId: conversation.conversation_id,
        content,
        clientRequestId: `key-${expectedCode}`,
      });
      const iterator = stream.events[Symbol.asyncIterator]();
      await iterator.next();
      if (pending.length > 0) pending.shift()?.();
      if (expectedCode === "PROVIDER_TIMEOUT") {
        expect((await iterator.next()).value).toMatchObject({ type: "delta" });
      }
      const terminal = await iterator.next();
      expect(terminal.value).toMatchObject({
        type: "failed",
        request_id: stream.requestId,
        error: { code: expectedCode, request_id: stream.requestId },
      });
      expect(store.read().chatRequests[stream.requestId]?.status).toBe(
        expectedCode === "PROVIDER_TIMEOUT" ? "timeout" : "content_rejected",
      );
    }
  });

  it("regenerates the assistant in place without adding another user message", async () => {
    const { service, pending } = setup();
    const conversation = DEMO_SCENARIO.conversations[0]!;
    const target = conversation.messages.at(-1)!;
    const beforeUsers = conversation.messages.filter((item) => item.role === "user").length;
    const stream = await service.regenerate({
      conversationId: conversation.conversation_id,
      messageId: target.message_id,
      clientRequestId: "regenerate-1",
    });
    expect((await service.getConversation(conversation.conversation_id)).messages.filter((item) => item.role === "user")).toHaveLength(beforeUsers);
    const iterator = stream.events[Symbol.asyncIterator]();
    const received: ChatStreamEvent[] = [];
    let next = await iterator.next();
    while (!next.done) {
      received.push(next.value);
      pending.shift()?.();
      next = await iterator.next();
    }
    expect(received.at(-1)?.type).toBe("completed");
    const latest = await service.getConversation(conversation.conversation_id);
    expect(latest.messages.filter((item) => item.role === "user")).toHaveLength(beforeUsers);
    expect(latest.messages.at(-1)?.message_id).toBe(target.message_id);
  });

  it("rejects regeneration of an older assistant candidate", async () => {
    const { service } = setup();
    const conversation = DEMO_SCENARIO.conversations[0]!;
    const olderAssistant = conversation.messages.find(
      (message) => message.role === "assistant",
    )!;
    await expect(
      service.regenerate({
        conversationId: conversation.conversation_id,
        messageId: olderAssistant.message_id,
        clientRequestId: "regenerate-old",
      }),
    ).rejects.toMatchObject({ code: "MESSAGE_NOT_LATEST" });
  });

  it("reports typed not-found errors", async () => {
    const { service } = setup();
    await expect(service.getConversation("missing")).rejects.toBeInstanceOf(ConversationServiceError);
  });
});
