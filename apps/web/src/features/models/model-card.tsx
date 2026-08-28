import Image from "next/image";
import {
  ArrowRight,
  BookmarkSimple,
  ChatCircleDots,
  FilmStrip,
  ImageSquare,
  SpeakerHigh,
  Waveform,
} from "@phosphor-icons/react";
import type { PublicProductModel } from "@mosaic/contracts";

import type { CatalogModel } from "@/services/interfaces";
import { cn } from "@/shared/ui/cn";
import { ModelDetailDrawer } from "./model-detail-drawer";

export interface ModelCardProps {
  model: CatalogModel;
  actionPending?: boolean;
  actionBusy?: boolean;
  favoritePending?: boolean;
  onAction: (model: PublicProductModel) => void;
  onToggleFavorite: (model: CatalogModel) => void;
}

const categoryLabels: Record<PublicProductModel["category"], string> = {
  text: "文本",
  image: "图像",
  video: "视频",
  audio: "音频",
};

function availabilityLabel(availability: PublicProductModel["availability"]): string | null {
  if (availability === "available") return "可用";
  if (availability === "maintenance") return "维护中";
  if (availability === "unavailable") return "暂不可用";
  return null;
}

function isUnavailable(availability: PublicProductModel["availability"]): boolean {
  return availability === "maintenance" || availability === "unavailable";
}

function CategoryIcon({ category }: { category: PublicProductModel["category"] }) {
  if (category === "text") return <ChatCircleDots size={20} aria-hidden weight="regular" />;
  if (category === "image") return <ImageSquare size={20} aria-hidden weight="regular" />;
  if (category === "video") return <FilmStrip size={20} aria-hidden weight="regular" />;
  return <SpeakerHigh size={20} aria-hidden weight="regular" />;
}

function CardHeader({ model, onToggleFavorite, favoritePending }: Omit<ModelCardProps, "onAction" | "actionPending">) {
  const product = model.item.model;
  const statusLabel = availabilityLabel(product.availability);
  return (
    <div className="relative z-10 flex items-start justify-between gap-4">
      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[var(--mosaic-color-accent)]">
        <CategoryIcon category={product.category} />
        <span>{categoryLabels[product.category]}</span>
        {statusLabel ? (
          <span className="rounded-[var(--mosaic-radius-pill)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface-muted)] px-2 py-0.5 text-xs font-medium text-[var(--mosaic-color-ink-muted)]">
            {statusLabel}
          </span>
        ) : null}
      </div>
      <button
        type="button"
        aria-label={`${model.favorite ? "取消收藏" : "收藏"} ${product.display_name}`}
        aria-pressed={model.favorite}
        disabled={favoritePending}
        onClick={() => onToggleFavorite(model)}
         className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,border-color,transform] duration-[var(--mosaic-motion-fast)] hover:border-[var(--mosaic-color-accent)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px disabled:cursor-wait disabled:opacity-50 motion-reduce:transition-none motion-reduce:transform-none"
      >
        <BookmarkSimple size={20} aria-hidden weight={model.favorite ? "fill" : "regular"} />
      </button>
    </div>
  );
}

type CardActionProps = Pick<ModelCardProps, "model" | "actionPending" | "actionBusy" | "favoritePending" | "onAction"> & {
  showDetails?: boolean;
  layout?: "default" | "inline";
};

function CardActions({ model, actionPending, actionBusy = false, onAction, favoritePending, showDetails = true, layout = "default" }: CardActionProps) {
  const product = model.item.model;
  const unavailable = isUnavailable(product.availability);
  return (
    <div className={cn("relative z-10", layout === "inline" ? "flex shrink-0 flex-wrap items-center gap-2 pt-0" : "mt-auto flex flex-wrap items-center gap-2 pt-4")}>
      {product.task_type === "chat" ? (
        <button
          type="button"
          aria-label={`${model.presentation.actionLabel} ${product.display_name}`}
          disabled={actionBusy || unavailable}
          onClick={() => onAction(product)}
          className="inline-flex min-h-11 items-center gap-2 rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-accent)] px-4 text-sm font-semibold text-[var(--mosaic-color-surface)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px disabled:cursor-wait disabled:opacity-60 motion-reduce:transition-none motion-reduce:transform-none"
        >
          {actionPending ? "正在打开" : model.presentation.actionLabel}
          <ArrowRight size={17} aria-hidden weight="regular" />
        </button>
      ) : null}
      {showDetails ? (
        <ModelDetailDrawer
          model={model}
          actionPending={actionPending ?? false}
          actionBusy={actionBusy}
          onAction={onAction}
        />
      ) : null}
      <span className="sr-only">{favoritePending ? "正在保存收藏" : ""}</span>
    </div>
  );
}

