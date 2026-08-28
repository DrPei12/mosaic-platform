import { Skeleton } from "@/shared/ui/feedback-state";

export default function Loading() {
  return (
    <main className="mx-auto max-w-[var(--mosaic-layout-workspace)] p-6">
      <Skeleton label="正在加载页面" />
    </main>
  );
}
