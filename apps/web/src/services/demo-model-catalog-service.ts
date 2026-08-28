import type { DemoScenario } from "@/shared/demo/demo-scenario";
import type { DemoStateStore } from "@/shared/demo/demo-state-store";
import {
  ModelCatalogServiceError,
  type CatalogModel,
  type ModelCatalogQuery,
  type ModelCatalogService,
} from "./interfaces";

export class DemoModelCatalogServiceError extends ModelCatalogServiceError {}

function abortIfNeeded(signal?: AbortSignal): void {
  if (!signal?.aborted) return;
  throw signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
}

function copyPresentation(presentation: CatalogModel["presentation"]): CatalogModel["presentation"] {
  return {
    productModelId: presentation.productModelId,
    cardStyle: presentation.cardStyle,
    media:
      presentation.media.kind === "gallery"
        ? {
            kind: "gallery",
            sources: presentation.media.sources.map((source) => ({ ...source })),
          }
        : presentation.media.kind === "audio"
          ? {
              kind: "audio",
              waveform: [...presentation.media.waveform],
              durationLabel: presentation.media.durationLabel,
            }
          : { ...presentation.media },
    actionLabel: presentation.actionLabel,
  };
}

function copyCatalogModel(model: CatalogModel): CatalogModel {
  return {
    item: {
      model: {
        ...model.item.model,
        capabilities: [...model.item.model.capabilities],
        ...(model.item.model.input_schema === undefined
          ? {}
          : { input_schema: { ...model.item.model.input_schema } }),
      },
      collections: [...model.item.collections],
    },
    presentation: copyPresentation(model.presentation),
    favorite: model.favorite,
  };
}

function normalizedSearch(value: string | undefined): string {
  return value?.trim().toLocaleLowerCase("zh-CN") ?? "";
}

function matchesQuery(model: CatalogModel, query: ModelCatalogQuery): boolean {
  if (query.category !== undefined && model.item.model.category !== query.category) {
    return false;
  }
  if (
    query.collection !== undefined &&
    !model.item.collections.includes(query.collection)
  ) {
    return false;
  }

  const search = normalizedSearch(query.search);
  if (search === "") return true;
  const haystack = [
    model.item.model.display_name,
    model.item.model.description,
    ...model.item.model.capabilities,
  ]
    .join("\n")
    .toLocaleLowerCase("zh-CN");
  return haystack.includes(search);
}

function catalogIdSet(scenario: DemoScenario): Set<string> {
  return new Set(scenario.catalog.map(({ model }) => model.product_model_id));
}

export function createDemoModelCatalogService(
  scenario: DemoScenario,
  store: DemoStateStore,
): ModelCatalogService {
  const ids = catalogIdSet(scenario);

  function snapshot(): readonly CatalogModel[] {
    const state = store.read();
    return scenario.catalog.map((item) => {
      const presentation = scenario.presentations[item.model.product_model_id];
      if (!presentation) {
        throw new DemoModelCatalogServiceError({
          code: "MODEL_CATALOG_UNAVAILABLE",
          status: 500,
          retryable: false,
          message: `Missing presentation for ${item.model.product_model_id}`,
        });
      }
      return {
        item: {
          model: { ...item.model, capabilities: [...item.model.capabilities] },
          collections: [...item.collections],
        },
        presentation: copyPresentation(presentation),
        favorite: state.favorites.includes(item.model.product_model_id),
      };
    });
  }

  return {
    async list(query = {}, signal) {
      abortIfNeeded(signal);
      return snapshot()
        .filter((model) => matchesQuery(model, query))
        .map(copyCatalogModel);
    },

    async get(productModelId, signal) {
      abortIfNeeded(signal);
      if (!ids.has(productModelId)) {
        throw new DemoModelCatalogServiceError({
          code: "MODEL_NOT_FOUND",
          status: 404,
          retryable: false,
        });
      }
      const model = snapshot().find(
        ({ item }) => item.model.product_model_id === productModelId,
      );
      if (!model) {
        throw new DemoModelCatalogServiceError({
          code: "MODEL_NOT_FOUND",
          status: 404,
          retryable: false,
        });
      }
      return copyCatalogModel(model);
    },

    async toggleFavorite(productModelId, signal) {
      abortIfNeeded(signal);
      if (!ids.has(productModelId)) {
        throw new DemoModelCatalogServiceError({
          code: "MODEL_NOT_FOUND",
          status: 404,
          retryable: false,
        });
      }
      const next = store.update((state) => {
        const favorite = state.favorites.includes(productModelId);
        return {
          ...state,
          favorites: favorite
            ? state.favorites.filter((id) => id !== productModelId)
            : [...state.favorites, productModelId],
        };
      });
      return next.favorites.includes(productModelId);
    },
  };
}
