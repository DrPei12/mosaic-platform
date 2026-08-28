"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { useState } from "react";

import { NavigationRail } from "./navigation-rail";
import { MobileBottomNavigation } from "./mobile-bottom-navigation";
import { NetworkStatus } from "./network-status";
import { MobileNavigationButton, TopBar } from "./top-bar";
import { cn } from "@/shared/ui/cn";

export const MOBILE_NAVIGATION_DIALOG_ID = "mosaic-mobile-navigation";

export interface AppShellProps {
  pathname?: string;
  children: ReactNode;
}

export function AppShell({ pathname = "/", children }: AppShellProps) {
  const [open, setOpen] = useState(false);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const isChatRoute = pathname === "/chat" || pathname.startsWith("/chat/");
  const isStudioRoute = pathname === "/studio" || pathname.startsWith("/studio/");

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <div className="min-h-[100dvh] bg-[var(--mosaic-color-canvas)]">
        <a
          href="#main-content"
          onClick={() => {
            document.getElementById("main-content")?.focus();
          }}
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-[var(--mosaic-radius-control)] focus:bg-[var(--mosaic-color-surface)] focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-[var(--mosaic-color-ink)]"
        >
          跳到主要内容
        </a>

        <TopBar
          pathname={pathname}
          railCollapsed={railCollapsed}
          onToggleRail={() => setRailCollapsed((current) => !current)}
          navigationTrigger={
            <Dialog.Trigger asChild>
              <MobileNavigationButton
                aria-label="打开导航"
                {...(open
                  ? { "aria-controls": MOBILE_NAVIGATION_DIALOG_ID }
                  : {})}
              />
            </Dialog.Trigger>
          }
        />

        <aside className={cn(
          "fixed bottom-0 left-0 top-[var(--mosaic-layout-top-bar-desktop)] z-30 hidden w-[var(--mosaic-layout-nav)] border-r border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)]",
          railCollapsed ? "lg:hidden" : "lg:block",
        )}>
          <NavigationRail pathname={pathname} ariaLabel="桌面主导航" />
        </aside>

        <div className={cn(!railCollapsed && "lg:pl-[var(--mosaic-layout-nav)]")}>
          {!isChatRoute ? <NetworkStatus /> : null}
          <main
            id="main-content"
            tabIndex={-1}
            data-shell-mode={isChatRoute ? "chat" : isStudioRoute ? "studio" : "console"}
            className={
              isChatRoute
                ? "h-[calc(100dvh-var(--mosaic-layout-top-bar-mobile))] w-full max-w-none overflow-hidden p-0 md:h-[calc(100dvh-var(--mosaic-layout-top-bar-desktop))]"
                : isStudioRoute
                  ? "w-full max-w-none p-0 pb-[calc(var(--mosaic-layout-mobile-bottom-navigation)+env(safe-area-inset-bottom))] md:pb-0"
                  : "mx-auto w-full max-w-[var(--mosaic-layout-workspace)] p-4 pb-[calc(var(--mosaic-grid-mobile-gutter)+var(--mosaic-layout-mobile-bottom-navigation)+env(safe-area-inset-bottom))] md:p-6"
            }
          >
            {children}
          </main>
        </div>

        {!isChatRoute ? <MobileBottomNavigation pathname={pathname} /> : null}

        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/25 motion-reduce:transition-none" />
          <Dialog.Content
            id={MOBILE_NAVIGATION_DIALOG_ID}
            aria-label="移动导航"
            className="fixed inset-y-0 left-0 z-50 max-h-dvh w-[min(86vw,320px)] overflow-y-auto bg-[var(--mosaic-color-surface)] shadow-[12px_0_40px_rgb(21_23_26_/_0.12)] motion-reduce:transition-none"
          >
            <Dialog.Title className="sr-only">移动导航</Dialog.Title>
            <NavigationRail
              pathname={pathname}
              ariaLabel="移动端抽屉导航"
              onNavigate={() => setOpen(false)}
            />
            <Dialog.Close
              type="button"
              className="absolute right-3 top-3 inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] text-[var(--mosaic-color-ink)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none"
              aria-label="关闭导航"
            >
              <X size={20} aria-hidden weight="regular" />
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </div>
    </Dialog.Root>
  );
}
