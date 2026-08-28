import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockGetSummary = vi.hoisted(() => vi.fn());

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    usage: { getSummary: mockGetSummary },
  }),
}));

import { UsageDashboard } from "./usage-dashboard";

describe("UsageDashboard", () => {
  afterEach(() => {
    cleanup();
    mockGetSummary.mockReset();
  });

  it("does not expose an internal usage service error", async () => {
    const internalMessage = "BILLING_PROVIDER_DATABASE_INTERNAL";
    mockGetSummary.mockRejectedValueOnce(new Error(internalMessage));

    render(<UsageDashboard />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("用量数据暂时不可用，请稍后重试。");
    expect(alert).not.toHaveTextContent(internalMessage);
  });
});
