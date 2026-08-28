import { SecuritySettings } from "@/features/account/security-settings";
import { requireServerSession } from "@/features/auth/server-session";
import { normalizeReturnTo } from "@/shared/config/routes";

export default async function AccountSecurityPage({
  searchParams,
}: {
  searchParams: Promise<{ returnTo?: string | string[] }>;
}) {
  const session = await requireServerSession("/account/security");
  const query = await searchParams;
  const rawReturnTo = Array.isArray(query.returnTo) ? query.returnTo[0] : query.returnTo;
  return (
    <SecuritySettings
      {...(session
        ? { initialPasswordChangeRequired: session.passwordChangeRequired }
        : {})}
      {...(rawReturnTo === undefined ? {} : { returnTo: normalizeReturnTo(rawReturnTo) })}
    />
  );
}
