import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import apiErrorSchema from "../schemas/api-error.schema.json";
import catalogSchema from "../schemas/model-catalog.schema.json";
import productSchema from "../schemas/public-product-model.schema.json";
import conversationSchema from "../schemas/conversation.schema.json";
import streamEventSchema from "../schemas/chat-stream-event.schema.json";
import summaryListSchema from "@mosaic/contracts/schemas/conversation-summary-list.schema.json";
import summarySchema from "@mosaic/contracts/schemas/conversation-summary.schema.json";
import type {
  ChatStreamEvent,
  Conversation,
  ConversationSummary,
  PublicModelCatalogResponse,
  PublicProductModel,
} from "./index";

const ajv = new Ajv2020({ allErrors: true });
addFormats(ajv);
ajv.addSchema(productSchema);
ajv.addSchema(apiErrorSchema);
ajv.addSchema(summarySchema);

const validateCatalog = ajv.compile(catalogSchema);
const validateConversation = ajv.compile(conversationSchema);
const validateStreamEvent = ajv.compile(streamEventSchema);
const validateSummary = ajv.compile(summarySchema);
const validateSummaryList = ajv.compile(summaryListSchema);

const publicModel: PublicProductModel = {
  product_model_id: "qwen-3-5",
  display_name: "Qwen 3.5",
  category: "text",
  task_type: "chat",
  description: "适合复杂推理与多轮对话",
  capabilities: ["多轮对话", "工具调用"],
  availability: "demo",
  pricing_summary: "演示点数",
};

const catalog: PublicModelCatalogResponse = {
  items: [{ model: publicModel, collections: ["featured", "new"] }],
};

const conversation: Conversation = {
  conversation_id: "conversation_demo_001",
  product_model_id: publicModel.product_model_id,
  title: "产品规划讨论",
  messages: [
    {
      message_id: "message_demo_001",
      role: "user",
      content: "帮我梳理一下产品规划。",
      status: "complete",
      created_at: "2026-08-21T14:00:00.000Z",
      request_id: "request_demo_001",
    },
    {
      message_id: "message_demo_002",
      role: "assistant",
      content: "可以从目标、用户和验证路径开始。",
      status: "complete",
      created_at: "2026-08-21T14:00:02.000Z",
    },
  ],
  updated_at: "2026-08-21T14:00:02.000Z",
  active_request_id: null,
  active_request_cursor: null,
};

const conversationSummary: ConversationSummary = {
  conversation_id: conversation.conversation_id,
  product_model_id: conversation.product_model_id,
  title: conversation.title,
  preview: "可以从目标、用户和验证路径开始。",
  updated_at: conversation.updated_at,
};

const conversationSummaryList: ConversationSummary[] = [conversationSummary];

const streamEvents: ChatStreamEvent[] = [
  {
    type: "started",
    request_id: "request_demo_002",
    conversation_id: conversation.conversation_id,
    message_id: "message_demo_003",
    sequence: 0,
  },
  {
    type: "delta",
    request_id: "request_demo_002",
    conversation_id: conversation.conversation_id,
    message_id: "message_demo_003",
    sequence: 1,
    delta: "第一段内容",
  },
  {
    type: "completed",
    request_id: "request_demo_002",
    conversation_id: conversation.conversation_id,
    message_id: "message_demo_003",
    sequence: 2,
    content: "第一段内容。",
  },
  {
    type: "stopped",
    request_id: "request_demo_003",
    conversation_id: conversation.conversation_id,
    message_id: "message_demo_004",
    sequence: 3,
  },
  {
    type: "failed",
    request_id: "request_demo_004",
    conversation_id: conversation.conversation_id,
    message_id: "message_demo_005",
    sequence: 1,
    error: {
      code: "SERVICE_UNAVAILABLE",
      message: "服务暂不可用",
      request_id: "request_demo_004",
      retryable: true,
    },
  },
];