function HeroMedia({ model }: { model: CatalogModel }) {
  if (model.presentation.media.kind !== "abstract") return null;
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 top-[38%] overflow-hidden bg-[var(--mosaic-color-surface-muted)] lg:inset-y-0 lg:left-auto lg:right-0 lg:top-0 lg:h-full lg:aspect-square lg:w-[48%]">
      <Image
        src={model.presentation.media.src}
        alt={model.presentation.media.alt}
        fill
        priority
        sizes="(max-width: 1023px) 100vw, 36vw"
        className="object-cover object-center transition-transform duration-[var(--mosaic-motion-normal)] ease-[var(--mosaic-motion-ease)] group-hover:scale-[1.015] motion-reduce:transition-none motion-reduce:transform-none"
      />
    </div>
  );
}

function GalleryMedia({ model }: { model: CatalogModel }) {
  if (model.presentation.media.kind !== "gallery") return null;
  return (
    <div className="grid w-full grid-cols-3 gap-3">
      {model.presentation.media.sources.map((source) => (
        <div key={source.src} className="relative aspect-square overflow-hidden rounded-[var(--mosaic-radius-media)] bg-[var(--mosaic-color-surface-muted)]">
          <Image
            src={source.src}
            alt={source.alt}
            fill
            sizes="(max-width: 767px) 30vw, 15vw"
            className="object-cover transition-transform duration-[var(--mosaic-motion-normal)] ease-[var(--mosaic-motion-ease)] group-hover:scale-[1.015] motion-reduce:transition-none motion-reduce:transform-none"
          />
        </div>
      ))}
    </div>
  );
}

function VideoMedia({ model }: { model: CatalogModel }) {
  if (model.presentation.media.kind !== "video") return null;
  return (
    <div className="relative aspect-[10/7] min-h-0 overflow-hidden bg-[var(--mosaic-color-surface-muted)] lg:absolute lg:inset-y-0 lg:right-0 lg:h-full lg:w-auto lg:aspect-[6/5] 2xl:aspect-[10/7]">
      <Image
        src={model.presentation.media.src}
        alt={model.presentation.media.alt}
        fill
        sizes="(max-width: 1023px) 100vw, 28vw"
        className="object-cover transition-transform duration-[var(--mosaic-motion-normal)] ease-[var(--mosaic-motion-ease)] group-hover:scale-[1.015] motion-reduce:transition-none motion-reduce:transform-none"
      />
      <span className="absolute inset-0 bg-[color-mix(in_srgb,var(--mosaic-color-ink)_8%,transparent)]" aria-hidden />
    </div>
  );
}

function AudioMedia({ model }: { model: CatalogModel }) {
  if (model.presentation.media.kind !== "audio") return null;
  return (
    <div className="flex min-h-[152px] items-center justify-center gap-6 border-t border-[var(--mosaic-color-line)] pt-6 sm:min-h-[164px] sm:gap-8 lg:absolute lg:right-5 lg:top-1/2 lg:h-24 lg:min-h-0 lg:w-[44%] lg:-translate-y-1/2 lg:border-t-0 lg:pt-0">
      <div className="min-w-0 flex-1">
        <div
          role="img"
          aria-label={`${model.item.model.display_name} 音频波形预览`}
          className="flex h-16 items-center gap-1.5 overflow-hidden"
        >
          {model.presentation.media.waveform.map((height, index) => (
            <span
              key={`${height}-${index}`}
              aria-hidden
              className="w-1.5 shrink-0 rounded-full bg-[var(--mosaic-color-accent)]"
              style={{ height: `${Math.max(18, Math.round(height * 58))}px`, opacity: 0.55 + height * 0.45 }}
            />
          ))}
        </div>
        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-[var(--mosaic-color-ink-muted)]">
          <span className="inline-flex items-center gap-1.5"><Waveform size={15} aria-hidden />音频示例</span>
          <span>{model.presentation.media.durationLabel}</span>
        </div>
      </div>
    </div>
  );
}

