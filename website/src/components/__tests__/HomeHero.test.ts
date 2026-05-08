import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(
  resolve(__dirname, "../HomeHero.tsx"),
  "utf8",
);
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, "../../app/page.tsx"),
  "utf8",
);

describe("HomeHero", () => {
  it("primary CTA links to /simulations/new", () => {
    expect(SOURCE).toMatch(/href="\/simulations\/new"/);
  });

  it('primary CTA reads "Run your own simulation"', () => {
    expect(SOURCE).toMatch(/Run your own simulation/);
  });

  it("secondary CTA links to /simulations/live", () => {
    expect(SOURCE).toMatch(/href="\/simulations\/live"/);
  });

  it('secondary CTA reads "Watch live"', () => {
    expect(SOURCE).toMatch(/Watch live/);
  });

  it("primary CTA is visually the most prominent (solid background, vs bordered secondary)", () => {
    // The primary CTA uses bg-neon-cyan (filled), the secondary uses border-only
    expect(SOURCE).toMatch(/bg-neon-cyan[^"]*"[\s\S]*data-testid="cta-run-your-own-simulation"/);
    expect(SOURCE).toMatch(/border border-neon-cyan\/[\s\S]*data-testid="cta-watch-live"/);
  });
});

describe("Home page", () => {
  it("renders the new HomeHero section", () => {
    expect(PAGE_SOURCE).toMatch(/<HomeHero\s*\/>/);
  });

  it("renders the Currently running, Featured and Recently completed sections", () => {
    expect(PAGE_SOURCE).toMatch(/<RunningSimulations\s*\/>/);
    expect(PAGE_SOURCE).toMatch(/<FeaturedSimulations\s*\/>/);
    expect(PAGE_SOURCE).toMatch(/<RecentSimulations\s*\/>/);
  });

  it("does not render the Cast or stream embed on the home", () => {
    expect(PAGE_SOURCE).not.toMatch(/<AgentGrid\s*\/>/);
    expect(PAGE_SOURCE).not.toMatch(/<StreamEmbed\s*\/>/);
  });

  it("keeps Latest posts in the footer area", () => {
    expect(PAGE_SOURCE).toMatch(/<LatestPosts\s*\/>/);
  });
});
