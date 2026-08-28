export const CONSOLE_ROUTES = [
  { href: "/models", label: "模型广场" },
  { href: "/generations", label: "生成记录" },
  { href: "/usage", label: "用量中心" },
] as const;

export const ROUTE_ACCESS = {
  public: ["/", "/login"],
  protectedPrefixes: [
    "/models",
    "/chat",
    "/studio",
    "/generations",
    "/usage",
    "/account",
  ],
} as const;

type PublicRoute = (typeof ROUTE_ACCESS.public)[number];
type ProtectedPrefix = (typeof ROUTE_ACCESS.protectedPrefixes)[number];

function matchesPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function isPublicRoute(pathname: string): pathname is PublicRoute {
  return ROUTE_ACCESS.public.includes(pathname as PublicRoute);
}

export function isProtectedRoute(pathname: string): pathname is ProtectedPrefix {
  return ROUTE_ACCESS.protectedPrefixes.some((prefix) =>
    matchesPrefix(pathname, prefix),
  );
}

export const isDemoGatedRoute = isProtectedRoute;

export function normalizeReturnTo(value: string | undefined): string {
  if (
    value === undefined ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(value)
  ) {
    return "/models";
  }
  let parsed: URL;
  try {
    parsed = new URL(value, "https://mosaic.invalid");
  } catch {
    return "/models";
  }
  if (parsed.origin !== "https://mosaic.invalid" || !isProtectedRoute(parsed.pathname)) {
    return "/models";
  }
  return `${parsed.pathname}${parsed.search}`;
}

export function isKnownRoute(pathname: string): boolean {
  return isPublicRoute(pathname) || isProtectedRoute(pathname);
}
