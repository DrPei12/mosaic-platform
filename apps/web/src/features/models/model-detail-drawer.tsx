import * as Dialog from "@radix-ui/react-dialog";
import { ArrowRight, Check, X } from "@phosphor-icons/react";
import type { PublicProductModel } from "@mosaic/contracts";

import type { CatalogModel } from "@/services/interfaces";
import { cn } from "@/shared/ui/cn";

export interface ModelDetailDrawerProps {
  model: CatalogModel;
  onAction: (model: PublicProductModel) => void;
  actionPending?: boolean;
  actionBusy?: boolean;
}

const categoryLabels: Record<PublicProductModel["category"], string> = {
  text: "文本",
  image: "图像",
  video: "视频",
  audio: "音频",
};

const taskLabels: Record<PublicProductModel["task_type"], string> = {
  chat: "多轮对话",
  text_to_image: "文字生成图像",
  text_to_video: "文字生成视频",
  image_to_video: "图像生成视频",
  tts: "文字转语音",
};

function availabilityLabel(availability: PublicProductModel["availability"]): string | null {
  if (availability === "available") return "可用";
  if (availability === "maintenance") return "维护中";
  if (availability === "unavailable") return "暂不可用";
  return null;
}

export function ModelDetailDrawer({
  model,
  onAction,
  actionPending = false,
  actionBusy = false,
}: ModelDetailDrawerProps) {
  const product = model.item.model;
  const statusLabel = availabilityLabel(product.availability);
  const unavailable = product.availability === "maintenance" || product.availability === "unavailable";

  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          aria-label={`查看 ${product.display_name} 详情`}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-[var(--mosaic-radius-control)] px-3 text-sm font-semibold text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none"
        >
          查看详情
          <ArrowRight size={16} aria-hidden weight="regular" />
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[color-mix(in_srgb,var(--mosaic-color-ink)_20%,transparent)] backdrop-blur-[1px] motion-reduce:backdrop-blur-none" />
        <Dialog.Content
          className="fixed inset-x-0 bottom-0 z-50 max-h-[88dvh] overflow-y-auto rounded-t-[var(--mosaic-radius-surface)] border border-b-0 border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-6 shadow-[0_-18px_48px_color-mix(in_srgb,var(--mosaic-color-ink)_12%,transparent)] focus:outline-none sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[min(100vw,480px)] sm:rounded-none sm:border-b sm:border-r-0 sm:p-8 sm:shadow-[-18px_0_48px_color-mix(in_srgb,var(--mosaic-color-ink)_12%,transparent)]"
        >
          <div className="mb-10 flex items-start justify-between gap-6">
            <div>
              <p className="mb-3 text-sm font-semibold text-[var(--mosaic-color-accent)]">
                {categoryLabels[product.category]}
              </p>
              {statusLabel ? (
                <span className="mb-3 inline-flex rounded-[var(--mosaic-radius-pill)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface-muted)] px-2 py-0.5 text-xs font-medium text-[var(--mosaic-color-ink-muted)]">
                  {statusLabel}
                </span>
              ) : null}
              <Dialog.Title className="text-3xl font-semibold tracking-[-0.04em] text-[var(--mosaic-color-ink)]">
                {product.display_name}
              </Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label={`关闭 ${product.display_name} 详情`}
                className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none"
              >
                <X size={20} aria-hidden weight="regular" />
              </button>
            </Dialog.Close>
          </div>

          <Dialog.Description className="sr-only">模型详情</Dialog.Description>

          <dl className="mt-10 grid gap-0 border-y border-[var(--mosaic-color-line)]">
            <div className="grid grid-cols-[96px_1fr] gap-4 border-b border-[var(--mosaic-color-line)] py-4 last:border-b-0">
              <dt className="text-sm text-[var(--mosaic-color-ink-muted)]">适用方式</dt>
              <dd className="text-sm font-medium text-[var(--mosaic-color-ink)]">{taskLabels[product.task_type]}</dd>
            </div>
            <div className="grid grid-cols-[96px_1fr] gap-4 border-b border-[var(--mosaic-color-line)] py-4 last:border-b-0">
              <dt className="text-sm text-[var(--mosaic-color-ink-muted)]">能力范围</dt>
              <dd className="flex flex-wrap gap-x-4 gap-y-2 text-sm font-medium text-[var(--mosaic-color-ink)]">
                {product.capabilities.map((capability) => (
                  <span key={capability} className="inline-flex items-center gap-1.5">
                    <Check size={15} aria-hidden weight="bold" className="text-[var(--mosaic-color-accent)]" />
                    {capability}
                  </span>
                ))}
              </dd>
            </div>
          </dl>

          <div className="mt-10 border-t border-[var(--mosaic-color-line)] pt-6">
            {unavailable ? (
              <p className="mb-4 text-sm leading-6 text-[var(--mosaic-color-ink-muted)]">
                当前模型暂不可用。
              </p>
            ) : null}
            <button
              type="button"
              disabled={actionBusy || unavailable}
              onClick={() => onAction(product)}
              className={cn(
                "inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-accent)] px-5 text-sm font-semibold text-[var(--mosaic-color-surface)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px disabled:cursor-wait disabled:opacity-60 motion-reduce:transition-none motion-reduce:transform-none",
              )}
            >
              {actionPending ? "正在打开" : model.presentation.actionLabel}
              <ArrowRight size={18} aria-hidden weight="regular" />
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
