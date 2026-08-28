import { CircleNotch, WarningCircle } from "@phosphor-icons/react";
import type { ConversationMessage } from "@mosaic/contracts";

export interface StreamResponseProps {
  message: ConversationMessage;
  onCopy?: (() => void) | undefined;
  onRegenerate?: (() => void) | undefined;
  copied?: boolean;
  canRegenerate?: boolean;
  busy?: boolean;
}

export function StreamResponse({
  message,
  onCopy,
  onRegenerate,
  copied = false,
  canRegenerate = false,
  busy = false,
}: StreamResponseProps) {
  const isStreaming = message.status === "streaming";
  const isFailed = message.status === "failed";
  const isStopped = message.status === "stopped";

  return (
    <div data-testid={`stream-response-${message.message_id}`}>
      <div className="whitespace-pre-wrap break-words text-base leading-7 text-[var(--mosaic-color-ink)]">
        {message.content || (isStreaming ? "" : "暂无内容")}
        {isStreaming ? (
          <span
            aria-label="正在生成"
            className="ml-1 inline-block h-4 w-0.5 translate-y-0.5 animate-pulse bg-[var(--mosaic-color-accent)] align-baseline motion-reduce:animate-none"
          />
        ) : null}
      </div>

      {isStreaming ? (
        <p className="mt-3 inline-flex items-center gap-2 text-xs text-[var(--mosaic-color-ink-muted)]">
          <CircleNotch size={14} aria-hidden className="animate-spin motion-reduce:animate-none" />
          正在生成
        </p>
      ) : null}

      {isStopped ? (
        <p className="mt-3 text-xs text-[var(--mosaic-color-ink-muted)]">已停止生成，以上为已保留内容。</p>
      ) : null}

      {isFailed ? (
        <p role="alert" className="mt-3 inline-flex items-center gap-2 text-xs text-[var(--mosaic-color-danger)]">
          <WarningCircle size={14} aria-hidden />
          这次响应未能完成，可以稍后重试。
        </p>
      ) : null}

      {!isStreaming && !isFailed && (onCopy || (canRegenerate && onRegenerate)) ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {onCopy ? (
            <button
              type="button"
              onClick={onCopy}
              className="inline-flex min-h-11 items-center rounded-[var(--mosaic-radius-control)] border border-transparent px-3 text-sm font-semibold leading-5 text-[var(--mosaic-color-ink-muted)] transition-[background-color,color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)]"
            >
              {copied ? "已复制" : "复制"}
            </button>
          ) : null}
          {canRegenerate && onRegenerate ? (
            <button
              type="button"
              onClick={onRegenerate}
              disabled={busy}
              className="inline-flex min-h-11 items-center rounded-[var(--mosaic-radius-control)] border border-transparent px-3 text-sm font-semibold leading-5 text-[var(--mosaic-color-ink-muted)] transition-[background-color,color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] disabled:cursor-wait disabled:opacity-50"
            >
              {busy ? "正在重试" : "重新生成"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
