import type {
  AuthService,
  AuthSession,
  AuthSessionRecord,
} from "./interfaces";
import { csrfRequestHeaders } from "./csrf";

export interface ApiServiceErrorOptions {
  code: "AUTH_REQUEST_FAILED" | "AUTH_RESPONSE_INVALID";
  status: number;
  retryable: boolean;
  /** Public error code returned by the API, when the body was valid. */
  apiCode?: string;
  requestId?: string;
  message?: string;
}

export class ApiServiceError extends Error {
  readonly code: ApiServiceErrorOptions["code"];
  readonly status: number;
  readonly retryable: boolean;
  readonly apiCode: string | undefined;
  readonly requestId: string | undefined;

  constructor(options: ApiServiceErrorOptions) {
    super(options.message ?? options.code);
    this.name = "ApiServiceError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable;
    this.apiCode = options.apiCode;
    this.requestId = options.requestId;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

function unauthenticatedSession(): AuthSession {
  return { authenticated: false, passwordChangeRequired: false };
}

function isExactAuthSession(value: unknown): value is AuthSession {
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
    keys.length !== 2 ||
    !keys.every(
      (key) =>
        typeof key === "string" &&
        (key === "authenticated" || key === "passwordChangeRequired"),
    )
  ) {
    return false;
  }

  const candidate = value as {
    authenticated?: unknown;
    passwordChangeRequired?: unknown;
  };
  return (
    typeof candidate.authenticated === "boolean" &&
    typeof candidate.passwordChangeRequired === "boolean"
  );
}

function normalizeAuthSession(value: AuthSession): AuthSession {
  return {
    authenticated: value.authenticated,
    passwordChangeRequired: value.passwordChangeRequired,
  };
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(new Date(value).getTime());
}

function isExactAuthSessionRecord(value: unknown): value is AuthSessionRecord {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    return false;
  }
  const keys = Object.keys(value);
  if (
    keys.length !== 7 ||
    !keys.every((key) =>
      [
        "sessionId",
        "current",
        "createdAt",
        "lastSeenAt",
        "expiresAt",
        "ipAddress",
        "userAgent",
      ].includes(key),
    )
  ) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.sessionId === "string" && candidate.sessionId.length > 0 &&
    typeof candidate.current === "boolean" &&
    isTimestamp(candidate.createdAt) &&
    isTimestamp(candidate.lastSeenAt) &&
    isTimestamp(candidate.expiresAt) &&
    (candidate.ipAddress === null || typeof candidate.ipAddress === "string") &&
    (candidate.userAgent === null || typeof candidate.userAgent === "string")
  );
}

function normalizeAuthSessionRecord(value: AuthSessionRecord): AuthSessionRecord {
  return {
    sessionId: value.sessionId,
    current: value.current,
    createdAt: value.createdAt,
    lastSeenAt: value.lastSeenAt,
    expiresAt: value.expiresAt,
    ipAddress: value.ipAddress,
    userAgent: value.userAgent,
  };
}

function requestInit(signal?: AbortSignal): RequestInit {
  const init: RequestInit = {
    credentials: "include",
    headers: { accept: "application/json" },
  };
  if (signal !== undefined) init.signal = signal;
  return init;
}

function responseStatus(response: Response): number {
  return Number.isFinite(response.status) ? response.status : 0;
}

function isRetryableStatus(status: number): boolean {
  return status === 408 || status === 429 || status >= 500;
}

function requestFailure(response: Response, options: {
  apiCode?: string;
  requestId?: string;
  retryable?: boolean;
  message?: string;
} = {}): ApiServiceError {
  const status = responseStatus(response);
  return new ApiServiceError({
    code: "AUTH_REQUEST_FAILED",
    status,
    retryable: options.retryable ?? isRetryableStatus(status),
    ...options,
  });
}

function invalidResponse(status: number): ApiServiceError {
  return new ApiServiceError({
    code: "AUTH_RESPONSE_INVALID",
    status,
    retryable: false,
  });
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

async function readSession(response: Response): Promise<AuthSession> {
  const status = responseStatus(response);
  if (!response.ok) {
    if (status === 401) return unauthenticatedSession();
    if (status === 403) {
      const failure = await responseFailure(response);
      // A valid session can still be rejected when the browser origin is not
      // allowlisted. Preserve that actionable error instead of mislabelling
      // it as bad credentials. Unknown 403 bodies retain the legacy session
      // gate behavior for compatibility with auth middleware.
      if (failure.apiCode === "AUTH_ORIGIN_INVALID") throw failure;
      return unauthenticatedSession();
    }
    throw await responseFailure(response);
  }

  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw invalidResponse(status);
  }

  if (!isExactAuthSession(value)) throw invalidResponse(status);
  return normalizeAuthSession(value);
}

