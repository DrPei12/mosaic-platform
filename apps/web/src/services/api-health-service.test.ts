import { describe, expect, it, vi } from "vitest";
import { createApiHealthService } from "./api-health-service";

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("API health service", () => {
  it("normalizes an exact health response and adds evidence", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      response({ service: "mosaic-api", status: "ready", version: "0.1.0" }),
    );
    const service = createApiHealthService(fetcher);

    const health = await service.getStatus();

    expect(health).toEqual({
      service: "mosaic-api",
      status: "ready",
      version: "0.1.0",
      evidence: "provider_unverified",
    });
    expect(Object.keys(health).sort()).toEqual([
      "evidence",
      "service",
      "status",
      "version",
    ]);
  });

  it.each([
    ["wrong service", { service: "other-api", status: "ready", version: "0.1.0" }],
    ["wrong status", { service: "mosaic-api", status: "starting", version: "0.1.0" }],
    ["empty version", { service: "mosaic-api", status: "ready", version: "" }],
    [
      "extra field",
      { service: "mosaic-api", status: "ready", version: "0.1.0", password: "secret" },
    ],
  ])("rejects %s health responses", async (_name, body) => {
    const fetcher = vi.fn().mockResolvedValue(response(body));
    const service = createApiHealthService(fetcher);

    await expect(service.getStatus()).rejects.toMatchObject({
      code: "API_NOT_READY",
      status: 200,
      retryable: false,
    });
  });

  it("throws API_NOT_READY for a non-ok response", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ status: "down" }, 503));
    const service = createApiHealthService(fetcher);

    await expect(service.getStatus()).rejects.toMatchObject({
      code: "API_NOT_READY",
      status: 503,
      retryable: true,
    });
  });

  it("rethrows a body-read AbortError unchanged", async () => {
    const abortError = new DOMException("body read aborted", "AbortError");
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw abortError;
      },
    } as unknown as Response);
    const service = createApiHealthService(fetcher);

    await expect(service.getStatus()).rejects.toBe(abortError);
  });

  it("forwards an abort signal with the JSON accept header", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      response({ service: "mosaic-api", status: "ok", version: "0.1.0" }),
    );
    const service = createApiHealthService(fetcher);
    const controller = new AbortController();

    await service.getStatus(controller.signal);

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/health/ready",
      expect.objectContaining({
        headers: { accept: "application/json" },
        signal: controller.signal,
      }),
    );
  });
});
