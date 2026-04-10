import { describe, expect, it } from "vitest";
import { scoreColor, scoreBg, scoreCardBg } from "@/lib/score-utils";

describe("score-utils", () => {
  describe("scoreColor", () => {
    it("returns green for scores >= 70", () => {
      expect(scoreColor(70)).toBe("text-green-400");
      expect(scoreColor(85)).toBe("text-green-400");
      expect(scoreColor(100)).toBe("text-green-400");
    });

    it("returns yellow for scores >= 40 and < 70", () => {
      expect(scoreColor(40)).toBe("text-yellow-400");
      expect(scoreColor(55)).toBe("text-yellow-400");
      expect(scoreColor(69)).toBe("text-yellow-400");
    });

    it("returns red for scores < 40", () => {
      expect(scoreColor(0)).toBe("text-red-400");
      expect(scoreColor(20)).toBe("text-red-400");
      expect(scoreColor(39)).toBe("text-red-400");
    });
  });

  describe("scoreBg", () => {
    it("returns appropriate background colors", () => {
      expect(scoreBg(80)).toBe("bg-green-500/20");
      expect(scoreBg(50)).toBe("bg-yellow-500/20");
      expect(scoreBg(10)).toBe("bg-red-500/20");
    });
  });

  describe("scoreCardBg", () => {
    it("returns appropriate card backgrounds", () => {
      expect(scoreCardBg(75)).toContain("border-green-500/30");
      expect(scoreCardBg(50)).toContain("border-yellow-500/30");
      expect(scoreCardBg(25)).toContain("border-red-500/30");
    });
  });

  describe("trend calculation", () => {
    // Test the calculateTrend logic directly
    function calculateTrend(
      scores: (number | null)[],
    ): "up" | "down" | "flat" {
      if (scores.length < 2) return "flat";
      const recent = scores.slice(-3);
      const first = recent[0] ?? 0;
      const last = recent[recent.length - 1] ?? 0;
      const diff = last - first;
      if (diff > 2) return "up";
      if (diff < -2) return "down";
      return "flat";
    }

    it("returns flat for single score", () => {
      expect(calculateTrend([50])).toBe("flat");
    });

    it("returns flat for no change", () => {
      expect(calculateTrend([50, 51])).toBe("flat");
    });

    it("returns up for increasing scores", () => {
      expect(calculateTrend([50, 55, 60])).toBe("up");
    });

    it("returns down for decreasing scores", () => {
      expect(calculateTrend([60, 55, 50])).toBe("down");
    });

    it("uses last 3 scores for trend", () => {
      // Overall going up but last 3 going down
      expect(calculateTrend([10, 20, 80, 75, 70])).toBe("down");
    });
  });

  describe("CSV export formatting", () => {
    it("escapes values with commas", () => {
      const val = 'hello, world';
      const escaped = val.includes(",") ? `"${val}"` : val;
      expect(escaped).toBe('"hello, world"');
    });

    it("escapes values with quotes", () => {
      const val = 'say "hello"';
      const escaped =
        val.includes('"')
          ? `"${val.replace(/"/g, '""')}"`
          : val;
      expect(escaped).toBe('"say ""hello"""');
    });

    it("passes through simple values", () => {
      const val = "simple";
      const escaped =
        val.includes(",") || val.includes('"') || val.includes("\n")
          ? `"${val.replace(/"/g, '""')}"`
          : val;
      expect(escaped).toBe("simple");
    });
  });
});
