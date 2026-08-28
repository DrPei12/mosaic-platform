import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ChatStreamEvent, Conversation } from "@mosaic/contracts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockPush = vi.hoisted(() => vi.fn());
const mockListConversations = vi.hoisted(() => vi.fn());
const mockGetConversation = vi.hoisted(() => vi.fn());
const mockGetDraft = vi.hoisted(() => vi.fn());
const mockSaveDraft = vi.hoisted(() => vi.fn());
const mockCreateConversation = vi.hoisted(() => vi.fn());
const mockSendMessage = vi.hoisted(() => vi.fn());
const mockResumeMessage = vi.hoisted(() => vi.fn());
const mockRegenerate = vi.hoisted(() => vi.fn());
const mockStopMessage = vi.hoisted(() => vi.fn());
const mockGetModel = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    conversation: {
      listConversations: mockListConversations,
      getConversation: mockGetConversation,
      getDraft: mockGetDraft,
      saveDraft: mockSaveDraft,
      createConversation: mockCreateConversation,
      sendMessage: mockSendMessage,
      resumeMessage: mockResumeMessage,
      regenerate: mockRegenerate,
      stopMessage: mockStopMessage,
    },
    modelCatalog: { get: mockGetModel },
  }),
}));

import { ChatWorkspace } from "./chat-workspace";
import { ConversationServiceError as ConversationServiceErrorClass } from "@/services/interfaces";

const NOW = "2026-08-22T12:00:00.000Z";

const model = {
  item: {
    model: {
      product_model_id: "qwen-3-5",
      display_name: "Qwen 3.5",
      category: "text" as const,
      task_type: "chat" as const,
      description: "适合多轮对话。",
      capabilities: ["多轮对话"],
      availability: "demo" as const,
      pricing_summary: "演示额度",
    },
    collections: ["featured" as const],
  },
  presentation: {
    productModelId: "qwen-3-5",
    cardStyle: "hero" as const,
    media: { kind: "none" as const },
    actionLabel: "开始对话",
  },
  favorite: false,
};

const firstConversation: Conversation = {
  conversation_id: "conversation-qwen-3-5-001",
  product_model_id: "qwen-3-5",
  title: "产品规划讨论",
  messages: [
    {
      message_id: "message-user-001",
      role: "user",
      content: "帮我把新产品的验证路径拆成几步。",
      status: "complete",
      created_at: NOW,
    },
    {
      message_id: "message-assistant-001",
      role: "assistant",
      content: "可以从目标用户、核心任务和最小验证开始。",
      status: "complete",
      created_at: NOW,
    },
  ],
  updated_at: NOW,
  active_request_id: null,
  active_request_cursor: null,
};

const secondConversation: Conversation = {
  ...firstConversation,
  conversation_id: "conversation-qwen-3-5-002",
  title: "研究摘要整理",
  messages: [],
};

const summaries = [
  {
    conversation_id: firstConversation.conversation_id,
    product_model_id: "qwen-3-5",
    title: firstConversation.title,
    preview: "可以从目标用户、核心任务和最小验证开始。",
    updated_at: NOW,
  },
  {
    conversation_id: secondConversation.conversation_id,
    product_model_id: "qwen-3-5",
    title: secondConversation.title,
    preview: "还没有消息",
    updated_at: NOW,
  },
];

function cloneConversation(conversation: Conversation): Conversation {
  return JSON.parse(JSON.stringify(conversation)) as Conversation;
}

function streamOf(events: readonly ChatStreamEvent[]) {
  return {
    requestId: events[0]?.request_id ?? "request-send",
    messageId: events[0]?.message_id ?? "message-assistant-send",
    events: (async function* () {
      for (const event of events) yield event;
    })(),
  };
}

