import { describe, expect, it, vi } from "vitest";
import {
  ApiServiceError,
  createApiAuthService,
} from "./api-auth-service";

function response(body: unknown, status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("API auth service", () => {
  it("forwards the double-submit CSRF token on logout", async () => {
    const token = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
    document.cookie = `mosaic_csrf=${token}; Path=/`;
    const fetcher = vi.fn().mockResolvedValue(response(undefined, 204));
    const service = createApiAuthService(fetcher);

    try {
      await service.signOut();
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/auth/logout",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "X-CSRF-Token": token }),
        }),
      );
    } finally {
      document.cookie = "mosaic_csrf=; Max-Age=0; Path=/";
    }
  });

  it("posts a password change with CSRF and the 12-character policy payload", async () => {
    const token = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
    document.cookie = `mosaic_csrf=${token}; Path=/`;
    const fetcher = vi.fn().mockResolvedValue(response(undefined, 204));
    const service = createApiAuthService(fetcher);

    try {
      await service.changePassword({
        currentPassword: "temporary-credential",
        newPassword: "a-valid-password-12",
      });
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/auth/password/change",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "X-CSRF-Token": token }),
          body: JSON.stringify({
            current_password: "temporary-credential",
            new_password: "a-valid-password-12",
          }),
        }),
      );
    } finally {
      document.cookie = "mosaic_csrf=; Max-Age=0; Path=/";
    }
  });

  it("parses the strict session management response", async () => {
    const session = {
      sessionId: "session-1",
      current: true,
      createdAt: "2026-08-26T12:00:00Z",
      lastSeenAt: "2026-08-26T12:05:00Z",
      expiresAt: "2026-08-26T20:00:00Z",
      ipAddress: "127.0.0.1",
      userAgent: "test-agent",
    };
    const fetcher = vi.fn().mockResolvedValue(response({ items: [session] }, 200));
    const service = createApiAuthService(fetcher);

    await expect(service.getSessions()).resolves.toEqual([session]);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/sessions",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("encodes a revoked session id and forwards CSRF", async () => {
    const token = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
    document.cookie = `mosaic_csrf=${token}; Path=/`;
    const fetcher = vi.fn().mockResolvedValue(response(undefined, 204));
    const service = createApiAuthService(fetcher);

    try {
      await service.revokeSession("session/one");
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/auth/sessions/session%2Fone",
        expect.objectContaining({
          method: "DELETE",
          headers: expect.objectContaining({ "X-CSRF-Token": token }),
        }),
      );
    } finally {
      document.cookie = "mosaic_csrf=; Max-Age=0; Path=/";
    }
  });

  it("maps registration fields to the native API contract", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({
      authenticated: true,
      passwordChangeRequired: false,
    }, 201));
    const service = createApiAuthService(fetcher);

    await expect(service.register({
      email: "owner@example.com",
      password: "correct-password",
      tenantName: "Example Workspace",
      tenantSlug: "example-workspace",
    })).resolves.toEqual({ authenticated: true, passwordChangeRequired: false });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/register",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          email: "owner@example.com",
          password: "correct-password",
          tenant_name: "Example Workspace",
          tenant_slug: "example-workspace",
        }),
      }),
    );
  });

  it("preserves public registration errors for the UI", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({
      error: {
        code: "REGISTRATION_UNAVAILABLE",
        message: "注册功能暂未开放",
        request_id: "req-register-001",
        retryable: false,
      },
    }, 409));
    const service = createApiAuthService(fetcher);

    await expect(service.register({
      email: "owner@example.com",
      password: "correct-password",
      tenantName: "Example Workspace",
      tenantSlug: "example-workspace",
    })).rejects.toMatchObject({
      code: "AUTH_REQUEST_FAILED",
      apiCode: "REGISTRATION_UNAVAILABLE",
      requestId: "req-register-001",
      status: 409,
    });
  });

  it.each([401, 403])("maps %s to a fresh unauthenticated session", async (status) => {
    const fetcher = vi.fn().mockResolvedValue(response({ ignored: true }, status));
    const service = createApiAuthService(fetcher);

    const first = await service.getSession();
    const second = await service.signIn({ account: "demo", password: "secret" });

    expect(first).toEqual({ authenticated: false, passwordChangeRequired: false });
    expect(second).toEqual({ authenticated: false, passwordChangeRequired: false });
    expect(first).not.toBe(second);
  });

  it.each([
    ["getSession", (service: ReturnType<typeof createApiAuthService>) => service.getSession()],
    [
      "signIn",
      (service: ReturnType<typeof createApiAuthService>) =>
        service.signIn({ account: "demo", password: "secret" }),
    ],
  ])("throws a typed error for a non-auth API failure (%s)", async (_name, invoke) => {
    const fetcher = vi.fn().mockResolvedValue(response({ error: "down" }, 500));
    const service = createApiAuthService(fetcher);

    await expect(invoke(service)).rejects.toMatchObject({
      code: "AUTH_REQUEST_FAILED",
      status: 500,
      retryable: true,
    });
    await expect(invoke(service)).rejects.toBeInstanceOf(ApiServiceError);
  });

  it("throws a typed error when logout fails", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ error: "down" }, 500));
    const service = createApiAuthService(fetcher);

    await expect(service.signOut()).rejects.toMatchObject({
      code: "AUTH_REQUEST_FAILED",
      status: 500,
      retryable: true,
    });
  });

  it("marks a non-retryable client failure correctly", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ error: "bad request" }, 400));
    const service = createApiAuthService(fetcher);

    await expect(service.signIn({ account: "demo", password: "secret" })).rejects.toMatchObject({
      code: "AUTH_REQUEST_FAILED",
      status: 400,
      retryable: false,
    });
  });

  it.each([
    ["malformed JSON", () => {
      throw new Error("invalid json");
    }],
    ["malformed session", () => ({ authenticated: "yes", passwordChangeRequired: false })],
    [
      "extra password field",
      () => ({ authenticated: true, passwordChangeRequired: false, password: "secret" }),
    ],
  ])("rejects %s response bodies", async (_name, bodyFactory) => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => bodyFactory(),
    } as unknown as Response);
    const service = createApiAuthService(fetcher);

    await expect(service.getSession()).rejects.toMatchObject({
      code: "AUTH_RESPONSE_INVALID",
      status: 200,
      retryable: false,
    });
  });

  it("normalizes a valid session to an exact fresh object", async () => {
    const body = { authenticated: true, passwordChangeRequired: false };
    const fetcher = vi.fn().mockResolvedValue(response(body, 200));
    const service = createApiAuthService(fetcher);

    const session = await service.getSession();

    expect(session).toEqual(body);
    expect(session).not.toBe(body);
    expect(Object.keys(session).sort()).toEqual([
      "authenticated",
      "passwordChangeRequired",
    ]);
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
    const service = createApiAuthService(fetcher);

    await expect(service.getSession()).rejects.toBe(abortError);
  });

  it("forwards an abort signal in strict request init", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({
      authenticated: false,
      passwordChangeRequired: false,
    }, 200));
    const service = createApiAuthService(fetcher);
    const controller = new AbortController();

    await service.getSession(controller.signal);

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/me",
      expect.objectContaining({ signal: controller.signal }),
    );
  });
});
