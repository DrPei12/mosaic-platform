import { describe, expect, it } from "vitest";
import type { ChatStreamEvent, Conversation } from "@mosaic/contracts";
import {
  createConversationReducerState,
  reduceConversation,
  reduceConversationEvent,
} from "./conversation-reducer";

const NOW = "2026-08-22T12:00:00.000Z";
const IDS = {
  conversation: "conversation-test",
  request: "request-test",
  message: "message-test",
} as const;

function conversation(): Conversation {
  return {
    conversation_id: IDS.conversation,
    product_model_id: "qwen-3-5",
    title: "测试会话",
    messages: [
      {
        message_id: "message-user",
        role: "user",
        content: "你好",
        status: "complete",
        created_at: NOW,
      },
      {
        message_id: IDS.message,
        role: "assistant",
        content: "已生成的部分",
        status: "streaming",
        created_at: NOW,
        request_id: IDS.request,
      },
    ],
    updated_at: NOW,
    active_request_id: IDS.request,
    active_request_cursor: -1,
  };
}

function event(
  patch: Partial<ChatStreamEvent> & Pick<ChatStreamEvent, "type" | "sequence">,
): ChatStreamEvent {
  return {
    type: patch.type,
    request_id: IDS.request,
    conversation_id: IDS.conversation,
    message_id: IDS.message,
    sequence: patch.sequence,
    ...(patch.type === "delta" ? { delta: patch.delta ?? "下一段" } : {}),
    ...(patch.type === "completed"
      ? { content: patch.content ?? "完整答案" }
      : {}),
    ...(patch.type === "failed"
      ? {
          error:
            patch.error ?? {
              code: "FAILED",
              message: "failed",
              request_id: IDS.request,
              retryable: false,
            },
        }
      : {}),
  } as ChatStreamEvent;
}

describe("conversation reducer", () => {
  it("accepts started seq 0, appends ordered deltas, and completes once", () => {
    let state = createConversationReducerState(conversation());
    state = reduceConversation(state, event({ type: "started", sequence: 0 }));
    state = reduceConversation(state, event({ type: "delta", sequence: 1, delta: "，你好" }));
    state = reduceConversation(state, event({ type: "completed", sequence: 2, content: "完整答案" }));

    expect(state.conversation.messages.at(-1)).toMatchObject({
      content: "完整答案",
      status: "complete",
    });
    expect(state.conversation.active_request_id).toBeNull();
    expect(state.terminal).toBe(true);
  });

  it("ignores duplicate, stale, wrong-id, post-terminal and non-started-first events", () => {
    const initial = createConversationReducerState(conversation());
    const nonStarted = reduceConversation(
      initial,
      event({ type: "delta", sequence: 1, delta: "不应接受" }),
    );
    expect(nonStarted).toEqual(initial);

    let state = reduceConversation(initial, event({ type: "started", sequence: 0 }));
    state = reduceConversation(state, event({ type: "delta", sequence: 1, delta: "一" }));
    const accepted = state;
    state = reduceConversation(state, event({ type: "delta", sequence: 1, delta: "重复" }));
    state = reduceConversation(state, event({ type: "delta", sequence: 0, delta: "过期" }));
    state = reduceConversation(state, {
      ...event({ type: "delta", sequence: 2, delta: "错误请求" }),
      request_id: "other-request",
    });
    expect(state).toEqual(accepted);

    state = reduceConversation(state, event({ type: "completed", sequence: 2, content: "完成" }));
    const completed = state;
    state = reduceConversation(state, event({ type: "delta", sequence: 3, delta: "终态后" }));
    state = reduceConversation(state, event({ type: "failed", sequence: 4 }));
    expect(state).toEqual(completed);
  });

  it("provides a conversation-only helper for feature consumers", () => {
    let result = reduceConversationEvent(conversation(), event({ type: "started", sequence: 0 }));
    result = reduceConversationEvent(result, event({ type: "completed", sequence: 1, content: "完成" }));
    expect(result.active_request_id).toBeNull();
    expect(result.messages.at(-1)?.status).toBe("complete");
  });

  it("binds a legal fresh started event to the active request without a placeholder", () => {
    const fresh: Conversation = {
      ...conversation(),
      messages: [conversation().messages[0]!],
      active_request_id: IDS.request,
    };
    const result = reduceConversation(
      createConversationReducerState(fresh),
      event({ type: "started", sequence: 0 }),
    );

    expect(result.conversation.active_request_id).toBe(IDS.request);
    expect(result.conversation.messages.at(-1)).toMatchObject({
      message_id: IDS.message,
      role: "assistant",
      status: "streaming",
      request_id: IDS.request,
    });
    expect(result.lastSequence).toBe(0);
  });

  it("rejects a stale first-start request when an active request is already intended", () => {
    const fresh: Conversation = {
      ...conversation(),
      messages: [conversation().messages[0]!],
      active_request_id: IDS.request,
    };
    const state = createConversationReducerState(fresh);
    const rejected = reduceConversation(state, {
      ...event({ type: "started", sequence: 0 }),
      request_id: "stale-request",
    });

    expect(rejected).toEqual(state);
    expect(rejected.conversation.messages).toHaveLength(1);
  });

  it("ignores sequence gaps instead of applying out-of-order content", () => {
    let state = createConversationReducerState(conversation());
    state = reduceConversation(state, event({ type: "started", sequence: 0 }));
    state = reduceConversation(state, event({ type: "delta", sequence: 1, delta: "第一段" }));
    const beforeGap = state;
    state = reduceConversation(state, event({ type: "delta", sequence: 3, delta: "跳过第二段" }));

    expect(state).toEqual(beforeGap);
    expect(state.lastSequence).toBe(1);
    expect(state.conversation.messages.at(-1)?.content).toBe("已生成的部分第一段");
  });

  it("continues from a persisted cursor without replaying the previous delta", () => {
    const resumedConversation: Conversation = {
      ...conversation(),
      messages: conversation().messages.map((message) => message.message_id === IDS.message
        ? { ...message, content: "已保存", status: "streaming" as const }
        : message),
      active_request_cursor: 1,
    };
    let state = createConversationReducerState(resumedConversation);
    state = reduceConversation(state, event({ type: "delta", sequence: 2, delta: "下一段" }));
    expect(state.conversation.messages.at(-1)?.content).toBe("已保存下一段");
    expect(state.lastSequence).toBe(2);

    const duplicate = reduceConversation(state, event({ type: "delta", sequence: 2, delta: "重复" }));
    expect(duplicate).toBe(state);
    expect(duplicate.conversation.messages.at(-1)?.content).toBe("已保存下一段");

    const completed = reduceConversation(state, event({ type: "completed", sequence: 3, content: "已保存下一段" }));
    expect(completed.conversation.active_request_id).toBeNull();
    expect(completed.conversation.active_request_cursor).toBeNull();
  });
});
