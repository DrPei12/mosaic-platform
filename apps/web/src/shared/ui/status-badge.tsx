import type { ReactNode } from "react";

import { cn } from "./cn";

const toneClasses = {
  neutral:
    "border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface-muted)] text-[var(--mosaic-color-ink)]",
  info: "border-[color-mix(in_srgb,var(--mosaic-color-accent)_35%,var(--mosaic-color-surface))] bg-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,var(--mosaic-color-surface))] text-[var(--mosaic-color-accent)]",
  success:
    "border-[color-mix(in_srgb,var(--mosaic-color-success)_35%,var(--mosaic-color-surface))] bg-[color-mix(in_srgb,var(--mosaic-color-success)_10%,var(--mosaic-color-surface))] text-[var(--mosaic-color-success)]",
  warning:
    "border-[color-mix(in_srgb,var(--mosaic-color-warning)_35%,var(--mosaic-color-surface))] bg-[color-mix(in_srgb,var(--mosaic-color-warning)_10%,var(--mosaic-color-surface))] text-[var(--mosaic-color-ink)]",
  danger:
    "border-[color-mix(in_srgb,var(--mosaic-color-danger)_35%,var(--mosaic-color-surface))] bg-[color-mix(in_srgb,var(--mosaic-color-danger)_10%,var(--mosaic-color-surface))] text-[var(--mosaic-color-ink)]",
} as const;

export type StatusBadgeTone = keyof typeof toneClasses;

export interface StatusBadgeProps {
  tone?: StatusBadgeTone;
  children: ReactNode;
  className?: string;
}

export function StatusBadge({
  tone = "neutral",
  children,
  className,
}: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex min-h-7 w-fit justify-self-start items-center rounded-[var(--mosaic-radius-pill)] border px-2.5 text-xs font-semibold",
        toneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
