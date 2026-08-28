"use client";

import {
  ArrowsOut,
  CaretDown,
  ChatCircleDots,
  ClockCounterClockwise,
  PlusSquare,
  WarningCircle,
} from "@phosphor-icons/react";
import type {
  Conversation,
  ConversationMessage,
  ConversationSummary,
} from "@mosaic/contracts";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { CatalogModel, ConversationServiceError, ConversationStream } from "@/services/interfaces";
import { ConversationServiceError as ConversationServiceErrorClass } from "@/services/interfaces";
import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import {
  createConversationReducerState,
  reduceConversation,
  type ConversationReducerState,
} from "./conversation-reducer";
import { Composer } from "./composer";
import {
  ConversationList,
  type ConversationListStatus,
} from "./conversation-list";
import { MessageList } from "./message-list";
import { ErrorState, Skeleton } from "@/shared/ui/feedback-state";
import { Button } from "@/shared/ui/button";

type AsyncStatus = "loading" | "ready" | "error";
type StreamStatus = "idle" | "starting" | "streaming" | "stopping";
type StreamAction = "send" | "resume" | "regenerate";
type DraftPersistence = "unknown" | "available" | "unavailable";
type ChatSubmissionStatus = "unknown" | "available" | "disabled";

interface StreamHandle {
  token: number;
  controller: AbortController;
  conversationId: string;
  requestId: string | null;
}

let clientIdSequence = 0;

function newClientId(prefix: string): string {
  clientIdSequence += 1;
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `demo-${prefix}-${Date.now()}-${clientIdSequence}`;
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error &&
    (error as { name?: unknown }).name === "AbortError";
}

function isOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

function errorCode(error: unknown): string | undefined {
  if (error instanceof ConversationServiceErrorClass) return error.code;
  if (typeof error === "object" && error !== null && "code" in error) {
    const code = (error as { code?: unknown }).code;
    return typeof code === "string" ? code : undefined;
  }
  return undefined;
}

function readableError(error: unknown, fallback: string): string {
  if (isOffline()) return "当前处于离线状态，请恢复网络后重试。";
  if (error instanceof ConversationServiceErrorClass) {
    switch (error.code) {
      case "CONVERSATION_NOT_FOUND":
        return "这个会话不存在，可能已被移除。";
      case "CONVERSATION_BUSY":
        return "当前会话仍在生成中，请先停止或等待本次响应完成。";
      case "MESSAGE_NOT_LATEST":
        return "只能重新生成最新一条回复。";
      case "MESSAGE_EMPTY":
        return "请输入内容后再发送。";
      case "CONTENT_REJECTED":
        return "这条内容无法处理，请调整后重试。";
      case "CHAT_SUBMISSION_DISABLED":
        return "聊天服务暂不可用，请稍后重试。";
      case "IDEMPOTENCY_IN_PROGRESS":
        return "相同消息正在处理中，请稍后查看会话状态。";
      case "STREAM_CURSOR_INVALID":
        return "响应恢复游标已失效，请重新加载会话后重试。";
      case "PROVIDER_TIMEOUT":
        return "响应超时，请稍后重试。";
      case "CONVERSATION_UNAVAILABLE":
        return "会话服务暂时不可用，请稍后重试。";
      default:
        return fallback;
    }
  }
  return fallback;
}

function conversationListStatus(status: AsyncStatus, summaries: readonly ConversationSummary[]): ConversationListStatus {
  if (status === "loading") return "loading";
  if (status === "error") return "error";
  return summaries.length === 0 ? "empty" : "ready";
}

export interface ChatWorkspaceProps {
  conversationId: string;
}

