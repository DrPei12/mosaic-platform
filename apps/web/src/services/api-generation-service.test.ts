import { describe, expect, it, vi } from "vitest";

import {
  GenerationServiceError,
  type GenerationJob,
} from "./interfaces";
import { createApiGenerationService } from "./api-generation-service";

const job: GenerationJob = {
  job_id: "job-001",
  product_model_id: "qwen-image-3-0-pro",
  modality: "image",
  status: "queued",
  created_at: "2026-08-24T12:00:00.000Z",
  updated_at: "2026-08-24T12:00:01.000Z",
  completed_at: null,
  error_code: null,
  reconciliation_pending: false,
  artifacts: [],
};

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("API generation service", () => {
  it("lists recent tenant-scoped jobs", async () => {
    const fetcher = vi.fn().mockResolvedValue(response([job]));
    const service = createApiGenerationService(fetcher);

    await expect(service.list()).resolves.toEqual([job]);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/generations?limit=50",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("creates a generation with the provider-neutral request envelope", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(job, 202));
    const service = createApiGenerationService(fetcher);

    await expect(service.create({
      productModelId: job.product_model_id,
      modality: "image",
      input: { prompt: "a mountain", size: "1024*1024", count: 1 },
      clientRequestId: "request-001",
    })).resolves.toEqual(job);

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/generations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          product_model_id: job.product_model_id,
          modality: "image",
          input: { prompt: "a mountain", size: "1024*1024", count: 1 },
          client_request_id: "request-001",
        }),
        headers: expect.objectContaining({
          "Idempotency-Key": "request-001",
          "content-type": "application/json",
        }),
      }),
    );
  });

  it("reads a job by encoded job id", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(job));
    const service = createApiGenerationService(fetcher);

    await expect(service.get("job/with space")).resolves.toEqual(job);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/generations/job%2Fwith%20space",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("cancels and deletes with CSRF-protected methods", async () => {
    const token = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
    document.cookie = `mosaic_csrf=${token}; Path=/`;
    const fetcher = vi.fn().mockResolvedValue(response(undefined, 204));
    const service = createApiGenerationService(fetcher);
    try {
      await service.cancel("job/1");
      await service.delete("job/1");
    } finally {
      document.cookie = "mosaic_csrf=; Max-Age=0; Path=/";
    }

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/generations/job%2F1/cancel",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-CSRF-Token": token }),
      }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/generations/job%2F1",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({ "X-CSRF-Token": token }),
      }),
    );
  });

  it("preserves a stable public error code and request id", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({
      error: {
        code: "GENERATION_SUBMISSION_DISABLED",
        message: "生成任务处理基础设施尚未配置",
        request_id: "req-001",
        retryable: true,
      },
    }, 503));
    const service = createApiGenerationService(fetcher);

    await expect(service.create({
      productModelId: job.product_model_id,
      modality: "image",
      input: { prompt: "a mountain" },
      clientRequestId: "request-001",
    })).rejects.toMatchObject({
      code: "GENERATION_SUBMISSION_DISABLED",
      status: 503,
      retryable: true,
      requestId: "req-001",
    });
    await expect(service.create({
      productModelId: job.product_model_id,
      modality: "image",
      input: { prompt: "a mountain" },
      clientRequestId: "request-002",
    })).rejects.toBeInstanceOf(GenerationServiceError);
  });

  it("fails closed on an invalid job response", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ ...job, status: "unknown" }));
    const service = createApiGenerationService(fetcher);

    await expect(service.get(job.job_id)).rejects.toMatchObject({
      code: "GENERATION_RESPONSE_INVALID",
      retryable: false,
    });
  });
});
