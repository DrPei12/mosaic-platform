export interface DemoScheduler {
  wait(delayMs: number, signal?: AbortSignal): Promise<void>;
}

function abortError(signal?: AbortSignal): unknown {
  if (signal?.reason !== undefined) return signal.reason;
  return new DOMException("The operation was aborted.", "AbortError");
}

/**
 * Browser-safe scheduler used by the deterministic demo. Every timer and
 * abort listener is cleaned up on either completion or cancellation.
 */
export function createDemoScheduler(): DemoScheduler {
  return {
    wait(delayMs, signal) {
      if (signal?.aborted) return Promise.reject(abortError(signal));

      return new Promise<void>((resolve, reject) => {
        let settled = false;
        const finish = (callback: () => void): void => {
          if (settled) return;
          settled = true;
          if (timer !== undefined) clearTimeout(timer);
          signal?.removeEventListener("abort", onAbort);
          callback();
        };
        const onAbort = (): void => finish(() => reject(abortError(signal)));
        const timer = setTimeout(() => finish(resolve), Math.max(0, delayMs));
        signal?.addEventListener("abort", onAbort, { once: true });

        // A signal can become aborted between the initial check and listener
        // registration. Re-check after registering so no wait hangs.
        if (signal?.aborted) onAbort();
      });
    },
  };
}

export const demoScheduler = createDemoScheduler();