export function ChatWorkspace({ conversationId }: ChatWorkspaceProps) {
  const router = useRouter();
  const registry = useMemo(() => createBrowserServiceRegistry(), []);
  const mountedRef = useRef(true);
  const loadRevisionRef = useRef(0);
  const streamTokenRef = useRef(0);
  const streamRef = useRef<StreamHandle | null>(null);
  const claimedRequestRef = useRef(new Set<string>());
  const requestCursorRef = useRef(new Map<string, number>());
  const draftCacheRef = useRef(new Map<string, string>());
  const draftRef = useRef("");
  const draftRevisionRef = useRef(0);
  const draftWriteControllerRef = useRef<AbortController | null>(null);
  const draftWriteRevisionRef = useRef(0);
  const newConversationTokenRef = useRef(0);
  const newConversationControllerRef = useRef<AbortController | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeConversationIdRef = useRef(conversationId);
  const mobileTriggerRef = useRef<HTMLButtonElement | null>(null);
  const previousMobileOpenRef = useRef(false);

  const [summaries, setSummaries] = useState<readonly ConversationSummary[]>([]);
  const [summaryStatus, setSummaryStatus] = useState<AsyncStatus>("loading");
  const [summaryError, setSummaryError] = useState("");
  const [summaryReloadKey, setSummaryReloadKey] = useState(0);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [conversationStatus, setConversationStatus] = useState<AsyncStatus>("loading");
  const [conversationError, setConversationError] = useState("");
  const [model, setModel] = useState<CatalogModel | null>(null);
  const [modelStatus, setModelStatus] = useState<AsyncStatus>("loading");
  const [modelError, setModelError] = useState("");
  const [draft, setDraft] = useState("");
  const [draftSaving, setDraftSaving] = useState(false);
  const [draftPersistence, setDraftPersistence] = useState<DraftPersistence>("unknown");
  const [composerError, setComposerError] = useState("");
  const [streamError, setStreamError] = useState("");
  const [chatSubmissionStatus, setChatSubmissionStatus] =
    useState<ChatSubmissionStatus>("unknown");
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("idle");
  const [streamAction, setStreamAction] = useState<StreamAction | null>(null);
  const [creating, setCreating] = useState(false);
  const [mobileConversationOpen, setMobileConversationOpen] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [regenerateBusy, setRegenerateBusy] = useState(false);

  const busy = streamStatus !== "idle";

  /* eslint-disable react-hooks/set-state-in-effect -- route and external service state are synchronized here. */
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      streamTokenRef.current += 1;
      streamRef.current?.controller.abort();
      streamRef.current = null;
      draftWriteControllerRef.current?.abort();
      draftWriteRevisionRef.current += 1;
      draftWriteControllerRef.current = null;
      newConversationTokenRef.current += 1;
      newConversationControllerRef.current?.abort();
      newConversationControllerRef.current = null;
      if (copyTimerRef.current) {
        clearTimeout(copyTimerRef.current);
        copyTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (previousMobileOpenRef.current && !mobileConversationOpen) {
      mobileTriggerRef.current?.focus();
    }
    previousMobileOpenRef.current = mobileConversationOpen;
  }, [mobileConversationOpen]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setSummaryStatus("loading");
    setSummaryError("");

    void registry.conversation.listConversations(controller.signal)
      .then((nextSummaries) => {
        if (!active || !mountedRef.current) return;
        setSummaries(nextSummaries);
        setSummaryStatus(nextSummaries.length === 0 ? "ready" : "ready");
      })
      .catch((error: unknown) => {
        if (!active || !mountedRef.current || isAbortError(error)) return;
        setSummaryError(readableError(error, "无法加载最近会话。"));
        setSummaryStatus("error");
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [conversationId, registry, summaryReloadKey]);

  useEffect(() => {
    const controller = new AbortController();
    const revision = ++loadRevisionRef.current;
    let active = true;

    activeConversationIdRef.current = conversationId;
    draftRevisionRef.current += 1;
    if (copyTimerRef.current) {
      clearTimeout(copyTimerRef.current);
      copyTimerRef.current = null;
    }
    setCopiedMessageId(null);
    newConversationTokenRef.current += 1;
    newConversationControllerRef.current?.abort();
    newConversationControllerRef.current = null;
    draftWriteRevisionRef.current += 1;
    draftWriteControllerRef.current?.abort();
    draftWriteControllerRef.current = null;
    setDraftSaving(false);
    setCreating(false);
    streamTokenRef.current += 1;
    streamRef.current?.controller.abort();
    streamRef.current = null;
    claimedRequestRef.current.clear();
    setConversation(null);
    setModel(null);
    setConversationStatus("loading");
    setConversationError("");
    setModelStatus("loading");
    setModelError("");
    setStreamStatus("idle");
    setStreamAction(null);
    setStreamError("");
    setChatSubmissionStatus("unknown");
    setComposerError("");
    setMobileConversationOpen(false);
    setDraftPersistence("unknown");
    const cachedDraft = draftCacheRef.current.get(conversationId) ?? "";
    draftRef.current = cachedDraft;
    setDraft(cachedDraft);

    void (async () => {
      try {
        const nextConversation = await registry.conversation.getConversation(conversationId, controller.signal);
        if (!active || !mountedRef.current || revision !== loadRevisionRef.current) return;
        if (
          nextConversation.active_request_id !== null &&
          nextConversation.active_request_cursor !== null
        ) {
          requestCursorRef.current.set(
            nextConversation.active_request_id,
            nextConversation.active_request_cursor,
          );
        }
        setConversation(nextConversation);
        setConversationStatus("ready");

        try {
          const persistedDraft = await registry.conversation.getDraft(conversationId, controller.signal);
          if (active && mountedRef.current && revision === loadRevisionRef.current) {
            draftCacheRef.current.set(conversationId, persistedDraft);
            setDraftPersistence("available");
            if (draftRef.current === cachedDraft) {
              draftRef.current = persistedDraft;
              setDraft(persistedDraft);
            }
          }
        } catch (error: unknown) {
          // The API adapter intentionally has no draft endpoint yet. Keep the
          // local controlled cache and make no false persistence claim.
          if (isAbortError(error)) throw error;
          if (errorCode(error) === "CONVERSATION_UNAVAILABLE") {
            if (active && mountedRef.current && revision === loadRevisionRef.current) {
              setDraftPersistence("unavailable");
            }
          } else if (active && mountedRef.current && revision === loadRevisionRef.current) {
            setComposerError(readableError(error, "草稿暂时无法读取。"));
          }
        }

        try {
          const nextModel = await registry.modelCatalog.get(nextConversation.product_model_id, controller.signal);
          if (!active || !mountedRef.current || revision !== loadRevisionRef.current) return;
          setModel(nextModel);
          setModelStatus("ready");
        } catch (error: unknown) {
          if (isAbortError(error)) throw error;
          if (!active || !mountedRef.current || revision !== loadRevisionRef.current) return;
          setModelError(readableError(error, "模型信息暂时不可用。"));
          setModelStatus("error");
        }
      } catch (error: unknown) {
        if (!active || !mountedRef.current || revision !== loadRevisionRef.current || isAbortError(error)) return;
        setConversationError(readableError(error, "无法打开这个会话。"));
        setConversationStatus("error");
        setModelStatus("error");
      }
    })();

    return () => {
      active = false;
      controller.abort();
      draftWriteRevisionRef.current += 1;
      draftWriteControllerRef.current?.abort();
      draftWriteControllerRef.current = null;
    };
  }, [conversationId, registry]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const refreshConversation = useCallback(async (id: string, signal?: AbortSignal) => {
    return registry.conversation.getConversation(id, signal);
  }, [registry]);

  const consumeStream = useCallback(async (
    stream: ConversationStream,
    seedConversation: Conversation,
    action: StreamAction,
    handle: StreamHandle,
  ) => {
    let reducerState: ConversationReducerState = createConversationReducerState(seedConversation);
    setStreamStatus("streaming");

    try {
      for await (const event of stream.events) {
        if (!mountedRef.current || streamRef.current?.token !== handle.token) return;
        const nextState = reduceConversation(reducerState, event);
        if (nextState !== reducerState) {
          reducerState = nextState;
          requestCursorRef.current.set(event.request_id, event.sequence);
          setConversation((current) => current?.conversation_id === handle.conversationId
            ? reducerState.conversation
            : current);
        }
        if (event.type === "failed") {
          setStreamError(readableError(new ConversationServiceErrorClass({
            code: event.error.code === "CONTENT_REJECTED" ? "CONTENT_REJECTED" : "CONVERSATION_UNAVAILABLE",
            status: 422,
            retryable: event.error.retryable,
            requestId: event.request_id,
            message: event.error.message,
          }), "这次响应未能完成。"));
        }
      }

      if (!mountedRef.current || streamRef.current?.token !== handle.token) return;
      const refreshed = await refreshConversation(handle.conversationId, handle.controller.signal);
      if (!mountedRef.current || streamRef.current?.token !== handle.token) return;
      setConversation(refreshed);
      setChatSubmissionStatus("available");
      setStreamStatus("idle");
      setStreamAction(null);
      setRegenerateBusy(false);
    } catch (error: unknown) {
      if (!mountedRef.current || streamRef.current?.token !== handle.token || isAbortError(error)) return;
      if (errorCode(error) === "CHAT_SUBMISSION_DISABLED") {
        setChatSubmissionStatus("disabled");
      }
      setStreamError(readableError(error, action === "resume" ? "恢复响应失败。" : "响应暂时无法完成。"));
      setStreamStatus("idle");
      setStreamAction(null);
      setRegenerateBusy(false);
    } finally {
      if (streamRef.current?.token === handle.token) streamRef.current = null;
    }
  }, [refreshConversation]);

  const startStream = useCallback(async (
    action: StreamAction,
    seedConversation: Conversation,
    request: (signal: AbortSignal) => Promise<ConversationStream>,
    onAccepted?: (() => void) | undefined,
  ) => {
    if (!mountedRef.current || streamRef.current !== null || busy) return false;
    const controller = new AbortController();
    const handle: StreamHandle = {
      token: ++streamTokenRef.current,
      controller,
      conversationId: seedConversation.conversation_id,
      requestId: null,
    };
    streamRef.current = handle;
    setStreamStatus("starting");
    setStreamAction(action);
    setStreamError("");

    let acceptedStream: ConversationStream | null = null;
    try {
      const stream = await request(controller.signal);
      acceptedStream = stream;
      if (!mountedRef.current || streamRef.current?.token !== handle.token) return false;
      handle.requestId = stream.requestId;
      // The service promise resolving is the acceptance boundary. Clear only
      // the exact submitted draft here; a newer draft typed during starting is
      // left under the latest ref/cache values.
      onAccepted?.();
      let hydrated: Conversation;
      try {
        hydrated = await refreshConversation(seedConversation.conversation_id, controller.signal);
      } catch (error: unknown) {
        if (!mountedRef.current || streamRef.current?.token !== handle.token || isAbortError(error)) return false;
        controller.abort();
        const requestId = stream.requestId;
        if (requestId) {
          setConversation((current) => current?.conversation_id === seedConversation.conversation_id
            ? {
                ...current,
                active_request_id: requestId,
                active_request_cursor: stream.lastSequence,
              }
            : current);
          setStreamError("响应已接受，但会话刷新失败；正在尝试恢复。若仍未恢复，请重新加载。");
        } else {
          setStreamError(readableError(error, "响应已接受，但会话刷新失败。请重新加载后恢复。"));
        }
        setStreamStatus("idle");
        setStreamAction(null);
        setRegenerateBusy(false);
        streamRef.current = null;
        return false;
      }
      if (!mountedRef.current || streamRef.current?.token !== handle.token) return false;
      void consumeStream(stream, hydrated, action, handle);
      return true;
    } catch (error: unknown) {
      if (!mountedRef.current || streamRef.current?.token !== handle.token || isAbortError(error)) return false;
      if (errorCode(error) === "CHAT_SUBMISSION_DISABLED") {
        setChatSubmissionStatus("disabled");
      }
      if (acceptedStream !== null) {
        acceptedStream = null;
        handle.controller.abort();
      }
      setStreamError(readableError(error, "响应暂时无法开始。"));
      setStreamStatus("idle");
      setStreamAction(null);
      setRegenerateBusy(false);
      streamRef.current = null;
      return false;
    }
  }, [busy, consumeStream, refreshConversation]);

  useEffect(() => {
    if (!conversation || conversationStatus !== "ready" || conversation.active_request_id === null) return;
    const key = `${conversation.conversation_id}:${conversation.active_request_id}`;
    // Claim each active request before starting its one controlled resume. A
    // failed resume remains recoverable through an explicit reload.
    if (claimedRequestRef.current.has(key) || streamRef.current !== null) return;
    claimedRequestRef.current.add(key);
    const cursor = requestCursorRef.current.get(conversation.active_request_id) ??
      conversation.active_request_cursor ?? -1;
    void startStream(
      "resume",
      conversation,
      (signal) => registry.conversation.resumeMessage({
        conversationId: conversation.conversation_id,
        requestId: conversation.active_request_id!,
        cursor,
      }, signal),
    );
  }, [conversation, conversationStatus, registry, startStream]);

  const persistDraft = useCallback((content: string) => {
    if (!conversation) return;
    const conversationIdForWrite = conversation.conversation_id;
    const revision = ++draftWriteRevisionRef.current;
    draftCacheRef.current.set(conversationIdForWrite, content);
    draftWriteControllerRef.current?.abort();
    const controller = new AbortController();
    draftWriteControllerRef.current = controller;
    setDraftSaving(true);
    void registry.conversation.saveDraft({
      conversationId: conversationIdForWrite,
      content,
    }, controller.signal)
      .then(() => {
        if (
          mountedRef.current &&
          draftWriteRevisionRef.current === revision &&
          draftWriteControllerRef.current === controller
        ) {
          setDraftPersistence("available");
        }
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        if (errorCode(error) === "CONVERSATION_UNAVAILABLE") {
          if (
            mountedRef.current &&
            draftWriteRevisionRef.current === revision &&
            draftWriteControllerRef.current === controller
          ) {
            setDraftPersistence("unavailable");
          }
          return;
        }
        if (
          mountedRef.current &&
          draftWriteRevisionRef.current === revision &&
          draftWriteControllerRef.current === controller
        ) {
          setComposerError(readableError(error, "草稿暂时无法保存。"));
        }
      })
      .finally(() => {
        if (
          draftWriteControllerRef.current === controller &&
          draftWriteRevisionRef.current === revision &&
          mountedRef.current
        ) {
          setDraftSaving(false);
        }
      });
  }, [conversation, registry]);

  const handleDraftChange = useCallback((nextDraft: string) => {
    draftRevisionRef.current += 1;
    draftRef.current = nextDraft;
    setDraft(nextDraft);
    setComposerError("");
    persistDraft(nextDraft);
  }, [persistDraft]);

  const handleSend = useCallback(() => {
    if (!conversation || !model || busy || draft.trim() === "") return;
    if (isOffline()) {
      setComposerError("当前处于离线状态，草稿已保留，恢复网络后再发送。");
      return;
    }
    const content = draft.trim();
    const submittedDraftRevision = draftRevisionRef.current;
    const clientRequestId = newClientId("message");
    setComposerError("");
    void (async () => {
      const accepted = await startStream(
        "send",
        conversation,
        (signal) => registry.conversation.sendMessage({
          conversationId: conversation.conversation_id,
          content,
          clientRequestId,
        }, signal),
        () => {
          if (draftRevisionRef.current !== submittedDraftRevision) return;
          draftRef.current = "";
          draftCacheRef.current.set(conversation.conversation_id, "");
          setDraft("");
          persistDraft("");
        },
      );
      if (!accepted || !mountedRef.current) return;
    })();
  }, [busy, conversation, draft, model, persistDraft, registry, startStream]);

  const handleStop = useCallback(() => {
    const handle = streamRef.current;
    if (!handle || handle.requestId === null || streamStatus === "stopping") return;
    setStreamStatus("stopping");
    void registry.conversation.stopMessage({
      conversationId: handle.conversationId,
      requestId: handle.requestId,
    }, handle.controller.signal)
      .catch((error: unknown) => {
        if (isAbortError(error) || !mountedRef.current) return;
        setStreamError(readableError(error, "暂时无法停止响应。"));
        setStreamStatus("streaming");
      });
  }, [registry, streamStatus]);

  const handleRegenerate = useCallback((message: ConversationMessage) => {
    if (!conversation || busy || isOffline()) {
      if (isOffline()) setComposerError("当前处于离线状态，无法重新生成。");
      return;
    }
    setRegenerateBusy(true);
    void startStream(
      "regenerate",
      conversation,
      (signal) => registry.conversation.regenerate({
        conversationId: conversation.conversation_id,
        messageId: message.message_id,
        clientRequestId: newClientId("regenerate"),
      }, signal),
    );
  }, [busy, conversation, registry, startStream]);

  const handleCopy = useCallback(async (message: ConversationMessage) => {
    const copyRevision = loadRevisionRef.current;
    const copyConversationId = conversationId;
    const isCurrentCopy = () => mountedRef.current &&
      copyRevision === loadRevisionRef.current &&
      copyConversationId === activeConversationIdRef.current;

    try {
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        throw new Error("Clipboard unavailable");
      }
      await navigator.clipboard.writeText(message.content);
      if (!isCurrentCopy()) return;
      setCopiedMessageId(message.message_id);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => {
        if (!isCurrentCopy()) return;
        copyTimerRef.current = null;
        setCopiedMessageId(null);
      }, 1800);
    } catch {
      if (isCurrentCopy()) setComposerError("无法访问剪贴板，请手动选择文本复制。 ");
    }
  }, [conversationId]);

  const handleSelectConversation = useCallback((nextId: string) => {
    if (nextId === conversationId) {
      setMobileConversationOpen(false);
      return;
    }
    newConversationTokenRef.current += 1;
    newConversationControllerRef.current?.abort();
    newConversationControllerRef.current = null;
    draftWriteRevisionRef.current += 1;
    draftWriteControllerRef.current?.abort();
    draftWriteControllerRef.current = null;
    setDraftSaving(false);
    setCreating(false);
    streamTokenRef.current += 1;
    streamRef.current?.controller.abort();
    streamRef.current = null;
    setConversation(null);
    setModel(null);
    setMobileConversationOpen(false);
    router.push(`/chat/${nextId}`);
  }, [conversationId, router]);

  const handleNewConversation = useCallback(() => {
    if (!model || model.item.model.task_type !== "chat" || creating) return;
    newConversationControllerRef.current?.abort();
    const token = ++newConversationTokenRef.current;
    const controller = new AbortController();
    newConversationControllerRef.current = controller;
    setCreating(true);
    setComposerError("");
    void registry.conversation.createConversation({
      productModelId: model.item.model.product_model_id,
      clientRequestId: newClientId("conversation"),
    }, controller.signal)
      .then((created) => {
        if (
          mountedRef.current &&
          newConversationTokenRef.current === token &&
          newConversationControllerRef.current === controller &&
          !controller.signal.aborted
        ) {
          router.push(`/chat/${created.conversation_id}`);
        }
      })
      .catch((error: unknown) => {
        if (
          mountedRef.current &&
          newConversationTokenRef.current === token &&
          newConversationControllerRef.current === controller &&
          !isAbortError(error)
        ) {
          setComposerError(readableError(error, "暂时无法创建会话。"));
        }
      })
      .finally(() => {
        if (
          mountedRef.current &&
          newConversationTokenRef.current === token &&
          newConversationControllerRef.current === controller
        ) {
          newConversationControllerRef.current = null;
          setCreating(false);
        }
      });
  }, [creating, model, registry, router]);

  const retrySummary = useCallback(() => setSummaryReloadKey((current) => current + 1), []);

  const handleFullscreen = useCallback(() => {
    if (typeof document === "undefined") return;
    const action = document.fullscreenElement
      ? document.exitFullscreen?.()
      : document.documentElement.requestFullscreen?.();
    if (action) {
      void action.catch(() => {
        setComposerError("当前浏览器未允许进入全屏模式。");
      });
    }
  }, []);

  const listStatus = conversationListStatus(summaryStatus, summaries);
  const showConversationError = conversationStatus === "error";
  const showConversationLoading = conversationStatus === "loading";
  const showModelError = modelStatus === "error";
  const emptyConversation = conversation?.messages.length === 0;

  const historyTrigger = (
    <button
      ref={mobileTriggerRef}
      type="button"
      aria-label="打开会话列表"
      className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--mosaic-radius-control)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)]"
    >
      <ClockCounterClockwise size={18} aria-hidden />
    </button>
  );

  return (
    <section
      data-testid="chat-workspace"
      data-stream-status={streamStatus}
      data-stream-action={streamAction ?? undefined}
      data-active-request-id={conversation?.active_request_id ?? undefined}
      className="flex h-full min-h-0 min-w-0 w-full flex-col overflow-hidden bg-[var(--mosaic-color-surface)]"
    >
      <div className="flex min-h-0 flex-1 flex-col bg-[var(--mosaic-color-surface)]">
          <header
            data-testid="chat-header"
            className="relative grid h-[var(--mosaic-layout-task-header)] min-h-[var(--mosaic-layout-task-header)] shrink-0 grid-cols-[1fr_auto] items-center gap-3 border-b border-[var(--mosaic-color-line)] px-5 sm:px-7"
          >
            <h1 className="truncate text-base font-semibold tracking-[-0.02em] text-[var(--mosaic-color-ink)]">
              文本模型
            </h1>
            <div className="flex shrink-0 items-center justify-end gap-1 text-[var(--mosaic-color-ink-muted)]">
              <button
                type="button"
                aria-label="新建会话"
                disabled={creating || model === null}
                onClick={handleNewConversation}
                className="inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-[var(--mosaic-radius-control)] px-2 text-sm font-medium transition-[background-color,color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] disabled:cursor-not-allowed disabled:opacity-50 sm:px-3"
              >
                <PlusSquare size={18} aria-hidden />
                <span className="hidden xl:inline">新建会话</span>
              </button>
              <button
                type="button"
                aria-label="切换全屏"
                onClick={handleFullscreen}
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--mosaic-radius-control)] transition-[background-color,color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)]"
              >
                <ArrowsOut size={18} aria-hidden />
              </button>
              <ConversationList
                summaries={summaries}
                activeConversationId={conversationId}
                status={listStatus}
                errorMessage={summaryError}
                creating={creating}
                trigger={historyTrigger}
                mobileOpen={mobileConversationOpen}
                onMobileOpenChange={setMobileConversationOpen}
                onSelect={handleSelectConversation}
                onNew={handleNewConversation}
                onRetry={retrySummary}
                onBackToModels={() => router.push("/models")}
              />
            </div>
          </header>

          <div
            data-testid="chat-model-toolbar"
            className="flex h-16 min-h-16 shrink-0 items-center justify-between border-b border-[var(--mosaic-color-line)] px-5 sm:px-7"
          >
            <div className="flex min-w-0 items-center gap-1">
              <ChatCircleDots size={22} weight="fill" aria-hidden className="shrink-0 text-[var(--mosaic-color-accent)]" />
              <button
                type="button"
                aria-label="选择模型"
                onClick={() => router.push("/models")}
                className="inline-flex min-h-11 min-w-0 items-center gap-2 rounded-[var(--mosaic-radius-control)] px-2 text-sm font-medium text-[var(--mosaic-color-ink)] hover:bg-[var(--mosaic-color-surface-muted)]"
              >
                <span className="truncate">
                  {model?.item.model.display_name ?? (showConversationError ? "会话不可用" : "正在加载模型")}
                </span>
                <CaretDown size={14} aria-hidden className="shrink-0 text-[var(--mosaic-color-ink-muted)]" />
              </button>
              <button
                type="button"
                onClick={() => router.push("/models")}
                className="hidden min-h-11 items-center px-2 text-sm font-medium text-[var(--mosaic-color-accent)] hover:underline sm:inline-flex"
              >
                模型详情
              </button>
            </div>
          </div>

          {showConversationLoading ? (
            <div className="flex min-h-0 flex-1 flex-col gap-4 px-5 py-6 sm:px-8" data-testid="chat-loading">
              <Skeleton label="正在加载会话" className="h-20 max-w-[640px]" />
              <Skeleton label="正在加载会话" className="ml-auto h-16 max-w-[480px]" />
              <Skeleton label="正在加载会话" className="h-24 max-w-[720px]" />
            </div>
          ) : null}

          {showConversationError ? (
            <div className="flex min-h-0 flex-1 items-center justify-center px-6" data-testid="chat-error">
              <ErrorState
                title="无法打开这个会话"
                description={conversationError || "会话不存在或暂时不可用。"}
                action={<Button variant="secondary" onClick={() => router.push("/models")}>返回模型广场</Button>}
                className="max-w-lg"
              />
            </div>
          ) : null}

          {!showConversationLoading && !showConversationError ? (
            <>
              {showModelError ? (
                <div className="border-b border-[var(--mosaic-color-line)] bg-[color-mix(in_srgb,var(--mosaic-color-danger)_5%,var(--mosaic-color-surface))] px-5 py-3 text-sm text-[var(--mosaic-color-danger)] sm:px-8" role="alert">
                  <span className="inline-flex items-center gap-2"><WarningCircle size={16} aria-hidden />{modelError}</span>
                </div>
              ) : null}
              {draftPersistence !== "unknown" ? (
                <p data-testid="draft-status" role="status" className="sr-only">
                  {draftPersistence === "available" ? "草稿自动保存" : "草稿仅保留在当前页面"}
                </p>
              ) : null}
              {chatSubmissionStatus === "disabled" ? (
                <div
                  data-testid="chat-submission-disabled"
                  role="status"
                  className="flex shrink-0 items-start gap-2 border-b border-[color-mix(in_srgb,var(--mosaic-color-warning)_35%,var(--mosaic-color-line))] bg-[color-mix(in_srgb,var(--mosaic-color-warning)_8%,var(--mosaic-color-surface))] px-5 py-3 text-sm leading-6 text-[var(--mosaic-color-ink)] sm:px-10"
                >
                  <WarningCircle size={18} aria-hidden className="mt-1 shrink-0 text-[var(--mosaic-color-warning)]" />
                  <span>聊天服务暂不可用。已输入内容仍保留在当前页面。</span>
                </div>
              ) : null}
              <p data-testid="copy-confirmation" role="status" aria-live="polite" className="sr-only">
                {copiedMessageId ? "已复制" : ""}
              </p>
              {emptyConversation ? (
                <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-5 py-8 sm:px-8 sm:py-12">
                  <div className="w-full max-w-[var(--mosaic-layout-task-message)]">
                    <MessageList
                      conversation={conversation}
                      layout="empty"
                      emptyModelName={model?.item.model.display_name}
                      assistantName={model?.item.model.display_name}
                      copiedMessageId={copiedMessageId}
                      actionBusy={regenerateBusy || busy}
                      onCopy={handleCopy}
                      onRegenerate={handleRegenerate}
                    />
                    <Composer
                      value={draft}
                      variant="empty"
                      busy={busy}
                      disabled={
                        conversation === null ||
                        model === null ||
                        showModelError ||
                        chatSubmissionStatus === "disabled"
                      }
                      errorMessage={composerError || streamError || undefined}
                      statusMessage={draftSaving ? "正在保存草稿" : undefined}
                      onChange={handleDraftChange}
                      onSend={handleSend}
                      onStop={handleStop}
                    />
                  </div>
                </div>
              ) : (
                <div className="flex min-h-0 flex-1 flex-col">
                  <MessageList
                    conversation={conversation}
                    assistantName={model?.item.model.display_name}
                    copiedMessageId={copiedMessageId}
                    actionBusy={regenerateBusy || busy}
                    onCopy={handleCopy}
                    onRegenerate={handleRegenerate}
                  />
                  <Composer
                    value={draft}
                    variant="active"
                    busy={busy}
                    disabled={
                      conversation === null ||
                      model === null ||
                      showModelError ||
                      chatSubmissionStatus === "disabled"
                    }
                    errorMessage={composerError || streamError || undefined}
                    statusMessage={draftSaving ? "正在保存草稿" : undefined}
                    onChange={handleDraftChange}
                    onSend={handleSend}
                    onStop={handleStop}
                  />
                </div>
              )}
            </>
          ) : null}
      </div>
    </section>
  );
}

export type { ConversationServiceError };
