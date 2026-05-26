import { describe, expect, it } from "vitest";
import HeadlessBadge from "@/components/HeadlessBadge";

type ReactElement = {
  type: unknown;
  props: Record<string, unknown>;
};

function isElement(node: unknown): node is ReactElement {
  return Boolean(
    node && typeof node === "object" && "props" in node && "type" in node,
  );
}

describe("HeadlessBadge", () => {
  it("renders the badge when config.headless is true", () => {
    const result = HeadlessBadge({ config: { headless: true } });
    expect(isElement(result)).toBe(true);
    if (isElement(result)) {
      expect(result.props["data-testid"]).toBe("headless-badge");
    }
  });

  it("renders nothing when config is null", () => {
    const result = HeadlessBadge({ config: null });
    expect(result).toBeNull();
  });

  it("renders nothing when config lacks the headless marker", () => {
    const result = HeadlessBadge({ config: { something: "else" } });
    expect(result).toBeNull();
  });

  it("renders nothing when headless is explicitly false", () => {
    const result = HeadlessBadge({ config: { headless: false } });
    expect(result).toBeNull();
  });
});
