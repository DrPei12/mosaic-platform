import type { ReactNode } from "react";

import { cn } from "./cn";

export interface ErrorStateProps {
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}

export function ErrorState({
  title,
  description,
  action,
  className,
}: ErrorStateProps) {
  return (
    <section
      role="alert"
      className={cn(
        "grid gap-3 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-6",
        className,
      )}
    >
      <h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">
        {title}
      </h2>
      <p className="text-[var(--mosaic-color-ink-muted)]">{description}</p>
      {action !== undefined && action !== null ? <div>{action}</div> : null}
    </section>
  );
}

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <section
      className={cn(
        "grid justify-items-start gap-3 border-t border-[var(--mosaic-color-line)] py-10",
        className,
      )}
    >
      <h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">
        {title}
      </h2>
      {description ? (
        <p className="max-w-[60ch] text-[var(--mosaic-color-ink-muted)]">
          {description}
        </p>
      ) : null}
      {action !== undefined && action !== null ? action : null}
    </section>
  );
}

export interface SkeletonProps {
  label: string;
  className?: string;
}

export function Skeleton({ label, className }: SkeletonProps) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={label}
      className={cn(
        "h-20 w-full animate-pulse rounded-[var(--mosaic-radius-surface)] bg-[var(--mosaic-color-surface-muted)] motion-reduce:animate-none",
        className,
      )}
    />
  );
}
