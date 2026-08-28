import { GenerationJobView } from "@/features/generations/generation-job-view";
import { requireServerSession } from "@/features/auth/server-session";
import { RouteState } from "@/shared/ui/route-state";
import { getPublicServiceMode } from "@/shared/config/service-mode";

export default async function GenerationDetailPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  await requireServerSession(`/generations/${encodeURIComponent(jobId)}`);
  if (getPublicServiceMode() === "api") {
    return <GenerationJobView jobId={jobId} />;
  }

  return <RouteState title="任务详情" />;
}
