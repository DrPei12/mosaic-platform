import type { UsageService, UsageSummary } from "./interfaces";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(new Date(value).getTime());
}

function isSummary(value: unknown): value is UsageSummary {
  if (!isObject(value) || !isObject(value.totals)) return false;
  const totals = value.totals;
  const measures = [
    "requests", "input_tokens", "output_tokens", "image_count", "video_seconds",
    "character_count", "storage_bytes", "charge_amount_minor",
  ];
  if (
    value.currency !== "PTS" ||
    !nonnegativeInteger(value.balance_minor) || !nonnegativeInteger(value.reserved_minor) ||
    !measures.every((key) => nonnegativeInteger(totals[key])) ||
    !Array.isArray(value.recent_usage) || !Array.isArray(value.recent_ledger)
  ) return false;
  return value.recent_usage.every((entry) =>
    isObject(entry) && typeof entry.usage_id === "string" &&
    (entry.source === "chat" || entry.source === "generation") &&
    typeof entry.modality === "string" && typeof entry.model_id === "string" &&
    nonnegativeInteger(entry.input_tokens) && nonnegativeInteger(entry.output_tokens) &&
    nonnegativeInteger(entry.billable_units) && nonnegativeInteger(entry.charge_amount_minor) &&
    timestamp(entry.created_at)
  ) && value.recent_ledger.every((entry) =>
    isObject(entry) && typeof entry.ledger_id === "string" &&
    ["credit", "debit", "hold", "release", "adjustment"].includes(String(entry.entry_type)) &&
    Number.isSafeInteger(entry.amount_minor) && Number(entry.amount_minor) > 0 &&
    entry.currency === "PTS" && typeof entry.reference_type === "string" &&
    timestamp(entry.created_at)
  );
}

export function createApiUsageService(fetcher: typeof fetch): UsageService {
  return {
    async getSummary(signal) {
      const response = await fetcher("/api/v1/usage", {
        credentials: "include",
        headers: { accept: "application/json" },
        ...(signal === undefined ? {} : { signal }),
      });
      if (!response.ok) throw new Error("用量数据暂时不可用");
      const value: unknown = await response.json();
      if (!isSummary(value)) throw new Error("用量数据格式无效");
      return value;
    },
  };
}
