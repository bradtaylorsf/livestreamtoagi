// Shared security header definitions used by next.config.ts and tested by
// src/lib/__tests__/security-headers.test.ts. Kept in src/lib/ so vitest can
// import it directly without having to require() the TypeScript next.config.

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

export const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: cspDirectives.join("; "),
  },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
];

export async function buildHeaderRules(): Promise<
  Array<{ source: string; headers: typeof securityHeaders }>
> {
  return [{ source: "/:path*", headers: securityHeaders }];
}
