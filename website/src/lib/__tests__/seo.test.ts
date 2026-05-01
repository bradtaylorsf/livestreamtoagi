import { describe, expect, it } from "vitest";
import sitemap from "../../app/sitemap";
import robots from "../../app/robots";

describe("sitemap", () => {
  it("returns an array of sitemap entries", () => {
    const entries = sitemap();
    expect(Array.isArray(entries)).toBe(true);
    expect(entries.length).toBeGreaterThan(0);
  });

  it("includes all static public pages", () => {
    const entries = sitemap();
    const urls = entries.map((e) => e.url);

    const requiredPages = [
      "",
      "/about",
      "/agents",
      "/blog",
      "/challenges",
      "/clips",
      "/conversations",
      "/evals",
      "/ethics",
      "/lore",
      "/safety",
      "/world",
    ];
    for (const page of requiredPages) {
      expect(urls).toContain(`https://livestreamtoagi.com${page}`);
    }
  });

  it("includes agent profile pages", () => {
    const entries = sitemap();
    const urls = entries.map((e) => e.url);
    expect(urls).toContain("https://livestreamtoagi.com/agents/vera");
    expect(urls).toContain("https://livestreamtoagi.com/agents/rex");
  });

  it("does not include admin pages", () => {
    const entries = sitemap();
    const urls = entries.map((e) => e.url);
    const adminUrls = urls.filter((u) => u.includes("/admin"));
    expect(adminUrls).toHaveLength(0);
  });
});

describe("robots", () => {
  it("allows public pages", () => {
    const config = robots();
    expect(config.rules).toBeDefined();
    const rules = Array.isArray(config.rules)
      ? config.rules
      : [config.rules];
    expect(rules[0].allow).toBe("/");
  });

  it("includes sitemap URL", () => {
    const config = robots();
    expect(config.sitemap).toBe(
      "https://livestreamtoagi.com/sitemap.xml",
    );
  });
});
