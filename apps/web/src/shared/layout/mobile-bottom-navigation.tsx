import {
  ClockCounterClockwise,
  GridFour,
  Wallet,
} from "@phosphor-icons/react";
import Link from "next/link";
import type { ComponentType } from "react";

import { cn } from "@/shared/ui/cn";

const navigationItems = [
  { href: "/models", label: "模型广场", icon: GridFour },
  { href: "/generations", label: "生成记录", icon: ClockCounterClockwise },
  { href: "/usage", label: "用量中心", icon: Wallet },
] as const;

type NavigationIcon = ComponentType<{
  size?: number;
  weight?: "regular";
  "aria-hidden"?: boolean;
}>;

export interface MobileBottomNavigationProps {
  pathname: string;
}

export function MobileBottomNavigation({ pathname }: MobileBottomNavigationProps) {
  const isModelWorkspace =
    pathname === "/studio" || pathname.startsWith("/studio/");
  return (
    <nav
      aria-label="移动端主导航"
      className="fixed inset-x-0 bottom-0 z-30 h-[calc(var(--mosaic-layout-mobile-bottom-navigation)+env(safe-area-inset-bottom))] border-t border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <div className="grid h-[var(--mosaic-layout-mobile-bottom-navigation)] grid-cols-3">
        {navigationItems.map((item) => {
          const Icon = item.icon as NavigationIcon;
          const active =
            pathname === item.href ||
            pathname.startsWith(`${item.href}/`) ||
            (item.href === "/models" && isModelWorkspace);

          return (
            <Link
              key={item.href}
              href={item.href}
              {...(active ? { "aria-current": "page" as const } : {})}
              className={cn(
                "flex h-full min-h-11 flex-col items-center justify-center gap-1 px-2 text-xs font-medium text-[var(--mosaic-color-ink-muted)] transition-[background-color,color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none",
                active && "text-[var(--mosaic-color-accent)]",
              )}
            >
              <Icon size={20} aria-hidden weight="regular" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
