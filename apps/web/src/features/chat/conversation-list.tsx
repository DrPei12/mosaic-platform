"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ArrowLeft, ChatCircleDots, Funnel, Plus, X } from "@phosphor-icons/react";
import type { ConversationSummary } from "@mosaic/contracts";

import { useMemo, useState, type ReactNode } from "react";

import { Button } from "@/shared/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/shared/ui/feedback-state";
import { cn } from "@/shared/ui/cn";

export type ConversationListStatus = "loading" | "ready" | "error" | "empty";

export interface ConversationListProps {
  summaries: readonly ConversationSummary[];
  activeConversationId: string;
  status?: ConversationListStatus | undefined;
  errorMessage?: string | undefined;
  creating?: boolean | undefined;
  /**
   * The history trigger lives in the workspace header. Keeping the trigger
   * under the same Dialog.Root as the content makes the history affordance
   * accessible at every viewport instead of maintaining a desktop rail and a
   * second mobile drawer.
   */
  trigger?: ReactNode;
  mobileOpen: boolean;
  onMobileOpenChange: (open: boolean) => void;
  onSelect: (conversationId: string) => void;
  onNew: () => void;
  onRetry?: (() => void) | undefined;
  onBackToModels: () => void;
}

function formatConversationTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function ConversationRows({
  summaries,
  activeConversationId,
  onSelect,
  onClose,
}: Pick<ConversationListProps, "summaries" | "activeConversationId" | "onSelect"> & {
  onClose?: (() => void) | undefined;
}) {
  return (
    <div className="grid gap-1 px-3 pb-4" data-testid="conversation-list-items">
      {summaries.map((summary) => (
        <button
          type="button"
          key={summary.conversation_id}
          data-testid={`conversation-${summary.conversation_id}`}
          aria-current={summary.conversation_id === activeConversationId ? "page" : undefined}
          onClick={() => {
            onSelect(summary.conversation_id);
            onClose?.();
          }}
          className={cn(
            "group grid min-h-[72px] w-full grid-cols-[24px_minmax(0,1fr)_auto] items-start gap-3 rounded-[var(--mosaic-radius-control)] px-3 py-3 text-left transition-[background-color,color] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] focus-visible:outline-none",
            summary.conversation_id === activeConversationId
              ? "bg-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,var(--mosaic-color-surface))] text-[var(--mosaic-color-accent)]"
              : "text-[var(--mosaic-color-ink-muted)]",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "mt-0.5 inline-flex size-6 items-center justify-center rounded-full border text-[var(--mosaic-color-ink-muted)]",
              summary.conversation_id === activeConversationId
                ? "border-[color-mix(in_srgb,var(--mosaic-color-accent)_45%,var(--mosaic-color-line))] text-[var(--mosaic-color-accent)]"
                : "border-[var(--mosaic-color-line)]",
            )}
          >
            <ChatCircleDots size={14} weight="regular" />
          </span>
          <span className="min-w-0">
            <span className={cn(
              "block truncate text-[13px] font-semibold leading-5",
              summary.conversation_id === activeConversationId
                ? "text-[var(--mosaic-color-accent)]"
                : "text-[var(--mosaic-color-ink)]",
            )}>
              {summary.title}
            </span>
            <span className={cn(
              "mt-0.5 block truncate text-xs leading-5",
              summary.conversation_id === activeConversationId
                ? "text-[var(--mosaic-color-ink)]"
                : "text-[var(--mosaic-color-ink-muted)]",
            )}>
              {summary.preview || "还没有消息"}
            </span>
          </span>
          <time
            dateTime={summary.updated_at}
            className={cn(
              "pt-0.5 text-[11px] tabular-nums",
              summary.conversation_id === activeConversationId
                ? "text-[var(--mosaic-color-ink)]"
                : "text-[var(--mosaic-color-ink-muted)]",
            )}
          >
            {formatConversationTime(summary.updated_at)}
          </time>
        </button>
      ))}
    </div>
  );
}

