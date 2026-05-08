import { describe, expect, it } from "vitest";
import {
  SkeletonBlock,
  SkeletonCardList,
  SkeletonGrid,
  SkeletonRow,
  SkeletonTable,
} from "@/components/Skeleton";

// Light-weight tests — we don't have jsdom/RTL here, so we invoke the
// function components directly and inspect the React element tree they
// return. This is enough to guard layout/aria props and the
// "no aggressive shimmer" requirement.

type ReactElement = {
  type: unknown;
  props: Record<string, unknown> & { children?: unknown };
};

function asElement(node: unknown): ReactElement {
  if (!node || typeof node !== "object" || !("props" in node)) {
    throw new Error("Expected a React element");
  }
  return node as ReactElement;
}

function asArray(node: unknown): ReactElement[] {
  if (!Array.isArray(node)) return [asElement(node)];
  return node.map(asElement);
}

describe("SkeletonBlock", () => {
  it("renders a div with default width and height classes", () => {
    const el = asElement(SkeletonBlock({}));
    expect(el.type).toBe("div");
    const className = el.props.className as string;
    expect(className).toContain("w-full");
    expect(className).toContain("h-3");
  });

  it("uses a slow pulse, not an aggressive shimmer", () => {
    const el = asElement(SkeletonBlock({}));
    const className = el.props.className as string;
    expect(className).toContain("animate-pulse");
    expect(className).toContain("[animation-duration:1.8s]");
    // Guard against re-introducing fast shimmer keyframes
    expect(className).not.toMatch(/animate-shimmer|animate-spin/);
  });

  it("respects width and height overrides", () => {
    const el = asElement(SkeletonBlock({ width: "w-1/3", height: "h-6" }));
    const className = el.props.className as string;
    expect(className).toContain("w-1/3");
    expect(className).toContain("h-6");
    expect(className).not.toContain("w-full");
  });

  it("is hidden from assistive tech (parent owns the label)", () => {
    const el = asElement(SkeletonBlock({}));
    expect(el.props["aria-hidden"]).toBe("true");
  });
});

describe("SkeletonRow", () => {
  it("renders one block per width", () => {
    const el = asElement(SkeletonRow({ widths: ["w-32", "w-16", "w-10"] }));
    const children = asArray(el.props.children);
    expect(children).toHaveLength(3);
    for (const child of children) {
      expect(child.type).toBe(SkeletonBlock);
    }
  });
});

describe("SkeletonTable", () => {
  it("renders the requested number of rows plus a header row", () => {
    const el = asElement(
      SkeletonTable({ rows: 5, columnWidths: ["w-32", "w-16"] }),
    );
    const containerChildren = asArray(el.props.children);
    // [header, body]
    expect(containerChildren).toHaveLength(2);
    const body = containerChildren[1];
    const bodyRows = asArray(body.props.children);
    expect(bodyRows).toHaveLength(5);
  });

  it("defaults to 5 rows when not specified", () => {
    const el = asElement(SkeletonTable({ columnWidths: ["w-10"] }));
    const containerChildren = asArray(el.props.children);
    const body = containerChildren[1];
    const bodyRows = asArray(body.props.children);
    expect(bodyRows).toHaveLength(5);
  });

  it("exposes a status role for assistive tech", () => {
    const el = asElement(SkeletonTable({ columnWidths: ["w-10"] }));
    expect(el.props.role).toBe("status");
    expect(el.props["aria-label"]).toBe("Loading");
  });
});

describe("SkeletonCardList", () => {
  it("renders the requested card count", () => {
    const el = asElement(SkeletonCardList({ count: 3 }));
    const cards = asArray(el.props.children);
    expect(cards).toHaveLength(3);
  });

  it("defaults to 5 cards", () => {
    const el = asElement(SkeletonCardList({}));
    const cards = asArray(el.props.children);
    expect(cards).toHaveLength(5);
  });
});

describe("SkeletonGrid", () => {
  it("renders the requested grid item count", () => {
    const el = asElement(SkeletonGrid({ count: 12 }));
    const items = asArray(el.props.children);
    expect(items).toHaveLength(12);
  });
});
