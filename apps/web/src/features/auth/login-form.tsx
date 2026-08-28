"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import { getPublicServiceMode, type ServiceMode } from "@/shared/config/service-mode";
import { Button } from "@/shared/ui/button";
import { InputField } from "@/shared/ui/input-field";

export interface LoginFormProps {
  mode?: ServiceMode;
  returnTo?: string;
}

function apiErrorCode(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("apiCode" in error)) return undefined;
  const code = (error as { apiCode?: unknown }).apiCode;
  return typeof code === "string" ? code : undefined;
}

function apiErrorRequestId(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("requestId" in error)) return undefined;
  const requestId = (error as { requestId?: unknown }).requestId;
  return typeof requestId === "string" ? requestId : undefined;
}

function readableAuthError(error: unknown): string {
  const code = apiErrorCode(error);
  let message = "登录服务暂时不可用，请稍后重试。";
  switch (code) {
    case "AUTHENTICATION_FAILED":
      message = "账号或密码不正确，请检查后重试。";
      break;
    case "AUTHENTICATION_RATE_LIMITED":
      message = "登录尝试过于频繁，请稍后再试。";
      break;
    case "TENANT_SELECTION_REQUIRED":
      message = "请选择工作区。";
      break;
    case "AUTHENTICATION_UNAVAILABLE":
      message = "认证服务暂时不可用，请稍后重试。";
      break;
    case "AUTH_ORIGIN_INVALID":
      message = "当前地址不可登录。";
      break;
    case "REQUEST_VALIDATION_FAILED":
      message = "登录信息格式不正确。";
      break;
  }
  const requestId = apiErrorRequestId(error);
  return requestId ? `${message}（请求 ID：${requestId}）` : message;
}

export function LoginForm({
  mode = getPublicServiceMode(),
  returnTo = "/models",
}: LoginFormProps) {
  const router = useRouter();
  const mountedRef = useRef(true);
  const requestRef = useRef<AbortController | null>(null);
  const isDemo = mode === "demo";
  const [account, setAccount] = useState(() => (isDemo ? "demo@mosaic.internal" : ""));
  const [password, setPassword] = useState(() => (isDemo ? "internal-demo" : ""));
  const [tenantSlug, setTenantSlug] = useState("");
  const [hydrated, setHydrated] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | undefined>();

  useEffect(() => {
    mountedRef.current = true;
    /* eslint-disable-next-line react-hooks/set-state-in-effect -- handlers must attach first. */
    setHydrated(true);
    return () => {
      mountedRef.current = false;
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (requestRef.current !== null) return;

    const controller = new AbortController();
    requestRef.current = controller;
    setError(undefined);
    setSubmitting(true);

    try {
      const session = await createBrowserServiceRegistry().auth.signIn(
        {
          account,
          password,
          ...(tenantSlug.trim() ? { tenantSlug: tenantSlug.trim() } : {}),
        },
        controller.signal,
      );
      if (
        !mountedRef.current ||
        controller.signal.aborted ||
        requestRef.current !== controller
      ) {
        return;
      }
      if (!session.authenticated) {
        setError("账号或密码不正确，请检查后重试。");
        return;
      }
      router.replace(
        session.passwordChangeRequired
          ? `/account/security?returnTo=${encodeURIComponent(returnTo)}`
          : returnTo,
      );
      router.refresh();
    } catch (caughtError) {
      if (
        !mountedRef.current ||
        controller.signal.aborted ||
        requestRef.current !== controller ||
        (caughtError instanceof DOMException && caughtError.name === "AbortError")
      ) {
        return;
      }
      setError(readableAuthError(caughtError));
    } finally {
      if (!mountedRef.current || requestRef.current !== controller) return;
      requestRef.current = null;
      setSubmitting(false);
      setPassword("");
    }
  }

  return (
    <form
      className="grid gap-5"
      data-hydrated={hydrated ? "true" : undefined}
      onSubmit={submit}
    >
      <InputField
        id="account"
        name="account"
        label="账户"
        autoComplete="username"
        type="email"
        value={account}
        onChange={(event) => setAccount(event.target.value)}
        disabled={submitting}
        required
      />
      {!isDemo ? (
        <InputField
          id="login-tenant-slug"
          name="tenantSlug"
          label="工作区标识（可选）"
          autoComplete="organization"
          pattern="[a-z0-9](?:[a-z0-9\-]{0,118}[a-z0-9])?"
          maxLength={120}
          value={tenantSlug}
          onChange={(event) => setTenantSlug(event.target.value)}
          disabled={submitting}
        />
      ) : null}
      <InputField
        id="password"
        name="password"
        label="密码"
        type="password"
        autoComplete="current-password"
        minLength={8}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        disabled={submitting}
        required
      />
      {error ? (
        <p role="alert" className="text-sm text-[var(--mosaic-color-danger)]">
          {error}
        </p>
      ) : null}
      <Button
        type={hydrated ? "submit" : "button"}
        disabled={!hydrated}
        loading={submitting}
      >
        登录
      </Button>
    </form>
  );
}
