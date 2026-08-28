import "server-only";

import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { getPublicServiceMode } from "@/shared/config/service-mode";
import { normalizeReturnTo } from "@/shared/config/routes";
import {
  API_ORIGIN_ENV_NAME,
  SESSION_COOKIE_ENV_NAME,
} from "@/shared/config/brand";
import type { AuthSession } from "@/services/interfaces";
import { requestServerSession } from "@/services/server-auth-session";

const SESSION_COOKIE_NAME =
  process.env[SESSION_COOKIE_ENV_NAME] ?? "mosaic_session";
const API_ORIGIN =
  process.env[API_ORIGIN_ENV_NAME] ?? "http://127.0.0.1:8000";

export const getServerSession = cache(async (): Promise<AuthSession | null> => {
  if (getPublicServiceMode() !== "api") return null;
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;
  return requestServerSession({
    apiOrigin: API_ORIGIN,
    cookieName: SESSION_COOKIE_NAME,
    cookieValue: token,
    signal: AbortSignal.timeout(5_000),
  });
});

export async function requireServerSession(
  returnTo: string,
  options: { allowPasswordChange?: boolean } = {},
): Promise<AuthSession | null> {
  if (getPublicServiceMode() !== "api") return null;
  const session = await getServerSession();
  if (!session) redirect(`/login?returnTo=${encodeURIComponent(normalizeReturnTo(returnTo))}`);
  if (
    session.passwordChangeRequired &&
    !options.allowPasswordChange &&
    normalizeReturnTo(returnTo) !== "/account/security"
  ) {
    redirect(`/account/security?returnTo=${encodeURIComponent(normalizeReturnTo(returnTo))}`);
  }
  return session;
}
