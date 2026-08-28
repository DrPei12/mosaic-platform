import type { DemoStateStore } from "@/shared/demo/demo-state-store";
import type { AuthService, AuthSession, AuthSessionRecord } from "./interfaces";

function sessionFromState(state: ReturnType<DemoStateStore["read"]>): AuthSession {
  return {
    authenticated: state.authenticated,
    passwordChangeRequired: state.passwordChangeRequired,
  };
}
export function createDemoAuthService(store: DemoStateStore): AuthService {
  return {
    async getSession() {
      return sessionFromState(store.read());
    },
    async signIn() {
      // Demo credentials are intentionally not persisted. Only the resulting
      // session flags are written to the versioned demo state.
      return sessionFromState(
        store.update((state) => ({
          ...state,
          authenticated: true,
        })),
      );
    },
    async register() {
      // Registration is intentionally unavailable. Demo mode has one
      // explicit internal session; it does not create a durable tenant.
      throw new Error("演示模式不提供注册能力。");
    },
    async signOut() {
      store.update((state) => ({ ...state, authenticated: false }));
    },
    async changePassword(input) {
      if (input.newPassword.length < 12 || input.newPassword.length > 128) {
        throw new Error("新密码长度必须为 12 到 128 个字符。");
      }
      store.update((state) => ({
        ...state,
        authenticated: true,
        passwordChangeRequired: false,
      }));
    },
    async getSessions() {
      const state = store.read();
      if (!state.authenticated) return [] satisfies readonly AuthSessionRecord[];
      const createdAt = new Date();
      const now = createdAt.toISOString();
      const expiresAt = new Date(createdAt.getTime() + 8 * 60 * 60 * 1000).toISOString();
      return [
        {
          sessionId: "demo-session",
          current: true,
          createdAt: now,
          lastSeenAt: now,
          expiresAt,
          ipAddress: null,
          userAgent: "浏览器",
        },
      ];
    },
    async revokeSession() {
      return undefined;
    },
  };
}
