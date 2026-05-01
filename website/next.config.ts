import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// Resolve the directory of this config file in both CJS (Next.js compile) and
// ESM (Vitest direct require) without relying on the global `__dirname`.
const HERE =
  typeof __dirname !== "undefined"
    ? __dirname
    : path.dirname(fileURLToPath(import.meta.url));

const cspDirectives = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' fonts.googleapis.com",
  "font-src 'self' fonts.gstatic.com",
  "img-src 'self' data: blob:",
  "frame-src www.youtube.com player.twitch.tv clips.twitch.tv",
  "connect-src 'self' ws://localhost:* wss://livestreamtoagi.com",
  "frame-ancestors 'none'",
];

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: cspDirectives.join("; "),
  },
  {
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
];

const nextConfig: NextConfig = {
  // Pin the file-tracing root to this package's directory.
  // With both pnpm-lock.yaml at the repo root and package-lock.json here,
  // Next.js would otherwise infer the workspace root as the repo root and
  // warn; pinning it silences the warning without affecting module resolution.
  outputFileTracingRoot: HERE,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
  async rewrites() {
    const apiUrl =
      process.env.BACKEND_URL ?? "http://localhost:8010";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
