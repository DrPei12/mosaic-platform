import { GenerationStudio } from "@/features/generations/generation-studio";
import { requireServerSession } from "@/features/auth/server-session";
import { RouteState } from "@/shared/ui/route-state";
import { getPublicServiceMode } from "@/shared/config/service-mode";

export default async function ImageStudioPage({
  params,
}: {
  params: Promise<{ modelId: string }>;
}) {
  const { modelId } = await params;
  await requireServerSession(`/studio/image/${encodeURIComponent(modelId)}`);
  if (getPublicServiceMode() === "api") {
    return <GenerationStudio modelId={modelId} modality="image" />;
  }

  return <RouteState title="图片工作台" />;
}
