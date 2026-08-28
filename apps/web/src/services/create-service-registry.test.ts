import { describe, expect, it, vi } from "vitest";
import { DEMO_SCENARIO } from "@/shared/demo/demo-scenario";
import {
  createServiceRegistry,
  resolveBrowserServiceMode,
} from "./create-service-registry";

const NOW = "2026-08-20T12:00:00.000Z";

function memoryStorage() {
  let value: string | null = null;
  return {
    getItem: (key: string) => {
      void key;
      return value;
    },
    setItem: (_key: string, next: string) => {
      value = next;
    },
    removeItem: () => {
      value = null;
    },
  };
}

describe("service registry", () => {
  it("defaults browser configuration to the production API", () => {
    expect(resolveBrowserServiceMode(undefined)).toBe("api");
  });

  it("allows demo only when it is explicitly configured", () => {
    expect(resolveBrowserServiceMode("demo")).toBe("demo");
    expect(resolveBrowserServiceMode("api")).toBe("api");
  });

  it("creates an API-backed browser registry when the mode is omitted", async () => {
    const previousMode = process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE;
    delete process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE;
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ service: "mosaic-api", status: "ready", version: "0.1.0" }),
    });
    vi.stubGlobal("fetch", fetcher);

    try {
      vi.resetModules();
      const { createBrowserServiceRegistry } = await import(
        "./create-service-registry"
      );
      await expect(createBrowserServiceRegistry().health.getStatus()).resolves.toMatchObject({
        evidence: "provider_unverified",
      });
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/health/ready",
        expect.objectContaining({ headers: { accept: "application/json" } }),
      );
    } finally {
      vi.unstubAllGlobals();
      if (previousMode === undefined) {
        delete process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE;
      } else {
        process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE = previousMode;
      }
      vi.resetModules();
    }
  });

  it.each(["", "staging", "true"])(
    "fails closed for an invalid browser service mode (%s)",
    (mode) => {
      expect(() => resolveBrowserServiceMode(mode)).toThrow("INVALID_SERVICE_MODE");
    },
  );

  it("selects demo services only in the composition root", async () => {
    const registry = createServiceRegistry({
      mode: "demo",
      storage: memoryStorage(),
      now: () => NOW,
    });

    await expect(registry.health.getStatus()).resolves.toEqual({
      service: "mosaic-api",
      status: "ready",
      version: "demo",
      evidence: "demo_scaffolding",
    });
    await expect(
      registry.auth.signIn({ account: "demo", password: "not-persisted" }),
    ).resolves.toMatchObject({ authenticated: true });
    await expect(registry.modelCatalog.list()).resolves.toHaveLength(12);
    await expect(registry.conversation.listConversations()).resolves.toHaveLength(2);
  });

  it("does not persist a demo sign-in password", async () => {
    const storage = memoryStorage();
    const registry = createServiceRegistry({
      mode: "demo",
      storage,
      now: () => NOW,
    });

    await registry.auth.signIn({ account: "demo", password: "not-persisted" });

    expect(storage.getItem("mosaic.demo-state.v2")).not.toContain("not-persisted");
  });

  it("selects the API health adapter and requests JSON", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ service: "mosaic-api", status: "ready", version: "0.1.0" }),
    });
    const registry = createServiceRegistry({ mode: "api", fetcher });

    await registry.health.getStatus();

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/health/ready",
      expect.objectContaining({ headers: { accept: "application/json" } }),
    );
  });

  it("selects the API model catalog adapter in API mode", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    });
    const registry = createServiceRegistry({ mode: "api", fetcher });

    await expect(registry.modelCatalog.list()).resolves.toEqual([]);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/models",
      expect.objectContaining({ headers: { accept: "application/json" } }),
    );
  });

  it("selects the API conversation adapter in API mode", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const registry = createServiceRegistry({ mode: "api", fetcher });

    await expect(registry.conversation.listConversations()).resolves.toEqual([]);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/conversations",
      expect.objectContaining({ headers: { accept: "application/json" } }),
    );
  });

  it("throws API_NOT_READY when the health endpoint is not okay", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) });
    const registry = createServiceRegistry({ mode: "api", fetcher });

    await expect(registry.health.getStatus()).rejects.toThrow("API_NOT_READY");
  });

  it("keeps a browser demo session across registry consumers when storage is unavailable", async () => {
    const previousMode = process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE;
    const localStorageDescriptor = Object.getOwnPropertyDescriptor(
      window,
      "localStorage",
    );

    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("storage is unavailable");
      },
    });
    process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE = "demo";

    try {
      vi.resetModules();
      const { createBrowserServiceRegistry } = await import(
        "./create-service-registry"
      );
      const loginRegistry = createBrowserServiceRegistry();
      await loginRegistry.auth.signIn({
        account: "demo@mosaic.internal",
        password: "internal-demo",
      });

      const authGateRegistry = createBrowserServiceRegistry();

      expect(authGateRegistry).toBe(loginRegistry);
      await expect(authGateRegistry.auth.getSession()).resolves.toMatchObject({
        authenticated: true,
      });
    } finally {
      if (localStorageDescriptor) {
        Object.defineProperty(window, "localStorage", localStorageDescriptor);
      }
      if (previousMode === undefined) {
        delete process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE;
      } else {
        process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE = previousMode;
      }
      vi.resetModules();
    }
  });

  it("keeps API mode out of DemoStateStore and scopes favorites to one registry", async () => {
    const previousMode = process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE;
    const previousStorage = Object.getOwnPropertyDescriptor(window, "localStorage");
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    };
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        items: DEMO_SCENARIO.catalog.map((item) => ({
          model: { ...item.model },
          collections: [...item.collections],
        })),
      }),
    });
    vi.stubGlobal("fetch", fetcher);

    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get: () => storage,
    });
    process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE = "api";

    try {
      vi.resetModules();
      const firstModule = await import("./create-service-registry");
      const firstRegistry = firstModule.createBrowserServiceRegistry();

      await firstRegistry.modelCatalog.list();
      await expect(
        firstRegistry.modelCatalog.toggleFavorite("qwen-3-5"),
      ).resolves.toBe(true);
      expect(values.size).toBe(0);

      vi.resetModules();
      const secondModule = await import("./create-service-registry");
      const secondRegistry = secondModule.createBrowserServiceRegistry();

      await secondRegistry.modelCatalog.list();
      await expect(
        secondRegistry.modelCatalog.toggleFavorite("qwen-3-5"),
      ).resolves.toBe(true);
      expect(values.size).toBe(0);
    } finally {
      if (previousStorage) {
        Object.defineProperty(window, "localStorage", previousStorage);
      }
      vi.unstubAllGlobals();
      if (previousMode === undefined) {
        delete process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE;
      } else {
        process.env.NEXT_PUBLIC_\u004dOSAIC_SERVICE_MODE = previousMode;
      }
      vi.resetModules();
    }
  });
});
