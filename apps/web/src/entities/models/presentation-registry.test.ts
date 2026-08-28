import { describe, expect, it } from "vitest";

import { createModelPresentation } from "./presentation-registry";

describe("production model presentations", () => {
  it("keeps verified Qwen product IDs on the high-fidelity card treatments", () => {
    expect(createModelPresentation({
      product_model_id: "qwen-3-5-plus",
      category: "text",
      task_type: "chat",
    })).toMatchObject({ cardStyle: "hero", media: { kind: "abstract" } });

    expect(createModelPresentation({
      product_model_id: "qwen-image-3-0-pro",
      category: "image",
      task_type: "text_to_image",
    })).toMatchObject({ cardStyle: "gallery", media: { kind: "gallery" } });

    expect(createModelPresentation({
      product_model_id: "qwen3-tts-flash",
      category: "audio",
      task_type: "tts",
    })).toMatchObject({ cardStyle: "audio", media: { kind: "audio" } });
  });

  it("does not relabel the Hunyuan preview as a Wan model result", () => {
    expect(createModelPresentation({
      product_model_id: "wan-2-7",
      category: "video",
      task_type: "text_to_video",
    })).toEqual({
      productModelId: "wan-2-7",
      cardStyle: "compact",
      media: { kind: "none" },
      actionLabel: "打开工作台",
    });
  });
});
