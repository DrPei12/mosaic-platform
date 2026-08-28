import { Skeleton } from "@/shared/ui/feedback-state";

export default function ChatLoading() {
  return (
    <section
      aria-label="正在加载文本对话"
      className="flex h-full min-h-[100dvh] min-w-0 w-full flex-col overflow-hidden bg-[var(--mosaic-color-surface)]"
    >
      <div className="flex min-h-[var(--mosaic-layout-top-bar-desktop)] items-center border-b border-[var(--mosaic-color-line)] px-5 sm:px-8">
        <Skeleton label="正在加载模型" className="h-10 w-48 rounded-[var(--mosaic-radius-control)]" />
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4 px-5 py-8 sm:px-8">
        <Skeleton label="正在加载消息" className="h-20 max-w-[640px]" />
        <Skeleton label="正在加载消息" className="ml-auto h-16 max-w-[480px]" />
        <Skeleton label="正在加载消息" className="h-24 max-w-[720px]" />
      </div>
    </section>
  );
}