async function readSessions(response: Response): Promise<readonly AuthSessionRecord[]> {
  if (!response.ok) throw await responseFailure(response);
  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw invalidResponse(responseStatus(response));
  }
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    Object.getPrototypeOf(value) !== Object.prototype
  ) {
    throw invalidResponse(responseStatus(response));
  }
  const candidate = value as Record<string, unknown>;
  const keys = Object.keys(candidate);
  if (keys.length !== 1 || keys[0] !== "items" || !Array.isArray(candidate.items)) {
    throw invalidResponse(responseStatus(response));
  }
  if (!candidate.items.every(isExactAuthSessionRecord)) {
    throw invalidResponse(responseStatus(response));
  }
  return candidate.items.map(normalizeAuthSessionRecord);
}

interface PublicAuthError {
  error: {
    code: string;
    message: string;
    request_id: string;
    retryable: boolean;
    details?: Record<string, unknown> | null;
  };
}

function isPublicAuthError(value: unknown): value is PublicAuthError {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const candidate = value as { error?: unknown };
  if (
    typeof candidate.error !== "object" ||
    candidate.error === null ||
    Array.isArray(candidate.error)
  ) {
    return false;
  }
  const error = candidate.error as Record<string, unknown>;
  return (
    typeof error.code === "string" &&
    /^[A-Z0-9_]+$/.test(error.code) &&
    typeof error.message === "string" &&
    error.message.length > 0 &&
    typeof error.request_id === "string" &&
    error.request_id.length > 0 &&
    typeof error.retryable === "boolean" &&
    (error.details === undefined || error.details === null || (
      typeof error.details === "object" &&
      !Array.isArray(error.details)
    ))
  );
}

async function responseFailure(response: Response): Promise<ApiServiceError> {
  let value: unknown;
  try {
    value = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    return requestFailure(response);
  }

  if (!isPublicAuthError(value)) return requestFailure(response);
  const error = value.error;
  return requestFailure(response, {
    apiCode: error.code,
    requestId: error.request_id,
    retryable: error.retryable,
    message: error.message,
  });
}

export function createApiAuthService(fetcher: typeof fetch): AuthService {
  return {
    async getSession(signal) {
      return readSession(await fetcher("/api/v1/auth/me", requestInit(signal)));
    },
    async bootstrapLocalSession(signal) {
      const init: RequestInit = {
        ...requestInit(signal),
        method: "POST",
        cache: "no-store",
      };
      const response = await fetcher("/api/demo/session", init);
      if (response.status === 404) return unauthenticatedSession();
      return readSession(response);
    },
    async signIn(input, signal) {
      const init: RequestInit = {
        ...requestInit(signal),
        method: "POST",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          ...csrfRequestHeaders(),
        },
        body: JSON.stringify({
          account: input.account,
          password: input.password,
          ...(input.tenantSlug === undefined ? {} : { tenant_slug: input.tenantSlug }),
        }),
      };
      return readSession(await fetcher("/api/v1/auth/login", init));
    },
    async register(input, signal) {
      const init: RequestInit = {
        ...requestInit(signal),
        method: "POST",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          ...csrfRequestHeaders(),
        },
        body: JSON.stringify({
          email: input.email,
          password: input.password,
          tenant_name: input.tenantName,
          tenant_slug: input.tenantSlug,
        }),
      };
      return readSession(await fetcher("/api/v1/auth/register", init));
    },
    async signOut(signal) {
      const init: RequestInit = {
        ...requestInit(signal),
        method: "POST",
        headers: {
          accept: "application/json",
          ...csrfRequestHeaders(),
        },
      };
      const response = await fetcher("/api/v1/auth/logout", init);
      if (!response.ok) throw await responseFailure(response);
    },
    async changePassword(input, signal) {
      const response = await fetcher("/api/v1/auth/password/change", {
        ...requestInit(signal),
        method: "POST",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          ...csrfRequestHeaders(),
        },
        body: JSON.stringify({
          current_password: input.currentPassword,
          new_password: input.newPassword,
        }),
      });
      if (!response.ok) throw await responseFailure(response);
    },
    async getSessions(signal) {
      return readSessions(await fetcher("/api/v1/auth/sessions", requestInit(signal)));
    },
    async revokeSession(sessionId, signal) {
      const response = await fetcher(
        `/api/v1/auth/sessions/${encodeURIComponent(sessionId)}`,
        {
          ...requestInit(signal),
          method: "DELETE",
          headers: {
            accept: "application/json",
            ...csrfRequestHeaders(),
          },
        },
      );
      if (!response.ok) throw await responseFailure(response);
    },
  };
}
