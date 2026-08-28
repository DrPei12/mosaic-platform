import {
  createDemoStateStore,
  type StorageLike,
} from "@/shared/demo/demo-state-store";
import { DEMO_SCENARIO } from "@/shared/demo/demo-scenario";
import {
  getPublicServiceMode,
  type ServiceMode,
} from "@/shared/config/service-mode";
import { createApiAuthService } from "./api-auth-service";
import { createApiConversationService } from "./api-conversation-service";
import { createApiHealthService } from "./api-health-service";
import { createApiModelCatalogService } from "./api-model-catalog-service";
import { createApiGenerationService } from "./api-generation-service";
import { createApiUsageService } from "./api-usage-service";
import { createDemoAuthService } from "./demo-auth-service";
import { createDemoConversationService } from "./demo-conversation-service";
import { demoHealthService } from "./demo-health-service";
import { createDemoModelCatalogService } from "./demo-model-catalog-service";
import type { ServiceRegistry } from "./interfaces";

export { resolveBrowserServiceMode } from "@/shared/config/service-mode";
export type { ServiceMode } from "@/shared/config/service-mode";

export interface ServiceRegistryOptions {
  mode: ServiceMode;
  fetcher?: typeof fetch;
  storage?: StorageLike;
  now?: () => string;
}

let browserServiceRegistry: ServiceRegistry | undefined;

function createMemoryStorage(): StorageLike {
  const values = new Map<string, string>();
  return {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

function browserStorage(): StorageLike {
  if (typeof window === "undefined") return createMemoryStorage();

  try {
    return window.localStorage;
  } catch {
    return createMemoryStorage();
  }
}

export function createServiceRegistry(
  input: ServiceRegistryOptions,
): ServiceRegistry {
  if (input.mode === "demo") {
    if (input.storage === undefined || input.now === undefined) {
      throw new Error("Demo mode requires storage and clock");
    }
    const store = createDemoStateStore({
      storage: input.storage,
      now: input.now,
    });
    return {
      health: demoHealthService,
      auth: createDemoAuthService(store),
      conversation: createDemoConversationService({
        scenario: DEMO_SCENARIO,
        store,
      }),
      modelCatalog: createDemoModelCatalogService(
        DEMO_SCENARIO,
        store,
      ),
    };
  }

  const fetcher = input.fetcher ?? globalThis.fetch;
  return {
    health: createApiHealthService(fetcher),
    auth: createApiAuthService(fetcher),
    conversation: createApiConversationService(fetcher),
    modelCatalog: createApiModelCatalogService(fetcher),
    generation: createApiGenerationService(fetcher),
    usage: createApiUsageService(fetcher),
  };
}

export function createBrowserServiceRegistry(): ServiceRegistry {
  if (typeof window !== "undefined" && browserServiceRegistry) {
    return browserServiceRegistry;
  }

  const mode = getPublicServiceMode();

  const registry =
    mode === "api"
      ? createServiceRegistry({
          mode,
          fetcher: globalThis.fetch,
          storage: browserStorage(),
          now: () => new Date().toISOString(),
        })
      : // Resolve browser-only storage at call time. A server-side call receives
        // a fresh in-memory store rather than touching `window` during module
        // loading.
        createServiceRegistry({
          mode,
          storage: browserStorage(),
          now: () => new Date().toISOString(),
        });

  if (typeof window !== "undefined") {
    browserServiceRegistry = registry;
  }

  return registry;
}
