"use client";

import { ArrowsClockwise, Coins, Database, Pulse, Wallet } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";

import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import type { UsageSummary } from "@/services/interfaces";
import { Button } from "@/shared/ui/button";
import { ErrorState, Skeleton } from "@/shared/ui/feedback-state";
import { StatusBadge } from "@/shared/ui/status-badge";

function points(value: number): string {
  return `${new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value / 100)} 点`;
}

function bytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function date(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function ledgerTypeLabel(value: UsageSummary["recent_ledger"][number]["entry_type"]): string {
  if (value === "credit") return "入账";
  if (value === "debit") return "扣费";
  if (value === "hold") return "冻结";
  if (value === "release") return "释放";
  return "调整";
}

function ledgerReferenceLabel(value: string): string {
  if (value === "chat") return "文本对话";
  if (value === "generation") return "生成任务";
  if (value === "demo_seed") return "账户入账";
  return "账户变动";
}

export function UsageDashboard() {
  const registry = useMemo(() => createBrowserServiceRegistry(), []);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  /* eslint-disable react-hooks/set-state-in-effect -- usage state is synchronized with the external API. */
  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    setError("");
    if (!registry.usage) {
      setStatus("error");
      setError("用量服务暂不可用，请稍后重试。");
      return () => controller.abort();
    }
    void registry.usage.getSummary(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setSummary(value);
        setStatus("ready");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError("用量数据暂时不可用，请稍后重试。");
        setStatus("error");
      });
    return () => controller.abort();
  }, [refreshKey, registry]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (status === "loading" && summary === null) {
    return <section className="grid gap-4"><Skeleton label="正在加载用量" className="h-36" /><Skeleton label="正在加载余额明细" className="h-72" /></section>;
  }
  if (status === "error" || summary === null) {
    return <ErrorState title="无法加载用量中心" description={error} action={<Button onClick={() => setRefreshKey((key) => key + 1)}>重新加载</Button>} />;
  }

  const cards = [
    { label: "账户余额（PTS）", value: points(summary.balance_minor), detail: `冻结 ${points(summary.reserved_minor)}`, icon: Wallet },
    { label: "请求数", value: String(summary.totals.requests), detail: `文本 Token ${summary.totals.input_tokens + summary.totals.output_tokens}`, icon: Pulse },
    { label: "媒体产出", value: `${summary.totals.image_count} 图 · ${summary.totals.video_seconds}s 视频`, detail: `${summary.totals.character_count} 个语音字符`, icon: Coins },
    { label: "存储用量", value: bytes(summary.totals.storage_bytes), detail: `累计费用 ${points(summary.totals.charge_amount_minor)}`, icon: Database },
  ];

  return (
    <section className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <h1 className="text-[40px] font-semibold leading-[48px] tracking-[-0.055em] text-[var(--mosaic-color-ink)] lg:text-[56px] lg:leading-[64px]">用量中心</h1>
        <Button variant="secondary" loading={status === "loading"} onClick={() => setRefreshKey((key) => key + 1)}><ArrowsClockwise size={17} aria-hidden />刷新</Button>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(({ label, value, detail, icon: Icon }) => <article key={label} className="rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-5"><Icon size={22} className="text-[var(--mosaic-color-accent)]" aria-hidden /><p className="mt-5 text-sm text-[var(--mosaic-color-ink-muted)]">{label}</p><p className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-[var(--mosaic-color-ink)]">{value}</p><p className="mt-2 text-xs text-[var(--mosaic-color-ink-muted)]">{detail}</p></article>)}
      </div>

      <section className="grid gap-4"><h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">最近用量</h2><div className="overflow-hidden rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)]">{summary.recent_usage.map((entry) => <article key={entry.usage_id} className="grid gap-2 border-b border-[var(--mosaic-color-line)] px-5 py-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div><div className="flex flex-wrap items-center gap-2"><StatusBadge tone="neutral">{entry.source === "chat" ? "对话" : "生成"}</StatusBadge><span className="font-semibold text-[var(--mosaic-color-ink)]">{entry.model_id}</span><span className="text-sm text-[var(--mosaic-color-ink-muted)]">{entry.modality}</span></div><p className="mt-2 text-xs text-[var(--mosaic-color-ink-muted)]">{date(entry.created_at)}</p></div><div className="text-right text-sm text-[var(--mosaic-color-ink-muted)]"><p>Token {entry.input_tokens + entry.output_tokens} · 单位 {entry.billable_units}</p><p className="mt-1 font-medium text-[var(--mosaic-color-ink)]">{points(entry.charge_amount_minor)}</p></div></article>)}</div></section>

      <section className="grid gap-4"><h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">余额明细</h2><div className="grid gap-3 sm:grid-cols-2">{summary.recent_ledger.map((entry) => <article key={entry.ledger_id} className="rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-5"><div className="flex items-center justify-between gap-3"><StatusBadge tone={entry.entry_type === "credit" ? "success" : "neutral"}>{ledgerTypeLabel(entry.entry_type)}</StatusBadge><span className="font-semibold text-[var(--mosaic-color-ink)]">{points(entry.amount_minor)}</span></div><p className="mt-3 text-sm text-[var(--mosaic-color-ink-muted)]">{ledgerReferenceLabel(entry.reference_type)}</p><p className="mt-1 text-xs text-[var(--mosaic-color-ink-muted)]">{date(entry.created_at)}</p></article>)}</div></section>
    </section>
  );
}
