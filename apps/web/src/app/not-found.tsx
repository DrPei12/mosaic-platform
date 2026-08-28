import Link from "next/link";

import { Button } from "@/shared/ui/button";
import { EmptyState } from "@/shared/ui/feedback-state";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-[var(--mosaic-layout-workspace)] p-6">
      <EmptyState
        title="页面不存在"
        action={
          <Button asChild>
            <Link href="/models">返回模型广场</Link>
          </Button>
        }
      />
    </main>
  );
}
