import { describe, expect, it, vi } from "vitest";
import type { ChatStreamEvent, Conversation } from "@mosaic/contracts";
import {
  ApiConversationServiceError,
  createApiConversationService,
} from "./api-conversation-service";

const NOW = "2026-08-22T12:00:00.000Z";
const baseConversation: Conversation = {
  conversation_id: "conversation-api",
  product_model_id: "qwen-3-5",
  title: "API 会话",
  messages: [],
  updated_at: NOW,
  active_request_id: null,
  active_request_cursor: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  } as Response;
}

function streamResponse(
  events: readonly ChatStreamEvent[],
  status = 200,
  lineEnding = "\n",
  extraHeaders: Record<string, string> = {},
): Response {
  const encoder = new TextEncoder();
  const payload = events.map((item) => `id: ${item.sequence}${lineEnding}data: ${JSON.stringify(item)}${lineEnding}${lineEnding}`).join("");
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({
      "content-type": "text/event-stream",
      "x-request-id": events[0]?.request_id ?? "request-api",
      "x-message-id": events[0]?.message_id ?? "message-api",
      ...extraHeaders,
    }),
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        const bytes = encoder.encode(payload);
        controller.enqueue(bytes.slice(0, 7));
        controller.enqueue(bytes.slice(7, 13));
        controller.enqueue(bytes.slice(13));
        controller.close();
      },
    }),
  } as Response;
}

function rawStreamResponse(payload: string, status = 200, splitAt?: number): Response {
  const encoder = new TextEncoder();
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({
      "content-type": "text/event-stream",
      "x-request-id": "request-api",
      "x-message-id": "message-api",
    }),
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        const bytes = encoder.encode(payload);
        const boundary = splitAt ?? Math.floor(bytes.length / 2);
        controller.enqueue(bytes.slice(0, boundary));
        controller.enqueue(bytes.slice(boundary));
        controller.close();
      },
    }),
  } as Response;
}

function emptyTerminalResponse(): Response {
  return {
    ok: true,
    status: 204,
    headers: new Headers({
      "x-chat-request-id": "request-api",
      "x-message-id": "message-api",
    }),
    body: null,
  } as Response;
}

const events: ChatStreamEvent[] = [
  {
    type: "started",
    request_id: "request-api",
    conversation_id: "conversation-api",
    message_id: "message-api",
    sequence: 0,
  },
  {
    type: "delta",
    request_id: "request-api",
    conversation_id: "conversation-api",
    message_id: "message-api",
    sequence: 1,
    delta: "你好",
  },
  {
    type: "completed",
    request_id: "request-api",
    conversation_id: "conversation-api",
    message_id: "message-api",
    sequence: 2,
    content: "你好",
  },
];

