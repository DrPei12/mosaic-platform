import {
  Cube,
  List,
} from "@phosphor-icons/react";
import Link from "next/link";
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";

import { BRAND } from "@/shared/config/brand";
import { cn } from "@/shared/ui/cn";

export interface TopBarProps {
  pathname?: string;
  navigationTrigger?: ReactNode;
  onOpenNavigation?: () => void;
  onToggleRail?: () => void;
  railCollapsed?: boolean;
}

export const MobileNavigationButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement>
>(function MobileNavigationButton({ className, ...props }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      {...props}
      className={cn(
        "inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--mosaic-radius-control)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px lg:hidden motion-reduce:transition-none motion-reduce:transform-none",
        className,
      )}
    >
      <List size={22} aria-hidden />
    </button>
  );
});

MobileNavigationButton.displayName = "MobileNavigationButton";

export function TopBar({
  pathname = "/",
  navigationTrigger,
  onOpenNavigation,
  onToggleRail,
  railCollapsed = false,
}: TopBarProps) {
  const fallbackTrigger = onOpenNavigation ? (
    <MobileNavigationButton
      onClick={onOpenNavigation}
      aria-label="打开导航"
    />
  ) : null;
  const modelActive =
    pathname === "/models" ||
    pathname.startsWith("/models/") ||
    pathname === "/chat" ||
    pathname.startsWith("/chat/") ||
    pathname === "/studio" ||
    pathname.startsWith("/studio/");

  return (
    <header className="sticky top-0 z-40 flex h-[var(--mosaic-layout-top-bar-mobile)] min-h-[var(--mosaic-layout-top-bar-mobile)] items-center border-b border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-3 md:h-[var(--mosaic-layout-top-bar-desktop)] md:min-h-[var(--mosaic-layout-top-bar-desktop)] md:px-5">
      {navigationTrigger ?? fallbackTrigger}
      {onToggleRail ? (
        <button
          type="button"
          aria-label={railCollapsed ? "展开侧栏" : "收起侧栏"}
          aria-pressed={railCollapsed}
          onClick={onToggleRail}
          className="hidden min-h-11 min-w-11 items-center justify-center rounded-[var(--mosaic-radius-control)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,color] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] lg:inline-flex"
        >
          <List size={22} aria-hidden />
        </button>
      ) : null}

      <Link
        href="/models"
        className="ml-1 inline-flex min-h-11 items-center gap-2 px-2 text-lg font-bold tracking-[0.09em] text-[var(--mosaic-color-ink)]"
      >
        <Cube size={24} weight="fill" aria-hidden className="text-[var(--mosaic-color-accent)]" />
        {BRAND.name}
      </Link>

      <nav aria-label="产品模块" className="ml-8 hidden h-full items-center md:flex">
        <Link
          href="/models"
          className={cn(
            "inline-flex min-h-11 items-center border-b-2 border-transparent px-3 text-sm font-medium text-[var(--mosaic-color-ink-muted)]",
            modelActive && "border-[var(--mosaic-color-accent)] font-semibold text-[var(--mosaic-color-ink)]",
          )}
        >
          模型
        </Link>
      </nav>
    </header>
  );
}
