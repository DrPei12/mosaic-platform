import { NextRequest, NextResponse } from "next/server";

import { isProtectedRoute, normalizeReturnTo } from "@/shared/config/routes";
import { SESSION_COOKIE_ENV_NAME } from "@/shared/config/brand";
import { getPublicServiceMode } from "@/shared/config/service-mode";

const SESSION_COOKIE_NAME =
  process.env[SESSION_COOKIE_ENV_NAME] ?? "mosaic_session";

export function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (
    getPublicServiceMode() === "demo" ||
    !isProtectedRoute(pathname) ||
    request.cookies.has(SESSION_COOKIE_NAME)
  ) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set(
    "returnTo",
    normalizeReturnTo(`${pathname}${request.nextUrl.search}`),
  );
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml).*)",
  ],
};
