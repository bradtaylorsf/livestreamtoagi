import { describe, expect, it } from "vitest";
import { conversationTopicLabel } from "@/lib/conversation-display";

describe("conversationTopicLabel", () => {
  it("returns the first detected topic when present", () => {
    expect(conversationTopicLabel(["budget"])).toBe("budget");
  });

  it("returns the first topic even when multiple are present", () => {
    expect(conversationTopicLabel(["autonomous", "budget"])).toBe("autonomous");
  });

  it("does NOT return status-like strings — null topics fall back to em-dash", () => {
    // Regression: previously the topic column rendered trigger_type ("idle"),
    // not topics_discussed[0]. The helper must never surface a status string
    // like "idle" when topics are absent.
    expect(conversationTopicLabel(null)).toBe("—");
  });

  it("falls back to em-dash when topics_discussed is undefined", () => {
    expect(conversationTopicLabel(undefined)).toBe("—");
  });

  it("falls back to em-dash when topics_discussed is empty", () => {
    expect(conversationTopicLabel([])).toBe("—");
  });

  it("falls back to em-dash when first topic is whitespace", () => {
    expect(conversationTopicLabel(["   "])).toBe("—");
  });
});
