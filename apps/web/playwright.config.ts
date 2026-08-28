import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";

function resolveBrowserExecutable(): string | undefined {
  const explicit = process.env.MOSAIC_E2E_BROWSER_EXECUTABLE?.trim();
  if (explicit && existsSync(explicit)) return explicit;

  // The repository may be checked out on a Windows machine without the
  // Playwright browser bundle. Keep this best-effort and cross-platform: CI
  // on other operating systems falls back to its bundled browser.
  const candidates = process.platform === "win32"
    ? [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
        "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      ]
    : [];
  return candidates.find((candidate) => existsSync(candidate));
}

function portFromEnv(name: string, fallback: number): number {
  const value = process.env[name];
  if (value === undefined || value.trim() === "") return fallback;

  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535`);
  }

  return port;
}

const webPort = portFromEnv("MOSAIC_E2E_WEB_PORT", 3100);
const apiPort = portFromEnv("MOSAIC_E2E_API_PORT", 8100);
if (webPort === apiPort) {
  throw new Error(
    `MOSAIC_E2E_WEB_PORT (${webPort}) and MOSAIC_E2E_API_PORT (${apiPort}) must be different`,
  );
}

const webOrigin = `http://127.0.0.1:${webPort}`;
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const unavailableDatabaseUrl =
  "postgresql+asyncpg://mosaic:mosaic@127.0.0.1:1/mosaic";
const browserExecutable = resolveBrowserExecutable();

const browserLaunchOptions = browserExecutable
  ? {
      launchOptions: {
        executablePath: browserExecutable,
        // Installed Chrome may attempt to load stale enterprise extensions
        // from the user profile; E2E must use an isolated extension-free
        // process while preserving the explicit/system-browser fallback.
        args: ["--disable-extensions"],
      },
    }
  : {};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: webOrigin,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `pnpm build && pnpm exec next start --hostname 127.0.0.1 --port ${webPort}`,
      url: webOrigin,
      env: {
        ...process.env,
        MOSAIC_API_ORIGIN: apiOrigin,
        // Existing visual and interaction suites exercise the explicitly
        // seeded internal demo. Production/API E2E sets
        // MOSAIC_E2E_SERVICE_MODE=api and is a separate acceptance gate.
        NEXT_PUBLIC_MOSAIC_SERVICE_MODE:
          process.env.MOSAIC_E2E_SERVICE_MODE ?? "demo",
        MOSAIC_E2E_USE_NEXT_START: "true",
      },
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command:
        `uv run --project ../api uvicorn app.main:app --app-dir ../api --host 127.0.0.1 --port ${apiPort}`,
      url: `${apiOrigin}/api/v1/health/live`,
      env: {
        ...process.env,
        DATABASE_URL: unavailableDatabaseUrl,
      },
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        ...browserLaunchOptions,
      },
    },
    {
      name: "wide",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1728, height: 1117 },
        ...browserLaunchOptions,
      },
    },
    {
      name: "mobile",
      use: {
        // CSS breakpoint geometry is the contract under test. Keep the
        // browser engine identical to desktop so installed Chrome can run
        // headless on Windows; touch/UA emulation is not required by Phase 2.
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        ...browserLaunchOptions,
      },
    },
    {
      name: "mobile-large",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 426, height: 923 },
        ...browserLaunchOptions,
      },
    },
  ],
});
