import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  ...(process.env.MOSAIC_E2E_USE_NEXT_START === "true" ? {} : { output: "standalone" as const }),
  outputFileTracingRoot: path.resolve(import.meta.dirname, "../.."),
  outputFileTracingIncludes: {
    "/*": [
      "../../node_modules/.pnpm/@swc+helpers@*/node_modules/@swc/helpers/**/*",
    ],
  },
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  transpilePackages: ["@mosaic/contracts", "@mosaic/design-tokens"],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.MOSAIC_API_ORIGIN ?? "http://127.0.0.1:8000"}/api/v1/:path*`,
      },
      {
        source: "/docs",
        destination: `${process.env.MOSAIC_API_ORIGIN ?? "http://127.0.0.1:8000"}/docs`,
      },
      {
        source: "/openapi.json",
        destination: `${process.env.MOSAIC_API_ORIGIN ?? "http://127.0.0.1:8000"}/openapi.json`,
      },
    ];
  },
};

export default nextConfig;
