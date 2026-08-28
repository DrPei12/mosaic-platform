import { GenerationStudio } from "@/features/generations/generation-studio";
import { requireServerSession } from "@/features/auth/server-session";
import { RouteState } from "@/shared/ui/route-state";
import { getPublicServiceMode } from "@/shared/config/service-mode";

export default async function VideoStudioPage({
  params,
}: {
  params: Promise<{ modelId: string }>;
}) {
  const { modelId } = await params;
  await requireServerSession(`/studio/video/${encodeURIComponent(modelId)}`);
  if (getPublicServiceMode() === "api") {
    return <GenerationStudio modelId={modelId} modality="video" />;
  }

  return <RouteState title="视频工作台" />;
}
