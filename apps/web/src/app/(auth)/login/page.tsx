import { redirect } from "next/navigation";

import { LoginForm } from "@/features/auth/login-form";
import { getServerSession } from "@/features/auth/server-session";
import { BRAND } from "@/shared/config/brand";
import { getPublicServiceMode } from "@/shared/config/service-mode";
import { normalizeReturnTo } from "@/shared/config/routes";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ returnTo?: string | string[] }>;
}) {
  const mode = getPublicServiceMode();
  const query = await searchParams;
  const returnTo = normalizeReturnTo(
    Array.isArray(query.returnTo) ? query.returnTo[0] : query.returnTo,
  );
  if (mode === "api") {
    const session = await getServerSession();
    if (session?.authenticated) {
      redirect(session.passwordChangeRequired ? "/account/security" : returnTo);
    }
  }

  return (
    <main className="min-h-[100dvh] bg-[var(--mosaic-color-canvas)] px-6 py-12 md:px-10 md:py-16">
      <div className="mx-auto grid w-full max-w-md content-center gap-8 pt-[12vh]">
        <div>
          <p className="text-sm font-semibold tracking-[0.16em] text-[var(--mosaic-color-ink-muted)]">
            {BRAND.name}
          </p>
          <h1 className="mt-4 [font-size:var(--mosaic-typography-h1-font-size)] font-semibold [line-height:var(--mosaic-typography-h1-line-height)] tracking-[-0.04em] text-[var(--mosaic-color-ink)]">
            登录你的账户
          </h1>
        </div>
        <LoginForm mode={mode} returnTo={returnTo} />
      </div>
    </main>
  );
}