function pendingStream(eventsBeforeGate: readonly ChatStreamEvent[], eventAfterGate: ChatStreamEvent) {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return {
    stream: {
      requestId: eventsBeforeGate[0]?.request_id ?? "request-send",
      messageId: eventsBeforeGate[0]?.message_id ?? "message-assistant-send",
      events: (async function* () {
        for (const event of eventsBeforeGate) yield event;
        await gate;
        yield eventAfterGate;
      })(),
    },
    release,
  };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function setup() {
  mockPush.mockReset();
  mockListConversations.mockReset();
  mockGetConversation.mockReset();
  mockGetDraft.mockReset();
  mockSaveDraft.mockReset();
  mockCreateConversation.mockReset();
  mockSendMessage.mockReset();
  mockResumeMessage.mockReset();
  mockRegenerate.mockReset();
  mockStopMessage.mockReset();
  mockGetModel.mockReset();

  mockListConversations.mockResolvedValue(summaries);
  mockGetConversation.mockImplementation((id: string) => Promise.resolve(
    cloneConversation(id === secondConversation.conversation_id ? secondConversation : firstConversation),
  ));
  mockGetDraft.mockResolvedValue("");
  mockSaveDraft.mockResolvedValue(undefined);
  mockCreateConversation.mockResolvedValue({ ...secondConversation, conversation_id: "conversation-created" });
  mockGetModel.mockResolvedValue(model);
  mockResumeMessage.mockRejectedValue(new Error("not active"));
}

describe("ChatWorkspace", () => {
  beforeEach(() => {
    setup();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
  });

  afterEach(() => cleanup());

  it("loads seeded summaries, active conversation and public model", async () => {
    const user = userEvent.setup();
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);

    expect(await screen.findByRole("heading", { name: "文本模型" })).toBeInTheDocument();
    expect(screen.getByText("帮我把新产品的验证路径拆成几步。")).toBeInTheDocument();
    expect(screen.queryByText("内部演示")).not.toBeInTheDocument();
    expect(screen.queryByText("API 实时")).not.toBeInTheDocument();
    expect(screen.queryByText("体验账户")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chat-notice")).not.toBeInTheDocument();
    expect(screen.queryByText("模型调试")).not.toBeInTheDocument();
    expect(screen.getByTestId("chat-model-toolbar")).toHaveTextContent("Qwen 3.5");
    expect(screen.getByRole("textbox", { name: "输入消息" })).toHaveClass("min-h-11");
    expect(screen.getByTestId("chat-workspace")).toHaveClass("h-full", "min-h-0", "w-full");
    const userRow = screen.getByTestId("message-message-user-001");
    expect(userRow).toHaveClass("flex", "justify-end");
    expect(userRow.querySelector("div")).toHaveClass("bg-[color-mix(in_srgb,var(--mosaic-color-accent)_7%,var(--mosaic-color-surface))]");
    expect(userRow.querySelector("span[aria-hidden=\"true\"]")).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "打开会话列表" });
    expect(trigger).toHaveClass("min-h-11", "min-w-11");
    expect(trigger).not.toHaveClass("border");
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    expect(dialog).toBeVisible();
    expect(within(dialog).getByText("产品规划讨论")).toBeInTheDocument();
    const activeConversation = within(dialog).getByTestId(`conversation-${firstConversation.conversation_id}`);
    expect(activeConversation).toHaveClass("bg-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,var(--mosaic-color-surface))]");
    expect(activeConversation.querySelector(".text-\\[var\\(--mosaic-color-accent\\)\\]" )).toBeInTheDocument();
  });

  it("uses one header history trigger and one accessible dialog at every viewport", async () => {
    render(
      <main id="test-main">
        <ChatWorkspace conversationId={firstConversation.conversation_id} />
      </main>,
    );
    await screen.findByRole("heading", { name: "文本模型" });

    const trigger = screen.getByRole("button", { name: "打开会话列表" });
    expect(trigger).not.toHaveClass("md:hidden", "lg:hidden");
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(document.querySelectorAll("main")).toHaveLength(1);

    const user = userEvent.setup();
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    expect(dialog).toHaveClass("fixed", "w-[min(100vw,420px)]");
    expect(within(dialog).getByText("产品规划讨论")).toBeInTheDocument();
  });

  it("filters conversations by title or preview with an accessible toggle", async () => {
    const user = userEvent.setup();
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });

    await user.click(screen.getByRole("button", { name: "打开会话列表" }));
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    const filterButton = within(dialog).getByRole("button", { name: "筛选会话" });
    expect(filterButton).toHaveAttribute("aria-expanded", "false");
    await user.click(filterButton);
    expect(filterButton).toHaveAttribute("aria-expanded", "true");
    const filterInput = within(dialog).getByRole("searchbox", { name: "筛选会话" });
    await user.type(filterInput, "研究");
    expect(screen.getByText("研究摘要整理")).toBeInTheDocument();
    expect(screen.queryByText("产品规划讨论")).not.toBeInTheDocument();
  });

  it("keeps the single dialog filter control uniquely associated", async () => {
    const user = userEvent.setup();
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });

    await user.click(screen.getByRole("button", { name: "打开会话列表" }));
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    const filterButton = within(dialog).getByRole("button", { name: "筛选会话" });
    await user.click(filterButton);
    const filterInput = within(dialog).getByRole("searchbox", { name: "筛选会话" });
    expect(filterInput.id).toBe("conversation-filter-input");
    expect(filterButton).toHaveAttribute("aria-controls", filterInput.id);
  });

  it("switches routes without reusing the previous conversation", async () => {
    const user = userEvent.setup();
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });

    await user.click(screen.getByRole("button", { name: "打开会话列表" }));
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    await user.click(within(dialog).getByTestId(`conversation-${secondConversation.conversation_id}`));
    expect(mockPush).toHaveBeenCalledWith(`/chat/${secondConversation.conversation_id}`);
    expect(screen.queryByText("帮我把新产品的验证路径拆成几步。")).not.toBeInTheDocument();
  });

  it("creates a new session with the current text model", async () => {
    const user = userEvent.setup();
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });

    await user.click(screen.getByRole("button", { name: "打开会话列表" }));
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    await user.click(within(dialog).getByRole("button", { name: "新建会话" }));
    expect(mockCreateConversation).toHaveBeenCalledWith(
      { productModelId: "qwen-3-5", clientRequestId: expect.any(String) },
      expect.any(AbortSignal),
    );
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/chat/conversation-created"));
  });

  it("aborts and ignores a stale new-conversation completion after a route switch", async () => {
    const user = userEvent.setup();
    const createGate = deferred<Conversation>();
    let createSignal: AbortSignal | undefined;
    mockCreateConversation.mockImplementation((_input: unknown, signal: AbortSignal) => {
      createSignal = signal;
      return createGate.promise;
    });
    const view = render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });
    await user.click(screen.getByRole("button", { name: "打开会话列表" }));
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    await user.click(within(dialog).getByRole("button", { name: "新建会话" }));
    view.rerender(<ChatWorkspace conversationId={secondConversation.conversation_id} />);
    await screen.findByText("从一个好问题开始");
    expect(createSignal?.aborted).toBe(true);
    createGate.resolve({ ...secondConversation, conversation_id: "stale-created" });
    await Promise.resolve();
    expect(mockPush).not.toHaveBeenCalledWith("/chat/stale-created");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows unknown-conversation error honestly", async () => {
    mockGetConversation.mockRejectedValueOnce(Object.assign(new Error("missing"), {
      code: "CONVERSATION_NOT_FOUND",
    }));
    render(<ChatWorkspace conversationId="unknown-conversation" />);
    expect(await screen.findByTestId("chat-error")).toHaveTextContent("无法打开这个会话");
    expect(within(screen.getByTestId("chat-error")).getByRole("button", { name: "返回模型广场" })).toBeInTheDocument();
  });

  it("distinguishes a service error from an unknown conversation", async () => {
    const internalMessage = "PROVIDER_DEPLOYMENT_QUEUE_INTERNAL";
    mockGetConversation.mockRejectedValueOnce(new ConversationServiceErrorClass({
      code: "CONVERSATION_UNAVAILABLE",
      status: 503,
      retryable: true,
      message: internalMessage,
    }));
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const error = await screen.findByTestId("chat-error");
    expect(error).toHaveTextContent("会话服务暂时不可用");
    expect(error).not.toHaveTextContent(internalMessage);
  });

  it("resumes an active request after loading the conversation", async () => {
    const activeRequestId = "request-resume";
    const messageId = "message-resume";
    const activeConversation: Conversation = {
      ...firstConversation,
      active_request_id: activeRequestId,
      active_request_cursor: -1,
      messages: [
        ...firstConversation.messages,
        { message_id: messageId, role: "assistant", content: "部分", status: "streaming", created_at: NOW, request_id: activeRequestId },
      ],
    };
    const completedConversation: Conversation = {
      ...activeConversation,
      active_request_id: null,
      active_request_cursor: null,
      messages: activeConversation.messages.map((message) => message.message_id === messageId
        ? { ...message, content: "部分完成", status: "complete" as const }
        : message),
    };
    mockGetConversation.mockImplementation((id: string) => Promise.resolve(
      id === firstConversation.conversation_id && mockResumeMessage.mock.calls.length > 0
        ? cloneConversation(completedConversation)
        : cloneConversation(activeConversation),
    ));
    mockResumeMessage.mockResolvedValue(streamOf([
      { type: "started", request_id: activeRequestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      { type: "completed", request_id: activeRequestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, content: "部分完成" },
    ]));

    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    expect(await screen.findByText("部分完成")).toBeInTheDocument();
    expect(mockResumeMessage).toHaveBeenCalledWith(
      {
        conversationId: firstConversation.conversation_id,
        requestId: activeRequestId,
        cursor: -1,
      },
      expect.any(AbortSignal),
    );
  });

  it("aborts an accepted stream when hydrate fails and performs one recoverable resume", async () => {
    const user = userEvent.setup();
    const requestId = "request-hydrate-recovery";
    const messageId = "message-hydrate-recovery";
    const activeResponse: Conversation = {
      ...firstConversation,
      active_request_id: requestId,
      active_request_cursor: -1,
      messages: [
        ...firstConversation.messages,
        { message_id: "message-user-recovery", role: "user", content: "恢复它", status: "complete", created_at: NOW, request_id: requestId },
        { message_id: messageId, role: "assistant", content: "部分", status: "streaming", created_at: NOW, request_id: requestId },
      ],
    };
    const completedResponse: Conversation = {
      ...activeResponse,
      active_request_id: null,
      active_request_cursor: null,
      messages: activeResponse.messages.map((message) => message.message_id === messageId
        ? { ...message, content: "恢复完成", status: "complete" as const }
        : message),
    };
    const recovery = pendingStream([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
    ], { type: "completed", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, content: "恢复完成" });
    let sendSignal: AbortSignal | undefined;
    let hydrateFailed = false;
    let resumeHydrates = 0;
    mockSendMessage.mockImplementation((_input: unknown, signal: AbortSignal) => {
      sendSignal = signal;
      return Promise.resolve(streamOf([
        { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      ]));
    });
    mockResumeMessage.mockResolvedValue(recovery.stream);
    mockGetConversation.mockImplementation((id: string) => {
      if (id !== firstConversation.conversation_id || !mockSendMessage.mock.calls.length) {
        return Promise.resolve(cloneConversation(firstConversation));
      }
      if (!hydrateFailed) {
        hydrateFailed = true;
        return Promise.reject(new Error("刷新失败"));
      }
      if (mockResumeMessage.mock.calls.length > 0) {
        resumeHydrates += 1;
        return Promise.resolve(cloneConversation(resumeHydrates === 1 ? activeResponse : completedResponse));
      }
      return Promise.resolve(cloneConversation(activeResponse));
    });

    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "恢复它");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(mockResumeMessage).toHaveBeenCalledTimes(1));
    expect(sendSignal?.aborted).toBe(true);
    expect(screen.getByTestId("chat-workspace")).toHaveAttribute("data-active-request-id", requestId);
    expect(screen.getByTestId("chat-workspace")).toHaveAttribute("data-stream-action", "resume");
    recovery.release();
    expect(await screen.findByText("恢复完成", { selector: "div" })).toBeInTheDocument();
    expect(mockResumeMessage).toHaveBeenCalledTimes(1);
  });

  it("persists a draft and keeps it after a refresh load", async () => {
    const user = userEvent.setup();
    mockGetDraft.mockResolvedValue("刷新后仍保留");
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    expect(input).toHaveValue("刷新后仍保留");

    await user.clear(input);
    await user.type(input, "新的草稿");
    expect(mockSaveDraft).toHaveBeenLastCalledWith(
      { conversationId: firstConversation.conversation_id, content: "新的草稿" },
      expect.any(AbortSignal),
    );
  });

  it("reports draft persistence truthfully and separates saving status from errors", async () => {
    const view = render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });
    expect(screen.getByTestId("draft-status")).toHaveTextContent("草稿自动保存");
    expect(screen.getByTestId("composer-panel")).toHaveClass(
      "min-h-[var(--mosaic-layout-composer-panel)]",
      "max-h-[calc(var(--mosaic-layout-composer-panel)+var(--mosaic-spacing-8))]",
    );
    expect(screen.getByRole("textbox", { name: "输入消息" })).toHaveClass("text-base", "leading-7");
    expect(screen.getByRole("button", { name: "发送消息" })).toHaveClass("self-end");

    const pendingSave = deferred<void>();
    mockSaveDraft.mockImplementationOnce(() => pendingSave.promise);
    const input = screen.getByRole("textbox", { name: "输入消息" });
    fireEvent.change(input, { target: { value: "正在保存" } });
    expect(screen.getByTestId("composer-status")).toHaveAttribute("role", "status");
    expect(screen.getByTestId("composer-status")).toHaveTextContent("正在保存草稿");
    pendingSave.resolve();
    await waitFor(() => expect(screen.queryByText("正在保存草稿")).not.toBeInTheDocument());
    view.unmount();

    mockGetDraft.mockRejectedValueOnce(new ConversationServiceErrorClass({
      code: "CONVERSATION_UNAVAILABLE",
      status: 503,
      retryable: true,
    }));
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });
    expect(await screen.findByTestId("draft-status")).toHaveTextContent("草稿仅保留在当前页面");
  });

  it("does not submit Enter while an IME composition is active", async () => {
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    fireEvent.change(input, { target: { value: "拼音中" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter", isComposing: true });
    expect(mockSendMessage).not.toHaveBeenCalled();
    expect(input).toHaveValue("拼音中");
  });

  it("does not fabricate a request while offline and keeps the draft", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "离线草稿");
    await user.keyboard("{Enter}");
    expect(mockSendMessage).not.toHaveBeenCalled();
    expect(input).toHaveValue("离线草稿");
    expect(screen.getByRole("alert")).toHaveTextContent("草稿已保留");
  });

  it("fails closed and preserves the draft when chat submission is disabled", async () => {
    const user = userEvent.setup();
    mockSendMessage.mockRejectedValue(new ConversationServiceErrorClass({
      code: "CHAT_SUBMISSION_DISABLED",
      status: 503,
      retryable: true,
      message: "聊天执行栈尚未就绪",
    }));

    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "保留这条草稿");
    await user.keyboard("{Enter}");

    expect(await screen.findByTestId("chat-submission-disabled")).toHaveTextContent(
      "聊天服务暂不可用",
    );
    expect(input).toHaveValue("保留这条草稿");
    expect(input).toBeDisabled();
  });

  it("prevents duplicate submit and folds an ordered stream", async () => {
    const user = userEvent.setup();
    const requestId = "request-send";
    const messageId = "message-assistant-send";
    const response: Conversation = {
      ...firstConversation,
      active_request_id: requestId,
      active_request_cursor: -1,
      messages: [
        ...firstConversation.messages,
        { message_id: "message-user-send", role: "user", content: "新问题", status: "complete", created_at: NOW, request_id: requestId },
        { message_id: messageId, role: "assistant", content: "", status: "streaming", created_at: NOW, request_id: requestId },
      ],
    };
    const completedResponse: Conversation = {
      ...response,
      active_request_id: null,
      active_request_cursor: null,
      messages: response.messages.map((message) => message.message_id === messageId
        ? { ...message, content: "已收到。", status: "complete" as const }
        : message),
    };
    mockSendMessage.mockResolvedValue(streamOf([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      { type: "delta", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, delta: "已收到。" },
      { type: "completed", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 2, content: "已收到。" },
    ]));
    mockGetConversation.mockImplementation((id: string) => Promise.resolve(
      id === firstConversation.conversation_id && mockSendMessage.mock.calls.length > 0
        ? cloneConversation(completedResponse)
        : cloneConversation(firstConversation),
    ));
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "新问题");
    await user.keyboard("{Enter}");
    await user.keyboard("{Enter}");
    expect(mockSendMessage).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("已收到。", { selector: "div" })).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("keeps a newer draft typed while an accepted send is hydrating", async () => {
    const user = userEvent.setup();
    const requestId = "request-deferred-draft";
    const messageId = "message-deferred-draft";
    const sendGate = deferred<ReturnType<typeof streamOf>>();
    const acceptedResponse: Conversation = {
      ...firstConversation,
      active_request_id: requestId,
      active_request_cursor: -1,
      messages: [
        ...firstConversation.messages,
        { message_id: "message-user-deferred", role: "user", content: "已提交", status: "complete", created_at: NOW, request_id: requestId },
        { message_id: messageId, role: "assistant", content: "", status: "streaming", created_at: NOW, request_id: requestId },
      ],
    };
    const completedResponse: Conversation = {
      ...acceptedResponse,
      active_request_id: null,
      active_request_cursor: null,
      messages: acceptedResponse.messages.map((message) => message.message_id === messageId
        ? { ...message, content: "完成", status: "complete" as const }
        : message),
    };
    mockSendMessage.mockReturnValue(sendGate.promise);
    let postSendRefreshes = 0;
    mockGetConversation.mockImplementation((id: string) => {
      if (id !== firstConversation.conversation_id || mockSendMessage.mock.calls.length === 0) {
        return Promise.resolve(cloneConversation(firstConversation));
      }
      postSendRefreshes += 1;
      return Promise.resolve(cloneConversation(postSendRefreshes === 1 ? acceptedResponse : completedResponse));
    });

    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "已提交");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(mockSendMessage).toHaveBeenCalledTimes(1));
    const emptyDraftCallsBeforeNext = mockSaveDraft.mock.calls.filter(
      ([payload]) => (payload as { content: string }).content === "",
    ).length;
    await user.clear(input);
    await user.type(input, "下一条草稿");
    sendGate.resolve(streamOf([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      { type: "completed", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, content: "完成" },
    ]));
    expect(await screen.findByText("完成", { selector: "div" })).toBeInTheDocument();
    expect(input).toHaveValue("下一条草稿");
    expect(mockSaveDraft.mock.calls.filter(
      ([payload]) => (payload as { content: string }).content === "",
    )).toHaveLength(emptyDraftCallsBeforeNext + 1);
    expect(mockSaveDraft).toHaveBeenLastCalledWith(
      { conversationId: firstConversation.conversation_id, content: "下一条草稿" },
      expect.any(AbortSignal),
    );
  });

  it("keeps a draft retyped to the same value while an accepted send is hydrating", async () => {
    const user = userEvent.setup();
    const requestId = "request-retyped-draft";
    const messageId = "message-retyped-draft";
    const sendGate = deferred<ReturnType<typeof streamOf>>();
    const acceptedResponse: Conversation = {
      ...firstConversation,
      active_request_id: requestId,
      active_request_cursor: -1,
      messages: [
        ...firstConversation.messages,
        { message_id: "message-user-retyped", role: "user", content: "相同草稿", status: "complete", created_at: NOW, request_id: requestId },
        { message_id: messageId, role: "assistant", content: "", status: "streaming", created_at: NOW, request_id: requestId },
      ],
    };
    const completedResponse: Conversation = {
      ...acceptedResponse,
      active_request_id: null,
      active_request_cursor: null,
      messages: acceptedResponse.messages.map((message) => message.message_id === messageId
        ? { ...message, content: "已完成", status: "complete" as const }
        : message),
    };
    mockSendMessage.mockReturnValue(sendGate.promise);
    let postSendRefreshes = 0;
    mockGetConversation.mockImplementation((id: string) => {
      if (id !== firstConversation.conversation_id || mockSendMessage.mock.calls.length === 0) {
        return Promise.resolve(cloneConversation(firstConversation));
      }
      postSendRefreshes += 1;
      return Promise.resolve(cloneConversation(postSendRefreshes === 1 ? acceptedResponse : completedResponse));
    });

    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "相同草稿");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(mockSendMessage).toHaveBeenCalledTimes(1));
    await user.clear(input);
    await user.type(input, "相同草稿");
    sendGate.resolve(streamOf([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      { type: "completed", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, content: "已完成" },
    ]));

    expect(await screen.findByText("已完成", { selector: "div" })).toBeInTheDocument();
    expect(input).toHaveValue("相同草稿");
  });

  it("clears the full whitespace-padded draft after an accepted send", async () => {
    const user = userEvent.setup();
    const requestId = "request-whitespace-draft";
    const messageId = "message-whitespace-draft";
    const completedResponse: Conversation = {
      ...firstConversation,
      active_request_id: null,
      active_request_cursor: null,
      messages: [
        ...firstConversation.messages,
        { message_id: "message-user-whitespace", role: "user", content: "带空格", status: "complete", created_at: NOW, request_id: requestId },
        { message_id: messageId, role: "assistant", content: "已处理", status: "complete", created_at: NOW, request_id: requestId },
      ],
    };
    mockSendMessage.mockResolvedValue(streamOf([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      { type: "completed", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, content: "已处理" },
    ]));
    mockGetConversation.mockImplementation((id: string) => Promise.resolve(
      id === firstConversation.conversation_id && mockSendMessage.mock.calls.length > 0
        ? cloneConversation(completedResponse)
        : cloneConversation(firstConversation),
    ));

    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "  带空格  ");
    await user.keyboard("{Enter}");

    expect(mockSendMessage).toHaveBeenCalledWith(
      expect.objectContaining({ content: "带空格" }),
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("已处理", { selector: "div" })).toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(mockSaveDraft).toHaveBeenCalledWith(
      { conversationId: firstConversation.conversation_id, content: "" },
      expect.any(AbortSignal),
    );
  });

  it("stops after a partial delta and keeps the partial response", async () => {
    const user = userEvent.setup();
    const requestId = "request-stop";
    const messageId = "message-stop";
    const activeConversation: Conversation = {
      ...firstConversation,
      active_request_id: requestId,
      active_request_cursor: -1,
      messages: [
        ...firstConversation.messages,
        { message_id: "message-user-stop", role: "user", content: "停止它", status: "complete", created_at: NOW, request_id: requestId },
        { message_id: messageId, role: "assistant", content: "", status: "streaming", created_at: NOW, request_id: requestId },
      ],
    };
    const stoppedConversation: Conversation = {
      ...activeConversation,
      active_request_id: null,
      active_request_cursor: null,
      messages: activeConversation.messages.map((message) => message.message_id === messageId
        ? { ...message, content: "先输出一部分", status: "stopped" as const }
        : message),
    };
    const pending = pendingStream([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      { type: "delta", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, delta: "先输出一部分" },
    ], { type: "stopped", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 2 });
    mockSendMessage.mockResolvedValue(pending.stream);
    mockStopMessage.mockImplementation(async () => {
      pending.release();
    });
    let postSendConversationFetches = 0;
    mockGetConversation.mockImplementation((id: string) => Promise.resolve(
      id === firstConversation.conversation_id && mockSendMessage.mock.calls.length > 0
        ? (++postSendConversationFetches === 1
          ? cloneConversation(activeConversation)
          : cloneConversation(stoppedConversation))
        : cloneConversation(firstConversation),
    ));
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "停止它");
    await user.keyboard("{Enter}");
    expect(await screen.findByText("先输出一部分")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "停止生成" }));
    expect(mockStopMessage).toHaveBeenCalledWith(
      { conversationId: firstConversation.conversation_id, requestId },
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("已停止生成，以上为已保留内容。")).toBeInTheDocument();
  });

  it("regenerates the latest assistant without adding another user message", async () => {
    const user = userEvent.setup();
    const requestId = "request-regenerate";
    const messageId = "message-regenerate";
    const regenerated: Conversation = {
      ...firstConversation,
      messages: firstConversation.messages.map((message) => message.message_id === "message-assistant-001"
        ? { ...message, content: "重新生成的回复" }
        : message),
    };
    mockRegenerate.mockResolvedValue(streamOf([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
      { type: "completed", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, content: "重新生成的回复" },
    ]));
    mockGetConversation.mockImplementation((id: string) => Promise.resolve(
      id === firstConversation.conversation_id && mockRegenerate.mock.calls.length > 0
        ? cloneConversation(regenerated)
        : cloneConversation(firstConversation),
    ));
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });
    await user.click(screen.getByRole("button", { name: "重新生成" }));
    await waitFor(() => expect(mockRegenerate).toHaveBeenCalledWith(
      { conversationId: firstConversation.conversation_id, messageId: "message-assistant-001", clientRequestId: expect.any(String) },
      expect.any(AbortSignal),
    ));
    expect(screen.getAllByTestId(/^message-message-user/)).toHaveLength(1);
  });

  it("ignores a stale stream after the workspace switches conversations", async () => {
    const user = userEvent.setup();
    const requestId = "request-stale";
    const messageId = "message-stale";
    const pending = pendingStream([
      { type: "started", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 0 },
    ], { type: "delta", request_id: requestId, conversation_id: firstConversation.conversation_id, message_id: messageId, sequence: 1, delta: "不应泄漏" });
    mockSendMessage.mockResolvedValue(pending.stream);
    const view = render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    await user.type(input, "新问题");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(mockSendMessage).toHaveBeenCalled());
    view.rerender(<ChatWorkspace conversationId={secondConversation.conversation_id} />);
    await screen.findByText("从一个好问题开始");
    pending.release();
    await Promise.resolve();
    expect(screen.queryByText("不应泄漏")).not.toBeInTheDocument();
  });

  it("ignores a deferred draft rejection from the previous conversation", async () => {
    const draftGate = deferred<void>();
    mockSaveDraft.mockImplementationOnce(() => draftGate.promise);
    const view = render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const input = await screen.findByRole("textbox", { name: "输入消息" });
    fireEvent.change(input, { target: { value: "旧会话草稿" } });
    view.rerender(<ChatWorkspace conversationId={secondConversation.conversation_id} />);
    await screen.findByText("从一个好问题开始");
    draftGate.reject(new Error("旧会话保存失败"));
    await Promise.resolve();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("旧会话保存失败")).not.toBeInTheDocument();
    expect(screen.queryByText("正在保存草稿")).not.toBeInTheDocument();
  });

  it("ignores a deferred getDraft rejection from the previous conversation", async () => {
    const draftGate = deferred<string>();
    mockGetDraft.mockImplementation((id: string) => id === firstConversation.conversation_id
      ? draftGate.promise
      : Promise.resolve(""));
    const view = render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await waitFor(() => expect(mockGetDraft).toHaveBeenCalledWith(
      firstConversation.conversation_id,
      expect.any(AbortSignal),
    ));

    view.rerender(<ChatWorkspace conversationId={secondConversation.conversation_id} />);
    await screen.findByText("从一个好问题开始");
    draftGate.reject(new Error("旧会话草稿读取失败"));
    await Promise.resolve();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("旧会话草稿读取失败")).not.toBeInTheDocument();
  });

  it("opens the conversation dialog from the header, supports Escape, and restores focus", async () => {
    const user = userEvent.setup();
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const trigger = await screen.findByRole("button", { name: "打开会话列表" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    expect(within(dialog).getByText("研究摘要整理")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("opens the conversation dialog, toggles its filter, closes, and restores focus", async () => {
    const user = userEvent.setup();
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    const trigger = await screen.findByRole("button", { name: "打开会话列表" });

    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "会话列表" });
    const header = within(dialog).getByTestId("conversation-list-header");
    const filterButton = within(header).getByRole("button", { name: "筛选会话" });
    const closeButton = within(header).getByRole("button", { name: "关闭会话列表" });

    expect(header.children).toHaveLength(3);
    expect(header.children[1]).toBe(filterButton);
    expect(header.children[2]).toBe(closeButton);
    expect(closeButton).toHaveClass("min-h-11", "min-w-11", "shrink-0");
    expect(closeButton).not.toHaveClass("absolute", "right-2", "top-2");

    await user.click(filterButton);
    const mobileInput = within(dialog).getByRole("searchbox", { name: "筛选会话" });
    expect(mobileInput).toHaveAttribute("id", "conversation-filter-input");

    await user.type(mobileInput, "研究");
    expect(mobileInput).toHaveValue("研究");
    expect(within(dialog).getByText("研究摘要整理")).toBeInTheDocument();
    expect(within(dialog).queryByText("产品规划讨论")).not.toBeInTheDocument();

    await user.click(closeButton);
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "会话列表" })).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
  });

  it("shows accessible copy confirmation", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });
    await user.click(screen.getByRole("button", { name: "复制" }));
    expect(writeText).toHaveBeenCalledWith("可以从目标用户、核心任务和最小验证开始。");
    expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
    expect(screen.getByTestId("copy-confirmation")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByTestId("copy-confirmation")).toHaveTextContent("已复制");
  });

  it("resets copy confirmation and ignores a deferred old-route clipboard success", async () => {
    const user = userEvent.setup();
    const copyGate = deferred<void>();
    const writeText = vi.fn().mockReturnValue(copyGate.promise);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const view = render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });
    await user.click(screen.getByRole("button", { name: "复制" }));
    expect(writeText).toHaveBeenCalledWith("可以从目标用户、核心任务和最小验证开始。");

    view.rerender(<ChatWorkspace conversationId={secondConversation.conversation_id} />);
    await screen.findByText("从一个好问题开始");
    expect(screen.getByTestId("copy-confirmation")).toHaveTextContent("");
    copyGate.resolve();
    await Promise.resolve();

    expect(screen.queryByRole("button", { name: "已复制" })).not.toBeInTheDocument();
    expect(screen.queryByText("无法访问剪贴板，请手动选择文本复制。")).not.toBeInTheDocument();
  });

  it("ignores a deferred old-route clipboard failure", async () => {
    const user = userEvent.setup();
    const copyGate = deferred<void>();
    const writeText = vi.fn().mockReturnValue(copyGate.promise);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const view = render(<ChatWorkspace conversationId={firstConversation.conversation_id} />);
    await screen.findByRole("heading", { name: "文本模型" });
    await user.click(screen.getByRole("button", { name: "复制" }));
    view.rerender(<ChatWorkspace conversationId={secondConversation.conversation_id} />);
    await screen.findByText("从一个好问题开始");
    copyGate.reject(new Error("旧会话剪贴板失败"));
    await Promise.resolve();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("无法访问剪贴板，请手动选择文本复制。")).not.toBeInTheDocument();
  });
});
