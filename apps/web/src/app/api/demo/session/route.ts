import { NextResponse } from "next/server";

import { requestLocalSession } from "@/services/local-session-bootstrap-server";

function localBypassEnabled(): boolean {
  return (
    process.env.NODE_ENV !== "production" &&
    process.env.APP_ENVIRONMENT !== "production" &&
    process.env.NEXT_PUBLIC_\u004dOSAIC_SKIP_LOGIN === "true" &&
    Boolean(process.env.\u004dOSAIC_DEMO_EMAIL && process.env.\u004dOSAIC_DEMO_PASSWORD)
  );
}

export async function POST(): Promise<NextResponse> {
  if (!localBypassEnabled()) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }

  const response = await requestLocalSession();

  const payload = await response.text();
  const result = new NextResponse(payload, {
    status: response.status,
    headers: {
      "cache-control": "no-store",
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
  const setCookies = response.headers.getSetCookie?.() ?? [];
  for (const cookie of setCookies) result.headers.append("set-cookie", cookie);
  return result;
}