describe("Phase 2 public contracts", () => {
  it("accepts a public model and exact catalog response", () => {
    expect(ajv.validate(productSchema, publicModel)).toBe(true);
    expect(validateCatalog(catalog), JSON.stringify(validateCatalog.errors)).toBe(true);
  });

  it("accepts Wan 2.7 as a text-to-video catalog model", () => {
    const wanModel: PublicProductModel = {
      product_model_id: "wan-2-7",
      display_name: "Wan 2.7",
      category: "video",
      task_type: "text_to_video",
      description: "用于文字生成视频的模型。",
      capabilities: ["文字生成视频"],
      availability: "available",
      pricing_summary: "按量计费",
    };
    const wanCatalog: PublicModelCatalogResponse = {
      items: [{ model: wanModel, collections: ["new"] }],
    };

    expect(ajv.validate(productSchema, wanModel)).toBe(true);
    expect(validateCatalog(wanCatalog), JSON.stringify(validateCatalog.errors)).toBe(true);
    expect(wanModel).not.toHaveProperty("provider_model_id");
  });

  it("accepts the exact conversation shape", () => {
    expect(validateConversation(conversation), JSON.stringify(validateConversation.errors)).toBe(true);
  });

  it("accepts dedicated conversation summary and summary-list schemas", () => {
    expect(validateSummary(conversationSummary), JSON.stringify(validateSummary.errors)).toBe(true);
    expect(validateSummaryList(conversationSummaryList), JSON.stringify(validateSummaryList.errors)).toBe(true);
    expect(validateSummary({ ...conversationSummary, updated_at: "2026-08-21T10:00:00-04:00" })).toBe(true);
  });

  it("rejects extra and missing fields from dedicated summary schemas", () => {
    expect(validateSummary({ ...conversationSummary, provider: "must-not-leak" })).toBe(false);
    expect(validateSummaryList({ items: conversationSummaryList })).toBe(false);
    expect(validateSummaryList([{ ...conversationSummary, extra: true }])).toBe(false);
    expect(validateSummaryList([{ ...conversationSummary, preview: undefined }])).toBe(false);
  });

  it("keeps the conversation schema focused on messages and conversation shape", () => {
    expect(Object.prototype.hasOwnProperty.call(conversationSchema.$defs, "summary")).toBe(false);
  });

  it.each([
    "2026-13-01T14:00:00.000Z",
    "2026-02-30T14:00:00.000Z",
    "2026-08-21T25:00:00.000Z",
    "2026-08-21T14:00:00.000+24:00",
    "2026-08-21T14:00:00.000+05:60",
  ])("rejects invalid RFC3339 timestamp %s", (timestamp) => {
    expect(validateConversation({ ...conversation, updated_at: timestamp })).toBe(false);
    expect(validateSummary({ ...conversationSummary, updated_at: timestamp })).toBe(false);
  });

  it.each(streamEvents.map((event) => [event.type, event] as const))(
    "accepts the %s stream event variant",
    (_type, event) => {
      expect(validateStreamEvent(event), JSON.stringify(validateStreamEvent.errors)).toBe(true);
    },
  );

  it.each(["provider", "provider_model_id", "deployment_id", "quantization", "precision", "license", "snapshot_date", "revision"])(
    "rejects public model internal field %s",
    (field) => {
      const payload = { ...publicModel, [field]: "must-not-leak" };
      expect(ajv.validate(productSchema, payload)).toBe(false);
    },
  );

  it.each(["provider", "provider_model_id", "deployment_id", "quantization", "precision", "license", "snapshot_date", "revision"])(
    "rejects internal field %s in a catalog model",
    (field) => {
      const payload = {
        ...catalog,
        items: [{ ...catalog.items[0], model: { ...publicModel, [field]: "must-not-leak" } }],
      };
      expect(validateCatalog(payload)).toBe(false);
    },
  );

  it("rejects extra catalog fields and invalid collection values", () => {
    expect(validateCatalog({ ...catalog, extra: true })).toBe(false);
    expect(validateCatalog({ items: [{ ...catalog.items[0], collections: ["featured", "featured"] }] })).toBe(false);
    expect(validateCatalog({ items: [{ ...catalog.items[0], collections: ["archived"] }] })).toBe(false);
    expect(validateCatalog({ items: [{ model: publicModel }] })).toBe(false);
  });

  it("rejects extra conversation fields and invalid message fields", () => {
    expect(validateConversation({ ...conversation, extra: true })).toBe(false);
    expect(
      validateConversation({
        ...conversation,
        messages: [{ ...conversation.messages[0], extra: true }],
      }),
    ).toBe(false);
    expect(
      validateConversation({
        ...conversation,
        messages: [{ ...conversation.messages[0], role: "system" }],
      }),
    ).toBe(false);
    expect(
      validateConversation({
        ...conversation,
        messages: [{ ...conversation.messages[0], status: "pending" }],
      }),
    ).toBe(false);
    expect(
      validateConversation({
        ...conversation,
        messages: [{ ...conversation.messages[0], created_at: "not-a-timestamp" }],
      }),
    ).toBe(false);
  });

  it("requires an explicit resumable cursor with null, -1, or non-negative semantics", () => {
    expect(validateConversation({ ...conversation, active_request_cursor: null })).toBe(true);
    expect(validateConversation({ ...conversation, active_request_id: "request-active", active_request_cursor: -1 })).toBe(true);
    expect(validateConversation({ ...conversation, active_request_id: "request-active", active_request_cursor: 0 })).toBe(true);
    expect(validateConversation({ ...conversation, active_request_cursor: -2 })).toBe(false);
    expect(validateConversation({ ...conversation, active_request_cursor: 1.5 })).toBe(false);
    expect(validateConversation({ ...conversation, active_request_cursor: 0, active_request_id: null })).toBe(false);
    expect(validateConversation({ ...conversation, active_request_cursor: null, active_request_id: "request-active" })).toBe(false);
    expect(validateConversation({
      ...conversation,
      active_request_cursor: undefined,
    })).toBe(false);
  });

  it.each(["conversation_id", "product_model_id", "title", "updated_at"])(
    "rejects an empty conversation %s",
    (field) => {
      expect(validateConversation({ ...conversation, [field]: "" })).toBe(false);
    },
  );

  it("rejects empty message IDs and request IDs", () => {
    expect(
      validateConversation({
        ...conversation,
        messages: [{ ...conversation.messages[0], message_id: "" }],
      }),
    ).toBe(false);
    expect(
      validateConversation({
        ...conversation,
        messages: [{ ...conversation.messages[0], request_id: "" }],
      }),
    ).toBe(false);
  });

  it("rejects unknown, incomplete, and extra stream event variants", () => {
    expect(validateStreamEvent({ ...streamEvents[0], type: "unknown" })).toBe(false);
    expect(
      validateStreamEvent({
        type: "delta",
        request_id: "request_demo_002",
        conversation_id: conversation.conversation_id,
        message_id: "message_demo_003",
        sequence: 1,
      }),
    ).toBe(false);
    expect(validateStreamEvent({ ...streamEvents[0], extra: true })).toBe(false);
    expect(validateStreamEvent({ ...streamEvents[3], content: "unexpected" })).toBe(false);
  });

  it("rejects invalid stream IDs and sequence values", () => {
    expect(validateStreamEvent({ ...streamEvents[0], request_id: "" })).toBe(false);
    expect(validateStreamEvent({ ...streamEvents[0], sequence: 1 })).toBe(false);
    expect(validateStreamEvent({ ...streamEvents[1], sequence: -1 })).toBe(false);
    expect(validateStreamEvent({ ...streamEvents[1], sequence: 1.5 })).toBe(false);
    expect(validateStreamEvent({ ...streamEvents[1], delta: "" })).toBe(false);
  });

  it("requires the exact existing error body for failed events", () => {
    expect(
      validateStreamEvent({
        ...streamEvents[4],
        error: { code: "BROKEN", message: "bad", request_id: "request_demo_004", retryable: false, extra: true },
      }),
    ).toBe(false);
    expect(
      validateStreamEvent({
        ...streamEvents[4],
        error: { code: "BROKEN", message: "bad", request_id: "", retryable: false },
      }),
    ).toBe(false);
  });
});
