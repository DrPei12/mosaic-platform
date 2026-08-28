import { describe, expect, it } from "vitest";
import type { ModelCategory } from "@mosaic/contracts";
import { DEMO_SCENARIO } from "@/shared/demo/demo-scenario";
import { createDemoStateStore, type StorageLike } from "@/shared/demo/demo-state-store";
import { createDemoModelCatalogService } from "./demo-model-catalog-service";

function memoryStorage(): StorageLike {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

function makeService() {
  const storage = memoryStorage();
  const store = createDemoStateStore({
    storage,
    now: () => "2026-08-22T12:00:00.000Z",
  });
  return { service: createDemoModelCatalogService(DEMO_SCENARIO, store), store };
}

describe("demo model catalog service", () => {
  it("returns the exact canonical twelve-model catalog in scenario order", async () => {
    const { service } = makeService();
    const models = await service.list();

    expect(models).toHaveLength(12);
    expect(models.map(({ item }) => item.model.display_name)).toEqual([
      "Qwen 3.5",
      "DeepSeek V4",
      "GLM 5.2",
      "Kimi K2.7 Code",
      "GPT-OSS",
      "Gemma 4",
      "Qwen Image",
      "FLUX 2",
      "HunyuanVideo 1.5",
      "Qwen3-TTS 1.7B VoiceDesign",
      "Qwen3-TTS 1.7B CustomVoice",
      "Qwen3-TTS 1.7B Base",
    ]);
    expect(models.every(({ item }) => item.model.availability === "demo")).toBe(true);
  });

  it.each([
    ["text", 6],
    ["image", 2],
    ["video", 1],
    ["audio", 3],
  ] satisfies [ModelCategory, number][]) (
    "filters category %s",
    async (category, expected) => {
      const { service } = makeService();
      await expect(service.list({ category })).resolves.toHaveLength(expected);
    },
  );

  it("treats category, collection and search as an intersection", async () => {
    const { service } = makeService();
    const models = await service.list({
      category: "text",
      collection: "popular",
      search: "代码",
    });

    expect(models.map(({ item }) => item.model.product_model_id)).toEqual([
      "kimi-k2-7-code",
    ]);
  });

  it("searches display name, description and capabilities", async () => {
    const { service } = makeService();
    await expect(service.list({ search: "deepseek" })).resolves.toHaveLength(1);
    await expect(service.list({ search: "构图探索" })).resolves.toHaveLength(1);
    await expect(service.list({ search: "声音设计" })).resolves.toHaveLength(1);
    await expect(service.list({ search: "  " })).resolves.toHaveLength(12);
  });

  it("supports collection filters without mutating the scenario", async () => {
    const { service } = makeService();
    const before = JSON.stringify(DEMO_SCENARIO);
    const featured = await service.list({ collection: "featured" });

    expect(featured.map(({ item }) => item.model.product_model_id)).toEqual([
      "qwen-3-5",
      "qwen-image",
      "hunyuan-video-1-5",
    ]);
    expect(JSON.stringify(DEMO_SCENARIO)).toBe(before);
  });

  it("returns a fresh model and throws for an unknown id", async () => {
    const { service } = makeService();
    const first = await service.get("qwen-3-5");
    const second = await service.get("qwen-3-5");

    expect(first).toEqual(second);
    expect(first).not.toBe(second);
    await expect(service.get("missing-model")).rejects.toMatchObject({
      code: "MODEL_NOT_FOUND",
    });
  });

  it("toggles favorites idempotently and persists through the state store", async () => {
    const { service, store } = makeService();

    await expect(service.toggleFavorite("qwen-3-5")).resolves.toBe(true);
    await expect(service.toggleFavorite("qwen-3-5")).resolves.toBe(false);
    await expect(service.toggleFavorite("qwen-3-5")).resolves.toBe(true);
    expect(store.read().favorites).toEqual(["qwen-3-5"]);
    await expect(service.list()).resolves.toContainEqual(
      expect.objectContaining({
        item: expect.objectContaining({ model: expect.objectContaining({ product_model_id: "qwen-3-5" }) }),
        favorite: true,
      }),
    );
  });

  it("does not expose forbidden provider or deployment fields", async () => {
    const { service } = makeService();
    const value = await service.get("qwen-3-5");
    const forbidden = /provider|deployment|revision|quantization|precision|license|snapshot/i;

    const keys = JSON.stringify(value).match(/"([A-Za-z_]+)"\s*:/g) ?? [];
    expect(keys.some((key) => forbidden.test(key))).toBe(false);
  });
});
