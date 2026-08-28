import { describe, expect, it, vi } from "vitest";
import { DEMO_SCENARIO } from "@/shared/demo/demo-scenario";
import {
  ApiModelCatalogServiceError,
  createApiModelCatalogService,
} from "./api-model-catalog-service";

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function validCatalog() {
  return {
    items: DEMO_SCENARIO.catalog.map((item) => ({
      model: { ...item.model },
      collections: [...item.collections],
    })),
  };
}

function newProductionModel() {
  return {
    model: {
      product_model_id: "studio-image-next",
      display_name: "Studio Image Next",
      category: "image" as const,
      task_type: "text_to_image" as const,
      description: "服务端新增的图像生成模型。",
      capabilities: ["文字生成图像"],
      availability: "available" as const,
      pricing_summary: "按量计费",
    },
    collections: ["new" as const],
  };
}

function wanProductionModel() {
  return {
    model: {
      product_model_id: "wan-2-7",
      display_name: "Wan 2.7",
      category: "video" as const,
      task_type: "text_to_video" as const,
      description: "用于文字生成视频的模型。",
      capabilities: ["文字生成视频"],
      availability: "available" as const,
      pricing_summary: "按量计费",
    },
    collections: ["new" as const],
  };
}

describe("api model catalog service", () => {
  it("builds encoded query parameters and attaches local presentation metadata", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(validCatalog()));
    const service = createApiModelCatalogService(fetcher);

    const result = await service.list({
      category: "text",
      search: "代码 / 设计",
      collection: "popular",
    });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/models?category=text&search=%E4%BB%A3%E7%A0%81%20%2F%20%E8%AE%BE%E8%AE%A1&collection=popular",
      expect.objectContaining({ headers: { accept: "application/json" } }),
    );
    expect(result[0]).toEqual(
      expect.objectContaining({
        item: expect.objectContaining({ model: expect.objectContaining({ product_model_id: "qwen-3-5" }) }),
        presentation: DEMO_SCENARIO.presentations["qwen-3-5"],
        favorite: false,
      }),
    );
  });

  it("keeps a server-added model and gives it an honest compact presentation", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ items: [newProductionModel()] }));
    const service = createApiModelCatalogService(fetcher);

    await expect(service.list()).resolves.toEqual([
      expect.objectContaining({
        item: expect.objectContaining({
          model: expect.objectContaining({ product_model_id: "studio-image-next" }),
        }),
        presentation: {
          productModelId: "studio-image-next",
          cardStyle: "compact",
          media: { kind: "none" },
          actionLabel: "打开工作台",
        },
        favorite: false,
      }),
    ]);
  });

  it("accepts Wan 2.7 text-to-video without exposing provider fields", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ items: [wanProductionModel()] }));
    const service = createApiModelCatalogService(fetcher);

    const [model] = await service.list();

    expect(model).toEqual(expect.objectContaining({
      item: expect.objectContaining({
        model: expect.objectContaining({
          product_model_id: "wan-2-7",
          category: "video",
          task_type: "text_to_video",
        }),
      }),
      presentation: {
        productModelId: "wan-2-7",
        cardStyle: "compact",
        media: { kind: "none" },
        actionLabel: "打开工作台",
      },
    }));
    expect(model?.item.model).not.toHaveProperty("provider_model_id");
  });

  it("validates the exact public catalog response", async () => {
    const extra = validCatalog() as unknown as {
      items: Array<{ model: Record<string, unknown> }>;
    };
    extra.items[0]!.model.provider = "internal";
    const service = createApiModelCatalogService(
      vi.fn().mockResolvedValue(response(extra)),
    );

    await expect(service.list()).rejects.toMatchObject({
      code: "MODEL_CATALOG_UNAVAILABLE",
      status: 200,
      retryable: false,
    });
  });

  it.each([
    ["missing items", {}],
    ["malformed model", { items: [{ model: {}, collections: [] }] }],
    ["unknown collection", { items: [{ model: DEMO_SCENARIO.catalog[0]!.model, collections: ["internal"] }] }],
  ])("rejects %s response bodies", async (_name, body) => {
    const service = createApiModelCatalogService(
      vi.fn().mockResolvedValue(response(body)),
    );

    await expect(service.list()).rejects.toBeInstanceOf(ApiModelCatalogServiceError);
  });

  it.each([404, 500, 503])("maps HTTP %s to a typed unavailable error", async (status) => {
    const service = createApiModelCatalogService(
      vi.fn().mockResolvedValue(response({ error: "hidden" }, status)),
    );

    await expect(service.list()).rejects.toMatchObject({
      code: "MODEL_CATALOG_UNAVAILABLE",
      status,
      retryable: status >= 500,
    });
  });

  it("maps an absent stable id to MODEL_NOT_FOUND", async () => {
    const service = createApiModelCatalogService(
      vi.fn().mockResolvedValue(response(validCatalog())),
    );

    await expect(service.get("missing-model")).rejects.toMatchObject({
      code: "MODEL_NOT_FOUND",
      status: 404,
      retryable: false,
    });
  });

  it("preserves AbortError from fetch and response parsing", async () => {
    const abortError = new DOMException("aborted", "AbortError");
    const fetcher = vi.fn().mockRejectedValue(abortError);
    const service = createApiModelCatalogService(fetcher);

    await expect(service.list()).rejects.toBe(abortError);
  });

  it("keeps frontend-only favorites in the current API service session", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(validCatalog()));
    const service = createApiModelCatalogService(fetcher);

    await service.list();
    await expect(service.toggleFavorite("qwen-3-5")).resolves.toBe(true);
    await expect(service.list()).resolves.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          item: expect.objectContaining({
            model: expect.objectContaining({ product_model_id: "qwen-3-5" }),
          }),
          favorite: true,
        }),
      ]),
    );
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("allows a server-added model to be favorited after a real catalog check", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ items: [newProductionModel()] }));
    const service = createApiModelCatalogService(fetcher);

    await expect(service.toggleFavorite("studio-image-next")).resolves.toBe(true);
    await expect(service.list()).resolves.toEqual([
      expect.objectContaining({ favorite: true }),
    ]);
  });

  it("rejects a presentation-known id when the server catalog does not contain it", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ items: [] }));
    const service = createApiModelCatalogService(fetcher);

    await expect(service.toggleFavorite("qwen-3-5")).rejects.toMatchObject({
      code: "MODEL_NOT_FOUND",
      status: 404,
      retryable: false,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/models",
      expect.objectContaining({ headers: { accept: "application/json" } }),
    );
  });
});
