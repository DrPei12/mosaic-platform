import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReplace = vi.hoisted(() => vi.fn());
const mockRefresh = vi.hoisted(() => vi.fn());
const mockGetSession = vi.hoisted(() => vi.fn());
const mockGetSessions = vi.hoisted(() => vi.fn());
const mockChangePassword = vi.hoisted(() => vi.fn());
const mockRevokeSession = vi.hoisted(() => vi.fn());
const mockSignOut = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, refresh: mockRefresh }),
}));

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    auth: {
      getSession: mockGetSession,
      getSessions: mockGetSessions,
      changePassword: mockChangePassword,
      revokeSession: mockRevokeSession,
      signOut: mockSignOut,
    },
  }),
}));

import { SecuritySettings } from "./security-settings";

describe("SecuritySettings", () => {
  afterEach(() => {
    cleanup();
    mockReplace.mockReset();
    mockRefresh.mockReset();
    mockGetSession.mockReset();
    mockGetSessions.mockReset();
    mockChangePassword.mockReset();
    mockRevokeSession.mockReset();
    mockSignOut.mockReset();
  });

  it("keeps a first-login session on the password form until rotation succeeds", async () => {
    mockChangePassword.mockResolvedValue(undefined);
    mockGetSessions.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<SecuritySettings initialPasswordChangeRequired returnTo="/models" />);

    expect(screen.getByRole("heading", { name: "账户安全" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "设置密码" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "会话" })).not.toBeInTheDocument();
    expect(mockGetSessions).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("当前密码"), "temporary-credential");
    await user.type(screen.getByLabelText("新密码"), "a-valid-password-12");
    await user.type(screen.getByLabelText("确认新密码"), "a-valid-password-12");
    await user.click(screen.getByRole("button", { name: "保存密码" }));

    await waitFor(() => expect(mockChangePassword).toHaveBeenCalledWith({
      currentPassword: "temporary-credential",
      newPassword: "a-valid-password-12",
    }));
    expect(mockReplace).toHaveBeenCalledWith("/models");
  });

  it("loads and renders the current session for an unrestricted account", async () => {
    mockGetSessions.mockResolvedValue([
      {
        sessionId: "session-1",
        current: true,
        createdAt: "2026-08-26T12:00:00Z",
        lastSeenAt: "2026-08-26T12:05:00Z",
        expiresAt: "2026-08-26T20:00:00Z",
        ipAddress: "127.0.0.1",
        userAgent: "test-agent",
      },
    ]);
    render(<SecuritySettings initialPasswordChangeRequired={false} />);

    expect(await screen.findByText("test-agent")).toBeVisible();
    expect(screen.getByText("当前")).toBeVisible();
  });

  it("does not expose an internal session service error", async () => {
    const internalMessage = "AUTH_PROVIDER_DATABASE_INTERNAL";
    mockGetSessions.mockRejectedValueOnce(new Error(internalMessage));

    render(<SecuritySettings initialPasswordChangeRequired={false} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("操作失败，请稍后重试。");
    expect(alert).not.toHaveTextContent(internalMessage);
  });
});
