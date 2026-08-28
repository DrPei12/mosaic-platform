import { afterEach, describe, expect, it } from "vitest";

import {
  CSRF_HEADER_NAME,
  csrfRequestHeaders,
  readCsrfToken,
} from "./csrf";

const TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";

afterEach(() => {
  document.cookie = "mosaic_csrf=; Max-Age=0; Path=/";
});

describe("CSRF request helper", () => {
  it("reads only the exact URL-safe CSRF cookie", () => {
    expect(readCsrfToken(`other=value; mosaic_csrf=${TOKEN}; suffix=value`)).toBe(TOKEN);
    expect(readCsrfToken(`mosaic_csrf=${encodeURIComponent(TOKEN)}`)).toBe(TOKEN);
  });

  it.each([
    "",
    "mosaic_csrf=short",
    "mosaic_csrf=contains%20space",
    "mosaic_csrf=%E0%A4%A",
    `mosaic_csrfx=${TOKEN}`,
  ])("rejects a missing or malformed token (%s)", (source) => {
    expect(readCsrfToken(source)).toBeUndefined();
  });

  it("adds the token to unsafe API requests without persisting it", () => {
    document.cookie = `mosaic_csrf=${TOKEN}; Path=/`;

    expect(csrfRequestHeaders()).toEqual({ [CSRF_HEADER_NAME]: TOKEN });
  });
});
