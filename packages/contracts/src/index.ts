export type EvidenceStatus = "demo_scaffolding" | "provider_unverified" | "observed_accepted";
export type ModelCategory = "text" | "image" | "video" | "audio";
export type TaskType =
  | "chat"
  | "text_to_image"
  | "text_to_video"
  | "image_to_video"
  | "tts";
export type Availability = "available" | "maintenance" | "unavailable" | "demo";

export interface HealthResponse {
  service: "mosaic-api";
  status: "ok" | "ready";
  version: string;
}

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    request_id: string;
    retryable: boolean;
    details?: Record<string, unknown> | null;
  };
}

export interface PublicProductModel {
  product_model_id: string;
  display_name: string;
  category: ModelCategory;
  task_type: TaskType;
  description: string;
  capabilities: string[];
  input_schema?: Record<string, unknown>;
  availability: Availability;
  pricing_summary: string;
}

export type CatalogCollection = "featured" | "popular" | "new";

export interface PublicModelCatalogItem {
  model: PublicProductModel;
  collections: CatalogCollection[];
}

export interface PublicModelCatalogResponse {
  items: PublicModelCatalogItem[];
}

export type ConversationRole = "user" | "assistant";
export type ConversationMessageStatus = "streaming" | "complete" | "stopped" | "failed";

export interface ConversationMessage {
  message_id: string;
  role: ConversationRole;
  content: string;
  status: ConversationMessageStatus;
  created_at: string;
  request_id?: string | null;
}

export interface ConversationSummary {
  conversation_id: string;
  product_model_id: string;
  title: string;
  preview: string;
  updated_at: string;
}

export interface Conversation {
  conversation_id: string;
  product_model_id: string;
  title: string;
  messages: ConversationMessage[];
  updated_at: string;
  active_request_id: string | null;
  /**
   * Last persisted event sequence for the active request. `null` means there
   * is no active request; `-1` means an active request has not emitted an
   * accepted event yet; non-negative values are resumable SSE cursors.
   */
  active_request_cursor: number | null;
}

export type ChatStreamEvent =
  | { type: "started"; request_id: string; conversation_id: string; message_id: string; sequence: 0 }
  | { type: "delta"; request_id: string; conversation_id: string; message_id: string; sequence: number; delta: string }
  | { type: "completed"; request_id: string; conversation_id: string; message_id: string; sequence: number; content: string }
  | { type: "stopped"; request_id: string; conversation_id: string; message_id: string; sequence: number }
  | { type: "failed"; request_id: string; conversation_id: string; message_id: string; sequence: number; error: ApiErrorResponse["error"] };
