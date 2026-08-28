"use client";

import type { CatalogCollection, ModelCategory, PublicProductModel } from "@mosaic/contracts";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createBrowserServiceRegistry } from "@/services/create-service-registry";
import {
  ModelCatalogServiceError,
  type CatalogModel,
  type ModelCatalogQuery,
} from "@/services/interfaces";
import {
  ModelFilterBar,
  type ModelCategoryFilter,
  type ModelCollectionFilter,
} from "./model-filter-bar";
import { ModelCard } from "./model-card";

type MarketplaceStatus = "loading" | "ready" | "empty" | "error";

const categoryValues = new Set<ModelCategory>(["text", "image", "video", "audio"]);
const collectionValues = new Set<CatalogCollection>(["featured", "popular", "new"]);

let actionSequence = 0;

function parseCategory(value: string | null): ModelCategoryFilter {
  return value !== null && categoryValues.has(value as ModelCategory)
    ? (value as ModelCategory)
    : "all";
}

function parseCollection(value: string | null): ModelCollectionFilter {
  return value !== null && collectionValues.has(value as CatalogCollection)
    ? (value as CatalogCollection)
    : "all";
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error &&
    (error as { name?: unknown }).name === "AbortError";
}

function newClientRequestId(productModelId: string): string {
  actionSequence += 1;
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `marketplace-${productModelId}-${actionSequence}`;
}

function modelPriority(model: CatalogModel): number {
  const priority: Record<string, number> = {
    hero: 0,
    gallery: 1,
    video: 2,
    audio: 3,
    compact: 4,
  };
  return priority[model.presentation.cardStyle] ?? 5;
}

function readableError(error: unknown): string {
  if (error instanceof ModelCatalogServiceError && !error.retryable) {
    return "模型目录暂时不可用，请稍后重试。";
  }
  return "模型目录暂时不可用，请稍后重试。";
}

function isUnavailable(model: CatalogModel): boolean {
  const availability = model.item.model.availability;
  return availability === "maintenance" || availability === "unavailable";
}

