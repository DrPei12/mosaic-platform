import { Suspense } from "react";

import {
  ModelMarketplace,
  ModelMarketplaceLoading,
} from "@/features/models/model-marketplace";
import { requireServerSession } from "@/features/auth/server-session";

export default async function ModelsPage() {
  await requireServerSession("/models");
  return <Suspense fallback={<ModelMarketplaceLoading />}><ModelMarketplace /></Suspense>;
}
