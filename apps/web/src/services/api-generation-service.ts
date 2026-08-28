import {
  GenerationServiceError,
  type GenerationArtifact,
  type GenerationJob,
  type GenerationServiceErrorCode,
  type GenerationService,
} from "./interfaces";
import { csrfRequestHeaders } from "./csrf";

const MODALITIES = new Set(["text", "image", "video", "audio"]);
const STATUSES = new Set([
  "accepted",
  "reserved",
  "submitted",
  "submitted_unknown",
  "queued",
  "running",
  "storing",
  "succeeded",
  "failed",
  "cancelled",
  "expired",
]);
const ARTIFACT_KINDS = new Set(["input", "output", "thumbnail", "preview"]);
const ARTIFACT_STATUSES = new Set(["pending", "ready", "expired", "deleted"]);
const PUBLIC_ERROR_CODES = new Set([
  "MODEL_UNAVAILABLE",
  "IDEMPOTENCY_CONFLICT",
  "IDEMPOTENCY_IN_PROGRESS",
  "GENERATION_NOT_FOUND",
  "GENERATION_STATE_CONFLICT",
  "GENERATION_SUBMISSION_DISABLED",
  "GENERATION_PERSISTENCE_UNAVAILABLE",
  "GENERATION_WORKER_NOT_CONFIGURED",
  "REQUEST_VALIDATION_FAILED",
]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

function exactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  return (
    Object.keys(value).every((key) => allowed.has(key)) &&
    required.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

const RFC3339_DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

function isoTimestamp(value: unknown): value is string {
  if (!nonEmptyString(value) || !RFC3339_DATE_TIME.test(value)) return false;
  const parts = value.match(RFC3339_DATE_TIME);
  if (!parts) return false;
  const year = Number(parts[1]);
  const month = Number(parts[2]);
  const day = Number(parts[3]);
  const hour = Number(parts[4]);
  const minute = Number(parts[5]);
  const second = Number(parts[6]);
  const timezone = parts[7]!;
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > monthDays[month - 1]! ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) return false;
  if (timezone !== "Z") {
    const offset = timezone.match(/^[+-](\d{2}):(\d{2})$/);
    if (!offset || Number(offset[1]) > 23 || Number(offset[2]) > 59) return false;
  }
  return !Number.isNaN(new Date(value).getTime());
}

function isArtifact(value: unknown): value is GenerationArtifact {
  if (!isPlainObject(value)) return false;
  return (
    exactKeys(value, ["artifact_id", "kind", "status", "mime_type", "size_bytes"]) &&
    nonEmptyString(value.artifact_id) &&
    typeof value.kind === "string" &&
    ARTIFACT_KINDS.has(value.kind) &&
    typeof value.status === "string" &&
    ARTIFACT_STATUSES.has(value.status) &&
    nonEmptyString(value.mime_type) &&
    Number.isInteger(value.size_bytes) &&
    (value.size_bytes as number) >= 0
  );
}

function isGenerationJob(value: unknown): value is GenerationJob {
  if (!isPlainObject(value)) return false;
  return (
    exactKeys(value, [
      "job_id",
      "product_model_id",
      "modality",
      "status",
      "created_at",
      "updated_at",
      "completed_at",
      "error_code",
      "reconciliation_pending",
      "artifacts",
    ]) &&
    nonEmptyString(value.job_id) &&
    nonEmptyString(value.product_model_id) &&
    typeof value.modality === "string" &&
    MODALITIES.has(value.modality) &&
    typeof value.status === "string" &&
    STATUSES.has(value.status) &&
    isoTimestamp(value.created_at) &&
    isoTimestamp(value.updated_at) &&
    (value.completed_at === null || isoTimestamp(value.completed_at)) &&
    (value.error_code === null || (
      nonEmptyString(value.error_code) && /^[A-Z0-9_]+$/.test(value.error_code)
    )) &&
    typeof value.reconciliation_pending === "boolean" &&
    Array.isArray(value.artifacts) &&
    value.artifacts.every(isArtifact)
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

function statusOf(response: Response): number {
  return Number.isFinite(response.status) ? response.status : 0;
}

function fallbackCode(status: number): "GENERATION_NOT_FOUND" | "GENERATION_UNAVAILABLE" {
  return status === 404 ? "GENERATION_NOT_FOUND" : "GENERATION_UNAVAILABLE";
}

function errorCode(
  value: unknown,
  fallback: "GENERATION_NOT_FOUND" | "GENERATION_UNAVAILABLE",
): GenerationServiceErrorCode {
  if (!isPlainObject(value) || !isPlainObject(value.error)) return fallback;
  const candidate = value.error.code;
  return typeof candidate === "string" && PUBLIC_ERROR_CODES.has(candidate)
    ? candidate as GenerationServiceErrorCode
    : fallback;
}

async function responseError(
  response: Response,
): Promise<GenerationServiceError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
  }

  const fallback = fallbackCode(statusOf(response));
  const code = errorCode(body, fallback);
  const errorBody = isPlainObject(body) && isPlainObject(body.error)
    ? body.error
    : undefined;
  const message = errorBody && typeof errorBody.message === "string"
    ? errorBody.message
    : undefined;
  const requestId = errorBody && typeof errorBody.request_id === "string"
    ? errorBody.request_id
    : undefined;
  const retryable = errorBody && typeof errorBody.retryable === "boolean"
    ? errorBody.retryable
    : statusOf(response) === 408 || statusOf(response) === 429 || statusOf(response) >= 500;

  return new GenerationServiceError({
    code,
    status: statusOf(response),
    retryable,
    ...(requestId === undefined ? {} : { requestId }),
    ...(message === undefined ? {} : { message }),
  });
}

function requestInit(signal?: AbortSignal, body?: unknown, idempotencyKey?: string): RequestInit {
  return {
    credentials: "include",
    method: body === undefined ? "GET" : "POST",
    ...(signal === undefined ? {} : { signal }),
    headers: {
      accept: "application/json",
      ...(body === undefined ? {} : { "content-type": "application/json" }),
      ...(idempotencyKey === undefined ? {} : { "Idempotency-Key": idempotencyKey }),
      ...(body === undefined ? {} : csrfRequestHeaders()),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  };
}

function mutationInit(method: "POST" | "DELETE", signal?: AbortSignal): RequestInit {
  return {
    credentials: "include",
    method,
    ...(signal === undefined ? {} : { signal }),
    headers: {
      accept: "application/json",
      ...csrfRequestHeaders(),
    },
  };
}

async function readJob(response: Response): Promise<GenerationJob> {
  if (!response.ok) throw await responseError(response);
  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new GenerationServiceError({
      code: "GENERATION_RESPONSE_INVALID",
      status: statusOf(response),
      retryable: false,
      message: "生成任务响应格式无效",
    });
  }
  if (!isGenerationJob(value)) {
    throw new GenerationServiceError({
      code: "GENERATION_RESPONSE_INVALID",
      status: statusOf(response),
      retryable: false,
      message: "生成任务响应格式无效",
    });
  }
  return {
    ...value,
    artifacts: value.artifacts.map((artifact) => ({ ...artifact })),
  };
}

async function readJobs(response: Response): Promise<readonly GenerationJob[]> {
  if (!response.ok) throw await responseError(response);
  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    value = undefined;
  }
  if (!Array.isArray(value) || !value.every(isGenerationJob)) {
    throw new GenerationServiceError({
      code: "GENERATION_RESPONSE_INVALID",
      status: statusOf(response),
      retryable: false,
      message: "生成任务列表响应格式无效",
    });
  }
  return value.map((job) => ({
    ...job,
    artifacts: job.artifacts.map((artifact) => ({ ...artifact })),
  }));
}

export function createApiGenerationService(fetcher: typeof fetch): GenerationService {
  return {
    async list(signal) {
      return readJobs(await fetcher(
        "/api/v1/generations?limit=50",
        requestInit(signal),
      ));
    },

    async create(input, signal) {
      const body = {
        product_model_id: input.productModelId,
        modality: input.modality,
        input: input.input,
        client_request_id: input.clientRequestId,
      };
      return readJob(await fetcher(
        "/api/v1/generations",
        requestInit(signal, body, input.clientRequestId),
      ));
    },

    async get(jobId, signal) {
      return readJob(await fetcher(
        `/api/v1/generations/${encodeURIComponent(jobId)}`,
        requestInit(signal),
      ));
    },

    async cancel(jobId, signal) {
      const response = await fetcher(
        `/api/v1/generations/${encodeURIComponent(jobId)}/cancel`,
        mutationInit("POST", signal),
      );
      if (!response.ok) throw await responseError(response);
    },

    async delete(jobId, signal) {
      const response = await fetcher(
        `/api/v1/generations/${encodeURIComponent(jobId)}`,
        mutationInit("DELETE", signal),
      );
      if (!response.ok) throw await responseError(response);
    },
  };
}
