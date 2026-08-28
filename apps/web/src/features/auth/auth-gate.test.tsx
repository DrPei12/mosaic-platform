import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReplace = vi.hoisted(() => vi.fn());
const mockGetSession = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    auth: { getSession: mockGetSession },
  }),
}));

import { AuthGate } from "./auth-gate";

describe("AuthGate", () => {
  afterEach(() => {
    cleanup();
    mockReplace.mockReset();
    mockGetSession.mockReset();
  });

  it("uses real account verification copy in API mode", () => {
    mockGetSession.mockReturnValue(new Promise(() => undefined));

    render(
      <AuthGate mode="api">
        <p>protected content</p>
      </AuthGate>,
    );

    expect(screen.getByRole("status", { name: "正在验证登录状态" })).toBeVisible();
    expect(screen.queryByText(/演示/)).not.toBeInTheDocument();
  });

  it("uses the same account verification copy in Demo mode", () => {
    mockGetSession.mockReturnValue(new Promise(() => undefined));

    render(
      <AuthGate mode="demo">
        <p>protected content</p>
      </AuthGate>,
    );

    expect(screen.getByRole("status", { name: "正在验证登录状态" })).toBeVisible();
  });
});
