"use client";

import {
  ArrowLeft,
  ArrowsClockwise,
  CheckCircle,
  CircleNotch,
  DownloadSimple,
  Trash,
  XCircle,
} from "@phosphor-icons/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import type { GenerationJob } from "@/services/interfaces";
import { Button } from "@/shared/ui/button";
import { ErrorState, Skeleton } from "@/shared/ui/feedback-state";
import { StatusBadge } from "@/shared/ui/status-badge";
import {
  formatArtifactSize,
  formatGenerationDate,
  generationModalityLabels,
  generationStatusLabels,
  generationTone,
  isTerminalGenerationStatus,
  readableGenerationErrorCode,
  readableGenerationError,
  shouldAutoPollGenerationStatus,
} from "./generation-copy";

export interface GenerationJobViewProps {
  jobId: string;
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error &&
    (error as { name?: unknown }).name === "AbortError";
}

function artifactKindLabel(kind: GenerationJob["artifacts"][number]["kind"]): string {
  if (kind === "output") return "输出结果";
  if (kind === "thumbnail") return "缩略图";
  if (kind === "preview") return "预览文件";
  return "输入文件";
}

function artifactStatusLabel(status: GenerationJob["artifacts"][number]["status"]): string {
  if (status === "ready") return "已就绪";
  if (status === "pending") return "处理中";
  if (status === "expired") return "已过期";
  return "已删除";
}

function artifactUrl(jobId: string, artifactId: string): string {
  return `/api/v1/generations/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactId)}`;
}

