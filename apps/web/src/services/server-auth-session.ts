import type { AuthSession } from "./interfaces";

export interface ServerSessionRequest {
  apiOrigin: string;
  cookieName: string;
  cookieValue: string;
  fetcher?: typeof fetch;
  signal?: AbortSignal;
}

export class ServerSessionUnavailableError extends Error {
  constructor(message = "AUTHENTICATION_UNAVAILABLE") {
    super(message);
    this.name = "ServerSessionUnavailableError";
  }
}

export function normalizeApiOrigin(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new ServerSessionUnavailableError();
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new ServerSessionUnavailableError();
  }
  return parsed.origin;
}

export function normalizeSessionCookieName(value: string): string {
  if (!/^[A-Za-z][A-Za-z0-9_-]{2,63}$/.test(value)) {
    throw new ServerSessionUnavailableError();
  }
  return value;
}

function isExactSession(value: unknown): value is AuthSession {
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
    keys.length !== 2 ||
    !keys.every((key) => key === "authenticated" || key === "passwordChangeRequired")
  ) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.authenticated === "boolean" &&
    typeof candidate.passwordChangeRequired === "boolean"
  );
}

export async function requestServerSession(
  input: ServerSessionRequest,
): Promise<AuthSession | null> {
  const origin = normalizeApiOrigin(input.apiOrigin);
  const cookieName = normalizeSessionCookieName(input.cookieName);
  let response: Response;
  try {
    response = await (input.fetcher ?? globalThis.fetch)(
      `${origin}/api/v1/auth/me`,
      {
        method: "GET",
        cache: "no-store",
        headers: {
          accept: "application/json",
          cookie: `${cookieName}=${encodeURIComponent(input.cookieValue)}`,
        },
        ...(input.signal === undefined ? {} : { signal: input.signal }),
      },
    );
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ServerSessionUnavailableError();
  }

  if (response.status === 401 || response.status === 403) return null;
  if (!response.ok) throw new ServerSessionUnavailableError();

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ServerSessionUnavailableError();
  }
  if (!isExactSession(body) || !body.authenticated) {
    throw new ServerSessionUnavailableError();
  }
  return {
    authenticated: true,
    passwordChangeRequired: body.passwordChangeRequired,
  };
}
