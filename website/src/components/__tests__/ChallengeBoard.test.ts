import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";
import { rerunHref } from "@/components/ChallengeBoard";

const BOARD_SOURCE = readFileSync(
  resolve(__dirname, "../ChallengeBoard.tsx"),
  "utf8",
);
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, "../../app/challenges/page.tsx"),
  "utf8",
);

describe("rerunHref", () => {
  it("encodes the challenge id into a /simulations/new query string", () => {
    expect(rerunHref(42)).toBe("/simulations/new?challenge_id=42");
  });
});

describe("ChallengeBoard source", () => {
  it("offers a 'Re-run this challenge' action on every card", () => {
    expect(BOARD_SOURCE).toContain("Re-run this challenge");
  });

  it("links each card to the source simulation workspace", () => {
    expect(BOARD_SOURCE).toContain("/simulations/${challenge.simulation_id}");
    expect(BOARD_SOURCE).toContain("Open simulation");
  });

  it("renders simulation name, tags, and shared_at metadata", () => {
    expect(BOARD_SOURCE).toContain("simulation_name");
    expect(BOARD_SOURCE).toContain("challenge.tags");
    expect(BOARD_SOURCE).toContain("shared_at");
  });

  it("preserves the existing upvote affordance via upvoteChallenge", () => {
    expect(BOARD_SOURCE).toContain("upvoteChallenge");
    expect(BOARD_SOURCE).toContain("Upvote challenge");
  });

  it("filters now use a tag dropdown, not a status dropdown", () => {
    expect(BOARD_SOURCE).toContain("Filter by tag");
    expect(BOARD_SOURCE).not.toContain("STATUS_FILTER_OPTIONS");
  });
});

describe("/challenges page source", () => {
  it("no longer mounts ChallengeSubmitForm", () => {
    expect(PAGE_SOURCE).not.toContain("ChallengeSubmitForm");
  });

  it("explains the new sharing flow in the banner", () => {
    expect(PAGE_SOURCE).toContain("Re-run this challenge");
    expect(PAGE_SOURCE).toContain("HOW SHARING WORKS");
  });
});
