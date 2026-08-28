import type { ModelCategory, PublicProductModel } from "@mosaic/contracts";

import type { ModelPresentation } from "./catalog";

/**
 * Presentation metadata belongs to the frontend, not to a demo scenario or a
 * provider adapter. The keys are stable public product ids only; provider
 * model ids and execution details must never be added here.
 */
export const MODEL_PRESENTATION_REGISTRY: Readonly<Record<string, ModelPresentation>> = {
  "qwen-3-5": {
    productModelId: "qwen-3-5",
    cardStyle: "hero",
    media: {
      kind: "abstract",
      src: "/media/models/qwen-3-5-folded-paper.png",
      alt: "折纸构成的抽象模型卡片图",
    },
    actionLabel: "开始对话",
  },
  "qwen-3-5-plus": {
    productModelId: "qwen-3-5-plus",
    cardStyle: "hero",
    media: {
      kind: "abstract",
      src: "/media/models/qwen-3-5-folded-paper.png",
      alt: "折纸构成的抽象模型卡片图",
    },
    actionLabel: "开始对话",
  },
  "deepseek-v4": {
    productModelId: "deepseek-v4",
    cardStyle: "compact",
    media: { kind: "none" },
    actionLabel: "开始对话",
  },
  "glm-5-2": {
    productModelId: "glm-5-2",
    cardStyle: "compact",
    media: { kind: "none" },
    actionLabel: "开始对话",
  },
  "kimi-k2-7-code": {
    productModelId: "kimi-k2-7-code",
    cardStyle: "compact",
    media: { kind: "none" },
    actionLabel: "开始对话",
  },
  "gpt-oss": {
    productModelId: "gpt-oss",
    cardStyle: "compact",
    media: { kind: "none" },
    actionLabel: "开始对话",
  },
  "gemma-4": {
    productModelId: "gemma-4",
    cardStyle: "compact",
    media: { kind: "none" },
    actionLabel: "开始对话",
  },
  "qwen-image": {
    productModelId: "qwen-image",
    cardStyle: "gallery",
    media: {
      kind: "gallery",
      sources: [
        { src: "/media/models/qwen-image-alpine.png", alt: "雪山风景图像样例" },
        { src: "/media/models/qwen-image-chair.png", alt: "椅子产品图像样例" },
        { src: "/media/models/qwen-image-studio-illustration.png", alt: "工作室插画样例" },
      ],
    },
    actionLabel: "打开工作台",
  },
  "qwen-image-3-0-pro": {
    productModelId: "qwen-image-3-0-pro",
    cardStyle: "gallery",
    media: {
      kind: "gallery",
      sources: [
        { src: "/media/models/qwen-image-alpine.png", alt: "雪山风景图像样例" },
        { src: "/media/models/qwen-image-chair.png", alt: "椅子产品图像样例" },
        { src: "/media/models/qwen-image-studio-illustration.png", alt: "工作室插画样例" },
      ],
    },
    actionLabel: "打开工作台",
  },
  "flux-2": {
    productModelId: "flux-2",
    cardStyle: "compact",
    media: { kind: "none" },
    actionLabel: "打开工作台",
  },
  "hunyuan-video-1-5": {
    productModelId: "hunyuan-video-1-5",
    cardStyle: "video",
    media: {
      kind: "video",
      src: "/media/models/hunyuan-video-coastal-car.png",
      alt: "海岸公路汽车视频卡片图",
    },
    actionLabel: "打开工作台",
  },
  "qwen3-tts-voice-design": {
    productModelId: "qwen3-tts-voice-design",
    cardStyle: "audio",
    media: { kind: "audio", waveform: [0.18, 0.42, 0.29, 0.76, 0.51, 0.88, 0.35, 0.62, 0.23, 0.69, 0.46, 0.81], durationLabel: "00:18" },
    actionLabel: "打开工作台",
  },
  "qwen3-tts-custom-voice": {
    productModelId: "qwen3-tts-custom-voice",
    cardStyle: "audio",
    media: { kind: "audio", waveform: [0.18, 0.42, 0.29, 0.76, 0.51, 0.88, 0.35, 0.62, 0.23, 0.69, 0.46, 0.81], durationLabel: "00:21" },
    actionLabel: "打开工作台",
  },
  "qwen3-tts-base": {
    productModelId: "qwen3-tts-base",
    cardStyle: "audio",
    media: { kind: "audio", waveform: [0.18, 0.42, 0.29, 0.76, 0.51, 0.88, 0.35, 0.62, 0.23, 0.69, 0.46, 0.81], durationLabel: "00:16" },
    actionLabel: "打开工作台",
  },
  "qwen3-tts-flash": {
    productModelId: "qwen3-tts-flash",
    cardStyle: "audio",
    media: { kind: "audio", waveform: [0.18, 0.42, 0.29, 0.76, 0.51, 0.88, 0.35, 0.62, 0.23, 0.69, 0.46, 0.81], durationLabel: "00:16" },
    actionLabel: "打开工作台",
  },
  "wan-2-7": {
    productModelId: "wan-2-7",
    cardStyle: "compact",
    media: { kind: "none" },
    actionLabel: "打开工作台",
  },
};

const FALLBACK_CARD_STYLES: Record<ModelCategory, ModelPresentation["cardStyle"]> = {
  // Unknown production models have no trusted preview asset. Every category
  // therefore uses the compact, no-preview treatment.
  text: "compact",
  image: "compact",
  video: "compact",
  audio: "compact",
};

function fallbackCardStyle(category: ModelCategory): ModelPresentation["cardStyle"] {
  return FALLBACK_CARD_STYLES[category];
}

function fallbackActionLabel(model: Pick<PublicProductModel, "category" | "task_type">): string {
  return model.task_type === "chat" || model.category === "text"
    ? "开始对话"
    : "打开工作台";
}

function copyPresentation(presentation: ModelPresentation): ModelPresentation {
  return {
    productModelId: presentation.productModelId,
    cardStyle: presentation.cardStyle,
    media:
      presentation.media.kind === "gallery"
        ? { kind: "gallery", sources: presentation.media.sources.map((source) => ({ ...source })) }
        : presentation.media.kind === "audio"
          ? { kind: "audio", waveform: [...presentation.media.waveform], durationLabel: presentation.media.durationLabel }
          : { ...presentation.media },
    actionLabel: presentation.actionLabel,
  };
}

/**
 * Resolve frontend-only card metadata for a server catalog item. Known ids
 * keep the designed media treatment; new ids receive an honest no-preview
 * fallback instead of being rejected or shown with invented examples.
 */
export function createModelPresentation(
  model: Pick<PublicProductModel, "product_model_id" | "category" | "task_type">,
): ModelPresentation {
  const registered = MODEL_PRESENTATION_REGISTRY[model.product_model_id];
  if (registered) return copyPresentation(registered);

  return {
    productModelId: model.product_model_id,
    cardStyle: fallbackCardStyle(model.category),
    media: { kind: "none" },
    actionLabel: fallbackActionLabel(model),
  };
}
