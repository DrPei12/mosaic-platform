import {
  GenerationServiceError,
  ModelCatalogServiceError,
} from "@/services/interfaces";
import type { GenerationModality, GenerationStatus } from "@/services/interfaces";

export const generationModalityLabels: Record<GenerationModality, string> = {
  text: "文本",
  image: "图片",
  video: "视频",
  audio: "音频",
};

export const generationStatusLabels: Record<GenerationStatus, string> = {
  accepted: "已接收",
  reserved: "准备中",
  submitted: "已提交",
  submitted_unknown: "提交状态待确认",
  queued: "排队中",
  running: "生成中",
  storing: "保存结果中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  expired: "已过期",
};

export function isTerminalGenerationStatus(status: GenerationStatus): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled" || status === "expired";
}

export function shouldAutoPollGenerationStatus(status: GenerationStatus): boolean {
  return !isTerminalGenerationStatus(status) && status !== "submitted_unknown";
}

export function generationTone(status: GenerationStatus): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "succeeded") return "success";
  if (status === "failed") return "danger";
  if (status === "submitted_unknown") return "warning";
  if (status === "cancelled" || status === "expired") return "warning";
  if (status === "running" || status === "queued" || status === "storing") return "info";
  return "neutral";
}

const GENERATION_ERROR_FALLBACK = "生成任务暂时不可用，请稍后重试。";

const generationErrorMessages: ReadonlyMap<string, string> = new Map([
  ["GENERATION_SUBMISSION_DISABLED", "生成服务暂不可用，请稍后重试。"],
  ["GENERATION_WORKER_NOT_CONFIGURED", "生成服务暂不可用，请稍后重试。"],
  ["GENERATION_PERSISTENCE_UNAVAILABLE", "生成服务暂不可用，请稍后重试。"],
  ["GENERATION_PROVIDER_NOT_CONFIGURED", "生成服务暂不可用，请稍后重试。"],
  ["GENERATION_PROVIDER_ROUTE_UNAVAILABLE", "生成服务暂不可用，请稍后重试。"],
  ["GENERATION_PROVIDER_PROTOCOL_ERROR", "生成服务暂不可用，请稍后重试。"],
  ["GENERATION_PROVIDER_TASK_FAILED", "生成未完成，请稍后重试。"],
  ["GENERATION_PROVIDER_MODEL_UNAVAILABLE", "所选模型当前不可用，请返回模型广场查看最新状态。"],
  ["GENERATION_NOT_FOUND", "找不到这个生成任务，或任务不属于当前账户。"],
  ["MODEL_UNAVAILABLE", "所选模型当前不可用，请返回模型广场查看最新状态。"],
  ["IDEMPOTENCY_IN_PROGRESS", "相同任务正在处理中，请稍后刷新任务状态。"],
  ["IDEMPOTENCY_CONFLICT", "任务请求标识已被使用，请重新提交一次。"],
  ["GENERATION_STATE_CONFLICT", "任务状态已更新，请刷新后重试。"],
  ["GENERATION_RESPONSE_INVALID", "任务状态暂不可用，请稍后重试。"],
  ["GENERATION_UNAVAILABLE", GENERATION_ERROR_FALLBACK],
  ["GENERATION_EXECUTION_FAILED", "生成未完成，请稍后重试。"],
  ["GENERATION_WORKER_STALLED", "生成任务处理超时，请稍后重试。"],
  ["GENERATION_RECONCILIATION_REQUIRED", "任务状态待确认，请刷新任务状态。"],
  ["GENERATION_SUBMITTED_UNKNOWN", "任务提交状态待确认，请刷新任务状态。"],
  ["GENERATION_BILLING_RESERVATION_MISSING", "任务额度状态暂不可用，请稍后重试。"],
  ["GENERATION_OPERATOR_RESOLVED_FAILED", "生成未完成，请重新提交。"],
  ["REQUEST_VALIDATION_FAILED", "请求内容不符合要求，请检查后重试。"],
  ["PROVIDER_TIMEOUT", "生成服务响应超时，请稍后重试。"],
  ["PROVIDER_CONNECTION_ERROR", "生成服务暂不可用，请稍后重试。"],
  ["PROVIDER_HTTP_ERROR", "生成服务暂不可用，请稍后重试。"],
  ["PROVIDER_SUBMISSION_UNKNOWN", "任务提交状态待确认，请刷新任务状态。"],
  ["PROVIDER_POLL_TRANSPORT_ERROR", "生成服务暂不可用，请稍后重试。"],
  ["PROVIDER_NOT_CONFIGURED", "生成服务暂不可用，请稍后重试。"],
  ["INVALID_PROVIDER_RESPONSE", "生成服务暂不可用，请稍后重试。"],
  ["DEPLOYMENT_UNAVAILABLE", "生成服务暂不可用，请稍后重试。"],
  ["DEPLOYMENT_NOT_CONFIGURED", "生成服务暂不可用，请稍后重试。"],
  ["MODEL_DEPLOYMENT_UNAVAILABLE", "生成服务暂不可用，请稍后重试。"],
]);

export function readableGenerationErrorCode(errorCode: string | null | undefined): string | null {
  if (!errorCode) return null;
  return generationErrorMessages.get(errorCode) ?? GENERATION_ERROR_FALLBACK;
}

export function readableGenerationError(error: unknown): string {
  if (error instanceof GenerationServiceError) {
    return readableGenerationErrorCode(error.code) ?? GENERATION_ERROR_FALLBACK;
  }
  return GENERATION_ERROR_FALLBACK;
}

export function readableModelError(error: unknown): string {
  if (error instanceof ModelCatalogServiceError && error.code === "MODEL_NOT_FOUND") {
    return "找不到这个模型，请返回模型广场重新选择。";
  }
  return "模型信息暂时不可用，请稍后重试。";
}

export function formatGenerationDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    hour12: false,
  }).format(date);
}

export function formatArtifactSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}
