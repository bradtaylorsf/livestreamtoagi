import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

// Issue #464: cold-loading /simulations/[id]?tab=<key> must select the
// requested tab on first render, not just after a click. The fix swaps
// pure-derived `activeTab` for a useState whose lazy initializer reads
// window.location.search, with a useEffect that keeps state in sync with
// click-driven router.push() URL updates.
//
// We're in a node test env without RTL/jsdom, so we verify the shape of
// the source — sufficient to guard against regressing back to pure
// derived state, consistent with the pattern used elsewhere in __tests__.
const SOURCE = readFileSync(
  resolve(__dirname, "../simulations/[id]/page.tsx"),
  "utf8",
);

describe("simulation detail page tab initialization (#464)", () => {
  it("initializes activeTab from window.location.search on cold load", () => {
    expect(SOURCE).toMatch(/window\.location\.search/);
    expect(SOURCE).toMatch(
      /useState<TabKey>\(\(\)\s*=>\s*\{[\s\S]*?window\.location\.search[\s\S]*?\}\)/,
    );
  });

  it("guards the window read for SSR (typeof window check, default 'overview')", () => {
    expect(SOURCE).toMatch(
      /typeof window === "undefined"[\s\S]*?return "overview"/,
    );
  });

  it("gates the URL value through isValidTab in the lazy initializer", () => {
    expect(SOURCE).toMatch(
      /window\.location\.search[\s\S]*?isValidTab\([^)]+\)\s*\?\s*\w+\s*:\s*"overview"/,
    );
  });

  it("syncs activeTab from searchParams in a useEffect (click-driven router.push)", () => {
    expect(SOURCE).toMatch(
      /useEffect\(\(\)\s*=>\s*\{[\s\S]*?searchParams\.get\("tab"\)[\s\S]*?setActiveTabState\([\s\S]*?\}\s*,\s*\[searchParams\]\)/,
    );
  });

  it("does not regress to pure derived state for activeTab", () => {
    // The buggy form was:
    //   const activeTab: TabKey = isValidTab(tabParam) ? tabParam : "overview";
    expect(SOURCE).not.toMatch(
      /const activeTab:\s*TabKey\s*=\s*isValidTab\(tabParam\)/,
    );
  });
});