describe("api conversation service", () => {
  it("forwards the double-submit CSRF token on message writes", async () => {
    const token = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
    document.cookie = `mosaic_csrf=${token}; Path=/`;
    const fetcher = vi.fn().mockResolvedValue(streamResponse(events));
    const service = createApiConversationService(fetcher);

    try {
      await service.sendMessage({
        conversationId: "conversation-1",
        content: "hello",
        clientRequestId: "client-1",
      });
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/conversations/conversation-1/messages",
        expect.objectContaining({
          headers: expect.objectContaining({ "X-CSRF-Token": token }),
        }),
      );
    } finally {
      document.cookie = "mosaic_csrf=; Max-Age=0; Path=/";
    }
  });

  it("reports draft persistence as unavailable without inventing an endpoint", async () => {
    const fetcher = vi.fn();
    const service = createApiConversationService(fetcher);

    await expect(service.getDraft("conversation-api")).rejects.toMatchObject({
      code: "CONVERSATION_UNAVAILABLE",
      status: 503,
      retryable: true,
    });
    await expect(service.saveDraft({ conversationId: "conversation-api", content: "draft" })).rejects.toMatchObject({
      code: "CONVERSATION_UNAVAILABLE",
      status: 503,
      retryable: true,
    });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("sends idempotency headers and parses arbitrary SSE chunk boundaries", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(jsonResponse(baseConversation))
      .mockResolvedValueOnce(streamResponse(events));
    const service = createApiConversationService(fetcher);
    await service.createConversation({ productModelId: "qwen-3-5", clientRequestId: "create-key" });
    const stream = await service.sendMessage({
      conversationId: "conversation-api",
      content: "你好",
      clientRequestId: "send-key",
    });
    const received: ChatStreamEvent[] = [];
    for await (const item of stream.events) received.push(item);
    expect(received).toEqual(events);
    expect(fetcher.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "Idempotency-Key": "create-key" }),
    }));
    expect(fetcher.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "Idempotency-Key": "send-key" }),
    }));
    expect(fetcher.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      headers: expect.objectContaining({ accept: "text/event-stream" }),
    }));
  });

  it("uses the SSE Accept header for resume and regenerate", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(streamResponse(events))
      .mockResolvedValueOnce(streamResponse(events));
    const service = createApiConversationService(fetcher);
    await service.resumeMessage({ conversationId: "conversation-api", requestId: "request-api", cursor: null });
    await service.regenerate({
      conversationId: "conversation-api",
      messageId: "message-api",
      clientRequestId: "regen-key",
    });

    expect(fetcher.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      headers: expect.objectContaining({ accept: "text/event-stream" }),
    }));
    expect(fetcher.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      headers: expect.objectContaining({ accept: "text/event-stream" }),
    }));
  });

  it("sends Last-Event-ID only for a real resume cursor and keeps global sequences", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(streamResponse([events[2]!]))
      .mockResolvedValueOnce(streamResponse(events));
    const service = createApiConversationService(fetcher);

    const resumed = await service.resumeMessage({
      conversationId: "conversation-api",
      requestId: "request-api",
      cursor: 1,
    });
    expect(resumed.cursor).toBe(1);
    expect(resumed.lastSequence).toBe(1);
    const resumedEvents: ChatStreamEvent[] = [];
    for await (const event of resumed.events) resumedEvents.push(event);
    expect(resumedEvents).toEqual([events[2]]);
    expect(resumed.lastSequence).toBe(2);
    expect(fetcher.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      headers: expect.objectContaining({ "Last-Event-ID": "1" }),
    }));

    await service.resumeMessage({
      conversationId: "conversation-api",
      requestId: "request-api",
      cursor: null,
    });
    expect(fetcher.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      headers: expect.not.objectContaining({ "Last-Event-ID": expect.anything() }),
    }));
  });

  it("accepts an explicit 204 when a resume cursor already covers the terminal event", async () => {
    const fetcher = vi.fn().mockResolvedValue(emptyTerminalResponse());
    const service = createApiConversationService(fetcher);
    const stream = await service.resumeMessage({
      conversationId: "conversation-api",
      requestId: "request-api",
      cursor: 2,
    });
    const received: ChatStreamEvent[] = [];
    for await (const event of stream.events) received.push(event);

    expect(received).toEqual([]);
    expect(stream.lastSequence).toBe(2);
  });

  it("prefers the business chat request id over the HTTP correlation id", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      streamResponse(events, 200, "\n", {
        "x-chat-request-id": "request-api",
        "x-request-id": "http-correlation-id",
      }),
    );
    const service = createApiConversationService(fetcher);
    const stream = await service.sendMessage({
      conversationId: "conversation-api",
      content: "你好",
      clientRequestId: "chat-id",
    });
    expect(stream.requestId).toBe("request-api");
  });

  it("validates event IDs and rejects malformed or extra fields", async () => {
    const invalid = {
      ...events[1],
      extra: true,
    };
    const fetcher = vi.fn().mockResolvedValue(streamResponse([events[0]!, invalid as ChatStreamEvent]));
    const service = createApiConversationService(fetcher);
    const stream = await service.resumeMessage({ conversationId: "conversation-api", requestId: "request-api", cursor: null });
    await expect((async () => {
      for await (const event of stream.events) {
        void event;
      }
    })()).rejects.toMatchObject({ code: "STREAM_RESPONSE_INVALID" });
  });

  it("preserves AbortError from fetch and reader", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    const fetcher = vi.fn().mockRejectedValue(abortError);
    const service = createApiConversationService(fetcher);
    await expect(service.listConversations()).rejects.toBe(abortError);
  });

  it("rejects RFC3339 timestamps without a timezone", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      jsonResponse({ ...baseConversation, updated_at: "2026-08-22T12:00:00" }),
    );
    const service = createApiConversationService(fetcher);
    await expect(service.getConversation("conversation-api")).rejects.toMatchObject({
      code: "STREAM_RESPONSE_INVALID",
    });
  });

  it("accepts an explicit null request id on persisted user messages", async () => {
    const conversation: Conversation = {
      ...baseConversation,
      messages: [
        {
          message_id: "message-user",
          role: "user",
          content: "hello",
          status: "complete",
          created_at: NOW,
          request_id: null,
        },
      ],
    };
    const fetcher = vi.fn().mockResolvedValue(jsonResponse(conversation));
    const service = createApiConversationService(fetcher);

    await expect(service.getConversation("conversation-api")).resolves.toEqual(conversation);
  });

  it("rejects RFC3339 timestamps with impossible calendar days", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      jsonResponse({ ...baseConversation, updated_at: "2026-02-30T12:00:00.000Z" }),
    );
    const service = createApiConversationService(fetcher);
    await expect(service.getConversation("conversation-api")).rejects.toMatchObject({
      code: "STREAM_RESPONSE_INVALID",
    });
  });

  it("rejects malformed failed-event error codes", async () => {
    const failed: ChatStreamEvent = {
      type: "failed",
      request_id: "request-api",
      conversation_id: "conversation-api",
      message_id: "message-api",
      sequence: 1,
      error: {
        code: "bad-code",
        message: "bad",
        request_id: "request-api",
        retryable: false,
      },
    };
    const fetcher = vi.fn().mockResolvedValue(streamResponse([events[0]!, failed]));
    const service = createApiConversationService(fetcher);
    const stream = await service.resumeMessage({ conversationId: "conversation-api", requestId: "request-api", cursor: null });
    await expect((async () => {
      for await (const event of stream.events) void event;
    })()).rejects.toMatchObject({ code: "STREAM_RESPONSE_INVALID" });
  });

  it("rejects a stream that reaches EOF without one terminal event", async () => {
    const fetcher = vi.fn().mockResolvedValue(streamResponse([events[0]!, events[1]! ]));
    const service = createApiConversationService(fetcher);
    const stream = await service.resumeMessage({ conversationId: "conversation-api", requestId: "request-api", cursor: null });
    await expect((async () => {
      for await (const event of stream.events) void event;
    })()).rejects.toMatchObject({ code: "STREAM_RESPONSE_INVALID" });
  });

  it("rejects a terminal payload truncated before its blank SSE frame boundary", async () => {
    const completeFrames = events.slice(0, 2).map(
      (event) => `id: ${event.sequence}\ndata: ${JSON.stringify(event)}\n\n`,
    ).join("");
    const truncatedTerminal = `id: 2\ndata: ${JSON.stringify(events[2]!)}`;
    const fetcher = vi.fn().mockResolvedValue(
      rawStreamResponse(`${completeFrames}${truncatedTerminal}`),
    );
    const service = createApiConversationService(fetcher);
    const stream = await service.resumeMessage({
      conversationId: "conversation-api",
      requestId: "request-api",
      cursor: null,
    });

    await expect((async () => {
      for await (const event of stream.events) void event;
    })()).rejects.toMatchObject({ code: "STREAM_RESPONSE_INVALID" });
  });

  it("rejects sequence gaps and accepts CRLF-framed complete streams", async () => {
    const gap = { ...events[1]!, sequence: 2 } as ChatStreamEvent;
    const gapFetcher = vi.fn().mockResolvedValue(streamResponse([events[0]!, gap, events[2]! ]));
    const gapService = createApiConversationService(gapFetcher);
    const gapStream = await gapService.resumeMessage({ conversationId: "conversation-api", requestId: "request-api", cursor: null });
    await expect((async () => {
      for await (const event of gapStream.events) void event;
    })()).rejects.toMatchObject({ code: "STREAM_RESPONSE_INVALID" });

    const crlfFetcher = vi.fn().mockResolvedValue(streamResponse(events, 200, "\r\n"));
    const crlfService = createApiConversationService(crlfFetcher);
    const crlfStream = await crlfService.resumeMessage({ conversationId: "conversation-api", requestId: "request-api", cursor: null });
    const received: ChatStreamEvent[] = [];
    for await (const event of crlfStream.events) received.push(event);
    expect(received).toEqual(events);
  });

  it.each([
    ["non-integer id", "id: nope\ndata: ${JSON.stringify(events[0])}\n\n"],
    ["id mismatch", `id: 9\ndata: ${JSON.stringify(events[0])}\n\n`],
    ["duplicate id", `id: 0\ndata: ${JSON.stringify(events[0])}\n\nid: 0\ndata: ${JSON.stringify(events[0])}\n\n`],
  ])("rejects %s", async (_name, payload) => {
    const fetcher = vi.fn().mockResolvedValue(rawStreamResponse(payload));
    const service = createApiConversationService(fetcher);
    const stream = await service.sendMessage({
      conversationId: "conversation-api",
      content: "你好",
      clientRequestId: "invalid-sse",
    });
    await expect((async () => {
      for await (const event of stream.events) void event;
    })()).rejects.toMatchObject({ code: "STREAM_RESPONSE_INVALID" });
  });

  it("retains a trailing CR split from LF and joins standard multiline data", async () => {
    const startedJson = JSON.stringify(events[0]!);
    const splitPoint = startedJson.indexOf(",", 20);
    const multilinePayload = [
      `id: 0\r\n`,
      `data: ${startedJson.slice(0, splitPoint + 1)}\r\n`,
      `data: ${startedJson.slice(splitPoint + 1)}\r\n\r\n`,
      ...events.slice(1).map((event) => `id: ${event.sequence}\r\ndata: ${JSON.stringify(event)}\r\n\r\n`),
    ].join("");
    const crlfIndex = multilinePayload.indexOf("\r\n");
    const fetcher = vi.fn().mockResolvedValue(
      rawStreamResponse(multilinePayload, 200, crlfIndex + 1),
    );
    const service = createApiConversationService(fetcher);
    const stream = await service.resumeMessage({ conversationId: "conversation-api", requestId: "request-api", cursor: null });
    const received: ChatStreamEvent[] = [];
    for await (const event of stream.events) received.push(event);
    expect(received).toEqual(events);
  });

  it("maps endpoint failures to typed service errors", async () => {
    const fetcher = vi.fn().mockResolvedValue(jsonResponse({}, 503));
    const service = createApiConversationService(fetcher);
    await expect(service.getConversation("conversation-api")).rejects.toBeInstanceOf(ApiConversationServiceError);
    await expect(service.getConversation("conversation-api")).rejects.toMatchObject({ status: 503, retryable: true });
  });
});
