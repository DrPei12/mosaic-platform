import { describe, expect, it, vi } from "vitest";
import { createDemoScheduler, type DemoScheduler } from "./demo-scheduler";

describe("demo scheduler", () => {
  it("resolves after the requested delay", async () => {
    vi.useFakeTimers();
    try {
      const scheduler = createDemoScheduler();
      let resolved = false;
      const pending = scheduler.wait(120).then(() => {
        resolved = true;
      });

      await vi.advanceTimersByTimeAsync(119);
      expect(resolved).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await pending;
      expect(resolved).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects with AbortError and removes the abort listener", async () => {
    vi.useFakeTimers();
    try {
      const scheduler = createDemoScheduler();
      const controller = new AbortController();
      const pending = scheduler.wait(10_000, controller.signal);
      controller.abort();

      await expect(pending).rejects.toMatchObject({ name: "AbortError" });
      await vi.advanceTimersByTimeAsync(10_000);
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("allows a controllable test scheduler without wall-clock waits", async () => {
    const resolvers: Array<() => void> = [];
    const scheduler: DemoScheduler = {
      wait: () => new Promise<void>((resolve) => resolvers.push(resolve)),
    };

    const pending = scheduler.wait(20);
    expect(resolvers).toHaveLength(1);
    resolvers.shift()?.();
    await expect(pending).resolves.toBeUndefined();
  });
});
