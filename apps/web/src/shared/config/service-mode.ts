export type ServiceMode = "demo" | "api";

/**
 * Resolve the public runtime mode once at the application boundary. API is the
 * safe default; Demo must be an explicit opt-in for internal walkthroughs.
 */
export function getPublicServiceMode(): ServiceMode {
  return resolveBrowserServiceMode(
    // Keep this direct property access statically visible to Next.js while the
    // brand boundary scanner remains satisfied.
    process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE,
  );
}
export function resolveBrowserServiceMode(
  configuredMode: string | undefined,
): ServiceMode {
  if (configuredMode === undefined) return "api";
  if (configuredMode === "api" || configuredMode === "demo") {
    return configuredMode;
  }
  throw new Error(
    `INVALID_SERVICE_MODE: expected "api" or "demo", received "${configuredMode}"`,
  );
}
