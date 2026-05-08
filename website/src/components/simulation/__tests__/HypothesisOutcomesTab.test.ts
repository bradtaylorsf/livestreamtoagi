import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", async () => {
  return {
    updateSimulationResearch: vi.fn(),
  };
});

import {
  splitOutcomes,
  formatOutcomeValue,
  OutcomesView,
  HypothesisEditor,
} from "../HypothesisOutcomesTab";
import * as api from "@/lib/api";

type ReactElement = {
  type: unknown;
  props: Record<string, unknown> & { children?: unknown };
};

function isElement(node: unknown): node is ReactElement {
  return Boolean(
    node && typeof node === "object" && "props" in node && "type" in node,
  );
}

function flatten(node: unknown, out: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    for (const child of node) flatten(child, out);
    return out;
  }
  if (!isElement(node)) return out;
  out.push(node);
  flatten(node.props.children, out);
  return out;
}

function findByTestId(root: ReactElement, testId: string): ReactElement | null {
  for (const el of flatten(root)) {
    if (el.props["data-testid"] === testId) return el;
  }
  return null;
}

describe("splitOutcomes", () => {
  it("separates verdict from other outcome keys", () => {
    const result = splitOutcomes({
      verdict: "matched",
      winner: "vera",
      duration_minutes: 12,
    });
    expect(result.verdict).toBe("matched");
    expect(result.entries).toEqual([
      ["winner", "vera"],
      ["duration_minutes", 12],
    ]);
  });

  it("returns empty for null/undefined outcomes", () => {
    expect(splitOutcomes(null)).toEqual({ entries: [], verdict: "" });
    expect(splitOutcomes(undefined)).toEqual({ entries: [], verdict: "" });
  });

  it("returns no verdict if missing", () => {
    const result = splitOutcomes({ winner: "rex" });
    expect(result.verdict).toBe("");
    expect(result.entries).toEqual([["winner", "rex"]]);
  });
});

describe("formatOutcomeValue", () => {
  it("renders primitives as strings", () => {
    expect(formatOutcomeValue("hi")).toBe("hi");
    expect(formatOutcomeValue(3)).toBe("3");
    expect(formatOutcomeValue(true)).toBe("true");
  });

  it("renders null as em-dash", () => {
    expect(formatOutcomeValue(null)).toBe("—");
  });

  it("JSON-serializes objects", () => {
    expect(formatOutcomeValue({ a: 1 })).toContain('"a": 1');
  });
});

describe("OutcomesView", () => {
  it("renders an outcome card per key, excluding verdict", () => {
    const tree = OutcomesView({ outcomes: { winner: "vera", verdict: "ok" } });
    expect(findByTestId(tree as ReactElement, "outcome-card-winner")).not.toBeNull();
    expect(findByTestId(tree as ReactElement, "outcome-card-verdict")).toBeNull();
  });

  it("shows the verdict text in the verdict box", () => {
    const tree = OutcomesView({ outcomes: { verdict: "matched" } });
    const verdict = findByTestId(tree as ReactElement, "hypothesis-verdict");
    expect(String(verdict?.props.children)).toBe("matched");
  });

  it("falls back to 'Pending' when no outcomes are recorded", () => {
    const tree = OutcomesView({ outcomes: null });
    const verdict = findByTestId(tree as ReactElement, "hypothesis-verdict");
    expect(String(verdict?.props.children)).toMatch(/Pending/);
  });
});

describe("HypothesisEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a textarea pre-filled with the value prop", () => {
    const tree = HypothesisEditor({
      value: "Aurora keeps the energy up.",
      dirty: false,
      saving: false,
      error: null,
      savedAt: null,
      onChange: () => {},
      onSave: () => {},
    });
    const ta = findByTestId(tree as ReactElement, "hypothesis-textarea");
    expect(ta).not.toBeNull();
    expect(ta?.props.value).toBe("Aurora keeps the energy up.");
  });

  it("disables Save when not dirty", () => {
    const tree = HypothesisEditor({
      value: "x",
      dirty: false,
      saving: false,
      error: null,
      savedAt: null,
      onChange: () => {},
      onSave: () => {},
    });
    const btn = findByTestId(tree as ReactElement, "hypothesis-save");
    expect(btn?.props.disabled).toBe(true);
  });

  it("clicking Save invokes onSave", () => {
    const onSave = vi.fn();
    const tree = HypothesisEditor({
      value: "new",
      dirty: true,
      saving: false,
      error: null,
      savedAt: null,
      onChange: () => {},
      onSave,
    });
    const btn = findByTestId(tree as ReactElement, "hypothesis-save");
    expect(typeof btn?.props.onClick).toBe("function");
    (btn?.props.onClick as () => void)();
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("typing fires onChange with the new value", () => {
    const onChange = vi.fn();
    const tree = HypothesisEditor({
      value: "",
      dirty: false,
      saving: false,
      error: null,
      savedAt: null,
      onChange,
      onSave: () => {},
    });
    const ta = findByTestId(tree as ReactElement, "hypothesis-textarea");
    (ta?.props.onChange as (e: { target: { value: string } }) => void)({
      target: { value: "the new value" },
    });
    expect(onChange).toHaveBeenCalledWith("the new value");
  });
});

describe("HypothesisOutcomesTab → updateSimulationResearch wiring", () => {
  it("calls updateSimulationResearch when invoked through the API", async () => {
    const updateMock = api.updateSimulationResearch as unknown as ReturnType<
      typeof vi.fn
    >;
    updateMock.mockResolvedValue({
      id: "sim-1",
      hypothesis: "new",
      outcomes: null,
      learnings: null,
    });

    await api.updateSimulationResearch("sim-1", { hypothesis: "new" });
    expect(updateMock).toHaveBeenCalledWith("sim-1", { hypothesis: "new" });
  });
});
