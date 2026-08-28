import type { ApiErrorResponse, Conversation, ConversationMessage } from "@mosaic/contracts";

/** A persisted demo conversation uses the same shape as the public contract. */
export type DemoConversationState = Conversation;

export type DemoChatRequestStatus =
  | "streaming"
  | "completed"
  | "stopped"
  | "failed"
  | "timeout"
  | "content_rejected";

export type DemoChatOperation = "send" | "resume" | "regenerate";

/** Metadata needed to resume an in-flight deterministic demo request. */
export interface DemoConversationCreateState {
  client_request_id: string;
  product_model_id: string;
  conversation_id: string;
  payload_fingerprint: string;
}

/**
 * The demo adapter's resumable cursor. Error payloads intentionally reuse the
 * public API error body, so the demo cannot introduce a second error shape.
 */
export interface DemoChatRequestState {
  request_id: string;
  conversation_id: string;
  message_id: string;
  status: DemoChatRequestStatus;
  next_chunk_index: number;
  turn_index: number;
  /** Internal demo-only idempotency metadata. Never exposed in Conversation. */
  operation?: DemoChatOperation;
  client_request_id?: string;
  payload_fingerprint?: string;
  prompt?: string;
  script_id?: string;
  error?: ApiErrorResponse["error"];
}

export type { ConversationMessage };
