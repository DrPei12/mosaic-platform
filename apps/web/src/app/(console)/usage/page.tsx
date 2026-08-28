import { UsageDashboard } from "@/features/usage/usage-dashboard";
import { requireServerSession } from "@/features/auth/server-session";
import { getPublicServiceMode } from "@/shared/config/service-mode";
import { RouteState } from "@/shared/ui/route-state";

export default async function UsagePage() {
  await requireServerSession("/usage");
  return getPublicServiceMode() === "api"
    ? <UsageDashboard />
    : <RouteState title="用量中心" />;
}
