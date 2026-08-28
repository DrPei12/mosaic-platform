import type {
  CatalogCollection,
  ChatStreamEvent,
  Conversation,
  ConversationSummary,
  EvidenceStatus,
  HealthResponse,
  ModelCategory,
  PublicModelCatalogItem,
} from "@mosaic/contracts";
import type { ModelPresentation } from "@/entities/models/catalog";

export interface PlatformHealth extends HealthResponse {
  evidence: EvidenceStatus;
}

export interface AuthSession {
  authenticated: boolean;
  passwordChangeRequired: boolean;
}

export interface AuthSessionRecord {
  sessionId: string;
  current: boolean;
  createdAt: string;
  lastSeenAt: string;
  expiresAt: string;
  ipAddress: string | null;
  userAgent: string | null;
}

export interface AuthService {
  getSession(signal?: AbortSignal): Promise<AuthSession>;
  bootstrapLocalSession?(signal?: AbortSignal): Promise<AuthSession>;
  signIn(
    input: { account: string; password: string; tenantSlug?: string },
    signal?: AbortSignal,
  ): Promise<AuthSession>;
  register(
    input: {
      email: string;
      password: string;
      tenantName: string;
      tenantSlug: string;
    },
    signal?: AbortSignal,
  ): Promise<AuthSession>;
  signOut(signal?: AbortSignal): Promise<void>;
  changePassword(
    input: { currentPassword: string; newPassword: string },
    signal?: AbortSignal,
  ): Promise<void>;
  getSessions(signal?: AbortSignal): Promise<readonly AuthSessionRecord[]>;
  revokeSession(sessionId: string, signal?: AbortSignal): Promise<void>;
}

export interface HealthService {
  getStatus(signal?: AbortSignal): Promise<PlatformHealth>;
}

export interface ModelCatalogQuery {
  category?: ModelCategory;
  search?: string;
  collection?: CatalogCollection;
}

export interface CatalogModel {
  item: PublicModelCatalogItem;
  presentation: ModelPresentation;
  favorite: boolean;
}

export type ModelCatalogServiceErrorCode =
  | "MODEL_CATALOG_UNAVAILABLE"
  | "MODEL_NOT_FOUND";

export class ModelCatalogServiceError extends Error {
  readonly code: ModelCatalogServiceErrorCode;
  readonly status: number;
  readonly retryable: boolean;

  constructor(options: {
    code: ModelCatalogServiceErrorCode;
    status: number;
    retryable: boolean;
    message?: string;
  }) {
    super(options.message ?? options.code);
    this.name = "ModelCatalogServiceError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export interface ModelCatalogService {
  list(
    query?: ModelCatalogQuery,
    signal?: AbortSignal,
  ): Promise<readonly CatalogModel[]>;
  get(productModelId: string, signal?: AbortSignal): Promise<CatalogModel>;
  toggleFavorite(productModelId: string, signal?: AbortSignal): Promise<boolean>;
}

export type GenerationModality = "text" | "image" | "video" | "audio";

export type GenerationStatus =
  | "accepted"
  | "reserved"
  | "submitted"
  | "submitted_unknown"
  | "queued"
  | "running"
  | "storing"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "expired";

export interface GenerationInput {
  messages?: readonly {
    role: "system" | "user" | "assistant" | "tool";
    content: string;
  }[];
  prompt?: string;
  text?: string;
  language_type?: string;
  size?: string;
  count?: number;
  resolution?: "720P" | "1080P";
  ratio?: "1:1" | "16:9" | "9:16" | "4:3" | "3:4";
  duration_seconds?: number;
}

export interface GenerationArtifact {
  artifact_id: string;
  kind: "input" | "output" | "thumbnail" | "preview";
  status: "pending" | "ready" | "expired" | "deleted";
  mime_type: string;
  size_bytes: number;
}

export interface GenerationJob {
  job_id: string;
  product_model_id: string;
  modality: GenerationModality;
  status: GenerationStatus;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error_code: string | null;
  reconciliation_pending: boolean;
  artifacts: readonly GenerationArtifact[];
}

export type GenerationServiceErrorCode =
  | "MODEL_UNAVAILABLE"
  | "IDEMPOTENCY_CONFLICT"
  | "IDEMPOTENCY_IN_PROGRESS"
  | "GENERATION_NOT_FOUND"
  | "GENERATION_STATE_CONFLICT"
  | "GENERATION_SUBMISSION_DISABLED"
  | "GENERATION_PERSISTENCE_UNAVAILABLE"
  | "GENERATION_WORKER_NOT_CONFIGURED"
  | "GENERATION_UNAVAILABLE"
  | "GENERATION_RESPONSE_INVALID";

export class GenerationServiceError extends Error {
  readonly code: GenerationServiceErrorCode;
  readonly status: number;
  readonly retryable: boolean;
  readonly requestId: string | undefined;

