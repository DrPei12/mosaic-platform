"use client";

import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  ClockCounterClockwise,
  ImageSquare,
  Info,
  MagicWand,
  SpeakerHigh,
  VideoCamera,
  WarningCircle,
  Waveform,
} from "@phosphor-icons/react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import type {
  CatalogModel,
  GenerationInput,
  GenerationJob,
  GenerationModality,
} from "@/services/interfaces";
import { cn } from "@/shared/ui/cn";
import { StatusBadge } from "@/shared/ui/status-badge";
import {
  formatGenerationDate,
  generationStatusLabels,
  generationTone,
  readableGenerationError,
  readableModelError,
} from "./generation-copy";

/**
 * This component intentionally keeps the generation contract local. The API
 * adapter owns the canonical service type; keeping this structural view here
 * lets the workspace remain presentationally isolated while the adapter is
 * unavailable in demo builds.
 */
export type StudioModality = Exclude<GenerationModality, "text">;

export interface GenerationStudioProps {
  modelId: string;
  modality: StudioModality;
}

type ModelStatus = "loading" | "ready" | "error";

const inspirationImages = [
  { src: "/media/models/qwen-image-alpine.png", alt: "山谷与湖泊的风景灵感图" },
  { src: "/media/models/qwen-image-chair.png", alt: "阳光房间中的椅子灵感图" },
  { src: "/media/models/qwen-image-studio-illustration.png", alt: "工作室场景灵感图" },
  { src: "/media/models/qwen-3-5-folded-paper.png", alt: "折纸构成的抽象灵感图" },
] as const;

const videoInspirationImages = [
  { src: "/media/models/hunyuan-video-coastal-car.png", alt: "海岸公路汽车镜头灵感图" },
  { src: "/media/models/qwen-image-alpine.png", alt: "山谷湖泊镜头灵感图" },
  { src: "/media/models/qwen-image-chair.png", alt: "室内静物镜头灵感图" },
  { src: "/media/models/qwen-image-studio-illustration.png", alt: "工作室镜头灵感图" },
] as const;

const modalityLabel: Record<StudioModality, string> = {
  image: "图片",
  video: "视频",
  audio: "语音",
};

const modalityIcon: Record<StudioModality, typeof ImageSquare> = {
  image: ImageSquare,
  video: VideoCamera,
  audio: SpeakerHigh,
};

let requestSequence = 0;

function newClientRequestId(modelId: string): string {
  requestSequence += 1;
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `generation-${modelId}-${Date.now()}-${requestSequence}`;
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error &&
    (error as { name?: unknown }).name === "AbortError";
}

function taskMatches(model: CatalogModel, modality: StudioModality): boolean {
  const taskType = model.item.model.task_type;
  if (modality === "image") return taskType === "text_to_image";
  if (modality === "video") return taskType === "text_to_video" || taskType === "image_to_video";
  return taskType === "tts";
}

function fieldClassName(): string {
  return "min-h-11 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-3 text-[var(--mosaic-color-ink)] outline-none transition-[border-color,box-shadow] duration-[var(--mosaic-motion-fast)] focus:border-[var(--mosaic-color-accent)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--mosaic-color-accent)_12%,transparent)] disabled:cursor-not-allowed disabled:bg-[var(--mosaic-color-surface-muted)] disabled:text-[var(--mosaic-color-ink-muted)] motion-reduce:transition-none";
}

function textAreaClassName(): string {
  return "min-h-40 w-full resize-y rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-4 py-3 text-base leading-7 text-[var(--mosaic-color-ink)] outline-none transition-[border-color,box-shadow] duration-[var(--mosaic-motion-fast)] placeholder:text-[var(--mosaic-color-ink-muted)] focus:border-[var(--mosaic-color-accent)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--mosaic-color-accent)_12%,transparent)] disabled:cursor-not-allowed disabled:bg-[var(--mosaic-color-surface-muted)] motion-reduce:transition-none";
}

