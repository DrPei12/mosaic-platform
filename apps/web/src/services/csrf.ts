export const CSRF_COOKIE_NAME = "mosaic_csrf";
export const CSRF_HEADER_NAME = "X-CSRF-Token";

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,256}$/;

export function readCsrfToken(cookieSource?: string): string | undefined {
  const source = cookieSource ?? (
    typeof document === "undefined" ? "" : document.cookie
  );
  for (const part of source.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    const name = part.slice(0, separator).trim();
    if (name !== CSRF_COOKIE_NAME) continue;
    try {
      const value = decodeURIComponent(part.slice(separator + 1).trim());
      return TOKEN_PATTERN.test(value) ? value : undefined;
    } catch {
      return undefined;
    }
  }
  return undefined;
}

export function csrfRequestHeaders(): Record<string, string> {
  const token = readCsrfToken();
  return token === undefined ? {} : { [CSRF_HEADER_NAME]: token };
}