function ConversationListBody({
  summaries,
  activeConversationId,
  status,
  errorMessage,
  creating,
  filterOpen,
  filterQuery,
  onSelect,
  onNew,
  onRetry,
  onBackToModels,
  onClose,
  onFilterOpenChange,
  onFilterQueryChange,
  filterInputId,
  closeControl,
}: Pick<ConversationListProps, "summaries" | "activeConversationId" | "status" | "errorMessage" | "creating" | "onSelect" | "onNew" | "onRetry" | "onBackToModels"> & {
  filterOpen: boolean;
  filterQuery: string;
  filterInputId: string;
  closeControl?: ReactNode;
  onFilterOpenChange: (open: boolean) => void;
  onFilterQueryChange: (query: string) => void;
  onClose?: (() => void) | undefined;
}) {
  const filteredSummaries = useMemo(() => {
    const normalizedQuery = filterQuery.trim().toLocaleLowerCase();
    if (!normalizedQuery) return summaries;
    return summaries.filter((summary) =>
      `${summary.title} ${summary.preview}`.toLocaleLowerCase().includes(normalizedQuery),
    );
  }, [filterQuery, summaries]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        data-testid="conversation-list-header"
        className="flex h-[var(--mosaic-layout-task-header)] min-h-[var(--mosaic-layout-task-header)] items-center gap-2 border-b border-[var(--mosaic-color-line)] px-5"
      >
        <Button
          variant="secondary"
          className="h-11 min-w-0 flex-1 justify-start gap-2 px-3"
          onClick={() => {
            onNew();
            onClose?.();
          }}
          loading={creating ?? false}
          aria-label="新建会话"
        >
          <Plus size={17} aria-hidden />
          <span>新建会话</span>
        </Button>
        <button
          type="button"
          aria-label="筛选会话"
          aria-expanded={filterOpen}
          aria-controls={filterOpen ? filterInputId : undefined}
          onClick={() => onFilterOpenChange(!filterOpen)}
          className={cn(
            "inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,border-color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)]",
            filterOpen && "border-[var(--mosaic-color-accent)] text-[var(--mosaic-color-accent)]",
          )}
        >
          <Funnel size={17} aria-hidden />
        </button>
        {closeControl}
      </div>
      {filterOpen ? (
        <div className="border-b border-[var(--mosaic-color-line)] px-3 py-3">
          <label className="sr-only" htmlFor={filterInputId}>筛选会话</label>
          <input
            id={filterInputId}
            data-testid="conversation-filter-input"
            type="search"
            value={filterQuery}
            onChange={(event) => onFilterQueryChange(event.target.value)}
            placeholder="按标题或预览筛选"
            className="min-h-11 w-full rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-3 text-sm text-[var(--mosaic-color-ink)] placeholder:text-[var(--mosaic-color-ink-muted)] focus:border-[var(--mosaic-color-accent)] focus:outline-none"
          />
        </div>
      ) : null}
      <span className="sr-only">
        {status === "ready" ? `${filteredSummaries.length} 个会话` : "最近会话"}
      </span>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {status === "loading" ? (
          <div className="grid gap-2 px-3 py-2" data-testid="conversation-list-loading">
            <Skeleton label="正在加载会话" className="h-[72px] rounded-[var(--mosaic-radius-control)]" />
            <Skeleton label="正在加载会话" className="h-[72px] rounded-[var(--mosaic-radius-control)]" />
            <Skeleton label="正在加载会话" className="h-[72px] rounded-[var(--mosaic-radius-control)]" />
          </div>
        ) : null}

        {status === "error" ? (
          <ErrorState
            title="会话暂时不可用"
            description={errorMessage ?? "无法加载最近会话。"}
            action={onRetry ? <Button variant="secondary" onClick={onRetry}>重新加载</Button> : undefined}
            className="mx-3 border-0 p-3"
          />
        ) : null}

        {status === "empty" ? (
          <EmptyState
            title="还没有会话"
            className="mx-3 border-0 px-3 py-8"
          />
        ) : null}

        {status === "ready" ? (
          filteredSummaries.length > 0 ? (
            <ConversationRows
              summaries={filteredSummaries}
              activeConversationId={activeConversationId}
              onSelect={onSelect}
              onClose={onClose}
            />
          ) : (
            <p className="px-6 py-8 text-sm text-[var(--mosaic-color-ink-muted)]">没有匹配的会话。</p>
          )
        ) : null}
      </div>

      <div className="border-t border-[var(--mosaic-color-line)] p-3">
        <button
          type="button"
          onClick={onBackToModels}
          className="flex min-h-11 w-full items-center gap-2 rounded-[var(--mosaic-radius-control)] px-3 text-sm font-medium text-[var(--mosaic-color-ink-muted)] transition-[background-color,color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)]"
        >
          <ArrowLeft size={17} aria-hidden />
          返回模型广场
        </button>
      </div>
    </div>
  );
}

export function ConversationList({
  summaries,
  activeConversationId,
  status = "ready",
  errorMessage,
  creating = false,
  trigger,
  mobileOpen,
  onMobileOpenChange,
  onSelect,
  onNew,
  onRetry,
  onBackToModels,
}: ConversationListProps) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");

  return (
    <Dialog.Root open={mobileOpen} onOpenChange={onMobileOpenChange}>
      {trigger ? <Dialog.Trigger asChild>{trigger}</Dialog.Trigger> : null}
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-[color-mix(in_srgb,var(--mosaic-color-ink)_25%,transparent)]" />
        <Dialog.Content
          data-testid="conversation-list"
          className="fixed inset-y-0 right-0 z-[60] flex w-[min(100vw,420px)] flex-col border-l border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] shadow-[-18px_0_50px_color-mix(in_srgb,var(--mosaic-color-ink)_14%,transparent)] outline-none sm:inset-y-4 sm:right-4 sm:h-[min(720px,calc(100dvh-32px))] sm:rounded-[var(--mosaic-radius-surface)] sm:border sm:shadow-[0_20px_60px_color-mix(in_srgb,var(--mosaic-color-ink)_16%,transparent)]"
          aria-describedby={undefined}
        >
          <Dialog.Title className="sr-only">会话列表</Dialog.Title>
          <ConversationListBody
            summaries={summaries}
            activeConversationId={activeConversationId}
            status={status}
            errorMessage={errorMessage}
            creating={creating}
            filterOpen={filterOpen}
            filterQuery={filterQuery}
            onSelect={onSelect}
            onNew={onNew}
            onRetry={onRetry}
            onBackToModels={onBackToModels}
            onFilterOpenChange={setFilterOpen}
            onFilterQueryChange={setFilterQuery}
            filterInputId="conversation-filter-input"
            onClose={() => onMobileOpenChange(false)}
            closeControl={
              <Dialog.Close
                type="button"
                aria-label="关闭会话列表"
                className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-[var(--mosaic-radius-control)] text-[var(--mosaic-color-ink-muted)] hover:bg-[var(--mosaic-color-surface-muted)]"
              >
                <X size={18} aria-hidden />
              </Dialog.Close>
            }
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
