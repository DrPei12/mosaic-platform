"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { getPublicServiceMode, type ServiceMode } from "@/shared/config/service-mode";
import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import { Button } from "@/shared/ui/button";
import { ErrorState, Skeleton } from "@/shared/ui/feedback-state";

export interface AuthGateProps {
  children: ReactNode;
  mode?: ServiceMode;
}
/** Client-side session gate; server-side authorization remains a backend responsibility. */
export function AuthGate({
  children,
  mode = getPublicServiceMode(),
}: AuthGateProps) {
  const router = useRouter();
  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  /* eslint-disable react-hooks/set-state-in-effect -- route access is synchronized with the external session service. */
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const registry = createBrowserServiceRegistry();
    setSessionError("");
    setAllowed(null);

    void registry.auth
      .getSession(controller.signal)
      .then(async (session) => {
        if (session.authenticated || mode !== "api" || process.env.NEXT_PUBLIC_\u004dOSAIC_SKIP_LOGIN !== "true") {
          return session;
        }

        if (!registry.auth.bootstrapLocalSession) return session;
        return registry.auth.bootstrapLocalSession(controller.signal);
      })
      .then((session) => {
        if (!active) return;

        if (!session.authenticated) {
          setAllowed(false);
          router.replace("/login");
          return;
        }

        setAllowed(true);
      })
      .catch((error: unknown) => {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }

        // A transient API failure is not evidence that the user is signed
        // out. Keep the protected shell out of view, but let the user retry
        // session verification without losing the current route.
        setSessionError(
          "暂时无法验证登录状态，请检查网络或稍后重试。",
        );
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [mode, retryKey, router]);
  /* eslint-enable react-hooks/set-state-in-effect */

  if (allowed === true) return children;

  if (sessionError) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-[var(--mosaic-color-canvas)] p-6">
        <ErrorState
          title="登录状态暂时无法确认"
          description={sessionError}
          action={<Button variant="secondary" onClick={() => setRetryKey((value) => value + 1)}>重新验证</Button>}
          className="w-full max-w-lg"
        />
      </div>
    );
  }

  return (
    <Skeleton
      label="正在验证登录状态"
    />
  );
}
