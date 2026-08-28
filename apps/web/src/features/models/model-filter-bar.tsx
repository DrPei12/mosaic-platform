import {
  FunnelSimple,
  MagnifyingGlass,
  X,
} from "@phosphor-icons/react";
import type { CatalogCollection, ModelCategory } from "@mosaic/contracts";
import { cn } from "@/shared/ui/cn";

export type ModelCategoryFilter = ModelCategory | "all";
export type ModelCollectionFilter = CatalogCollection | "all";

export interface ModelFilterBarProps {
  category: ModelCategoryFilter;
  search: string;
  collection: ModelCollectionFilter;
  filterOpen: boolean;
  onCategoryChange: (category: ModelCategoryFilter) => void;
  onSearchChange: (search: string) => void;
  onCollectionChange: (collection: ModelCollectionFilter) => void;
  onFilterToggle: () => void;
  onClearFilters: () => void;
}

const categoryTabs: readonly { value: ModelCategoryFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "text", label: "文本" },
  { value: "image", label: "图像" },
  { value: "video", label: "视频" },
  { value: "audio", label: "音频" },
];

const collectionOptions: readonly {
  value: ModelCollectionFilter;
  label: string;
}[] = [
  { value: "all", label: "全部模型" },
  { value: "featured", label: "精选" },
  { value: "popular", label: "热门" },
  { value: "new", label: "最新加入" },
];

export function ModelFilterBar({
  category,
  search,
  collection,
  filterOpen,
  onCategoryChange,
  onSearchChange,
  onCollectionChange,
  onFilterToggle,
  onClearFilters,
}: ModelFilterBarProps) {
  const hasFilters = category !== "all" || search.trim() !== "" || collection !== "all";

  return (
    <section aria-label="模型筛选" className="relative z-10 mb-6 lg:mb-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div
          role="group"
          aria-label="模型类型"
          className="-mx-1 flex min-w-0 gap-1 overflow-x-auto px-1 pb-px"
        >
          {categoryTabs.map((tab) => {
            const active = category === tab.value;
            return (
              <button
                key={tab.value}
                type="button"
                aria-pressed={active}
                onClick={() => onCategoryChange(tab.value)}
                className={cn(
                  "relative min-h-11 shrink-0 px-3 text-base leading-6 text-[var(--mosaic-color-ink-muted)] transition-colors duration-[var(--mosaic-motion-fast)] hover:text-[var(--mosaic-color-ink)] focus-visible:z-10 motion-reduce:transition-none",
                  "after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:origin-center after:bg-[var(--mosaic-color-accent)] after:transition-transform after:duration-[var(--mosaic-motion-fast)] after:content-[''] motion-reduce:after:transition-none",
                  active
                    ? "font-semibold text-[var(--mosaic-color-accent)] after:scale-x-100"
                    : "after:scale-x-0",
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        <div className="flex min-w-0 items-center gap-3 lg:justify-end">
          <label className="relative min-w-0 flex-1 lg:w-[304px] lg:flex-none" htmlFor="model-search">
            <span className="sr-only">搜索模型</span>
            <MagnifyingGlass
              aria-hidden
              size={20}
              weight="regular"
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--mosaic-color-ink-muted)]"
            />
            <input
              id="model-search"
              type="search"
              value={search}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="搜索模型或能力"
              aria-label="搜索模型"
              className="min-h-11 w-full rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] pl-10 pr-10 text-sm text-[var(--mosaic-color-ink)] placeholder:text-[var(--mosaic-color-ink-muted)] transition-[border-color,box-shadow] duration-[var(--mosaic-motion-fast)] focus:border-[var(--mosaic-color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--mosaic-color-accent)] motion-reduce:transition-none"
            />
            {search ? (
              <button
                type="button"
                aria-label="清空搜索"
                onClick={() => onSearchChange("")}
                className="absolute right-0 top-0 inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--mosaic-radius-control)] text-[var(--mosaic-color-ink-muted)] transition-colors duration-[var(--mosaic-motion-fast)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] motion-reduce:transition-none"
              >
                <X size={16} aria-hidden weight="bold" />
              </button>
            ) : null}
          </label>

          <button
            type="button"
            aria-label="打开筛选"
            aria-expanded={filterOpen}
            aria-controls="model-collection-filter"
            onClick={onFilterToggle}
            className={cn(
              "inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] text-[var(--mosaic-color-ink-muted)] transition-[background-color,border-color,color,transform] duration-[var(--mosaic-motion-fast)] hover:border-[var(--mosaic-color-accent)] hover:bg-[var(--mosaic-color-surface-muted)] hover:text-[var(--mosaic-color-ink)] active:translate-y-px motion-reduce:transition-none motion-reduce:transform-none",
              filterOpen && "border-[var(--mosaic-color-accent)] text-[var(--mosaic-color-accent)]",
            )}
          >
            <FunnelSimple size={20} aria-hidden weight="regular" />
          </button>
        </div>
      </div>

      {filterOpen ? (
        <div
          id="model-collection-filter"
          role="region"
          aria-label="模型集合筛选"
          className="mt-4 flex flex-col gap-3 rounded-[var(--mosaic-radius-surface)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] p-4 sm:flex-row sm:items-center sm:justify-between"
        >
          <label className="flex items-center gap-3 text-sm font-medium text-[var(--mosaic-color-ink)]" htmlFor="collection-filter">
            模型集合
            <select
              id="collection-filter"
              value={collection}
              onChange={(event) => onCollectionChange(event.target.value as ModelCollectionFilter)}
              className="min-h-11 min-w-[160px] rounded-[var(--mosaic-radius-control)] border border-[var(--mosaic-color-line)] bg-[var(--mosaic-color-surface)] px-3 text-sm font-normal text-[var(--mosaic-color-ink)] focus:border-[var(--mosaic-color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--mosaic-color-accent)]"
            >
              {collectionOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {hasFilters ? (
            <button
              type="button"
              onClick={onClearFilters}
              className="min-h-11 self-start rounded-[var(--mosaic-radius-control)] px-3 text-sm font-semibold text-[var(--mosaic-color-accent)] transition-colors duration-[var(--mosaic-motion-fast)] hover:bg-[color-mix(in_srgb,var(--mosaic-color-accent)_8%,var(--mosaic-color-surface))] motion-reduce:transition-none sm:self-auto"
            >
              清除筛选
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
