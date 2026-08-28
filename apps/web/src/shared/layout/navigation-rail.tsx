import {
  ClockCounterClockwise,
  GridFour,
  Wallet,
} from "@phosphor-icons/react";
import Link from "next/link";
import type { ComponentType } from "react";

import { CONSOLE_ROUTES } from "@/shared/config/routes";
import { cn } from "@/shared/ui/cn";

const iconsByHref = {
  "/models": GridFour,
  "/generations": ClockCounterClockwise,
  "/usage": Wallet,
} as const;

export interface NavigationRailProps {
  pathname: string;
  onNavigate?: () => void;
  ariaLabel?: string;
}

export function NavigationRail({
  pathname,
  onNavigate,
  ariaLabel = "主导航",
}: NavigationRailProps) {
  const isModelWorkspace =
    pathname === "/chat" ||
    pathname.startsWith("/chat/") ||
    pathname === "/studio" ||
    pathname.startsWith("/studio/");
  return (
    <nav
      aria-label={ariaLabel}
      className="flex h-full min-h-full flex-col bg-[var(--mosaic-color-surface)] px-3 py-4"
    >
      <div className="grid gap-1">
        {CONSOLE_ROUTES.map((route) => {
          const Icon = iconsByHref[route.href] as ComponentType<{
            size?: number;
            weight?: "regular";
            "aria-hidden"?: boolean;
          }>;
          const active =
            pathname === route.href ||
            pathname.startsWith(`${route.href}/`) ||
            (route.href === "/models" && isModelWorkspace);

          return (
            <Link
              key={route.href}
              href={route.href}
              {...(onNavigate ? { onClick: () => onNavigate() } : {})}
              {...(active ? { "aria-current": "page" as const } : {})}
              className={cn(
                "flex min-h-11 items-center gap-3 rounded-[var(--mosaic-radius-control)] px-3 text-sm font-medium text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none",
                active &&
                  "bg-[color-mix(in_srgb,var(--mosaic-color-accent)_10%,var(--mosaic-color-surface))] text-[var(--mosaic-color-accent)]",
              )}
            >
              <Icon size={20} aria-hidden weight="regular" />
              <span>{route.label}</span>
            </Link>
          );
        })}
      </div>

    </nav>
  );
}
