import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockPush = vi.hoisted(() => vi.fn());
const mockReplace = vi.hoisted(() => vi.fn());
const mockList = vi.hoisted(() => vi.fn());
const mockToggleFavorite = vi.hoisted(() => vi.fn());
const mockCreateConversation = vi.hoisted(() => vi.fn());
const mockSearchParams = vi.hoisted(() => new URLSearchParams());

vi.mock("next/navigation", () => ({
  usePathname: () => "/models",
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
}));

vi.mock("next/image", () => ({
  default: (inputProps: Record<string, unknown>) => {
    const props = { ...inputProps };
    delete props.fill;
    delete props.priority;
    // eslint-disable-next-line @next/next/no-img-element
    return <img alt={(props.alt as string | undefined) ?? ""} {...props} />;
  },
}));

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    modelCatalog: {
      list: mockList,
      get: vi.fn(),
      toggleFavorite: mockToggleFavorite,
    },
    conversation: {
      createConversation: mockCreateConversation,
    },
  }),
}));

import type { CatalogModel } from "@/services/interfaces";
import { ModelMarketplace } from "./model-marketplace";

const model = (overrides: Partial<CatalogModel["item"]["model"]> & { id: string; name: string; category: CatalogModel["item"]["model"]["category"]; task: CatalogModel["item"]["model"]["task_type"] }): CatalogModel => {
  const { id, name, category, task, ...rest } = overrides;
  const presentation: CatalogModel["presentation"] = id === "qwen-3-5"
    ? {
        productModelId: id,
        cardStyle: "hero",
        media: { kind: "abstract", src: "/media/models/qwen-3-5-folded-paper.png", alt: "折纸构成的抽象模型卡片图" },
        actionLabel: "开始对话",
      }
    : id === "qwen-image"
      ? {
          productModelId: id,
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
        }
      : id === "hunyuan-video-1-5"
        ? {
            productModelId: id,
            cardStyle: "video",
            media: { kind: "video", src: "/media/models/hunyuan-video-coastal-car.png", alt: "海岸公路汽车视频卡片图" },
            actionLabel: "打开工作台",
          }
        : id.startsWith("qwen3-tts")
          ? {
              productModelId: id,
              cardStyle: "audio",
              media: { kind: "audio", waveform: [0.18, 0.42, 0.76, 0.51, 0.88, 0.35], durationLabel: "00:18" },
              actionLabel: "打开工作台",
            }
          : {
              productModelId: id,
              cardStyle: "compact",
              media: { kind: "none" },
              actionLabel: task === "chat" ? "开始对话" : "打开工作台",
            };
  return {
  item: {
    model: {
      product_model_id: id,
      display_name: name,
      category,
      task_type: task,
      description: `${name} description`,
      capabilities: ["多轮对话", "内容创作"],
      availability: "demo",
      pricing_summary: "演示额度",
      ...rest,
    },
    collections: ["featured"],
  },
  presentation,
  favorite: false,
  };
};

const catalog: readonly CatalogModel[] = [
  model({ id: "qwen-3-5", name: "Qwen 3.5", category: "text", task: "chat" }),
  model({ id: "deepseek-v4", name: "DeepSeek V4", category: "text", task: "chat" }),
  model({ id: "glm-5-2", name: "GLM 5.2", category: "text", task: "chat" }),
  model({ id: "kimi-k2-7-code", name: "Kimi K2.7 Code", category: "text", task: "chat" }),
  model({ id: "gpt-oss", name: "GPT-OSS", category: "text", task: "chat" }),
  model({ id: "gemma-4", name: "Gemma 4", category: "text", task: "chat" }),
  model({ id: "qwen-image", name: "Qwen Image", category: "image", task: "text_to_image" }),
  model({ id: "flux-2", name: "FLUX 2", category: "image", task: "text_to_image" }),
  model({ id: "hunyuan-video-1-5", name: "HunyuanVideo 1.5", category: "video", task: "image_to_video" }),
  model({ id: "qwen3-tts-voice-design", name: "Qwen3-TTS 1.7B VoiceDesign", category: "audio", task: "tts" }),
  model({ id: "qwen3-tts-custom-voice", name: "Qwen3-TTS 1.7B CustomVoice", category: "audio", task: "tts" }),
  model({ id: "qwen3-tts-base", name: "Qwen3-TTS 1.7B Base", category: "audio", task: "tts" }),
];

