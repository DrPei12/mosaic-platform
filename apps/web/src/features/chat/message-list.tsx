import { Robot } from "@phosphor-icons/react";
import type { Conversation, ConversationMessage } from "@mosaic/contracts";
import { useEffect, useRef } from "react";

import { cn } from "@/shared/ui/cn";
import { StreamResponse } from "./stream-response";

export interface MessageListProps {
  conversation: Conversation | null;
  layout?: "rail" | "empty";
  emptyModelName?: string | undefined;
  assistantName?: string | undefined;
  copiedMessageId?: string | null;
  actionBusy?: boolean;
  onCopy: (message: ConversationMessage) => void;
  onRegenerate: (message: ConversationMessage) => void;
}

export function MessageList({
  conversation,
  layout = "rail",
  emptyModelName,
  assistantName = "Mosaic",
  copiedMessageId = null,
  actionBusy = false,
  onCopy,
  onRegenerate,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const lastMessageContent = conversation?.messages.at(-1)?.content;
  const messageCount = conversation?.messages.length;

  useEffect(() => {
    if (typeof endRef.current?.scrollIntoView === "function") {
      endRef.current.scrollIntoView({ block: "nearest" });
    }
  }, [messageCount, lastMessageContent]);

  if (!conversation) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-6" data-testid="message-list-empty">
        <p className="text-sm text-[var(--mosaic-color-ink-muted)]">选择一个会话开始。</p>
      </div>
    );
  }

  if (conversation.messages.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center px-6 text-center",
          layout === "empty" ? "w-full" : "min-h-0 flex-1",
        )}
        data-testid="message-list-empty"
        data-state="empty"
      >
        <div className="max-w-[720px]">
          <h2 className="text-[26px] font-semibold leading-8 tracking-[-0.045em] text-[var(--mosaic-color-ink)] sm:text-4xl sm:leading-tight">
            开始使用 {emptyModelName ?? "文本模型"}
          </h2>
          <p className="mt-3 text-sm leading-6 text-[var(--mosaic-color-ink-muted)]">
            从一个好问题开始
          </p>
        </div>
      </div>
    );
  }

  const latestAssistantId = [...conversation.messages]
    .reverse()
    .find((message) => message.role === "assistant")?.message_id;

  return (
    <div
      role="log"
      aria-live="polite"
      aria-label="对话消息"
      data-testid="message-list"
      className="min-h-0 flex-1 overflow-y-auto"
    >
      <div className="mx-auto w-full max-w-[var(--mosaic-layout-task-message)] px-5 pb-12 pt-4 sm:px-8 sm:pt-6">
        {conversation.messages.map((message) => {
          const isAssistant = message.role === "assistant";
          const isLatestAssistant = isAssistant && message.message_id === latestAssistantId;
          if (!isAssistant) {
            return (
              <article
                key={message.message_id}
                data-testid={`message-${message.message_id}`}
                data-role={message.role}
                className="flex justify-end py-5 sm:py-6"
              >
                <div className="max-w-[min(78%,680px)] rounded-[var(--mosaic-radius-surface)] bg-[color-mix(in_srgb,var(--mosaic-color-accent)_7%,var(--mosaic-color-surface))] px-4 py-3 text-left">
                  <span className="sr-only">你：</span>
                  <p className="whitespace-pre-wrap break-words text-base leading-7 text-[var(--mosaic-color-ink)]">
                    {message.content}
                  </p>
                  <time dateTime={message.created_at} className="sr-only">
                    {new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(message.created_at))}
                  </time>
                </div>
              </article>
            );
          }
          return (
            <article
              key={message.message_id}
              data-testid={`message-${message.message_id}`}
              data-role={message.role}
              className={cn(
                "grid grid-cols-[32px_minmax(0,1fr)] gap-4 border-b border-[var(--mosaic-color-line)] py-6 sm:gap-5 sm:py-7",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "inline-flex size-8 items-center justify-center rounded-full border text-[var(--mosaic-color-ink-muted)]",
                  "border-[color-mix(in_srgb,var(--mosaic-color-accent)_35%,var(--mosaic-color-line))] text-[var(--mosaic-color-accent)]",
                )}
              >
                <Robot size={20} weight="regular" />
              </span>
              <div className="min-w-0">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold leading-5 text-[var(--mosaic-color-ink-muted)]">
                  <span className="text-[var(--mosaic-color-accent)]">{assistantName}</span>
                  <time dateTime={message.created_at} className="font-normal tabular-nums">
                    {new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(message.created_at))}
                  </time>
                </div>
                <StreamResponse
                  message={message}
                  onCopy={message.status !== "failed" ? () => onCopy(message) : undefined}
                  onRegenerate={isLatestAssistant && message.status !== "streaming" ? () => onRegenerate(message) : undefined}
                  copied={copiedMessageId === message.message_id}
                  canRegenerate={isLatestAssistant && message.status !== "streaming"}
                  busy={actionBusy}
                />
              </div>
            </article>
          );
        })}
        <div ref={endRef} aria-hidden />
      </div>
    </div>
  );
}
