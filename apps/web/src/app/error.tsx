"use client";

import { Button } from "@/shared/ui/button";
import { ErrorState } from "@/shared/ui/feedback-state";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  void error;

  return (
    <main className="mx-auto max-w-[var(--mosaic-layout-workspace)] p-6">
      <ErrorState
        title="页面加载失败"
        description="当前页面没有完成加载，请重试。"
        action={<Button onClick={reset}>重试</Button>}
      />
    </main>
  );
}
