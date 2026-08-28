import { ArrowUp, Stop } from "@phosphor-icons/react";
import { useRef } from "react";

import { cn } from "@/shared/ui/cn";

export interface ComposerProps {
  value: string;
  variant?: "active" | "empty";
  busy?: boolean;
  disabled?: boolean;
  errorMessage?: string | undefined;
  statusMessage?: string | undefined;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
}

export function Composer({
  value,
  variant = "active",
  busy = false,
  disabled = false,
  errorMessage,
  statusMessage,
  onChange,
  onSend,
  onStop,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canSend = value.trim().length > 0 && !disabled && !busy;
  const isEmpty = variant === "empty";

  return (
    <div className={cn(
      "shrink-0 bg-[var(--mosaic-color-surface)] px-5 pb-[calc(16px+env(safe-area-inset-bottom))] sm:px-10",
      isEmpty
        ? "pt-4 sm:pt-5"
        : "sticky bottom-0 border-t border-[var(--mosaic-color-line)] pt-3 shadow-[0_-14px_32px_color-mix(in_srgb,var(--mosaic-color-ink)_6%,transparent)]",
    )}>
      <form
        className="mx-auto w-full max-w-[var(--mosaic-layout-task-message)]"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSend) onSend();
        }}
      >
        <div
          className={cn(
            "grid grid-cols-[minmax(0,1fr)_44px] items-stretch gap-3 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] transition-[border-color,box-shadow] focus-within:border-[var(--mosaic-color-accent)] focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--mosaic-color-accent)_10%,transparent)]",
            isEmpty
              ? "min-h-[var(--mosaic-layout-task-composer)] p-3 sm:p-4"
              : "min-h-[var(--mosaic-layout-composer-panel)] max-h-[calc(var(--mosaic-layout-composer-panel)+var(--mosaic-spacing-8))] p-3",
            disabled && "opacity-70",
          )}
          data-testid="composer-panel"
        >
          <textarea
            ref={textareaRef}
            value={value}
            disabled={disabled}
            rows={isEmpty ? 2 : 1}
            aria-label="输入消息"
            placeholder="输入消息"
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (canSend) onSend();
              }
            }}
            className={cn(
              "resize-none self-start bg-transparent px-2 py-2 text-base leading-7 text-[var(--mosaic-color-ink)] placeholder:text-[var(--mosaic-color-ink-muted)] focus:outline-none disabled:cursor-not-allowed",
              isEmpty ? "h-full min-h-[64px] max-h-[96px]" : "h-full max-h-[72px] min-h-11",
            )}
          />
          {busy ? (
            <button
              type="button"
              aria-label="停止生成"
              onClick={onStop}
              className="inline-flex min-h-11 min-w-11 self-end items-center justify-center rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-ink)] text-[var(--mosaic-color-surface)] transition-[background-color,transform] hover:bg-[color-mix(in_srgb,var(--mosaic-color-ink)_84%,var(--mosaic-color-accent))] active:translate-y-px"
            >
              <Stop size={17} weight="fill" aria-hidden />
            </button>
          ) : (
            <button
              type="submit"
              aria-label="发送消息"
              disabled={!canSend}
              className="inline-flex min-h-11 min-w-11 self-end items-center justify-center rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-accent)] text-[var(--mosaic-color-surface)] transition-[background-color,transform] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px disabled:cursor-not-allowed disabled:bg-[var(--mosaic-color-surface-muted)] disabled:text-[var(--mosaic-color-ink-muted)]"
            >
              <ArrowUp size={18} weight="bold" aria-hidden />
            </button>
          )}
        </div>
        <div className="mt-1 flex min-h-4 items-center justify-between gap-3 px-1 text-[11px] text-[var(--mosaic-color-ink-muted)]">
          <span>{busy ? "生成中的消息会保留在当前会话。" : "Enter 发送 · Shift + Enter 换行"}</span>
          {statusMessage ? <span data-testid="composer-status" role="status" aria-live="polite">{statusMessage}</span> : null}
          {errorMessage ? <span role="alert" className="text-[var(--mosaic-color-danger)]">{errorMessage}</span> : null}
        </div>
      </form>
    </div>
  );
}