function withAvailability(
  catalogModel: CatalogModel,
  availability: CatalogModel["item"]["model"]["availability"],
): CatalogModel {
  return {
    ...catalogModel,
    item: {
      ...catalogModel.item,
      model: { ...catalogModel.item.model, availability },
    },
  };
}

const mixedAvailabilityCatalog: readonly CatalogModel[] = catalog.map((catalogModel) => {
  if (catalogModel.item.model.product_model_id === "deepseek-v4") {
    return withAvailability(catalogModel, "maintenance");
  }
  if (catalogModel.item.model.product_model_id === "glm-5-2") {
    return withAvailability(catalogModel, "unavailable");
  }
  if (catalogModel.item.model.product_model_id === "qwen3-tts-voice-design") {
    return withAvailability(catalogModel, "unavailable");
  }
  return catalogModel;
});

function listForQuery(query?: { category?: string; search?: string; collection?: string }) {
  return catalog.filter(({ item }) => {
    if (query?.category && item.model.category !== query.category) return false;
    if (query?.collection && !item.collections.includes(query.collection as "featured")) return false;
    if (query?.search && !JSON.stringify(item).toLocaleLowerCase().includes(query.search.toLocaleLowerCase())) return false;
    return true;
  });
}

describe("ModelMarketplace", () => {
  beforeEach(() => {
    mockSearchParams.delete("category");
    mockSearchParams.delete("search");
    mockSearchParams.delete("collection");
    mockSearchParams.delete("workspace");
    mockPush.mockReset();
    mockReplace.mockReset();
    mockList.mockReset();
    mockToggleFavorite.mockReset();
    mockCreateConversation.mockReset();
    mockList.mockImplementation((query) => Promise.resolve(listForQuery(query)));
    mockToggleFavorite.mockImplementation((id: string) => Promise.resolve(id === "qwen-3-5"));
    mockCreateConversation.mockResolvedValue({ conversation_id: "conversation-created" });
  });

  afterEach(() => cleanup());

  it("renders the exact twelve canonical model names and category tabs", async () => {
    render(<ModelMarketplace />);

    for (const name of [
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
    ]) {
      expect(await screen.findByText(name)).toBeInTheDocument();
    }

    const categoryGroup = screen.getByRole("group", { name: "模型类型" });
    expect(categoryGroup).toBeInTheDocument();
    expect(within(categoryGroup).getByRole("button", { name: "全部", pressed: true })).toBeInTheDocument();
    for (const label of ["文本", "图像", "视频", "音频"]) {
      expect(within(categoryGroup).getByRole("button", { name: label, pressed: false })).toBeInTheDocument();
    }
  });

  it("renders the real hero, gallery, video, audio and compact compositions", async () => {
    render(<ModelMarketplace />);

    const hero = await screen.findByTestId("model-card-qwen-3-5");
    expect(within(hero).getByRole("img", { name: "折纸构成的抽象模型卡片图" })).toBeInTheDocument();
    expect(within(hero).queryByRole("button", { name: "查看 Qwen 3.5 详情" })).not.toBeInTheDocument();
    expect(within(hero).queryByText("内部演示入口")).not.toBeInTheDocument();
    expect(within(hero).queryByText("可保存收藏")).not.toBeInTheDocument();

    const gallery = screen.getByTestId("model-card-qwen-image");
    expect(within(gallery).getAllByRole("img")).toHaveLength(3);
    expect(gallery.querySelectorAll(".aspect-square")).toHaveLength(3);
    const galleryRow = within(gallery).getByTestId("model-gallery-row");
    expect(galleryRow).toHaveClass("lg:flex-row");
    expect(galleryRow.querySelector(".max-w-\\[320px\\]")).not.toBeInTheDocument();
    expect(within(galleryRow).getByRole("button", { name: "查看 Qwen Image 详情" })).toBeInTheDocument();

    const video = screen.getByTestId("model-card-hunyuan-video-1-5");
    expect(within(video).getByRole("img", { name: "海岸公路汽车视频卡片图" })).toBeInTheDocument();
    expect(within(video).getByRole("button", { name: "查看 HunyuanVideo 1.5 详情" })).toBeInTheDocument();

    const audio = screen.getByTestId("model-card-qwen3-tts-voice-design");
    expect(within(audio).getByRole("img", { name: "Qwen3-TTS 1.7B VoiceDesign 音频波形预览" })).toBeInTheDocument();
    expect(within(audio).queryByRole("button", { name: /播放/ })).not.toBeInTheDocument();

    const compact = screen.getByTestId("model-card-deepseek-v4");
    expect(within(compact).getByRole("button", { name: "查看 DeepSeek V4 详情" })).toBeInTheDocument();
    expect(within(compact).queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows a partial availability notice and disables only unavailable model actions", async () => {
    const user = userEvent.setup();
    mockList.mockResolvedValueOnce(mixedAvailabilityCatalog);
    render(<ModelMarketplace />);

    expect(await screen.findByTestId("model-marketplace-partial-availability")).toHaveTextContent(
      "部分模型暂不可用",
    );
    expect(screen.getAllByRole("status")).toHaveLength(1);

    const maintenanceCard = screen.getByTestId("model-card-deepseek-v4");
    expect(within(maintenanceCard).getByText("维护中")).toBeInTheDocument();
    expect(within(maintenanceCard).getByRole("button", { name: "开始对话 DeepSeek V4" })).toBeDisabled();
    expect(within(maintenanceCard).getByRole("button", { name: "收藏 DeepSeek V4" })).not.toBeDisabled();

    const unavailableCard = screen.getByTestId("model-card-glm-5-2");
    expect(within(unavailableCard).getByText("暂不可用")).toBeInTheDocument();
    expect(within(unavailableCard).getByRole("button", { name: "开始对话 GLM 5.2" })).toBeDisabled();

    const unavailableAudioCard = screen.getByTestId("model-card-qwen3-tts-voice-design");
    expect(within(unavailableAudioCard).getByText("暂不可用")).toBeInTheDocument();
    expect(within(unavailableAudioCard).queryByRole("button", { name: /播放/ })).not.toBeInTheDocument();

    await user.click(within(maintenanceCard).getByRole("button", { name: "查看 DeepSeek V4 详情" }));
    const dialog = await screen.findByRole("dialog", { name: "DeepSeek V4" });
    expect(within(dialog).getByText("维护中")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "开始对话" })).toBeDisabled();
    expect(mockCreateConversation).not.toHaveBeenCalled();
  });

  it("keeps the search clear target at the same 44px size as the input", async () => {
    const user = userEvent.setup();
    render(<ModelMarketplace />);
    const search = await screen.findByRole("searchbox", { name: "搜索模型" });
    await user.type(search, "Qwen");
    const clear = screen.getByRole("button", { name: "清空搜索" });
    expect(clear).toHaveClass("min-h-11", "min-w-11");
    expect(clear).not.toHaveClass("min-h-9", "min-w-9");
  });

  it("applies category and search as one intersection and recovers from empty results", async () => {
    const user = userEvent.setup();
    render(<ModelMarketplace />);

    await user.click(await screen.findByRole("button", { name: "图像" }));
    const search = screen.getByRole("searchbox", { name: "搜索模型" });
    await user.type(search, "FLUX");

    expect(await screen.findByRole("heading", { name: "FLUX 2" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Qwen Image" })).not.toBeInTheDocument();
    expect(mockList).toHaveBeenLastCalledWith(
      { category: "image", search: "FLUX" },
      expect.any(AbortSignal),
    );

    await user.clear(search);
    await user.type(search, "not-a-real-model");
    expect(await screen.findByRole("status")).toHaveTextContent("没有找到匹配的模型");
    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(await screen.findByRole("heading", { name: "Qwen Image" })).toBeInTheDocument();
  });

  it("hydrates local filters when URL history changes after mount", async () => {
    const user = userEvent.setup();
    const view = render(<ModelMarketplace />);
    await screen.findByRole("heading", { name: "Qwen 3.5" });

    mockSearchParams.set("category", "audio");
    mockSearchParams.set("search", "Base");
    view.rerender(<ModelMarketplace />);

    await waitFor(() => expect(screen.getByRole("searchbox", { name: "搜索模型" })).toHaveValue("Base"));
    expect(screen.getByRole("button", { name: "音频" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("heading", { name: "Qwen3-TTS 1.7B Base" })).toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox", { name: "搜索模型" }));
    expect(mockReplace).toHaveBeenLastCalledWith("/models?category=audio", { scroll: false });
  });

  it("aborts the superseded catalog request and ignores its result", async () => {
    const user = userEvent.setup();
    const requests: Array<{ signal: AbortSignal; resolve: (items: readonly CatalogModel[]) => void }> = [];
    mockList.mockImplementation((_query: unknown, signal: AbortSignal) => new Promise((resolve, reject) => {
      requests.push({ signal, resolve });
      signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    render(<ModelMarketplace />);
    await waitFor(() => expect(requests).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: "图像" }));
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0]?.signal.aborted).toBe(true);
    requests[0]?.resolve(catalog);
    requests[1]?.resolve(catalog.filter(({ item }) => item.model.category === "image"));
    expect(await screen.findByRole("heading", { name: "Qwen Image" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Qwen 3.5" })).not.toBeInTheDocument();
  });

  it("clears only marketplace query keys and preserves unrelated URL state", async () => {
    const user = userEvent.setup();
    mockSearchParams.set("workspace", "review");
    mockSearchParams.set("category", "image");
    mockSearchParams.set("search", "Qwen");
    mockSearchParams.set("collection", "featured");
    render(<ModelMarketplace />);
    await screen.findByRole("heading", { name: "Qwen Image" });

    await user.click(screen.getByRole("button", { name: "打开筛选" }));
    await user.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(mockReplace).toHaveBeenLastCalledWith("/models?workspace=review", { scroll: false });
  });

  it("opens the collection filter and keeps URL state observable", async () => {
    const user = userEvent.setup();
    render(<ModelMarketplace />);

    await user.click(screen.getByRole("button", { name: "打开筛选" }));
    const filter = screen.getByRole("region", { name: "模型集合筛选" });
    expect(filter).toBeInTheDocument();
    await user.selectOptions(within(filter).getByRole("combobox", { name: "模型集合" }), "popular");

    expect(mockReplace).toHaveBeenCalled();
    expect(mockReplace.mock.lastCall?.[0]).toContain("collection=popular");
  });

  it("toggles favorite without navigating and exposes an independent pressed state", async () => {
    const user = userEvent.setup();
    render(<ModelMarketplace />);

    const favorite = await screen.findByRole("button", { name: "收藏 Qwen 3.5" });
    expect(favorite).toHaveAttribute("aria-pressed", "false");
    await user.click(favorite);

    expect(mockToggleFavorite).toHaveBeenCalledWith("qwen-3-5", expect.any(AbortSignal));
    expect(favorite).toHaveAttribute("aria-pressed", "true");
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("disables every action CTA while another model action is in flight", async () => {
    const user = userEvent.setup();
    let resolveConversation: ((value: { conversation_id: string }) => void) | undefined;
    mockCreateConversation.mockImplementation(
      () => new Promise((resolve) => { resolveConversation = resolve; }),
    );
    render(<ModelMarketplace />);

    const qwenAction = await screen.findByRole("button", { name: "开始对话 Qwen 3.5" });
    const deepseekAction = screen.getByRole("button", { name: "开始对话 DeepSeek V4" });
    await user.click(qwenAction);

    await waitFor(() => expect(qwenAction).toBeDisabled());
    expect(deepseekAction).toBeDisabled();
    await user.click(deepseekAction);
    expect(mockCreateConversation).toHaveBeenCalledTimes(1);

    const imageDetails = screen.getByRole("button", { name: "查看 Qwen Image 详情" });
    await user.click(imageDetails);
    const dialog = await screen.findByRole("dialog", { name: "Qwen Image" });
    expect(within(dialog).getByRole("button", { name: /打开工作台/ })).toBeDisabled();

    resolveConversation?.({ conversation_id: "conversation-created" });
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/chat/conversation-created"));
  });

  it("aborts pending favorite writes on unmount and ignores the late result", async () => {
    const user = userEvent.setup();
    let favoriteSignal: AbortSignal | undefined;
    let resolveFavorite: ((value: boolean) => void) | undefined;
    mockToggleFavorite.mockImplementation((_id: string, signal: AbortSignal) => {
      favoriteSignal = signal;
      return new Promise((resolve, reject) => {
        resolveFavorite = resolve;
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      });
    });
    const view = render(<ModelMarketplace />);
    await user.click(await screen.findByRole("button", { name: "收藏 Qwen 3.5" }));
    view.unmount();

    expect(favoriteSignal?.aborted).toBe(true);
    resolveFavorite?.(true);
    await Promise.resolve();
  });

  it("does not let a stale favorite result overwrite a refreshed catalog", async () => {
    const user = userEvent.setup();
    let resolveFavorite: ((value: boolean) => void) | undefined;
    mockToggleFavorite.mockImplementation(() => new Promise((resolve) => { resolveFavorite = resolve; }));
    render(<ModelMarketplace />);
    await user.click(await screen.findByRole("button", { name: "收藏 Qwen 3.5" }));
    await user.click(screen.getByRole("button", { name: "文本" }));
    expect(await screen.findByRole("heading", { name: "Qwen 3.5" })).toBeInTheDocument();

    resolveFavorite?.(true);
    await waitFor(() => expect(screen.getByRole("button", { name: "收藏 Qwen 3.5" })).toHaveAttribute("aria-pressed", "false"));
  });

  it("uses a real Radix dialog trigger and restores focus after Escape", async () => {
    const user = userEvent.setup();
    render(<ModelMarketplace />);

    const trigger = await screen.findByRole("button", { name: "查看 DeepSeek V4 详情" });
    await user.click(trigger);
    expect(await screen.findByRole("dialog", { name: "DeepSeek V4" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog", { name: "DeepSeek V4" })).queryByText("DeepSeek V4 description")).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "DeepSeek V4" })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("routes text models through conversation creation and protects duplicate clicks", async () => {
    const user = userEvent.setup();
    let resolve: ((value: { conversation_id: string }) => void) | undefined;
    mockCreateConversation.mockImplementation(
      () => new Promise((res) => { resolve = res; }),
    );
    render(<ModelMarketplace />);

    const action = await screen.findByRole("button", { name: "开始对话 Qwen 3.5" });
    await user.click(action);
    await user.click(action);
    expect(mockCreateConversation).toHaveBeenCalledTimes(1);
    expect(action).toBeDisabled();
    expect(mockCreateConversation).toHaveBeenCalledWith(
      { productModelId: "qwen-3-5", clientRequestId: expect.any(String) },
      expect.any(AbortSignal),
    );

    resolve?.({ conversation_id: "conversation-created" });
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/chat/conversation-created"));
  });

  it.each([
    ["Qwen Image", "/studio/image/qwen-image"],
    ["HunyuanVideo 1.5", "/studio/video/hunyuan-video-1-5"],
    ["Qwen3-TTS 1.7B Base", "/studio/audio/qwen3-tts-base"],
  ])("routes %s to its honest future-stage workspace", async (name, href) => {
    const user = userEvent.setup();
    render(<ModelMarketplace />);
    await user.click(await screen.findByRole("button", { name: `查看 ${name} 详情` }));
    await user.click(await screen.findByRole("button", { name: /打开工作台/ }));
    expect(mockPush).toHaveBeenCalledWith(href);
  });

  it("renders loading, offline and recoverable error states", async () => {
    let resolveList: ((value: readonly CatalogModel[]) => void) | undefined;
    mockList.mockImplementationOnce(() => new Promise((resolve) => { resolveList = resolve; }));
    render(<ModelMarketplace />);
    expect(screen.getByTestId("model-marketplace-loading")).toBeInTheDocument();
    resolveList?.(catalog);
    expect(await screen.findByRole("heading", { name: "Qwen 3.5" })).toBeInTheDocument();

    cleanup();
    const offlineSpy = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    mockList.mockRejectedValueOnce(new Error("Network request failed"));
    render(<ModelMarketplace />);
    expect(await screen.findByRole("alert")).toHaveTextContent("当前处于离线状态");
    expect(screen.getByRole("alert")).toHaveAttribute("data-state", "offline");
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
    offlineSpy.mockRestore();
  });

  it("keeps interactive controls at or above the 44px target", async () => {
    render(<ModelMarketplace />);
    await screen.findByRole("heading", { name: "Qwen 3.5" });
    for (const control of [
      screen.getByRole("searchbox", { name: "搜索模型" }),
      screen.getByRole("button", { name: "打开筛选" }),
      screen.getByRole("button", { name: "开始对话 Qwen 3.5" }),
    ]) {
      expect(control.className).toMatch(/min-h-11/);
    }
  });
});