  constructor(options: {
    code: GenerationServiceErrorCode;
    status: number;
    retryable: boolean;
    requestId?: string;
    message?: string;
  }) {
    super(options.message ?? options.code);
    this.name = "GenerationServiceError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable;
    this.requestId = options.requestId;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export interface GenerationService {
  list(signal?: AbortSignal): Promise<readonly GenerationJob[]>;
  create(
    input: {
      productModelId: string;
      modality: GenerationModality;
      input: GenerationInput;
      clientRequestId: string;
    },
    signal?: AbortSignal,
  ): Promise<GenerationJob>;
  get(jobId: string, signal?: AbortSignal): Promise<GenerationJob>;
  cancel(jobId: string, signal?: AbortSignal): Promise<void>;
  delete(jobId: string, signal?: AbortSignal): Promise<void>;
}

export interface UsageSummary {
  currency: string;
  balance_minor: number;
  reserved_minor: number;
  totals: {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    image_count: number;
    video_seconds: number;
    character_count: number;
    storage_bytes: number;
    charge_amount_minor: number;
  };
  recent_usage: readonly {
    usage_id: string;
    source: "chat" | "generation";
    modality: string;
    model_id: string;
    input_tokens: number;
    output_tokens: number;
    billable_units: number;
    charge_amount_minor: number;
    created_at: string;
  }[];
  recent_ledger: readonly {
    ledger_id: string;
    entry_type: "credit" | "debit" | "hold" | "release" | "adjustment";
    amount_minor: number;
    currency: string;
    reference_type: string;
    created_at: string;
  }[];
}

export interface UsageService {
  getSummary(signal?: AbortSignal): Promise<UsageSummary>;
}

export interface ConversationStream {
  requestId: string;
  messageId: string;
  /** Cursor supplied when opening the stream; null means no persisted cursor. */
  readonly cursor: number | null;
  /** Last accepted sequence, initialized from cursor (`-1` when absent). */
  readonly lastSequence: number;
  events: AsyncIterable<ChatStreamEvent>;
}

export type ConversationServiceErrorCode =
  | "CONVERSATION_NOT_FOUND"
  | "MESSAGE_NOT_LATEST"
  | "MODEL_NOT_FOUND"
  | "MESSAGE_EMPTY"
  | "CONVERSATION_BUSY"
  | "IDEMPOTENCY_KEY_REUSED"
  | "PROVIDER_TIMEOUT"
  | "CONTENT_REJECTED"
  | "CHAT_SUBMISSION_DISABLED"
  | "IDEMPOTENCY_IN_PROGRESS"
  | "STREAM_CURSOR_INVALID"
  | "STREAM_RESPONSE_INVALID"
  | "CONVERSATION_UNAVAILABLE";

export class ConversationServiceError extends Error {
  readonly code: ConversationServiceErrorCode;
  readonly status: number;
  readonly retryable: boolean;
  readonly requestId: string | undefined;

  constructor(options: {
    code: ConversationServiceErrorCode;
    status: number;
    retryable: boolean;
    requestId?: string;
    message?: string;
  }) {
    super(options.message ?? options.code);
    this.name = "ConversationServiceError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable;
    this.requestId = options.requestId;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

export interface ConversationService {
  listConversations(signal?: AbortSignal): Promise<readonly ConversationSummary[]>;
  getConversation(conversationId: string, signal?: AbortSignal): Promise<Conversation>;
  /**
   * Drafts are an optional client-side convenience in the demo. The API
   * adapter deliberately reports this capability as unavailable until a
   * server draft contract exists; callers must keep the controlled local
   * value as the source of truth when that happens.
   */
  getDraft(conversationId: string, signal?: AbortSignal): Promise<string>;
  saveDraft(
    input: { conversationId: string; content: string },
    signal?: AbortSignal,
  ): Promise<void>;
  createConversation(
    input: { productModelId: string; clientRequestId: string },
    signal?: AbortSignal,
  ): Promise<Conversation>;
  sendMessage(
    input: { conversationId: string; content: string; clientRequestId: string },
    signal?: AbortSignal,
  ): Promise<ConversationStream>;
  resumeMessage(
    input: { conversationId: string; requestId: string; cursor: number | null },
    signal?: AbortSignal,
  ): Promise<ConversationStream>;
  regenerate(
    input: { conversationId: string; messageId: string; clientRequestId: string },
    signal?: AbortSignal,
  ): Promise<ConversationStream>;
  stopMessage(
    input: { conversationId: string; requestId: string },
    signal?: AbortSignal,
  ): Promise<void>;
}

export interface ServiceRegistry {
  health: HealthService;
  auth: AuthService;
  modelCatalog: ModelCatalogService;
  conversation: ConversationService;
  /** Generation is only exposed by the API composition; Demo has no fake job service. */
  generation?: GenerationService;
  usage?: UsageService;
}
