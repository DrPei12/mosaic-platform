import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import apiErrorSchema from "../schemas/api-error.schema.json";
import healthSchema from "../schemas/health.schema.json";
import productSchema from "../schemas/public-product-model.schema.json";

const ajv = new Ajv2020({ allErrors: true });

describe("public contracts", () => {
  it("accepts the health fixture", () => {
    expect(ajv.validate(healthSchema, { service: "mosaic-api", status: "ready", version: "0.1.0" })).toBe(true);
  });

  it("requires a stable error code and request id", () => {
    expect(
      ajv.validate(apiErrorSchema, {
        error: { code: "SERVICE_UNAVAILABLE", message: "服务暂不可用", request_id: "req_demo_001", retryable: true },
      }),
    ).toBe(true);
  });

  it("accepts a public text-to-video model without provider fields", () => {
    const payload = {
      product_model_id: "wan-2-7",
      display_name: "Wan 2.7",
      category: "video",
      task_type: "text_to_video",
      description: "用于文字生成视频的模型。",
      capabilities: ["文字生成视频"],
      availability: "available",
      pricing_summary: "按量计费",
    };

    expect(ajv.validate(productSchema, payload)).toBe(true);
    expect(payload).not.toHaveProperty("provider_model_id");
  });

  it.each(["provider", "provider_model_id", "quantization", "license", "snapshot_date", "deployment_id"])(
    "rejects internal field %s from public product models",
    (field) => {
      const payload = {
        product_model_id: "qwen-3-5",
        display_name: "Qwen 3.5",
        category: "text",
        task_type: "chat",
        description: "适合复杂推理与多轮对话",
        capabilities: ["多轮对话"],
        availability: "available",
        pricing_summary: "演示点数",
        [field]: "must-not-leak",
      };
      expect(ajv.validate(productSchema, payload)).toBe(false);
    },
  );
});
