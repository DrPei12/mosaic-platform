import { describe, expect, it } from "vitest";

import { isProtectedRoute, normalizeReturnTo } from "./routes";

describe("protected route policy", () => {
  it.each([
    "/models",
    "/chat/abc",
    "/studio/video/wan-2-7",
    "/generations?status=running",
    "/usage",
  ])("accepts a local protected return target: %s", (value) => {
    expect(normalizeReturnTo(value)).toBe(value);
  });

  it.each([
    undefined,
    "https://evil.example/models",
    "//evil.example/models",
    "/login",
    "/models\\..\\login",
    "/unknown",
  ])("rejects an unsafe return target: %s", (value) => {
    expect(normalizeReturnTo(value)).toBe("/models");
  });

  it("matches complete protected prefixes only", () => {
    expect(isProtectedRoute("/generations/123")).toBe(true);
    expect(isProtectedRoute("/generations-archive")).toBe(false);
  });
});
