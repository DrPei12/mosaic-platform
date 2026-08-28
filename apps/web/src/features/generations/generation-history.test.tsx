import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GenerationJob } from "@/services/interfaces";

const mockList = vi.hoisted(() => vi.fn());

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    generation: { list: mockList },
  }),
}));

vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: ReactNode; href: string }) => (
    <a {...props}>{children}</a>
  ),
}));

import { ApiGenerationHistory } from "./generation-history";

const job: GenerationJob = {
  job_id: "job-001",
  product_model_id: "qwen-image-3-0-pro",
  modality: "image",
  status: "submitted_unknown",
  created_at: "2026-08-24T12:00:00.000Z",
  updated_at: "2026-08-24T12:00:01.000Z",
  completed_at: null,
  error_code: "GENERATION_SUBMITTED_UNKNOWN",
  reconciliation_pending: true,
  artifacts: [],
};

describe("ApiGenerationHistory", () => {
  beforeEach(() => {
    mockList.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("marks the last successful list as possibly stale after refresh failure", async () => {
    const user = userEvent.setup();
    mockList
      .mockResolvedValueOnce([job])
      .mockRejectedValueOnce(new Error("network unavailable"));

    render(<ApiGenerationHistory />);
    expect(await screen.findByText(job.job_id)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "刷新" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("生成任务暂时不可用，请稍后重试。");
    });
    const staleNotice = screen.getByText("上次成功数据").parentElement;
    expect(staleNotice).toHaveTextContent("上次成功数据");
    expect(staleNotice).toHaveTextContent("可能已过期");
    expect(screen.getByText(job.job_id)).toBeInTheDocument();
  });

  it("shows submitted_unknown as a warning with reconciliation guidance", async () => {
    mockList.mockResolvedValueOnce([job]);

    render(<ApiGenerationHistory />);

    expect(await screen.findByText("提交状态待确认")).toBeInTheDocument();
    expect(screen.getByText("待对账")).toBeInTheDocument();
    expect(screen.getByText("提交状态待确认")).toHaveClass(
      "border-[color-mix(in_srgb,var(--mosaic-color-warning)_35%,var(--mosaic-color-surface))]",
    );
  });
});
