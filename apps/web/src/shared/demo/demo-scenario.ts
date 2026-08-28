import type {
  ApiErrorResponse,
  PublicModelCatalogItem,
  PublicProductModel,
} from "@mosaic/contracts";
import type { DemoChatRequestState, DemoConversationState } from "@/entities/chat/conversation";
import type { ModelPresentation } from "@/entities/models/catalog";
import { MODEL_PRESENTATION_REGISTRY } from "@/entities/models/presentation-registry";

export const DEMO_SCENARIO_VERSION = 1 as const;
export const DEMO_SEED = 8202026 as const;

export type DemoScriptTerminal =
  | "completed"
  | "timeout"
  | "content_rejected"
  | "stopped";

export interface DemoTurnScript {
  id: string;
  conversation_id: string;
  request_id: string;
  turn_index: number;
  prompt: string;
  chunks: readonly string[];
  terminal: DemoScriptTerminal;
  error?: ApiErrorResponse["error"];
}

export interface DemoScenario {
  scenarioVersion: typeof DEMO_SCENARIO_VERSION;
  seed: typeof DEMO_SEED;
  models: readonly PublicProductModel[];
  catalog: readonly PublicModelCatalogItem[];
  presentations: Readonly<Record<string, ModelPresentation>>;
  conversations: readonly DemoConversationState[];
  scripts: {
    twoTurn: readonly DemoTurnScript[];
    timeout: readonly DemoTurnScript[];
    contentRejected: readonly DemoTurnScript[];
    stop: readonly DemoTurnScript[];
  };
  selectedModelId: string;
  favorites: readonly string[];
  chatRequests: Readonly<Record<string, DemoChatRequestState>>;
  drafts: Readonly<Record<string, string>>;
}

