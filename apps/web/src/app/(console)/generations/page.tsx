import { ApiGenerationHistory } from "@/features/generations/generation-history";
import { requireServerSession } from "@/features/auth/server-session";
import { RouteState } from "@/shared/ui/route-state";
import { getPublicServiceMode } from "@/shared/config/service-mode";

export default async function GenerationsPage() {
  await requireServerSession("/generations");
  if (getPublicServiceMode() === "api") return <ApiGenerationHistory />;

  return <RouteState title="生成记录" />;
}