export function ModelMarketplace() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchParamsString = searchParams.toString();
  const registry = useMemo(() => createBrowserServiceRegistry(), []);
  const mounted = useRef(true);
  const actionController = useRef<AbortController | null>(null);
  const favoriteRequests = useRef(new Map<string, { controller: AbortController; token: number }>());
  const favoriteToken = useRef(0);
  const catalogRevision = useRef(0);
  const lastSyncedParams = useRef(searchParamsString);
  const initialParams = useMemo(() => new URLSearchParams(searchParamsString), [searchParamsString]);
  const [category, setCategory] = useState<ModelCategoryFilter>(() => parseCategory(initialParams.get("category")));
  const [search, setSearch] = useState(() => initialParams.get("search") ?? "");
  const [collection, setCollection] = useState<ModelCollectionFilter>(() => parseCollection(initialParams.get("collection")));
  const [filterOpen, setFilterOpen] = useState(false);
  const [models, setModels] = useState<readonly CatalogModel[]>([]);
  const [status, setStatus] = useState<MarketplaceStatus>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [offline, setOffline] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [favoritePending, setFavoritePending] = useState<ReadonlySet<string>>(() => new Set());
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");

  useEffect(() => {
    const requests = favoriteRequests.current;
    mounted.current = true;
    return () => {
      mounted.current = false;
      actionController.current?.abort();
      for (const { controller } of requests.values()) controller.abort();
      requests.clear();
    };
  // favoriteRequests is a stable ref; the cleanup intentionally captures its
  // current map once for the lifetime of this mounted marketplace.
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect -- browser history is an external filter source. */
  useEffect(() => {
    if (lastSyncedParams.current === searchParamsString) return;
    lastSyncedParams.current = searchParamsString;
    const nextParams = new URLSearchParams(searchParamsString);
    const nextCategory = parseCategory(nextParams.get("category"));
    const nextSearch = nextParams.get("search") ?? "";
    const nextCollection = parseCollection(nextParams.get("collection"));
    if (category === nextCategory && search === nextSearch && collection === nextCollection) return;
    // URL history is an external source of truth. These updates intentionally
    // hydrate local controls after a back/forward navigation.
    setCategory((current) => current === nextCategory ? current : nextCategory);
    setSearch((current) => current === nextSearch ? current : nextSearch);
    setCollection((current) => current === nextCollection ? current : nextCollection);
    setStatus("loading");
    setErrorMessage("");
    setOffline(false);
  }, [category, collection, search, searchParamsString]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const query = useMemo<ModelCatalogQuery>(() => {
    const next: ModelCatalogQuery = {};
    if (category !== "all") next.category = category;
    if (search.trim() !== "") next.search = search;
    if (collection !== "all") next.collection = collection;
    return next;
  }, [category, collection, search]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    void registry.modelCatalog.list(query, controller.signal)
      .then((nextModels) => {
        if (!active || !mounted.current) return;
        catalogRevision.current += 1;
        setModels(nextModels);
        setStatus(nextModels.length === 0 ? "empty" : "ready");
      })
      .catch((error: unknown) => {
        if (!active || !mounted.current || isAbortError(error)) return;
        const isOffline = typeof navigator !== "undefined" && navigator.onLine === false;
        setOffline(isOffline);
        setErrorMessage(isOffline ? "当前处于离线状态，无法加载模型目录。" : readableError(error));
        setStatus("error");
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [query, registry, reloadKey]);

  const updateUrl = useCallback((next: {
    category?: ModelCategoryFilter;
    search?: string;
    collection?: ModelCollectionFilter;
  }) => {
    const params = new URLSearchParams(searchParams.toString());
    const nextCategory = next.category ?? category;
    const nextSearch = next.search ?? search;
    const nextCollection = next.collection ?? collection;

    if (nextCategory === "all") params.delete("category");
    else params.set("category", nextCategory);
    if (nextSearch.trim() === "") params.delete("search");
    else params.set("search", nextSearch.trim());
    if (nextCollection === "all") params.delete("collection");
    else params.set("collection", nextCollection);

    const queryString = params.toString();
    router.replace(queryString ? `${pathname}?${queryString}` : pathname, { scroll: false });
  }, [category, collection, pathname, router, search, searchParams]);

  const handleCategoryChange = useCallback((nextCategory: ModelCategoryFilter) => {
    setStatus("loading");
    setErrorMessage("");
    setOffline(false);
    setCategory(nextCategory);
    updateUrl({ category: nextCategory });
  }, [updateUrl]);

  const handleSearchChange = useCallback((nextSearch: string) => {
    setStatus("loading");
    setErrorMessage("");
    setOffline(false);
    setSearch(nextSearch);
    updateUrl({ search: nextSearch });
  }, [updateUrl]);

  const handleCollectionChange = useCallback((nextCollection: ModelCollectionFilter) => {
    setStatus("loading");
    setErrorMessage("");
    setOffline(false);
    setCollection(nextCollection);
    updateUrl({ collection: nextCollection });
  }, [updateUrl]);

  const handleClearFilters = useCallback(() => {
    setStatus("loading");
    setErrorMessage("");
    setOffline(false);
    setCategory("all");
    setSearch("");
    setCollection("all");
    setFilterOpen(false);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("category");
    params.delete("search");
    params.delete("collection");
    const queryString = params.toString();
    router.replace(queryString ? `${pathname}?${queryString}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const handleToggleFavorite = useCallback(async (catalogModel: CatalogModel) => {
    const productModelId = catalogModel.item.model.product_model_id;
    if (favoriteRequests.current.has(productModelId)) return;
    const controller = new AbortController();
    const token = ++favoriteToken.current;
    const revision = catalogRevision.current;
    favoriteRequests.current.set(productModelId, { controller, token });
    setFavoritePending((previous) => new Set(previous).add(productModelId));
    setModels((previous) => previous.map((item) => item.item.model.product_model_id === productModelId
      ? { ...item, favorite: !item.favorite }
      : item));

    try {
      const favorite = await registry.modelCatalog.toggleFavorite(productModelId, controller.signal);
      const currentRequest = favoriteRequests.current.get(productModelId);
      if (!mounted.current || currentRequest?.token !== token || revision !== catalogRevision.current) return;
      setModels((previous) => previous.map((item) => item.item.model.product_model_id === productModelId
        ? { ...item, favorite }
        : item));
    } catch (error: unknown) {
      const currentRequest = favoriteRequests.current.get(productModelId);
      if (isAbortError(error) || !mounted.current || currentRequest?.token !== token || revision !== catalogRevision.current) return;
      setModels((previous) => previous.map((item) => item.item.model.product_model_id === productModelId
        ? { ...item, favorite: catalogModel.favorite }
        : item));
      setActionError("收藏状态暂时无法保存，请稍后重试。");
    } finally {
      const currentRequest = favoriteRequests.current.get(productModelId);
      if (currentRequest?.token === token) {
        favoriteRequests.current.delete(productModelId);
      }
      if (mounted.current && currentRequest?.token === token) {
        setFavoritePending((previous) => {
          const next = new Set(previous);
          next.delete(productModelId);
          return next;
        });
      }
    }
  }, [registry]);

  const handleAction = useCallback(async (product: PublicProductModel) => {
    if (actionPending !== null) return;
    const controller = new AbortController();
    actionController.current = controller;
    setActionPending(product.product_model_id);
    setActionError("");

    try {
      if (product.task_type === "chat") {
        const conversation = await registry.conversation.createConversation({
          productModelId: product.product_model_id,
          clientRequestId: newClientRequestId(product.product_model_id),
        }, controller.signal);
        if (mounted.current) router.push(`/chat/${conversation.conversation_id}`);
      } else if (product.task_type === "text_to_image") {
        router.push(`/studio/image/${product.product_model_id}`);
      } else if (product.task_type === "text_to_video" || product.task_type === "image_to_video") {
        router.push(`/studio/video/${product.product_model_id}`);
      } else {
        router.push(`/studio/audio/${product.product_model_id}`);
      }
    } catch (error: unknown) {
      if (mounted.current && !isAbortError(error)) {
        setActionError("暂时无法打开该模型，请稍后重试。");
      }
    } finally {
      if (mounted.current) {
        setActionPending(null);
        actionController.current = null;
      }
    }
  }, [actionPending, registry, router]);

  const visibleModels = useMemo(
    () => [...models].sort((left, right) => modelPriority(left) - modelPriority(right)),
    [models],
  );
  const hasPartialAvailability = visibleModels.some(isUnavailable) && visibleModels.some((model) => !isUnavailable(model));

  return (
    <section data-testid="model-marketplace" className="mx-auto w-full max-w-[var(--mosaic-layout-content)]">
      <header className="mb-10 max-w-3xl lg:mb-3">
        <h1 className="text-[40px] font-semibold leading-[48px] tracking-[-0.055em] text-[var(--mosaic-color-ink)] lg:text-[56px] lg:leading-[64px]">
          选择能力，开始创作
        </h1>
      </header>

      <ModelFilterBar
        category={category}
        search={search}
        collection={collection}
        filterOpen={filterOpen}
        onCategoryChange={handleCategoryChange}
        onSearchChange={handleSearchChange}
        onCollectionChange={handleCollectionChange}
        onFilterToggle={() => setFilterOpen((open) => !open)}
        onClearFilters={handleClearFilters}
      />

      {actionError ? <p role="alert" className="mb-5 rounded-[var(--mosaic-radius-control)] border border-[color-mix(in_srgb,var(--mosaic-color-danger)_32%,var(--mosaic-color-line))] bg-[color-mix(in_srgb,var(--mosaic-color-danger)_6%,var(--mosaic-color-surface))] px-4 py-3 text-sm text-[var(--mosaic-color-danger)]">{actionError}</p> : null}

      {status === "loading" ? <ModelMarketplaceLoading /> : null}

      {status === "error" ? (
        <section role="alert" data-state={offline ? "offline" : "error"} className="border-y border-[var(--mosaic-color-line)] py-16 text-center">
          <p className="text-base font-semibold text-[var(--mosaic-color-ink)]">{errorMessage}</p>
          <button
            type="button"
            onClick={() => {
              setStatus("loading");
              setErrorMessage("");
              setOffline(false);
              setReloadKey((key) => key + 1);
            }}
            className="mt-5 inline-flex min-h-11 items-center rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] px-4 text-sm font-semibold text-[var(--mosaic-color-ink)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none"
          >
            重新加载
          </button>
        </section>
      ) : null}

      {status === "empty" ? (
        <section role="status" className="border-y border-[var(--mosaic-color-line)] py-16 text-center">
          <p className="text-base font-semibold text-[var(--mosaic-color-ink)]">没有找到匹配的模型</p>
          <button
            type="button"
            onClick={handleClearFilters}
            className="mt-5 inline-flex min-h-11 items-center rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-accent)] px-4 text-sm font-semibold text-[var(--mosaic-color-surface)] transition-[background-color,transform] duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_88%,var(--mosaic-color-ink))] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none"
          >
            清除筛选
          </button>
        </section>
      ) : null}

      {status === "ready" ? (
        <>
          {hasPartialAvailability ? (
            <p
              role="status"
              data-testid="model-marketplace-partial-availability"
              className="mb-5 rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-4 py-3 text-sm text-[var(--mosaic-color-ink-muted)]"
            >
              部分模型暂不可用
            </p>
          ) : null}
          <div className="grid gap-4 lg:gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]" data-testid="model-card-grid">
            {visibleModels.map((model) => (
              <ModelCard
                key={model.item.model.product_model_id}
                model={model}
                actionPending={actionPending === model.item.model.product_model_id}
                actionBusy={actionPending !== null}
                favoritePending={favoritePending.has(model.item.model.product_model_id)}
                onAction={handleAction}
                onToggleFavorite={handleToggleFavorite}
              />
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

export function ModelMarketplaceLoading() {
  return (
    <section data-testid="model-marketplace-loading" aria-label="正在加载模型目录" className="grid gap-6 lg:grid-cols-2">
      {Array.from({ length: 6 }, (_, index) => (
        <div key={index} className="min-h-[260px] animate-pulse rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-6 motion-reduce:animate-none">
          <div className="h-5 w-20 rounded bg-[var(--mosaic-color-surface-muted)]" />
          <div className="mt-10 h-7 w-2/3 rounded bg-[var(--mosaic-color-surface-muted)]" />
          <div className="mt-4 h-4 w-full rounded bg-[var(--mosaic-color-surface-muted)]" />
          <div className="mt-3 h-4 w-4/5 rounded bg-[var(--mosaic-color-surface-muted)]" />
          <div className="mt-12 h-11 w-28 rounded-[var(--mosaic-radius-control)] bg-[var(--mosaic-color-surface-muted)]" />
        </div>
      ))}
    </section>
  );
}
