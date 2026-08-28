import type {
  CatalogCollection,
  ModelCategory,
  PublicModelCatalogItem,
  PublicModelCatalogResponse,
  PublicProductModel,
} from "@mosaic/contracts";
import { createModelPresentation } from "@/entities/models/presentation-registry";
import {
  ModelCatalogServiceError,
  type CatalogModel,
  type ModelCatalogQuery,
  type ModelCatalogService,
} from "./interfaces";

export type ApiModelCatalogServiceErrorCode =
  | "MODEL_CATALOG_UNAVAILABLE"
  | "MODEL_NOT_FOUND";

export class ApiModelCatalogServiceError extends ModelCatalogServiceError {
  readonly code: ApiModelCatalogServiceErrorCode;

  constructor(options: {
    code: ApiModelCatalogServiceErrorCode;
    status: number;
    retryable: boolean;
    message?: string;
  }) {
    super(options);
    this.name = "ApiModelCatalogServiceError";
    this.code = options.code;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

const COLLECTIONS = new Set<CatalogCollection>(["featured", "popular", "new"]);
const CATEGORIES = new Set<ModelCategory>(["text", "image", "video", "audio"]);
const TASK_TYPES = new Set(["chat", "text_to_image", "text_to_video", "image_to_video", "tts"]);
const AVAILABILITIES = new Set(["available", "maintenance", "unavailable", "demo"]);
const FORBIDDEN_KEY = /provider|deployment|revision|quantization|precision|license|snapshot/i;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

function hasExactKeys(value: Record<string, unknown>, required: readonly string[], optional: readonly string[] = []): boolean {
  const allowed = new Set([...required, ...optional]);
  const keys = Reflect.ownKeys(value);
  return (
    keys.every((key) => typeof key === "string" && allowed.has(key)) &&
    required.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
}

function containsForbiddenKey(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsForbiddenKey);
  if (!isPlainObject(value)) return false;
  return Object.entries(value).some(
    ([key, nested]) => FORBIDDEN_KEY.test(key) || containsForbiddenKey(nested),
  );
}

function isPublicProductModel(value: unknown): value is PublicProductModel {
  if (!isPlainObject(value)) return false;
  if (
    !hasExactKeys(
      value,
      [
        "product_model_id",
        "display_name",
        "category",
        "task_type",
        "description",
        "capabilities",
        "availability",
        "pricing_summary",
      ],
      ["input_schema"],
    ) || containsForbiddenKey(value)
  ) {
    return false;
  }
  const capabilities = value.capabilities;
  return (
    typeof value.product_model_id === "string" && /^[a-z0-9-]+$/.test(value.product_model_id) &&
    value.product_model_id.length > 0 &&
    typeof value.display_name === "string" && value.display_name.length > 0 &&
    typeof value.description === "string" && value.description.length > 0 &&
    typeof value.pricing_summary === "string" && value.pricing_summary.length > 0 &&
    CATEGORIES.has(value.category as ModelCategory) &&
    TASK_TYPES.has(value.task_type as string) &&
    AVAILABILITIES.has(value.availability as string) &&
    Array.isArray(capabilities) &&
    new Set(capabilities).size === capabilities.length &&
    capabilities.every((entry) => typeof entry === "string" && entry.length > 0) &&
    (value.input_schema === undefined || isPlainObject(value.input_schema))
  );
}

function isCatalogItem(value: unknown): value is PublicModelCatalogItem {
  if (!isPlainObject(value) || !hasExactKeys(value, ["model", "collections"])) {
    return false;
  }
  if (!isPublicProductModel(value.model) || !Array.isArray(value.collections)) {
    return false;
  }
  return (
    new Set(value.collections).size === value.collections.length &&
    value.collections.every(
      (collection): collection is CatalogCollection =>
        typeof collection === "string" && COLLECTIONS.has(collection as CatalogCollection),
    )
  );
}

function isCatalogResponse(value: unknown): value is PublicModelCatalogResponse {
  return (
    isPlainObject(value) &&
    hasExactKeys(value, ["items"]) &&
    Array.isArray(value.items) &&
    value.items.every(isCatalogItem) &&
    new Set(
      value.items.map((item) => item.model.product_model_id),
    ).size === value.items.length
  );
}

function statusOf(response: Response): number {
  return Number.isFinite(response.status) ? response.status : 0;
}

function requestInit(signal?: AbortSignal): RequestInit {
  const init: RequestInit = { headers: { accept: "application/json" } };
  if (signal !== undefined) init.signal = signal;
  return init;
}

function queryString(query: ModelCatalogQuery | undefined): string {
  if (!query) return "";
  const params: string[] = [];
  if (query.category !== undefined) params.push(`category=${encodeURIComponent(query.category)}`);
  if (query.search?.trim()) params.push(`search=${encodeURIComponent(query.search.trim())}`);
  if (query.collection !== undefined) params.push(`collection=${encodeURIComponent(query.collection)}`);
  return params.length > 0 ? `?${params.join("&")}` : "";
}

function requestFailure(response: Response): ApiModelCatalogServiceError {
  const status = statusOf(response);
  return new ApiModelCatalogServiceError({
    code: "MODEL_CATALOG_UNAVAILABLE",
    status,
    retryable: status === 408 || status === 429 || status >= 500,
  });
}

function invalidResponse(status: number): ApiModelCatalogServiceError {
  return new ApiModelCatalogServiceError({
    code: "MODEL_CATALOG_UNAVAILABLE",
    status,
    retryable: false,
  });
}

function modelNotFound(): ApiModelCatalogServiceError {
  return new ApiModelCatalogServiceError({
    code: "MODEL_NOT_FOUND",
    status: 404,
    retryable: false,
  });
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error &&
    (error as { name?: unknown }).name === "AbortError";
}

function copyItem(item: PublicModelCatalogItem): PublicModelCatalogItem {
  return {
    model: {
      ...item.model,
      capabilities: [...item.model.capabilities],
      ...(item.model.input_schema === undefined ? {} : { input_schema: { ...item.model.input_schema } }),
    },
    collections: [...item.collections],
  };
}

export function createApiModelCatalogService(
  fetcher: typeof fetch,
): ModelCatalogService {
  // Favorites remain session-only until a tenant-scoped server contract is
  // implemented. Persisting them in DemoStateStore would hydrate demo
  // conversations in API mode and could mix preferences across real tenants.
  const favoriteIds = new Set<string>();
  // Server authority is established only by a successful catalog response.
  // Presentation metadata is not an existence check.
  const serverKnownModelIds = new Set<string>();

  function attach(item: PublicModelCatalogItem): CatalogModel {
    return {
      item: copyItem(item),
      presentation: createModelPresentation(item.model),
      favorite: favoriteIds.has(item.model.product_model_id),
    };
  }

  async function fetchCatalog(query: ModelCatalogQuery | undefined, signal?: AbortSignal): Promise<readonly CatalogModel[]> {
    const response = await fetcher(`/api/v1/models${queryString(query)}`, requestInit(signal));
    if (!response.ok) throw requestFailure(response);

    let value: unknown;
    try {
      value = await response.json();
    } catch (error) {
      if (isAbortError(error)) throw error;
      throw invalidResponse(statusOf(response));
    }
    if (!isCatalogResponse(value)) throw invalidResponse(statusOf(response));

    try {
      const models = value.items.map((item) => attach(item));
      for (const item of value.items) {
        serverKnownModelIds.add(item.model.product_model_id);
      }
      return models;
    } catch (error) {
      if (error instanceof ApiModelCatalogServiceError) throw error;
      throw invalidResponse(statusOf(response));
    }
  }

  async function ensureServerKnownModel(
    productModelId: string,
    signal?: AbortSignal,
  ): Promise<void> {
    if (serverKnownModelIds.has(productModelId)) return;
    await fetchCatalog(undefined, signal);
    if (!serverKnownModelIds.has(productModelId)) throw modelNotFound();
  }

  return {
    list(query, signal) {
      return fetchCatalog(query, signal);
    },

    async get(productModelId, signal) {
      const models = await fetchCatalog(undefined, signal);
      const model = models.find(
        ({ item }) => item.model.product_model_id === productModelId,
      );
      if (!model) {
        throw modelNotFound();
      }
      return model;
    },

    async toggleFavorite(productModelId, signal) {
      if (signal?.aborted) {
        throw signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
      }
      await ensureServerKnownModel(productModelId, signal);
      if (favoriteIds.has(productModelId)) {
        favoriteIds.delete(productModelId);
        return false;
      }
      favoriteIds.add(productModelId);
      return true;
    },
  };
}
