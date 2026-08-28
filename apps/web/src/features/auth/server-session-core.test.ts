import { describe, expect, it, vi } from "vitest";

import {
  requestServerSession,
  ServerSessionUnavailableError,
} from "./server-session-core";

function response(body: unknown, status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("server session verification", () => {
  it("forwards only the opaque session cookie to the internal API", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      response({ authenticated: true, passwordChangeRequired: false }, 200),
    );

    await expect(requestServerSession({
      apiOrigin: "http://api.internal:8000",
      cookieName: "mosaic_session",
      cookieValue: "opaque/value",
      fetcher,
    })).resolves.toEqual({ authenticated: true, passwordChangeRequired: false });

    expect(fetcher).toHaveBeenCalledWith(
      "http://api.internal:8000/api/v1/auth/me",
      expect.objectContaining({
        cache: "no-store",
        headers: {
          accept: "application/json",
          cookie: "mosaic_session=opaque%2Fvalue",
        },
      }),
    );
  });

  it.each([401, 403])("treats %s as unauthenticated", async (status) => {
    const fetcher = vi.fn().mockResolvedValue(response({}, status));
    await expect(requestServerSession({
      apiOrigin: "https://api.example.com",
      cookieName: "mosaic_session",
      cookieValue: "opaque",
      fetcher,
    })).resolves.toBeNull();
  });

  it.each([
    ["bad origin", "https://user:secret@api.example.com"],
    ["origin path", "https://api.example.com/internal"],
  ])("fails closed for %s", async (_label, apiOrigin) => {
    await expect(requestServerSession({
      apiOrigin,
      cookieName: "mosaic_session",
      cookieValue: "opaque",
      fetcher: vi.fn(),
    })).rejects.toBeInstanceOf(ServerSessionUnavailableError);
  });

  it.each([
    response({ authenticated: true, passwordChangeRequired: false, token: "leak" }, 200),
    response({ authenticated: false, passwordChangeRequired: false }, 200),
    response({}, 503),
  ])("fails closed for an invalid or unavailable response", async (apiResponse) => {
    await expect(requestServerSession({
      apiOrigin: "https://api.example.com",
      cookieName: "mosaic_session",
      cookieValue: "opaque",
      fetcher: vi.fn().mockResolvedValue(apiResponse),
    })).rejects.toBeInstanceOf(ServerSessionUnavailableError);
  });
});
