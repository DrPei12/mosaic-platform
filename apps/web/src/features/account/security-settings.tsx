"use client";

import { ArrowClockwise, SignOut, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import type { AuthSessionRecord } from "@/services/interfaces";
import { Button } from "@/shared/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/shared/ui/feedback-state";
import { InputField } from "@/shared/ui/input-field";
import { StatusBadge } from "@/shared/ui/status-badge";

interface SecuritySettingsProps {
  initialPasswordChangeRequired?: boolean;
  returnTo?: string;
}

function apiErrorCode(error: unknown): string | undefined {
  if (typeof error !== "object" || error === null || !("apiCode" in error)) {
    return undefined;
  }
  const code = (error as { apiCode?: unknown }).apiCode;
  return typeof code === "string" ? code : undefined;
}

function readableError(error: unknown): string {
  switch (apiErrorCode(error)) {
    case "PASSWORD_CURRENT_INVALID":
      return "当前密码不正确。";
    case "PASSWORD_POLICY_INVALID":
      return "新密码长度必须为 12 到 128 个字符。";
    case "PASSWORD_CHANGE_REQUIRED":
      return "请先修改密码。";
    case "AUTHENTICATION_REQUIRED":
      return "登录状态已失效，请重新登录。";
    default:
      return "操作失败，请稍后重试。";
  }
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function sessionLabel(record: AuthSessionRecord): string {
  if (record.userAgent && record.userAgent.length > 0) return record.userAgent;
  if (record.ipAddress && record.ipAddress.length > 0) return record.ipAddress;
  return "当前设备";
}

export function SecuritySettings({
  initialPasswordChangeRequired,
  returnTo,
}: SecuritySettingsProps) {
  const router = useRouter();
  const registry = useMemo(() => createBrowserServiceRegistry(), []);
  const [passwordChangeRequired, setPasswordChangeRequired] = useState(
    initialPasswordChangeRequired ?? false,
  );
  const [passwordStateReady, setPasswordStateReady] = useState(
    initialPasswordChangeRequired !== undefined,
  );
  const [sessions, setSessions] = useState<readonly AuthSessionRecord[] | null>(null);
  const [sessionStatus, setSessionStatus] = useState<"loading" | "ready" | "error">("loading");
  const [sessionError, setSessionError] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [passwordNotice, setPasswordNotice] = useState("");
  const [passwordSubmitting, setPasswordSubmitting] = useState(false);
  const [revokingSessionId, setRevokingSessionId] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    if (initialPasswordChangeRequired !== undefined) return;
    let active = true;
    void registry.auth.getSession()
      .then((session) => {
        if (!active) return;
        setPasswordChangeRequired(session.passwordChangeRequired);
        setPasswordStateReady(true);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setSessionError(readableError(error));
        setSessionStatus("error");
        setPasswordStateReady(true);
      });
    return () => {
      active = false;
    };
  }, [initialPasswordChangeRequired, registry]);

  useEffect(() => {
    if (!passwordStateReady || passwordChangeRequired) return;
    let active = true;
    void registry.auth.getSessions()
      .then((value) => {
        if (!active) return;
        setSessions(value);
        setSessionStatus("ready");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setSessionError(readableError(error));
        setSessionStatus("error");
      });
    return () => {
      active = false;
    };
  }, [passwordChangeRequired, passwordStateReady, registry]);

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPasswordError("");
    setPasswordNotice("");
    if (newPassword.length < 12 || newPassword.length > 128) {
      setPasswordError("新密码长度必须为 12 到 128 个字符。");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的新密码不一致。");
      return;
    }
    setPasswordSubmitting(true);
    try {
      await registry.auth.changePassword({ currentPassword, newPassword });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordChangeRequired(false);
      setPasswordNotice("密码已更新。");
      if (returnTo) {
        router.replace(returnTo);
      } else {
        router.refresh();
      }
    } catch (error: unknown) {
      setPasswordError(readableError(error));
    } finally {
      setPasswordSubmitting(false);
    }
  }

  async function revokeSession(sessionId: string) {
    setRevokingSessionId(sessionId);
    setSessionError("");
    try {
      await registry.auth.revokeSession(sessionId);
      setSessions((current) => current?.filter((record) => record.sessionId !== sessionId) ?? null);
    } catch (error: unknown) {
      setSessionError(readableError(error));
      setSessionStatus("error");
    } finally {
      setRevokingSessionId(null);
    }
  }

  async function signOut() {
    setSigningOut(true);
    try {
      await registry.auth.signOut();
      router.replace("/login");
      router.refresh();
    } catch (error: unknown) {
      setSessionError(readableError(error));
      setSessionStatus("error");
      setSigningOut(false);
    }
  }

  if (!passwordStateReady) {
    return <Skeleton label="正在加载账户安全" className="h-72" />;
  }

  return (
    <section className="mx-auto grid w-full max-w-[var(--mosaic-layout-content)] gap-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div className="flex items-center gap-3">
          <h1 className="text-[40px] font-semibold leading-[48px] tracking-[-0.055em] text-[var(--mosaic-color-ink)] lg:text-[56px] lg:leading-[64px]">
            账户安全
          </h1>
          {passwordChangeRequired ? <StatusBadge tone="warning">需要设置密码</StatusBadge> : null}
        </div>
        <Button variant="secondary" loading={signingOut} onClick={signOut}>
          <SignOut size={17} aria-hidden />退出登录
        </Button>
      </header>

      <section className="grid gap-5 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-5 md:p-6">
        <h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">
          {passwordChangeRequired ? "设置密码" : "修改密码"}
        </h2>
        <form className="grid max-w-xl gap-5" onSubmit={submitPassword}>
          <InputField
            id="current-password"
            label="当前密码"
            type="password"
            autoComplete="current-password"
            minLength={8}
            maxLength={1024}
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            disabled={passwordSubmitting}
            required
          />
          <InputField
            id="new-password"
            label="新密码"
            type="password"
            autoComplete="new-password"
            minLength={12}
            maxLength={128}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            disabled={passwordSubmitting}
            required
          />
          <InputField
            id="confirm-password"
            label="确认新密码"
            type="password"
            autoComplete="new-password"
            minLength={12}
            maxLength={128}
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            disabled={passwordSubmitting}
            required
          />
          {passwordError ? <p role="alert" className="text-sm text-[var(--mosaic-color-danger)]">{passwordError}</p> : null}
          {passwordNotice ? <p role="status" className="text-sm text-[var(--mosaic-color-success)]">{passwordNotice}</p> : null}
          <div>
            <Button type="submit" loading={passwordSubmitting}>保存密码</Button>
          </div>
        </form>
      </section>

      {!passwordChangeRequired ? (
        <section className="grid gap-5">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-semibold text-[var(--mosaic-color-ink)]">会话</h2>
            <Button
              variant="ghost"
              aria-label="刷新会话"
              loading={sessionStatus === "loading"}
              onClick={() => {
                setSessionStatus("loading");
                void registry.auth.getSessions()
                  .then((value) => {
                    setSessions(value);
                    setSessionError("");
                    setSessionStatus("ready");
                  })
                  .catch((error: unknown) => {
                    setSessionError(readableError(error));
                    setSessionStatus("error");
                  });
              }}
            >
              <ArrowClockwise size={17} aria-hidden />刷新
            </Button>
          </div>
          {sessionError ? (
            <ErrorState
              title="会话加载失败"
              description={sessionError}
              action={
                <Button variant="secondary" onClick={() => router.refresh()}>
                  重新加载
                </Button>
              }
            />
          ) : null}
          {sessionStatus === "loading" && sessions === null ? <Skeleton label="正在加载会话" className="h-40" /> : null}
          {sessionStatus !== "loading" && sessions && sessions.length === 0 ? (
            <EmptyState title="暂无活动会话" />
          ) : null}
          {sessions && sessions.length > 0 ? (
            <div className="grid gap-3">
              {sessions.map((record) => (
                <article
                  key={record.sessionId}
                  className="flex flex-wrap items-center justify-between gap-4 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-5"
                >
                  <div className="grid gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-[var(--mosaic-color-ink)]">{sessionLabel(record)}</span>
                      {record.current ? <StatusBadge tone="success">当前</StatusBadge> : null}
                    </div>
                    <p className="text-sm text-[var(--mosaic-color-ink-muted)]">
                      最近活动 {formatDate(record.lastSeenAt)} · 到期 {formatDate(record.expiresAt)}
                    </p>
                    {record.ipAddress ? <p className="text-xs text-[var(--mosaic-color-ink-muted)]">{record.ipAddress}</p> : null}
                  </div>
                  {!record.current ? (
                    <Button
                      variant="secondary"
                      loading={revokingSessionId === record.sessionId}
                      onClick={() => void revokeSession(record.sessionId)}
                    >
                      <X size={17} aria-hidden />撤销
                    </Button>
                  ) : null}
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {returnTo ? <Button variant="ghost" onClick={() => router.replace(returnTo)}>返回</Button> : null}
    </section>
  );
}
