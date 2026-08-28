import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  getModel: vi.fn(),
  create: vi.fn(),
  list: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("next/image", () => ({
  default: (props: Record<string, unknown>) => {
    const nextProps = { ...props };
    delete nextProps.fill;
    delete nextProps.sizes;
    // eslint-disable-next-line @next/next/no-img-element
    return <img alt={(nextProps.alt as string | undefined) ?? ""} {...nextProps} />;
  },
}));

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    modelCatalog: {
      get: mocks.getModel,
    },
    generation: {
      create: mocks.create,
      list: mocks.list,
    },
  }),
}));

import type { CatalogModel } from "@/services/interfaces";
import { GenerationStudio } from "./generation-studio";

function model(
  modality: "image" | "video" | "audio",
  overrides: Partial<CatalogModel["item"]["model"]> = {},
): CatalogModel {
  const taskType = modality === "image" ? "text_to_image" : modality === "video" ? "text_to_video" : "tts";
  return {
    item: {
      model: {
        product_model_id: `${modality}-model`,
        display_name: modality === "image" ? "Qwen Image" : modality === "video" ? "Wan 2.7" : "Qwen3 TTS",
        category: modality,
        task_type: taskType,
        description: `${modality} model`,
        capabilities: ["生成"],
        availability: "available",
        pricing_summary: "服务端计费",
        ...overrides,
      },
      collections: [],
    },
    presentation: {
      productModelId: `${modality}-model`,
      cardStyle: "compact",
      media: { kind: "none" },
      actionLabel: "打开工作台",
    },
    favorite: false,
  };
}

async function openStudio(modality: "image" | "video" | "audio") {
  mocks.getModel.mockResolvedValue(model(modality));
  mocks.list.mockResolvedValue([]);
  render(<GenerationStudio modelId={`${modality}-model`} modality={modality} />);
  return screen.findByTestId(`generation-studio-${modality}`);
}

describe("GenerationStudio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("submits the image prompt, size and count, then opens the returned job", async () => {
    const user = userEvent.setup();
    await openStudio("image");
    mocks.create.mockResolvedValue({ job_id: "image-job-1", modality: "image", status: "accepted", created_at: "2026-08-24T12:00:00Z" });

    await user.type(screen.getByLabelText("提示词"), "A red paper boat on a lake");
    await user.selectOptions(screen.getByLabelText("尺寸"), "512*512");
    await user.selectOptions(screen.getByLabelText("数量"), "2");
    await user.click(screen.getByRole("button", { name: "提交生成任务" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        productModelId: "image-model",
        modality: "image",
        input: { prompt: "A red paper boat on a lake", size: "512*512", count: 2 },
        clientRequestId: expect.any(String),
      }),
      expect.any(AbortSignal),
    );
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/generations/image-job-1"));
  });

  it("uses the visible image defaults in the submitted payload", async () => {
    const user = userEvent.setup();
    await openStudio("image");
    mocks.create.mockResolvedValue({ job_id: "image-default-job", modality: "image", status: "accepted", created_at: "2026-08-24T12:00:00Z" });

    await user.type(screen.getByLabelText("提示词"), "A quiet editorial still life");
    await user.click(screen.getByRole("button", { name: "提交生成任务" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        input: {
          prompt: "A quiet editorial still life",
          size: "1024*1024",
          count: 1,
        },
      }),
      expect.any(AbortSignal),
    ));
  });

  it("submits the video prompt with resolution, ratio and duration", async () => {
    const user = userEvent.setup();
    await openStudio("video");
    mocks.create.mockResolvedValue({ job_id: "video-job-1", modality: "video", status: "accepted", created_at: "2026-08-24T12:00:00Z" });

    await user.type(screen.getByLabelText("提示词"), "A slow camera move through a pine forest");
    await user.selectOptions(screen.getByLabelText("清晰度"), "1080P");
    await user.selectOptions(screen.getByLabelText("画面比例"), "9:16");
    await user.selectOptions(screen.getByLabelText("时长"), "5");
    await user.click(screen.getByRole("button", { name: "提交生成任务" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        productModelId: "video-model",
        modality: "video",
        input: { prompt: "A slow camera move through a pine forest", resolution: "1080P", ratio: "9:16", duration_seconds: 5 },
      }),
      expect.any(AbortSignal),
    );
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/generations/video-job-1"));
  });

  it("keeps provider voice server-bound and sends only the language", async () => {
    const user = userEvent.setup();
    await openStudio("audio");
    mocks.create.mockResolvedValue({ job_id: "audio-job-1", modality: "audio", status: "accepted", created_at: "2026-08-24T12:00:00Z" });

    expect(screen.getByText("Cherry · 自然女声")).toBeInTheDocument();
    expect(screen.queryByLabelText("音色")).not.toBeInTheDocument();
    expect(screen.getByLabelText("语言")).toHaveValue("Chinese");
    expect(screen.queryByRole("button", { name: /参考媒体|参考图/ })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("要合成的文本"), "你好，欢迎使用这个平台。");
    await user.click(screen.getByRole("button", { name: "提交生成任务" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        modality: "audio",
        input: { text: "你好，欢迎使用这个平台。", language_type: "Chinese" },
      }),
      expect.any(AbortSignal),
    );
  });

  it("hides unsupported reference inputs", async () => {
    await openStudio("image");
    expect(screen.queryByText("参考图")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /参考图|参考媒体/ })).not.toBeInTheDocument();

    cleanup();
    await openStudio("video");
    expect(screen.queryByText("参考媒体")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /参考图|参考媒体/ })).not.toBeInTheDocument();
  });

  it("shows a submission error and does not navigate", async () => {
    const user = userEvent.setup();
    await openStudio("image");
    mocks.create.mockRejectedValue(new Error("服务端拒绝了这次任务"));

    await user.type(screen.getByLabelText("提示词"), "An impossible request");
    await user.click(screen.getByRole("button", { name: "提交生成任务" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("生成任务暂时不可用，请稍后重试。");
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("does not expose an internal model loading Error message", async () => {
    const internalMessage = "MODEL_PROVIDER_DEPLOYMENT_INTERNAL";
    mocks.getModel.mockRejectedValueOnce(new Error(internalMessage));

    render(<GenerationStudio modelId="image-model" modality="image" />);

    const error = await screen.findByTestId("generation-studio-error");
    expect(error).toHaveTextContent("模型信息暂时不可用，请稍后重试。");
    expect(error).not.toHaveTextContent(internalMessage);
  });

  it("fails closed when the catalog has not marked the model available", async () => {
    mocks.getModel.mockResolvedValue(model("image", { availability: "demo" }));
    render(<GenerationStudio modelId="image-model" modality="image" />);

    expect(await screen.findByText("当前能力暂不可提交")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交生成任务" })).not.toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
  });
});
