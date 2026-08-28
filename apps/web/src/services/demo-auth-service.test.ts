import { describe, expect, it } from "vitest";
import { createDemoAuthService } from "./demo-auth-service";
import {
  createDemoStateStore,
  type DemoStateStore,
  type StorageLike,
} from "@/shared/demo/demo-state-store";

const NOW = "2026-08-20T12:00:00.000Z";

function memoryStorage(): StorageLike {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
}

function racingStore(base: DemoStateStore): DemoStateStore {
  let injected = false;
  return {
    read() {
      const state = base.read();
      if (!injected) {
        injected = true;
        base.update((current) => ({
          ...current,
          favorites: ["qwen-image"],
          drafts: { ...current.drafts, [Object.keys(current.conversations)[0]!]: "keep me" },
          conversations: {
            ...current.conversations,
            [Object.keys(current.conversations)[0]!]: {
              ...current.conversations[Object.keys(current.conversations)[0]!]!,
              title: "并发保留",
            },
          },
        }));
      }
      return state;
    },
    write: (state) => base.write(state),
    update(mutator) {
      if (!injected) {
        injected = true;
        base.update((current) => ({
          ...current,
          favorites: ["qwen-image"],
          drafts: { ...current.drafts, [Object.keys(current.conversations)[0]!]: "keep me" },
          conversations: {
            ...current.conversations,
            [Object.keys(current.conversations)[0]!]: {
              ...current.conversations[Object.keys(current.conversations)[0]!]!,
              title: "并发保留",
            },
          },
        }));
      }
      return base.update(mutator);
    },
    reset: () => base.reset(),
  };
}

describe("demo auth service state updates", () => {
  it("preserves a concurrent favorite, draft, and conversation change on sign-in", async () => {
    const base = createDemoStateStore({ storage: memoryStorage(), now: () => NOW });
    const conversationId = Object.keys(base.read().conversations)[0]!;
    const auth = createDemoAuthService(racingStore(base));

    const session = await auth.signIn({ account: "demo", password: "not-persisted" });

    const state = base.read();
    expect(state.authenticated).toBe(true);
    expect(session.passwordChangeRequired).toBe(true);
    expect(state.favorites).toEqual(["qwen-image"]);
    expect(state.drafts[conversationId]).toBe("keep me");
    expect(state.conversations[conversationId]!.title).toBe("并发保留");
  });

  it("uses update for sign-out without dropping unrelated state", async () => {
    const base = createDemoStateStore({ storage: memoryStorage(), now: () => NOW });
    base.update((state) => ({
      ...state,
      authenticated: true,
      favorites: ["qwen-image"],
    }));
    const auth = createDemoAuthService(racingStore(base));

    await auth.signOut();

    expect(base.read().authenticated).toBe(false);
    expect(base.read().favorites).toEqual(["qwen-image"]);
  });
});
