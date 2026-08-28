import Link from "next/link";

import { BRAND } from "@/shared/config/brand";
import { Button } from "@/shared/ui/button";

export default function MarketingPage() {
  return (
    <main className="grid min-h-[100dvh] content-center bg-[var(--mosaic-color-canvas)] px-6 py-12 md:px-10 md:py-16 lg:px-16 lg:py-20">
      <div className="mx-auto w-full max-w-[var(--mosaic-layout-content)]">
        <div className="grid max-w-4xl gap-8">
          <p className="text-sm font-semibold tracking-[0.16em] text-[var(--mosaic-color-ink-muted)]">
            {BRAND.name}
          </p>
          <h1 className="max-w-4xl [font-size:clamp(2.5rem,7vw,var(--mosaic-typography-display-font-size))] font-semibold [line-height:clamp(2.75rem,8vw,var(--mosaic-typography-display-line-height))] tracking-[-0.055em] text-[var(--mosaic-color-ink)]">
            选择模型，开始创作。
          </h1>
          <div>
            <Button asChild>
              <Link href="/login">
                开始使用
              </Link>
            </Button>
          </div>
        </div>

      </div>
    </main>
  );
}
