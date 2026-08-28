import type { HealthResponse } from "@mosaic/contracts";
import type { HealthService } from "./interfaces";

export const API_NOT_READY = "API_NOT_READY";

export interface ApiHealthServiceErrorOptions {
  status: number;
  retryable: boolean;
}

export class ApiHealthServiceError extends Error {
  readonly code = API_NOT_READY;
  readonly status: number;
  readonly retryable: boolean;

  constructor(options: ApiHealthServiceErrorOptions) {
    super(API_NOT_READY);
    this.name = "ApiHealthServiceError";
    this.status = options.status;
    this.retryable = options.retryable;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

function requestInit(signal?: AbortSignal): RequestInit {
  const init: RequestInit = {
    headers: { accept: "application/json" },
  };
  if (signal !== undefined) init.signal = signal;
  return init;
}

function isExactHealthResponse(value: unknown): value is HealthResponse {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    return false;
  }

  const keys = Reflect.ownKeys(value);
  if (
    keys.length !== 3 ||
    !keys.every(
      (key) =>
        typeof key === "string" &&
        (key === "service" || key === "status" || key === "version"),
    )
  ) {
    return false;
  }

  const candidate = value as {
    service?: unknown;
    status?: unknown;
    version?: unknown;
  };
  return (
    candidate.service === "mosaic-api" &&
    (candidate.status === "ok" || candidate.status === "ready") &&
    typeof candidate.version === "string" &&
    candidate.version.trim().length > 0
  );
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

function notReady(response: Response): ApiHealthServiceError {
  return new ApiHealthServiceError({
    status: Number.isFinite(response.status) ? response.status : 0,
    retryable: response.status >= 500,
  });
}

function invalidHealthResponse(status: number): ApiHealthServiceError {
  return new ApiHealthServiceError({ status, retryable: false });
}

export function createApiHealthService(fetcher: typeof fetch): HealthService {
  return {
    async getStatus(signal) {
      const response = await fetcher(
        "/api/v1/health/ready",
        requestInit(signal),
      );
      if (!response.ok) throw notReady(response);

      let value: unknown;
      try {
        value = await response.json();
      } catch (error) {
        if (isAbortError(error)) throw error;
        throw invalidHealthResponse(response.status);
      }
      if (!isExactHealthResponse(value)) {
        throw invalidHealthResponse(response.status);
      }

      return {
        service: value.service,
        status: value.status,
        version: value.version,
        evidence: "provider_unverified",
      };
    },
  };
}
