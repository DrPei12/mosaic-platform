import { GenerationStudio } from "@/features/generations/generation-studio";
import { requireServerSession } from "@/features/auth/server-session";
import { RouteState } from "@/shared/ui/route-state";
import { getPublicServiceMode } from "@/shared/config/service-mode";

export default async function AudioStudioPage({
  params,
}: {
  params: Promise<{ modelId: string }>;
}) {
  const { modelId } = await params;
  await requireServerSession(`/studio/audio/${encodeURIComponent(modelId)}`);
  if (getPublicServiceMode() === "api") {
    return <GenerationStudio modelId={modelId} modality="audio" />;
  }

  return <RouteState title="音频工作台" />;
}