const models: PublicProductModel[] = [
  {
    product_model_id: "qwen-3-5",
    display_name: "Qwen 3.5",
    category: "text",
    task_type: "chat",
    description: "适合复杂问题拆解与多轮对话的文本模型。",
    capabilities: ["多轮对话", "结构化表达"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "deepseek-v4",
    display_name: "DeepSeek V4",
    category: "text",
    task_type: "chat",
    description: "适合分析、写作与上下文协作的文本模型。",
    capabilities: ["分析推理", "多轮对话"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "glm-5-2",
    display_name: "GLM 5.2",
    category: "text",
    task_type: "chat",
    description: "面向日常知识工作与内容整理的文本模型。",
    capabilities: ["内容整理", "多轮对话"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "kimi-k2-7-code",
    display_name: "Kimi K2.7 Code",
    category: "text",
    task_type: "chat",
    description: "适合代码理解、修改建议与工程协作的文本模型。",
    capabilities: ["代码理解", "工程协作"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "gpt-oss",
    display_name: "GPT-OSS",
    category: "text",
    task_type: "chat",
    description: "用于通用问答、头脑风暴与内容草拟的文本模型。",
    capabilities: ["通用问答", "内容草拟"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "gemma-4",
    display_name: "Gemma 4",
    category: "text",
    task_type: "chat",
    description: "用于轻量知识任务与快速文本交互的模型。",
    capabilities: ["快速交互", "知识问答"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "qwen-image",
    display_name: "Qwen Image",
    category: "image",
    task_type: "text_to_image",
    description: "将文字想法转化为可探索的图像草案。",
    capabilities: ["文字生成图像", "风格探索"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "flux-2",
    display_name: "FLUX 2",
    category: "image",
    task_type: "text_to_image",
    description: "用于视觉概念与构图方向探索的图像模型。",
    capabilities: ["文字生成图像", "构图探索"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "hunyuan-video-1-5",
    display_name: "HunyuanVideo 1.5",
    category: "video",
    task_type: "image_to_video",
    description: "用于图像动效与镜头方向探索的视频模型。",
    capabilities: ["图像生成视频", "镜头探索"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "qwen3-tts-voice-design",
    display_name: "Qwen3-TTS 1.7B VoiceDesign",
    category: "audio",
    task_type: "tts",
    description: "根据文字描述探索声音表达方向的语音模型。",
    capabilities: ["文字转语音", "声音设计"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "qwen3-tts-custom-voice",
    display_name: "Qwen3-TTS 1.7B CustomVoice",
    category: "audio",
    task_type: "tts",
    description: "用于定制语音表达与播报风格探索的语音模型。",
    capabilities: ["文字转语音", "语音定制"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
  {
    product_model_id: "qwen3-tts-base",
    display_name: "Qwen3-TTS 1.7B Base",
    category: "audio",
    task_type: "tts",
    description: "用于清晰自然的语音草案与文本播报探索。",
    capabilities: ["文字转语音", "语音播报"],
    availability: "demo",
    pricing_summary: "演示额度",
  },
];

const collections: Record<string, PublicModelCatalogItem["collections"]> = {
  "qwen-3-5": ["featured", "popular"],
  "deepseek-v4": ["popular"],
  "glm-5-2": ["new"],
  "kimi-k2-7-code": ["popular", "new"],
  "gpt-oss": ["new"],
  "gemma-4": ["new"],
  "qwen-image": ["featured", "popular"],
  "flux-2": ["popular"],
  "hunyuan-video-1-5": ["featured"],
  "qwen3-tts-voice-design": ["new"],
  "qwen3-tts-custom-voice": ["new"],
  "qwen3-tts-base": ["popular"],
};

const catalog: PublicModelCatalogItem[] = models.map((model) => ({
  model,
  collections: collections[model.product_model_id] ?? [],
}));

const presentations: Record<string, ModelPresentation> = Object.fromEntries(
  models.map((model) => {
    const presentation = MODEL_PRESENTATION_REGISTRY[model.product_model_id];
    if (presentation === undefined) {
      throw new Error(`Missing demo presentation for ${model.product_model_id}`);
    }
    return [model.product_model_id, presentation];
  }),
);

const conversations: DemoConversationState[] = [
  {
    conversation_id: "conversation-qwen-3-5-001",
    product_model_id: "qwen-3-5",
    title: "产品规划讨论",
    messages: [
      {
        message_id: "message-qwen-001-user-001",
        role: "user",
        content: "帮我把新产品的验证路径拆成几步。",
        status: "complete",
        created_at: "2026-08-20T10:00:00.000Z",
        request_id: "request-qwen-001-turn-001",
      },
      {
        message_id: "message-qwen-001-assistant-001",
        role: "assistant",
        content: "可以从目标用户、核心任务和最小验证开始，再安排可观测的反馈节点。",
        status: "complete",
        created_at: "2026-08-20T10:00:02.000Z",
        request_id: "request-qwen-001-turn-001",
      },
      {
        message_id: "message-qwen-001-user-002",
        role: "user",
        content: "第二步应该先做功能还是先做访谈？",
        status: "complete",
        created_at: "2026-08-20T10:01:00.000Z",
        request_id: "request-qwen-001-turn-002",
      },
      {
        message_id: "message-qwen-001-assistant-002",
        role: "assistant",
        content: "先做小样本访谈更稳妥，它能帮助你缩小功能范围，再用原型验证关键路径。",
        status: "complete",
        created_at: "2026-08-20T10:01:03.000Z",
        request_id: "request-qwen-001-turn-002",
      },
    ],
    updated_at: "2026-08-20T10:01:03.000Z",
    active_request_id: null,
    active_request_cursor: null,
  },
  {
    conversation_id: "conversation-qwen-3-5-002",
    product_model_id: "qwen-3-5",
    title: "研究摘要整理",
    messages: [
      {
        message_id: "message-qwen-002-user-001",
        role: "user",
        content: "请帮我整理一份研究摘要的结构。",
        status: "complete",
        created_at: "2026-08-20T11:00:00.000Z",
        request_id: "request-qwen-002-turn-001",
      },
      {
        message_id: "message-qwen-002-assistant-001",
        role: "assistant",
        content: "可以按问题、方法、观察结果和限制四段组织，让读者先理解研究动机。",
        status: "complete",
        created_at: "2026-08-20T11:00:02.000Z",
        request_id: "request-qwen-002-turn-001",
      },
      {
        message_id: "message-qwen-002-user-002",
        role: "user",
        content: "如何让限制部分更具体？",
        status: "complete",
        created_at: "2026-08-20T11:01:00.000Z",
        request_id: "request-qwen-002-turn-002",
      },
      {
        message_id: "message-qwen-002-assistant-002",
        role: "assistant",
        content: "把数据范围、未覆盖的情境和仍需验证的假设分别写出来，并说明它们对结论的影响。",
        status: "complete",
        created_at: "2026-08-20T11:01:03.000Z",
        request_id: "request-qwen-002-turn-002",
      },
    ],
    updated_at: "2026-08-20T11:01:03.000Z",
    active_request_id: null,
    active_request_cursor: null,
  },
];

const twoTurnScripts: DemoTurnScript[] = [
  {
    id: "script-qwen-001-turn-001",
    conversation_id: "conversation-qwen-3-5-001",
    request_id: "request-qwen-001-turn-001",
    turn_index: 0,
    prompt: "帮我把新产品的验证路径拆成几步。",
    chunks: ["可以从目标用户、", "核心任务和最小验证开始，", "再安排可观测的反馈节点。"],
    terminal: "completed",
  },
  {
    id: "script-qwen-001-turn-002",
    conversation_id: "conversation-qwen-3-5-001",
    request_id: "request-qwen-001-turn-002",
    turn_index: 1,
    prompt: "第二步应该先做功能还是先做访谈？",
    chunks: ["先做小样本访谈更稳妥，", "它能帮助你缩小功能范围，", "再用原型验证关键路径。"],
    terminal: "completed",
  },
  {
    id: "script-qwen-002-turn-001",
    conversation_id: "conversation-qwen-3-5-002",
    request_id: "request-qwen-002-turn-001",
    turn_index: 0,
    prompt: "请帮我整理一份研究摘要的结构。",
    chunks: ["可以按问题、方法、", "观察结果和限制四段组织，", "让读者先理解研究动机。"],
    terminal: "completed",
  },
  {
    id: "script-qwen-002-turn-002",
    conversation_id: "conversation-qwen-3-5-002",
    request_id: "request-qwen-002-turn-002",
    turn_index: 1,
    prompt: "如何让限制部分更具体？",
    chunks: ["把数据范围、未覆盖的情境", "和仍需验证的假设分别写出来，", "并说明它们对结论的影响。"],
    terminal: "completed",
  },
];

const timeoutScripts: DemoTurnScript[] = [
  {
    id: "script-qwen-timeout",
    conversation_id: "conversation-qwen-3-5-001",
    request_id: "request-qwen-timeout",
    turn_index: 2,
    prompt: "演示超时响应",
    chunks: ["正在整理上下文…"],
    terminal: "timeout",
    error: {
      code: "DEMO_TIMEOUT",
      message: "演示响应超时，请稍后重试。",
      request_id: "request-qwen-timeout",
      retryable: true,
    },
  },
];

const contentRejectedScripts: DemoTurnScript[] = [
  {
    id: "script-qwen-content-rejected",
    conversation_id: "conversation-qwen-3-5-001",
    request_id: "request-qwen-content-rejected",
    turn_index: 2,
    prompt: "演示内容拒绝响应",
    chunks: [],
    terminal: "content_rejected",
    error: {
      code: "CONTENT_REJECTED",
      message: "该请求无法在演示环境中处理。",
      request_id: "request-qwen-content-rejected",
      retryable: false,
    },
  },
];

const stopScripts: DemoTurnScript[] = [
  {
    id: "script-qwen-stop",
    conversation_id: "conversation-qwen-3-5-002",
    request_id: "request-qwen-stop",
    turn_index: 2,
    prompt: "演示停止响应",
    chunks: ["先输出已确认的", "部分内容，"],
    terminal: "stopped",
  },
];

function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
  for (const nested of Object.values(value as Record<string, unknown>)) deepFreeze(nested);
  return Object.freeze(value);
}

export const DEMO_SCENARIO: Readonly<DemoScenario> = deepFreeze({
  scenarioVersion: DEMO_SCENARIO_VERSION,
  seed: DEMO_SEED,
  models,
  catalog,
  presentations,
  conversations,
  scripts: {
    twoTurn: twoTurnScripts,
    timeout: timeoutScripts,
    contentRejected: contentRejectedScripts,
    stop: stopScripts,
  },
  selectedModelId: "qwen-3-5",
  favorites: [],
  chatRequests: {},
  drafts: {},
});
