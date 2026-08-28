"use client";

import { ArrowRight, ArrowsClockwise } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import type { GenerationJob } from "@/services/interfaces";
import { Button } from "@/shared/ui/button";
import { ErrorState, Skeleton } from "@/shared/ui/feedback-state";
import { StatusBadge } from "@/shared/ui/status-badge";
import {
  formatGenerationDate,
  generationModalityLabels,
  generationStatusLabels,
  generationTone,
  readableGenerationError,
} from "./generation-copy";

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error &&
    (error as { name?: unknown }).name === "AbortError";
}

export function ApiGenerationHistory() {
  const registry = useMemo(() => createBrowserServiceRegistry(), []);
  const [jobs, setJobs] = useState<readonly GenerationJob[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  /* eslint-disable react-hooks/set-state-in-effect -- list state is synchronized with the external API. */
  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError("");
    if (!registry.generation) {
      setStatus("error");
      setError("生成服务暂不可用，请稍后重试。");
      return () => controller.abort();
    }
    void registry.generation.list(controller.signal)
      .then((nextJobs) => {
        if (controller.signal.aborted) return;
        setJobs(nextJobs);
        setStatus("ready");
      })
      .catch((caughtError: unknown) => {
        if (controller.signal.aborted || isAbortError(caughtError)) return;
        setError(readableGenerationError(caughtError));
        setStatus("error");
      });
    return () => controller.abort();
  }, [refreshKey, registry]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <section className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div className="max-w-3xl">
          <StatusBadge tone="info">生成任务</StatusBadge>
          <h1 className="mt-5 text-[40px] font-semibold leading-[48px] tracking-[-0.055em] text-[var(--mosaic-color-ink)] lg:text-[56px] lg:leading-[64px]">生成记录</h1>
        </div>
        <Button variant="secondary" loading={status === "loading"} onClick={() => setRefreshKey((key) => key + 1)}>
          <ArrowsClockwise size={17} aria-hidden />刷新
        </Button>
      </header>

      {status === "loading" && jobs.length === 0 ? (
        <div className="grid gap-3"><Skeleton label="正在加载生成记录" className="h-28" /><Skeleton label="正在加载生成记录" className="h-28" /></div>
      ) : null}

      {status === "error" ? (
        <ErrorState title="无法加载生成记录" description={error} action={<Button onClick={() => setRefreshKey((key) => key + 1)}>重新加载</Button>} />
      ) : null}

      {status === "error" && jobs.length > 0 ? (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-wrap items-center gap-3 rounded-[var(--mosaic-radius-control)] border border-[color-mix(in_srgb,var(--mosaic-color-warning)_35%,var(--mosaic-color-line))] bg-[color-mix(in_srgb,var(--mosaic-color-warning)_8%,var(--mosaic-color-surface))] px-4 py-3 text-sm leading-6 text-[var(--mosaic-color-ink)]"
        >
          <StatusBadge tone="warning">上次成功数据</StatusBadge>
          <span>刷新失败，下面列表可能已过期。</span>
        </div>
      ) : null}

      {status === "ready" && jobs.length === 0 ? (
        <section className="grid gap-4 rounded-[var(--mosaic-radius-surface)] border border-dashed border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-8 text-center">
          <h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">还没有生成任务</h2>
          <Button asChild className="mx-auto"><Link href="/models">返回模型广场</Link></Button>
        </section>
      ) : null}

      {jobs.length > 0 ? (
        <div className="grid gap-3">
          {jobs.map((job) => (
            <Link key={job.job_id} href={`/generations/${job.job_id}`} className="group grid gap-4 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-5 transition-[border-color,transform] hover:-translate-y-0.5 hover:border-[var(--mosaic-color-accent)] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
              <div>
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge tone={generationTone(job.status)}>{generationStatusLabels[job.status]}</StatusBadge>
                  {job.reconciliation_pending ? <StatusBadge tone="warning">待对账</StatusBadge> : null}
                  <span className="text-sm text-[var(--mosaic-color-ink-muted)]">{generationModalityLabels[job.modality]}</span>
                  <span className="text-sm text-[var(--mosaic-color-ink-muted)]">{formatGenerationDate(job.created_at)}</span>
                </div>
                <h2 className="mt-3 text-lg font-semibold text-[var(--mosaic-color-ink)]">{job.product_model_id}</h2>
                <p className="mt-1 font-mono text-xs text-[var(--mosaic-color-ink-muted)]">{job.job_id}</p>
              </div>
              <span className="inline-flex items-center gap-2 text-sm font-semibold text-[var(--mosaic-color-accent)]">查看详情<ArrowRight size={16} aria-hidden /></span>
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}
