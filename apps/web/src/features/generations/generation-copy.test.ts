import { describe, expect, it } from "vitest";

import {
  GenerationServiceError,
  ModelCatalogServiceError,
} from "@/services/interfaces";
import {
  generationTone,
  readableGenerationError,
  readableGenerationErrorCode,
  readableModelError,
  shouldAutoPollGenerationStatus,
} from "./generation-copy";

describe("generation status presentation", () => {
  it("treats submitted_unknown as a warning and explains the manual path", () => {
    expect(generationTone("submitted_unknown")).toBe("warning");
    expect(shouldAutoPollGenerationStatus("submitted_unknown")).toBe(false);
  });

  it("keeps ordinary in-flight states eligible for polling without a warning copy", () => {
    expect(generationTone("running")).toBe("info");
    expect(shouldAutoPollGenerationStatus("running")).toBe(true);
  });

  it("maps provider and deployment error codes to user copy", () => {
    expect(readableGenerationErrorCode("GENERATION_PROVIDER_TASK_FAILED")).toBe("生成未完成，请稍后重试。");
    expect(readableGenerationErrorCode("DEPLOYMENT_ROUTE_INTERNAL_ERROR")).toBe("生成任务暂时不可用，请稍后重试。");
    expect(readableGenerationErrorCode("GENERATION_PROVIDER_TASK_FAILED")).not.toContain("GENERATION_");
  });

  it("never exposes service error messages in user-facing copy", () => {
    const generationError = new GenerationServiceError({
      code: "GENERATION_WORKER_NOT_CONFIGURED",
      status: 503,
      retryable: true,
      message: "provider deployment secret details",
    });
    const modelError = new ModelCatalogServiceError({
      code: "MODEL_CATALOG_UNAVAILABLE",
      status: 503,
      retryable: true,
      message: "MODEL_PROVIDER_DEPLOYMENT_INTERNAL",
    });

    expect(readableGenerationError(generationError)).toBe("生成服务暂不可用，请稍后重试。");
    expect(readableGenerationError(generationError)).not.toContain("provider deployment");
    expect(readableModelError(modelError)).toBe("模型信息暂时不可用，请稍后重试。");
    expect(readableModelError(modelError)).not.toContain("MODEL_PROVIDER_DEPLOYMENT_INTERNAL");
  });
});
