import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

import { buildHeaderRules } from "./src/lib/security-headers";

// Resolve the directory of this config file in both CJS (Next.js compile) and
// ESM (Vitest direct require) without relying on the global `__dirname`.
const HERE =
  typeof __dirname !== "undefined"
    ? __dirname
    : path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // Pin the file-tracing root to this package's directory.
  // With both pnpm-lock.yaml at the repo root and package-lock.json here,
  // Next.js would otherwise infer the workspace root as the repo root and
  // warn; pinning it silences the warning without affecting module resolution.
  outputFileTracingRoot: HERE,
  headers: buildHeaderRules,
  async rewrites() {
    const apiUrl = process.env.BACKEND_URL ?? "http://localhost:8010";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
