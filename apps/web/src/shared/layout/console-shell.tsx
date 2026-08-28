"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AuthGate } from "@/features/auth/auth-gate";
import type { ServiceMode } from "@/shared/config/service-mode";
import { AppShell } from "./app-shell";

export function ConsoleShell({
  children,
  mode,
}: {
  children: ReactNode;
  mode: ServiceMode;
}) {
  const pathname = usePathname();
  const shell = <AppShell pathname={pathname}>{children}</AppShell>;
  return mode === "demo" ? <AuthGate mode="demo">{shell}</AuthGate> : shell;
}
