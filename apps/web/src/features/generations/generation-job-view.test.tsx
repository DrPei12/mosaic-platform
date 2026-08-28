import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  get: vi.fn(),
  cancel: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
}));

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    generation: {
      get: mocks.get,
      cancel: mocks.cancel,
      delete: mocks.delete,
    },
  }),
}));

import type { GenerationJob } from "@/services/interfaces";
import { GenerationJobView } from "./generation-job-view";

const job: GenerationJob = {
  job_id: "job-001",
  product_model_id: "qwen-image-3-0-pro",
  modality: "image",
  status: "failed",
  created_at: "2026-08-24T12:00:00.000Z",
  updated_at: "2026-08-24T12:00:01.000Z",
  completed_at: "2026-08-24T12:00:01.000Z",
  error_code: "GENERATION_PROVIDER_TASK_FAILED",
  reconciliation_pending: false,
  artifacts: [],
};

describe("GenerationJobView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => cleanup());

  it("maps internal job error codes without rendering the code", async () => {
    mocks.get.mockResolvedValueOnce(job);

    render(<GenerationJobView jobId={job.job_id} />);

    expect(await screen.findByTestId("generation-job-view")).toBeInTheDocument();
    expect(screen.getByText("生成未完成，请稍后重试。")).toBeInTheDocument();
    expect(screen.queryByText("GENERATION_PROVIDER_TASK_FAILED")).not.toBeInTheDocument();
  });

  it("does not render an internal Error message when loading fails", async () => {
    const internalMessage = "provider deployment endpoint details";
    mocks.get.mockRejectedValueOnce(new Error(internalMessage));

    render(<GenerationJobView jobId={job.job_id} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("生成任务暂时不可用，请稍后重试。");
    expect(alert).not.toHaveTextContent(internalMessage);
  });
});