function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-[22px] font-semibold leading-7 tracking-[-0.03em] text-[var(--mosaic-color-ink)]">
        {children}
      </h2>
      {action}
    </div>
  );
}

function InspirationStrip({ modality }: { modality: "image" | "video" }) {
  const images = modality === "image" ? inspirationImages : videoInspirationImages;
  return (
    <section aria-labelledby={`${modality}-inspiration-title`} className="grid gap-4">
      <SectionTitle
        action={
          <Link
            href="/generations"
            className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-[var(--mosaic-color-accent)] transition-[color,transform] duration-[var(--mosaic-motion-fast)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none"
          >
            最近生成
            <ArrowUpRight size={16} aria-hidden weight="regular" />
          </Link>
        }
      >
        <span id={`${modality}-inspiration-title`}>灵感示例</span>
      </SectionTitle>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {images.map((image) => (
          <figure key={image.src} className="group grid gap-2">
            <div className="relative aspect-[4/3] overflow-hidden rounded-[var(--mosaic-radius-media)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface-muted)]">
              <Image
                src={image.src}
                alt={image.alt}
                fill
                sizes="(max-width: 768px) 50vw, (max-width: 1024px) 25vw, 280px"
                className="object-cover transition-transform duration-[var(--mosaic-motion-normal)] group-hover:scale-[1.02] motion-reduce:transition-none"
              />
            </div>
            <figcaption className="text-xs leading-5 text-[var(--mosaic-color-ink-muted)]">灵感示例</figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}

function WorkspaceNotice() {
  return (
    <p
      role="note"
      className="flex min-h-10 items-center gap-2 border-b border-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,var(--mosaic-color-line))] bg-[color-mix(in_srgb,var(--mosaic-color-accent)_7%,var(--mosaic-color-surface))] px-4 py-2 text-sm leading-5 text-[var(--mosaic-color-ink-muted)] md:px-6"
    >
      <Info size={17} aria-hidden weight="fill" className="shrink-0 text-[var(--mosaic-color-accent)]" />
      生成任务将消耗账户额度。
    </p>
  );
}

function RecentAudioJobs({ jobs }: { jobs: readonly GenerationJob[] }) {
  if (jobs.length === 0) {
    return (
      <p className="border-t border-[var(--mosaic-color-line)] pt-4 text-sm leading-6 text-[var(--mosaic-color-ink-muted)]">
        暂无音频任务。提交后可在
        <Link href="/generations" className="ml-1 font-semibold text-[var(--mosaic-color-accent)] hover:text-[var(--mosaic-color-ink)]">生成记录</Link>。
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)]">
      <div className="grid gap-2 border-b border-[var(--mosaic-color-line)] px-4 py-3 text-xs font-semibold text-[var(--mosaic-color-ink-muted)] sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
        <span>最近任务</span>
        <span>状态</span>
        <span>创建时间</span>
      </div>
      {jobs.map((job) => (
        <div key={job.job_id} className="grid gap-3 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
          <Link href={`/generations/${encodeURIComponent(job.job_id)}`} className="min-w-0 truncate text-sm font-semibold text-[var(--mosaic-color-ink)] hover:text-[var(--mosaic-color-accent)]">
            任务 {job.job_id}
          </Link>
          <StatusBadge tone={generationTone(job.status)}>
            {generationStatusLabels[job.status]}
          </StatusBadge>
          <time dateTime={job.created_at} className="text-sm text-[var(--mosaic-color-ink-muted)]">{formatGenerationDate(job.created_at)}</time>
        </div>
      ))}
    </div>
  );
}

export function GenerationStudio({ modelId, modality }: GenerationStudioProps) {
  const router = useRouter();
  const registry = useMemo(() => createBrowserServiceRegistry(), []);
  const mountedRef = useRef(true);
  const requestRef = useRef<AbortController | null>(null);
  const [model, setModel] = useState<CatalogModel | null>(null);
  const [modelStatus, setModelStatus] = useState<ModelStatus>("loading");
  const [modelError, setModelError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState("1024*1024");
  const [count, setCount] = useState("1");
  const [resolution, setResolution] = useState<"720P" | "1080P">("720P");
  const [ratio, setRatio] = useState<"1:1" | "16:9" | "9:16" | "4:3" | "3:4">("16:9");
  const [durationSeconds, setDurationSeconds] = useState("2");
  const [languageType, setLanguageType] = useState("Chinese");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [recentAudioJobs, setRecentAudioJobs] = useState<readonly GenerationJob[]>([]);

  /* eslint-disable react-hooks/set-state-in-effect -- model and recent jobs are external API state. */
  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    setModelStatus("loading");
    setModelError("");
    void registry.modelCatalog.get(modelId, controller.signal)
      .then((nextModel) => {
        if (!mountedRef.current || controller.signal.aborted) return;
        setModel(nextModel);
        setModelStatus("ready");
      })
      .catch((caughtError: unknown) => {
        if (!mountedRef.current || controller.signal.aborted || isAbortError(caughtError)) return;
        setModelError(readableModelError(caughtError));
        setModelStatus("error");
      });

    return () => {
      mountedRef.current = false;
      controller.abort();
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, [modelId, registry]);

  useEffect(() => {
    if (modality !== "audio" || !registry.generation?.list) {
      setRecentAudioJobs([]);
      return;
    }
    const controller = new AbortController();
    void registry.generation.list(controller.signal)
      .then((jobs) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        setRecentAudioJobs(
          jobs
            .filter(
              (job) =>
                job.modality === "audio" &&
                job.product_model_id === modelId,
            )
            .slice(0, 3),
        );
      })
      .catch((caughtError: unknown) => {
        if (controller.signal.aborted || !mountedRef.current || isAbortError(caughtError)) return;
        // Listing is an optional enhancement. Failure must not create a fake
        // row or prevent a user from submitting a new, real task.
        setRecentAudioJobs([]);
      });
    return () => controller.abort();
  }, [modelId, modality, registry]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const submit = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !model ||
      !registry.generation ||
      submitting ||
      model.item.model.availability !== "available"
    ) return;
    const content = prompt.trim();
    if (!content) {
      setError(modality === "audio" ? "请输入要合成的文本。" : "请输入提示词。");
      return;
    }

    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    setSubmitting(true);
    setError("");

    const input: GenerationInput = modality === "audio"
      ? { text: content, language_type: languageType }
      : modality === "image"
        ? { prompt: content, size, count: Number(count) }
        : { prompt: content, resolution, ratio, duration_seconds: Number(durationSeconds) };

    try {
      const job = await registry.generation.create({
        productModelId: model.item.model.product_model_id,
        modality,
        input,
        clientRequestId: newClientRequestId(model.item.model.product_model_id),
      }, controller.signal);
      if (!mountedRef.current || controller.signal.aborted) return;
      router.push(`/generations/${encodeURIComponent(job.job_id)}`);
    } catch (caughtError: unknown) {
      if (!mountedRef.current || controller.signal.aborted || isAbortError(caughtError)) return;
      setError(readableGenerationError(caughtError));
    } finally {
      if (mountedRef.current && requestRef.current === controller) {
        requestRef.current = null;
        setSubmitting(false);
      }
    }
  }, [count, durationSeconds, languageType, modality, model, prompt, ratio, registry, resolution, router, size, submitting]);

  if (modelStatus === "loading") {
    return (
      <section className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-5 px-4 py-8 md:px-6" data-testid="generation-studio-loading">
        <div className="h-8 w-56 animate-pulse rounded bg-[var(--mosaic-color-surface-muted)] motion-reduce:animate-none" aria-label="正在加载模型" />
        <div className="h-72 animate-pulse rounded-[var(--mosaic-radius-surface)] bg-[var(--mosaic-color-surface-muted)] motion-reduce:animate-none" aria-label="正在加载工作台" />
      </section>
    );
  }

  if (modelStatus === "error" || model === null) {
    return (
      <section className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-4 px-4 py-12 md:px-6" role="alert" data-testid="generation-studio-error">
        <h1 className="text-[30px] font-semibold leading-[38px] tracking-[-0.04em] text-[var(--mosaic-color-ink)]">无法打开工作台</h1>
        <p className="text-base leading-6 text-[var(--mosaic-color-ink-muted)]">{modelError || "模型不存在或暂时不可用。"}</p>
        <button type="button" onClick={() => router.push("/models")} className="inline-flex min-h-11 w-fit items-center gap-2 rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-accent)] px-4 text-sm font-semibold text-[var(--mosaic-color-surface)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none">
          <ArrowLeft size={17} aria-hidden />返回模型广场
        </button>
      </section>
    );
  }

  const product = model.item.model;
  const compatible = taskMatches(model, modality);
  const available = product.availability === "available";
  const serviceUnavailable = !registry.generation;
  const formDisabled = !compatible || !available || serviceUnavailable || submitting;
  const Icon = modalityIcon[modality];
  const headingSuffix = modality === "image" ? "创作" : modality === "video" ? "创作视频" : "生成自然语音";

  return (
    <section className="grid min-h-[calc(100dvh-var(--mosaic-layout-top-bar-mobile))] w-full content-start bg-[var(--mosaic-color-surface)] md:min-h-[calc(100dvh-var(--mosaic-layout-top-bar-desktop))]" data-testid={`generation-studio-${modality}`}>
      <header className="border-b border-[var(--mosaic-color-line)] px-4 md:px-6">
        <div className="flex min-h-[var(--mosaic-layout-task-header)] flex-wrap items-center justify-between gap-3">
          <div className="flex min-h-11 items-center gap-4">
            <button type="button" onClick={() => router.push("/models")} aria-label="返回模型广场" className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--mosaic-radius-control)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none">
              <ArrowLeft size={18} aria-hidden />
            </button>
            <div className="flex items-center gap-2 text-sm font-semibold text-[var(--mosaic-color-ink)]">
              <Icon size={18} aria-hidden weight="regular" className="text-[var(--mosaic-color-accent)]" />
              {modalityLabel[modality]}模型
            </div>
            <span className="hidden h-5 w-px bg-[var(--mosaic-color-line)] sm:block" aria-hidden />
            <span className="hidden text-sm text-[var(--mosaic-color-ink-muted)] sm:inline">{product.display_name}</span>
          </div>
          <nav aria-label="工作台导航" className="flex items-center gap-1 text-sm">
            <span className="inline-flex min-h-11 items-center border-b-2 border-[var(--mosaic-color-accent)] px-3 font-semibold text-[var(--mosaic-color-accent)]">{modalityLabel[modality]}生成</span>
            <Link href="/generations" className="inline-flex min-h-11 items-center gap-1 px-3 text-[var(--mosaic-color-ink-muted)] transition-[color,transform] duration-[var(--mosaic-motion-fast)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none">
              生成记录
              <ClockCounterClockwise size={16} aria-hidden weight="regular" />
            </Link>
          </nav>
        </div>
      </header>

      <WorkspaceNotice />

      <div className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-8 px-4 pb-12 pt-10 md:px-6">

      <div className="grid gap-3 text-center">
        <h1 className="text-[30px] font-semibold leading-[38px] tracking-[-0.045em] text-[var(--mosaic-color-ink)] sm:text-[40px] sm:leading-[48px]">
          使用 <span className="text-[var(--mosaic-color-accent)]">{product.display_name}</span> {headingSuffix}
        </h1>
        <p className="text-base leading-6 text-[var(--mosaic-color-ink-muted)]">
          {modality === "image" ? "描述你想生成的画面。" : modality === "video" ? "描述视频内容、画面和镜头。" : "输入文本并选择音色。"}
        </p>
      </div>

      {!compatible ? (
        <section role="alert" className="grid gap-2 rounded-[var(--mosaic-radius-surface)] border border-[color-mix(in_srgb,var(--mosaic-color-danger)_32%,var(--mosaic-color-line))] bg-[color-mix(in_srgb,var(--mosaic-color-danger)_5%,var(--mosaic-color-surface))] p-5 text-left">
          <p className="flex items-center gap-2 font-semibold text-[var(--mosaic-color-ink)]"><WarningCircle size={18} aria-hidden className="text-[var(--mosaic-color-danger)]" />模型与工作台类型不匹配</p>
          <p className="text-sm leading-6 text-[var(--mosaic-color-ink-muted)]">模型目录返回的任务类型与当前工作台不一致，请返回模型广场重新选择。</p>
        </section>
      ) : null}

      {compatible && !available ? (
        <section role="status" className="grid gap-2 rounded-[var(--mosaic-radius-surface)] border border-[color-mix(in_srgb,var(--mosaic-color-warning)_35%,var(--mosaic-color-line))] bg-[color-mix(in_srgb,var(--mosaic-color-warning)_8%,var(--mosaic-color-surface))] p-5 text-left">
          <p className="flex items-center gap-2 font-semibold text-[var(--mosaic-color-ink)]"><WarningCircle size={18} aria-hidden className="text-[var(--mosaic-color-warning)]" />当前能力暂不可提交</p>
          <p className="text-sm leading-6 text-[var(--mosaic-color-ink-muted)]">当前模型暂不可用，请选择其他模型。</p>
        </section>
      ) : null}

      {compatible && available ? (
        <form
          onSubmit={submit}
          className={cn(
            "mx-auto grid w-full gap-4 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-4 sm:p-5",
            modality === "audio"
              ? "max-w-[var(--mosaic-layout-content)]"
              : "max-w-[var(--mosaic-layout-task-interaction)]",
            modality === "video" &&
              "border-[color-mix(in_srgb,var(--mosaic-color-accent)_48%,var(--mosaic-color-line))] shadow-[0_10px_28px_color-mix(in_srgb,var(--mosaic-color-accent)_8%,transparent)]",
          )}
        >
          {modality === "image" ? (
            <>
              <div className="grid gap-3">
                <label htmlFor="generation-prompt-image" className="sr-only">提示词</label>
                <textarea id="generation-prompt-image" value={prompt} onChange={(event) => setPrompt(event.target.value)} disabled={formDisabled} maxLength={2000} className={textAreaClassName()} placeholder="描述你想生成的图像..." required />
                <div className="flex items-center justify-end text-xs text-[var(--mosaic-color-ink-muted)]">{prompt.length}/2000</div>
              </div>
              <div className="flex flex-wrap items-end justify-between gap-3 border-t border-[var(--mosaic-color-line)] pt-4">
                <div className="flex flex-wrap gap-3">
                  <label className="grid min-w-[144px] gap-1.5 text-xs font-semibold text-[var(--mosaic-color-ink-muted)]">尺寸<select aria-label="尺寸" value={size} onChange={(event) => setSize(event.target.value)} disabled={formDisabled} className={fieldClassName()}><option value="1024*1024">1024 × 1024</option><option value="512*512">512 × 512</option><option value="1280*720">1280 × 720</option></select></label>
                  <label className="grid min-w-[104px] gap-1.5 text-xs font-semibold text-[var(--mosaic-color-ink-muted)]">数量<select aria-label="数量" value={count} onChange={(event) => setCount(event.target.value)} disabled={formDisabled} className={fieldClassName()}><option value="1">1 张</option><option value="2">2 张</option><option value="4">4 张</option><option value="6">6 张</option></select></label>
                </div>
                <button type="submit" disabled={formDisabled} aria-label="提交生成任务" className="inline-flex min-h-11 items-center gap-2 rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-accent)] px-5 text-sm font-semibold text-[var(--mosaic-color-surface)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none motion-reduce:transform-none"><MagicWand size={17} aria-hidden weight="fill" />{submitting ? "提交中" : "生成"}</button>
              </div>
            </>
          ) : null}

          {modality === "video" ? (
            <>
              <div className="grid gap-2">
                <label htmlFor="generation-prompt-video" className="sr-only">提示词</label>
                <textarea id="generation-prompt-video" value={prompt} onChange={(event) => setPrompt(event.target.value)} disabled={formDisabled} maxLength={2000} className="min-h-[164px] w-full resize-y rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-4 py-3 text-base leading-7 text-[var(--mosaic-color-ink)] outline-none transition-[border-color,box-shadow] duration-[var(--mosaic-motion-fast)] placeholder:text-[var(--mosaic-color-ink-muted)] focus:border-[var(--mosaic-color-accent)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--mosaic-color-accent)_12%,transparent)] disabled:cursor-not-allowed disabled:bg-[var(--mosaic-color-surface-muted)] motion-reduce:transition-none" placeholder="描述你想生成的视频内容、画面、风格、镜头等" required />
                <div className="flex justify-end text-xs text-[var(--mosaic-color-ink-muted)]">{prompt.length}/2000</div>
              </div>
              <div className="flex flex-wrap items-end justify-between gap-3 border-t border-[var(--mosaic-color-line)] pt-4">
                <div className="flex flex-wrap gap-3">
                  <label className="grid min-w-[112px] gap-1.5 text-xs font-semibold text-[var(--mosaic-color-ink-muted)]">清晰度<select aria-label="清晰度" value={resolution} onChange={(event) => setResolution(event.target.value as "720P" | "1080P")} disabled={formDisabled} className={fieldClassName()}><option value="720P">720P</option><option value="1080P">1080P</option></select></label>
                  <label className="grid min-w-[112px] gap-1.5 text-xs font-semibold text-[var(--mosaic-color-ink-muted)]">画面比例<select aria-label="画面比例" value={ratio} onChange={(event) => setRatio(event.target.value as typeof ratio)} disabled={formDisabled} className={fieldClassName()}><option value="16:9">16:9</option><option value="9:16">9:16</option><option value="1:1">1:1</option><option value="4:3">4:3</option><option value="3:4">3:4</option></select></label>
                  <label className="grid min-w-[112px] gap-1.5 text-xs font-semibold text-[var(--mosaic-color-ink-muted)]">时长<select aria-label="时长" value={durationSeconds} onChange={(event) => setDurationSeconds(event.target.value)} disabled={formDisabled} className={fieldClassName()}><option value="2">2 秒</option><option value="5">5 秒</option><option value="10">10 秒</option><option value="15">15 秒</option></select></label>
                </div>
                <button type="submit" disabled={formDisabled} aria-label="提交生成任务" className="inline-flex min-h-11 items-center gap-2 rounded-[var(--mosaic-radius-pill)] bg-[var(--mosaic-color-accent)] px-5 text-sm font-semibold text-[var(--mosaic-color-surface)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none motion-reduce:transform-none"><MagicWand size={17} aria-hidden weight="fill" />{submitting ? "提交中" : "生成视频"}</button>
              </div>
            </>
          ) : null}

          {modality === "audio" ? (
            <>
              <div className="grid gap-4 md:grid-cols-[minmax(0,1.25fr)_minmax(280px,0.75fr)]">
                <section className="grid gap-3 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] p-4" aria-labelledby="audio-text-title">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-sm font-semibold text-[var(--mosaic-color-ink)]"><SpeakerHigh size={18} aria-hidden weight="regular" className="text-[var(--mosaic-color-accent)]" />输入文本</div>
                    <span id="audio-text-title" className="sr-only">输入要合成的文本</span>
                    <button type="button" onClick={() => setPrompt("")} disabled={formDisabled || prompt.length === 0} className="inline-flex min-h-11 items-center gap-1.5 text-sm text-[var(--mosaic-color-ink-muted)] transition-[color,transform] duration-[var(--mosaic-motion-fast)] hover:text-[var(--mosaic-color-ink)] disabled:cursor-not-allowed disabled:opacity-50 active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none">清空</button>
                  </div>
                  <label htmlFor="generation-prompt-audio" className="sr-only">要合成的文本</label>
                  <textarea id="generation-prompt-audio" value={prompt} onChange={(event) => setPrompt(event.target.value)} disabled={formDisabled} maxLength={8000} className="min-h-[240px] w-full resize-y rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-4 py-3 text-base leading-7 text-[var(--mosaic-color-ink)] outline-none transition-[border-color,box-shadow] duration-[var(--mosaic-motion-fast)] placeholder:text-[var(--mosaic-color-ink-muted)] focus:border-[var(--mosaic-color-accent)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--mosaic-color-accent)_12%,transparent)] disabled:cursor-not-allowed disabled:bg-[var(--mosaic-color-surface-muted)] motion-reduce:transition-none" placeholder="输入要转换成语音的文本..." required />
                  <div className="flex items-center justify-between gap-3 text-xs text-[var(--mosaic-color-ink-muted)]"><span>支持中文、英文及部分标点</span><span>{prompt.length}/8000</span></div>
                </section>
                <section className="grid content-start gap-4 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] p-4" aria-labelledby="audio-voice-title">
                  <div className="flex items-center gap-2 text-sm font-semibold text-[var(--mosaic-color-ink)]"><span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,var(--mosaic-color-surface))] text-xs font-bold text-[var(--mosaic-color-accent)]">2</span><span id="audio-voice-title">选择音色</span></div>
                  <label className="grid gap-1.5 text-sm font-semibold text-[var(--mosaic-color-ink)]">语言<select aria-label="语言" value={languageType} onChange={(event) => setLanguageType(event.target.value)} disabled={formDisabled} className={fieldClassName()}><option value="Chinese">Chinese</option></select></label>
                  <div className="grid gap-1.5 text-sm font-semibold text-[var(--mosaic-color-ink)]">
                    <span>当前音色</span>
                    <div className="flex min-h-11 items-center rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface-muted)] px-3 font-normal">
                      {modelId === "qwen3-tts-voice-design"
                        ? "平台设计音色"
                        : modelId === "qwen3-tts-custom-voice"
                          ? "租户自定义音色"
                          : "Cherry · 自然女声"}
                    </div>
                  </div>
                </section>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-4 border-t border-[var(--mosaic-color-line)] pt-4">
                <button type="submit" disabled={formDisabled} aria-label="提交生成任务" className="inline-flex min-h-11 items-center gap-2 rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-accent)] px-5 text-sm font-semibold text-[var(--mosaic-color-surface)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none motion-reduce:transform-none"><Waveform size={17} aria-hidden weight="bold" />{submitting ? "提交中" : "生成语音"}</button>
              </div>
            </>
          ) : null}

          {serviceUnavailable ? <p role="status" className="flex items-start gap-2 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface-muted)] px-3 py-2 text-sm leading-6 text-[var(--mosaic-color-ink-muted)]"><Info size={17} aria-hidden className="mt-1 shrink-0" />生成服务暂不可用。</p> : null}
          {error ? <p role="alert" className="flex items-start gap-2 rounded-[var(--mosaic-radius-control)] border border-[color-mix(in_srgb,var(--mosaic-color-danger)_32%,var(--mosaic-color-line))] bg-[color-mix(in_srgb,var(--mosaic-color-danger)_6%,var(--mosaic-color-surface))] px-3 py-2 text-sm leading-6 text-[var(--mosaic-color-danger)]"><WarningCircle size={17} aria-hidden className="mt-1 shrink-0" />{error}</p> : null}
        </form>
      ) : null}

      {modality === "audio" ? (
        <section aria-labelledby="audio-recent-title" className="grid gap-4">
          <SectionTitle action={<Link href="/generations" className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-[var(--mosaic-color-accent)] hover:text-[var(--mosaic-color-ink)]">查看全部 <ArrowRight size={16} aria-hidden /></Link>}>
            <span id="audio-recent-title">最近生成</span>
          </SectionTitle>
          <RecentAudioJobs jobs={recentAudioJobs} />
        </section>
      ) : (
        <InspirationStrip modality={modality} />
      )}
      </div>
    </section>
  );
}
