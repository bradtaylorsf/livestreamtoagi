import { describe, expect, it } from "vitest";
import {
  HIGHLIGHTS_PLACEHOLDER,
  buildHighlights,
} from "@/components/ResearchHighlights";

describe("ResearchHighlights buildHighlights", () => {
  it("renders the simulations count from the API as a plain integer (no '+')", () => {
    const tiles = buildHighlights(9, 9);
    const sims = tiles.find((t) => t.label === "Simulations Run");
    expect(sims).toBeDefined();
    expect(sims!.value).toBe("9");
    expect(sims!.value).not.toContain("+");
    // The legacy hard-coded "62+" must not appear anywhere.
    for (const t of tiles) {
      expect(t.value).not.toBe("62+");
    }
  });

  it("renders the eval categories count from the API", () => {
    const tiles = buildHighlights(9, 9);
    const cats = tiles.find((t) => t.label === "Eval Categories");
    expect(cats).toBeDefined();
    expect(cats!.value).toBe("9");
    // The legacy hard-coded "12" must not appear when API returned 9 categories.
    for (const t of tiles) {
      expect(t.value).not.toBe("12");
    }
  });

  it("uses an em-dash placeholder while the API responses are unresolved", () => {
    const tiles = buildHighlights(null, null);
    const sims = tiles.find((t) => t.label === "Simulations Run");
    const cats = tiles.find((t) => t.label === "Eval Categories");
    expect(sims!.value).toBe(HIGHLIGHTS_PLACEHOLDER);
    expect(cats!.value).toBe(HIGHLIGHTS_PLACEHOLDER);
    // Critically: no hard-coded numeric defaults leak into the placeholder state.
    for (const t of tiles) {
      expect(t.value).not.toBe("62+");
      expect(t.value).not.toBe("12");
    }
  });

  it("preserves the static '9 Agents' and '100% Open Source' tiles", () => {
    const tiles = buildHighlights(0, 0);
    expect(tiles.some((t) => t.label === "6 LLM Providers" && t.value === "9 Agents")).toBe(true);
    expect(tiles.some((t) => t.label === "Open Source" && t.value === "100%")).toBe(true);
  });

  it("returns four tiles", () => {
    expect(buildHighlights(5, 12)).toHaveLength(4);
  });
});