function CompactMark({ model }: { model: CatalogModel }) {
  const palette = model.item.model.product_model_id.length % 3;
  const classes = [
    "bg-[var(--mosaic-color-surface-muted)] text-[var(--mosaic-color-accent)]",
    "bg-[color-mix(in_srgb,var(--mosaic-color-accent)_8%,var(--mosaic-color-surface))] text-[var(--mosaic-color-accent)]",
    "bg-[color-mix(in_srgb,var(--mosaic-color-accent)_12%,var(--mosaic-color-surface))] text-[var(--mosaic-color-accent)]",
  ];
  return (
    <div className={cn("inline-flex min-h-12 min-w-12 items-center justify-center rounded-[var(--mosaic-radius-media)]", classes[palette])}>
      <CategoryIcon category={model.item.model.category} />
    </div>
  );
}

export function ModelCard({
  model,
  actionPending = false,
  actionBusy = false,
  favoritePending = false,
  onAction,
  onToggleFavorite,
}: ModelCardProps) {
  const product = model.item.model;
  const style = model.presentation.cardStyle;

  if (style === "hero") {
    return (
      <article data-testid={`model-card-${product.product_model_id}`} className="group relative flex min-h-[360px] flex-col overflow-hidden rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] transition-[border-color,transform] duration-[var(--mosaic-motion-normal)] hover:border-[var(--mosaic-color-accent)] hover:-translate-y-px motion-reduce:transition-none motion-reduce:transform-none lg:h-[326px] lg:min-h-0">
          <div className="relative z-10 flex min-h-[360px] min-w-0 flex-1 flex-col bg-[color-mix(in_srgb,var(--mosaic-color-surface)_90%,transparent)] p-4 lg:h-[326px] lg:min-h-0 lg:w-[56%] lg:p-5">
            <CardHeader model={model} onToggleFavorite={onToggleFavorite} favoritePending={favoritePending} />
            <div className="relative z-10 mt-5">
              <h2 className="text-[length:var(--mosaic-typography-h3-font-size)] font-semibold leading-[var(--mosaic-typography-h3-line-height)] tracking-[-0.03em] text-[var(--mosaic-color-ink)]">{product.display_name}</h2>
            </div>
            <div className="mt-5 hidden gap-x-6 gap-y-2 text-sm text-[var(--mosaic-color-ink-muted)] sm:grid sm:grid-cols-2">
              {product.capabilities.map((capability) => <span key={capability}>{capability}</span>)}
            </div>
            <CardActions model={model} actionPending={actionPending} actionBusy={actionBusy} favoritePending={favoritePending} onAction={onAction} showDetails={false} />
          </div>
          <HeroMedia model={model} />
      </article>
    );
  }

  if (style === "gallery") {
    return (
      <article data-testid={`model-card-${product.product_model_id}`} className="group flex min-h-[352px] flex-col overflow-hidden rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-4 transition-[border-color,transform] duration-[var(--mosaic-motion-normal)] hover:border-[var(--mosaic-color-accent)] hover:-translate-y-px motion-reduce:transition-none motion-reduce:transform-none lg:h-[326px] lg:min-h-0 lg:p-5">
        <CardHeader model={model} onToggleFavorite={onToggleFavorite} favoritePending={favoritePending} />
        <div className="relative z-10 mt-5">
          <h2 className="text-[length:var(--mosaic-typography-h3-font-size)] font-semibold leading-[var(--mosaic-typography-h3-line-height)] tracking-[-0.03em] text-[var(--mosaic-color-ink)]">{product.display_name}</h2>
        </div>
        <div data-testid="model-gallery-row" className="mt-auto flex flex-col gap-3 lg:flex-row lg:items-end lg:gap-5">
          <div className="min-w-0 flex-1">
            <GalleryMedia model={model} />
          </div>
          <CardActions model={model} actionPending={actionPending} actionBusy={actionBusy} favoritePending={favoritePending} onAction={onAction} layout="inline" />
        </div>
      </article>
    );
  }

  if (style === "video") {
    return (
      <article data-testid={`model-card-${product.product_model_id}`} className="group relative flex min-h-[280px] flex-col overflow-hidden rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-4 transition-[border-color,transform] duration-[var(--mosaic-motion-normal)] hover:border-[var(--mosaic-color-accent)] hover:-translate-y-px motion-reduce:transition-none motion-reduce:transform-none lg:h-[280px] lg:min-h-0 lg:pr-[52%] lg:p-5">
        <div className="relative z-10 lg:absolute lg:inset-x-5 lg:top-5">
          <CardHeader model={model} onToggleFavorite={onToggleFavorite} favoritePending={favoritePending} />
        </div>
        <div className="relative z-10 mt-5 lg:mt-16">
          <h2 className="text-[length:var(--mosaic-typography-h3-font-size)] font-semibold leading-[var(--mosaic-typography-h3-line-height)] tracking-[-0.03em] text-[var(--mosaic-color-ink)]">{product.display_name}</h2>
        </div>
        <div className="relative z-10 mt-4 grid gap-2 text-sm text-[var(--mosaic-color-ink-muted)]">
          {product.capabilities.map((capability) => <span key={capability}>{capability}</span>)}
        </div>
        <CardActions model={model} actionPending={actionPending} actionBusy={actionBusy} favoritePending={favoritePending} onAction={onAction} />
        <VideoMedia model={model} />
      </article>
    );
  }

  if (style === "audio") {
    return (
      <article data-testid={`model-card-${product.product_model_id}`} className="group relative flex min-h-[280px] flex-col overflow-hidden rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-4 transition-[border-color,transform] duration-[var(--mosaic-motion-normal)] hover:border-[var(--mosaic-color-accent)] hover:-translate-y-px motion-reduce:transition-none motion-reduce:transform-none lg:h-[280px] lg:min-h-0 lg:p-5">
        <CardHeader model={model} onToggleFavorite={onToggleFavorite} favoritePending={favoritePending} />
        <div className="relative z-10 mt-5">
          <h2 className="text-[length:var(--mosaic-typography-h3-font-size)] font-semibold leading-[var(--mosaic-typography-h3-line-height)] tracking-[-0.03em] text-[var(--mosaic-color-ink)]">{product.display_name}</h2>
        </div>
        <div className="mt-auto"><AudioMedia model={model} /></div>
        <CardActions model={model} actionPending={actionPending} actionBusy={actionBusy} favoritePending={favoritePending} onAction={onAction} />
      </article>
    );
  }

  return (
    <article data-testid={`model-card-${product.product_model_id}`} className="group flex min-h-[250px] flex-col overflow-hidden rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-4 transition-[border-color,transform] duration-[var(--mosaic-motion-normal)] hover:border-[var(--mosaic-color-accent)] hover:-translate-y-px motion-reduce:transition-none motion-reduce:transform-none lg:p-5">
      <CardHeader model={model} onToggleFavorite={onToggleFavorite} favoritePending={favoritePending} />
      <div className="relative z-10 mt-5 flex items-start gap-4">
        <CompactMark model={model} />
        <div className="min-w-0">
          <h2 className="text-[length:var(--mosaic-typography-h3-font-size)] font-semibold leading-[var(--mosaic-typography-h3-line-height)] tracking-[-0.03em] text-[var(--mosaic-color-ink)]">{product.display_name}</h2>
        </div>
      </div>
      <div className="relative z-10 mt-6 flex flex-wrap gap-x-4 gap-y-2 text-sm text-[var(--mosaic-color-ink-muted)]">
        {product.capabilities.map((capability) => <span key={capability}>{capability}</span>)}
      </div>
      <CardActions model={model} actionPending={actionPending} actionBusy={actionBusy} favoritePending={favoritePending} onAction={onAction} />
    </article>
  );
}
