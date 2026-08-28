import type { ReactNode } from "react";

import { requireServerSession } from "@/features/auth/server-session";
import { getPublicServiceMode } from "@/shared/config/service-mode";
import { ConsoleShell } from "@/shared/layout/console-shell";

export default async function ConsoleLayout({ children }: { children: ReactNode }) {
  const mode = getPublicServiceMode();
  if (mode === "api") {
    await requireServerSession("/models", { allowPasswordChange: true });
  }
  return <ConsoleShell mode={mode}>{children}</ConsoleShell>;
}
