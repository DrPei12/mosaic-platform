import { describe, expect, it } from "vitest";
import { DEMO_SCENARIO } from "./demo-scenario";

const APPROVED_TTS_NAMES = new Set([
  "Qwen3-TTS 1.7B VoiceDesign",
  "Qwen3-TTS 1.7B CustomVoice",
  "Qwen3-TTS 1.7B Base",
]);

const FORBIDDEN_PUBLIC_KEYS = new Set([
  "provider",
  "provider_model_id",
  "deployment",
  "deployment_id",
  "revision",
  "quantization",
  "precision",
  "license",
  "snapshot_date",
  "context_window",
  "parameter_count",
  "parameter_size",
]);

function findForbiddenKey(value: unknown): string | undefined {
  if (Array.isArray(value)) {
    for (const entry of value) {
      const forbidden = findForbiddenKey(entry);
      if (forbidden) return forbidden;
    }
    return undefined;
  }

  if (typeof value !== "object" || value === null) return undefined;

  for (const [key, entry] of Object.entries(value)) {
    if (FORBIDDEN_PUBLIC_KEYS.has(key.toLowerCase())) return key;
    const forbidden = findForbiddenKey(entry);
    if (forbidden) return forbidden;
  }
  return undefined;
}

describe("DEMO_SCENARIO", () => {
  it("contains the exact canonical model set and category counts", () => {
    expect(DEMO_SCENARIO.scenarioVersion).toBe(1);
    expect(DEMO_SCENARIO.seed).toBe(8202026);

    expect(DEMO_SCENARIO.models.map((model) => [model.product_model_id, model.display_name])).toEqual([
      ["qwen-3-5", "Qwen 3.5"],
      ["deepseek-v4", "DeepSeek V4"],
      ["glm-5-2", "GLM 5.2"],
      ["kimi-k2-7-code", "Kimi K2.7 Code"],
      ["gpt-oss", "GPT-OSS"],
      ["gemma-4", "Gemma 4"],
      ["qwen-image", "Qwen Image"],
      ["flux-2", "FLUX 2"],
      ["hunyuan-video-1-5", "HunyuanVideo 1.5"],
      ["qwen3-tts-voice-design", "Qwen3-TTS 1.7B VoiceDesign"],
      ["qwen3-tts-custom-voice", "Qwen3-TTS 1.7B CustomVoice"],
      ["qwen3-tts-base", "Qwen3-TTS 1.7B Base"],
    ]);

    expect(
      DEMO_SCENARIO.models.reduce<Record<string, number>>((counts, model) => {
        counts[model.category] = (counts[model.category] ?? 0) + 1;
        return counts;
      }, {}),
    ).toEqual({ text: 6, image: 2, video: 1, audio: 3 });
    expect(DEMO_SCENARIO.models.every((model) => model.availability === "demo")).toBe(true);
    expect(
      DEMO_SCENARIO.models
        .filter((model) => model.display_name.includes("1.7B"))
        .every((model) => APPROVED_TTS_NAMES.has(model.display_name)),
    ).toBe(true);
    expect(findForbiddenKey(DEMO_SCENARIO.models)).toBeUndefined();
  });

  it("maps every model to frontend-only presentation metadata and project assets", () => {
    expect(Object.keys(DEMO_SCENARIO.presentations).sort()).toEqual(
      DEMO_SCENARIO.models.map((model) => model.product_model_id).sort(),
    );

    const qwenText = DEMO_SCENARIO.presentations["qwen-3-5"]!;
    expect(qwenText.media).toEqual({
      kind: "abstract",
      src: "/media/models/qwen-3-5-folded-paper.png",
      alt: expect.any(String),
    });

    const qwenImage = DEMO_SCENARIO.presentations["qwen-image"]!;
    expect(qwenImage.media).toMatchObject({ kind: "gallery" });
    if (qwenImage.media.kind === "gallery") {
      expect(qwenImage.media.sources.map((source) => source.src)).toEqual([
        "/media/models/qwen-image-alpine.png",
        "/media/models/qwen-image-chair.png",
        "/media/models/qwen-image-studio-illustration.png",
      ]);
    }

    const video = DEMO_SCENARIO.presentations["hunyuan-video-1-5"]!;
    expect(video.media).toEqual({
      kind: "video",
      src: "/media/models/hunyuan-video-coastal-car.png",
      alt: expect.any(String),
    });

    for (const id of [
      "qwen3-tts-voice-design",
      "qwen3-tts-custom-voice",
      "qwen3-tts-base",
    ]) {
      const presentation = DEMO_SCENARIO.presentations[id]!;
      expect(presentation.media.kind).toBe("audio");
      if (presentation.media.kind === "audio") {
        expect(presentation.media.waveform.length).toBeGreaterThan(0);
      }
    }

    expect(findForbiddenKey(DEMO_SCENARIO.models)).toBeUndefined();
  });

  it("seeds two Qwen 3.5 conversations and fixed-boundary scripts", () => {
    const qwenConversations = DEMO_SCENARIO.conversations.filter(
      (conversation) => conversation.product_model_id === "qwen-3-5",
    );
    expect(qwenConversations.length).toBeGreaterThanOrEqual(2);
    expect(qwenConversations.every((conversation) => conversation.messages.length >= 4)).toBe(true);

    expect(DEMO_SCENARIO.scripts.twoTurn.length).toBeGreaterThanOrEqual(2);
    expect(DEMO_SCENARIO.scripts.twoTurn.every((script) => script.chunks.length >= 2)).toBe(true);
    expect(DEMO_SCENARIO.scripts.timeout[0]!.terminal).toBe("timeout");
    expect(DEMO_SCENARIO.scripts.contentRejected[0]!.terminal).toBe("content_rejected");
    expect(DEMO_SCENARIO.scripts.stop[0]!.terminal).toBe("stopped");
    expect(DEMO_SCENARIO.scripts.twoTurn.every((script) => script.chunks.every(Boolean))).toBe(true);
  });

  it("does not expose mutable scenario references", () => {
    expect(Object.isFrozen(DEMO_SCENARIO)).toBe(true);
    expect(Object.isFrozen(DEMO_SCENARIO.models)).toBe(true);
    expect(Object.isFrozen(DEMO_SCENARIO.presentations)).toBe(true);
    expect(Object.isFrozen(DEMO_SCENARIO.conversations)).toBe(true);
  });
});
