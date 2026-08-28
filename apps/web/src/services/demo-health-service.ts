import type { HealthService } from "./interfaces";

export const demoHealthService: HealthService = {
  async getStatus() {
    return {
      service: "mosaic-api",
      status: "ready",
      version: "demo",
      evidence: "demo_scaffolding",
    };
  },
};