export function GenerationJobView({ jobId }: GenerationJobViewProps) {
  const router = useRouter();
  const registry = useMemo(() => createBrowserServiceRegistry(), []);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionPending, setActionPending] = useState<"cancel" | "delete" | null>(null);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async (signal: AbortSignal) => {
    if (!registry.generation) {
      throw new Error("生成服务暂不可用。");
    }
    return registry.generation.get(jobId, signal);
  }, [jobId, registry]);

  /* eslint-disable react-hooks/set-state-in-effect -- task status is synchronized with the external API. */
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    setStatus("loading");
    setError("");

    const fetchJob = async () => {
      try {
        const nextJob = await load(controller.signal);
        if (!active || controller.signal.aborted) return;
        setJob(nextJob);
        setStatus("ready");
        if (shouldAutoPollGenerationStatus(nextJob.status)) {
          timer = setTimeout(() => void fetchJob(), 2500);
        }
      } catch (caughtError) {
        if (!active || controller.signal.aborted || isAbortError(caughtError)) return;
        setError(readableGenerationError(caughtError));
        setStatus("error");
      }
    };

    void fetchJob();
    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [load, refreshKey]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const cancelJob = useCallback(async () => {
    if (!registry.generation || actionPending !== null) return;
    setActionPending("cancel");
    setActionError("");
    try {
      await registry.generation.cancel(jobId);
      setRefreshKey((key) => key + 1);
    } catch (caughtError) {
      setActionError(readableGenerationError(caughtError));
    } finally {
      setActionPending(null);
    }
  }, [actionPending, jobId, registry]);

  const deleteJob = useCallback(async () => {
    if (!registry.generation || actionPending !== null || !window.confirm("删除任务？")) return;
    setActionPending("delete");
    setActionError("");
    try {
      await registry.generation.delete(jobId);
      router.replace("/generations");
    } catch (caughtError) {
      setActionError(readableGenerationError(caughtError));
    } finally {
      setActionPending(null);
    }
  }, [actionPending, jobId, registry, router]);

  if (status === "loading" && job === null) {
    return (
      <section className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-6" data-testid="generation-job-loading">
        <Skeleton label="正在加载生成任务" className="h-8 max-w-48" />
        <Skeleton label="正在加载生成任务" className="h-56" />
      </section>
    );
  }

  if (status === "error" || job === null) {
    return (
      <section className="mx-auto flex w-full max-w-[var(--mosaic-layout-content)] items-center justify-center py-12">
        <ErrorState
          title="无法加载生成任务"
          description={error || "任务不存在或暂时不可用。"}
          action={
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => setRefreshKey((key) => key + 1)}>
                重新加载
              </Button>
              <Button onClick={() => router.push("/models")}>返回模型广场</Button>
            </div>
          }
          className="w-full max-w-xl"
        />
      </section>
    );
  }

  const jobError = readableGenerationErrorCode(job.error_code);

  return (
    <section className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-8" data-testid="generation-job-view">
      <header className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <button
            type="button"
            onClick={() => router.push("/generations")}
            className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-[var(--mosaic-color-ink-muted)] hover:text-[var(--mosaic-color-ink)]"
          >
            <ArrowLeft size={17} aria-hidden />
            生成记录
          </button>
          <h1 className="mt-5 text-[40px] font-semibold leading-[48px] tracking-[-0.055em] text-[var(--mosaic-color-ink)] lg:text-[56px] lg:leading-[64px]">
            任务详情
          </h1>
          <p className="mt-3 break-all font-mono text-sm text-[var(--mosaic-color-ink-muted)]">
            {job.job_id}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {job.status === "accepted" ? (
            <Button variant="secondary" loading={actionPending === "cancel"} onClick={() => void cancelJob()}>
              <XCircle size={17} aria-hidden />取消任务
            </Button>
          ) : null}
          {isTerminalGenerationStatus(job.status) ? (
            <Button variant="secondary" loading={actionPending === "delete"} onClick={() => void deleteJob()}>
              <Trash size={17} aria-hidden />删除任务
            </Button>
          ) : null}
          <Button
            variant="secondary"
            loading={status === "loading"}
            onClick={() => setRefreshKey((key) => key + 1)}
          >
            <ArrowsClockwise size={17} aria-hidden />
            刷新状态
          </Button>
        </div>
      </header>

      {actionError ? <p role="alert" className="text-sm text-[var(--mosaic-color-danger)]">{actionError}</p> : null}

      <section role="status" aria-live="polite" className="grid gap-6 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-6 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.65fr)] lg:p-8">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone={generationTone(job.status)}>
              {generationStatusLabels[job.status]}
            </StatusBadge>
            {job.reconciliation_pending ? <StatusBadge tone="warning">待对账</StatusBadge> : null}
            <span className="text-sm text-[var(--mosaic-color-ink-muted)]">
              {generationModalityLabels[job.modality]}任务
            </span>
          </div>
          {jobError ? (
            <p className="mt-5 text-sm text-[var(--mosaic-color-danger)]">
              {jobError}
            </p>
          ) : null}
        </div>
        <dl className="grid gap-0 border-t border-[var(--mosaic-color-line)] lg:border-l lg:border-t-0 lg:pl-6">
          <div className="flex items-center justify-between gap-4 border-b border-[var(--mosaic-color-line)] py-3">
            <dt className="text-sm text-[var(--mosaic-color-ink-muted)]">模型</dt>
            <dd className="break-all text-right text-sm font-medium text-[var(--mosaic-color-ink)]">{job.product_model_id}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 border-b border-[var(--mosaic-color-line)] py-3">
            <dt className="text-sm text-[var(--mosaic-color-ink-muted)]">创建时间</dt>
            <dd className="text-right text-sm font-medium text-[var(--mosaic-color-ink)]">{formatGenerationDate(job.created_at)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-3">
            <dt className="text-sm text-[var(--mosaic-color-ink-muted)]">更新时间</dt>
            <dd className="text-right text-sm font-medium text-[var(--mosaic-color-ink)]">{formatGenerationDate(job.updated_at)}</dd>
          </div>
        </dl>
      </section>

      <section className="grid gap-4">
        <div className="flex items-center gap-3">
          {job.status === "succeeded" ? <CheckCircle size={22} className="text-[var(--mosaic-color-success)]" aria-hidden /> : <CircleNotch size={22} className="text-[var(--mosaic-color-accent)]" aria-hidden />}
          <h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">结果与文件</h2>
        </div>
        {job.artifacts.length === 0 ? (
          <div className="rounded-[var(--mosaic-radius-surface)] border border-dashed border-[var(--mosaic-color-line)] px-6 py-10 text-sm text-[var(--mosaic-color-ink-muted)]">
            结果正在准备中。
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {job.artifacts.map((artifact) => (
              <article key={artifact.artifact_id} className="grid gap-3 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="font-semibold text-[var(--mosaic-color-ink)]">{artifactKindLabel(artifact.kind)}</h3>
                  </div>
                  <StatusBadge tone={artifact.status === "ready" ? "success" : "neutral"}>{artifactStatusLabel(artifact.status)}</StatusBadge>
                </div>
                <dl className="grid grid-cols-2 gap-3 border-t border-[var(--mosaic-color-line)] pt-3 text-sm">
                  <div><dt className="text-[var(--mosaic-color-ink-muted)]">类型</dt><dd className="mt-1 font-medium text-[var(--mosaic-color-ink)]">{artifact.mime_type}</dd></div>
                  <div><dt className="text-[var(--mosaic-color-ink-muted)]">大小</dt><dd className="mt-1 font-medium text-[var(--mosaic-color-ink)]">{formatArtifactSize(artifact.size_bytes)}</dd></div>
                </dl>
                {artifact.status === "ready" ? (
                  <div className="grid gap-3">
                    {artifact.mime_type.startsWith("image/") ? (
                      // eslint-disable-next-line @next/next/no-img-element -- authenticated dynamic artifact has no build-time dimensions.
                      <img src={artifactUrl(job.job_id, artifact.artifact_id)} alt="生成结果" className="max-h-[36rem] w-full rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface-muted)] object-contain" />
                    ) : artifact.mime_type.startsWith("video/") ? (
                      <video aria-label={`生成视频 ${artifact.artifact_id}`} controls preload="metadata" src={artifactUrl(job.job_id, artifact.artifact_id)} className="aspect-video w-full rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-black" />
                    ) : artifact.mime_type.startsWith("audio/") ? (
                      <audio aria-label={`生成音频 ${artifact.artifact_id}`} controls preload="metadata" src={artifactUrl(job.job_id, artifact.artifact_id)} className="w-full" />
                    ) : null}
                    <a href={artifactUrl(job.job_id, artifact.artifact_id)} download className="inline-flex min-h-10 items-center justify-center gap-2 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] px-4 text-sm font-semibold text-[var(--mosaic-color-ink)] hover:border-[var(--mosaic-color-accent)] hover:text-[var(--mosaic-color-accent)]">
                      <DownloadSimple size={16} aria-hidden />
                      下载文件
                    </a>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
