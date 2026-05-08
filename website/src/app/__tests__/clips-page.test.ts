import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

// The empty state copy is the main acceptance criteria for issue #411.
// We're in a node test env without RTL/jsdom, so we verify the rendered
// JSX by reading the source — sufficient to catch regressions on the
// required wording and CTAs.
const SOURCE = readFileSync(
  resolve(__dirname, "../clips/page.tsx"),
  "utf8",
);

describe("clips page empty state", () => {
  it("explains clips are auto-detected from high-scoring moments", () => {
    expect(SOURCE).toMatch(/auto-detected/i);
    expect(SOURCE).toMatch(/high-scoring simulation moments/i);
  });

  it("explains clips are manually curated", () => {
    expect(SOURCE).toMatch(/manually curated/i);
  });

  it("tells the viewer when clips will appear", () => {
    expect(SOURCE).toMatch(/clip extractor/i);
  });

  it("offers a 'Subscribe to clip alerts' CTA", () => {
    expect(SOURCE).toMatch(/Subscribe to clip alerts/);
  });

  it("links to the blog as a path forward", () => {
    expect(SOURCE).toMatch(/href="\/blog"/);
  });
});
