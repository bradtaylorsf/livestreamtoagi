import { describe, expect, it } from "vitest";

import { buildHeaderRules, securityHeaders } from "../security-headers";

describe("security headers", () => {
  it("returns headers for all routes", async () => {
    const headerRules = await buildHeaderRules();
    expect(headerRules).toHaveLength(1);
    expect(headerRules[0].source).toBe("/:path*");
  });

  it("includes all required security headers", async () => {
    const headerRules = await buildHeaderRules();
    const headerKeys = headerRules[0].headers.map(
      (h: { key: string }) => h.key,
    );

    expect(headerKeys).toContain("Content-Security-Policy");
    expect(headerKeys).toContain("X-Frame-Options");
    expect(headerKeys).toContain("X-Content-Type-Options");
    expect(headerKeys).toContain("Referrer-Policy");
    expect(headerKeys).toContain("Permissions-Policy");
    expect(headerKeys).toContain("Strict-Transport-Security");
  });

  it("CSP allows Google Fonts", () => {
    const csp = securityHeaders.find(
      (h: { key: string }) => h.key === "Content-Security-Policy",
    );
    expect(csp?.value).toContain("fonts.googleapis.com");
    expect(csp?.value).toContain("fonts.gstatic.com");
  });

  it("CSP allows YouTube and Twitch embeds", () => {
    const csp = securityHeaders.find(
      (h: { key: string }) => h.key === "Content-Security-Policy",
    );
    expect(csp?.value).toContain("www.youtube.com");
    expect(csp?.value).toContain("player.twitch.tv");
  });

  it("CSP allows WebSocket connections for local and production", () => {
    const csp = securityHeaders.find(
      (h: { key: string }) => h.key === "Content-Security-Policy",
    );
    expect(csp?.value).toContain("ws://localhost:*");
    expect(csp?.value).toContain("wss://livestreamtoagi.com");
  });

  it("X-Frame-Options is DENY", () => {
    const xfo = securityHeaders.find(
      (h: { key: string }) => h.key === "X-Frame-Options",
    );
    expect(xfo?.value).toBe("DENY");
  });

  it("HSTS has a long max-age", () => {
    const hsts = securityHeaders.find(
      (h: { key: string }) => h.key === "Strict-Transport-Security",
    );
    expect(hsts?.value).toContain("max-age=63072000");
    expect(hsts?.value).toContain("includeSubDomains");
  });
});
