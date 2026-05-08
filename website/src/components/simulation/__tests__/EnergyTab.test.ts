import { describe, expect, it } from "vitest";
import { buildChartRows } from "../energy-chart";

describe("buildChartRows", () => {
  it("merges per-agent points into a single row keyed by turn", () => {
    const data = {
      vera: [
        { t: "t1", energy: 0.5, turn: 1, conversation_id: "c" },
        { t: "t2", energy: 0.6, turn: 2, conversation_id: "c" },
      ],
      rex: [
        { t: "t1", energy: 0.4, turn: 1, conversation_id: "c" },
        { t: "t2", energy: 0.7, turn: 2, conversation_id: "c" },
      ],
    };
    const { rows, agents } = buildChartRows(data);
    expect(agents).toEqual(["rex", "vera"]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ turn: 1, vera: 0.5, rex: 0.4 });
    expect(rows[1]).toEqual({ turn: 2, vera: 0.6, rex: 0.7 });
  });

  it("returns empty rows when input is empty", () => {
    const { rows, agents } = buildChartRows({});
    expect(rows).toEqual([]);
    expect(agents).toEqual([]);
  });

  it("preserves rows where only some agents have data", () => {
    const data = {
      vera: [{ t: "t1", energy: 0.3, turn: 1, conversation_id: "c" }],
      rex: [{ t: "t2", energy: 0.8, turn: 2, conversation_id: "c" }],
    };
    const { rows } = buildChartRows(data);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ turn: 1, vera: 0.3 });
    expect(rows[1]).toEqual({ turn: 2, rex: 0.8 });
  });

  it("orders rows by turn ascending even when input is unsorted", () => {
    const data = {
      vera: [
        { t: "t3", energy: 0.9, turn: 3, conversation_id: "c" },
        { t: "t1", energy: 0.2, turn: 1, conversation_id: "c" },
        { t: "t2", energy: 0.5, turn: 2, conversation_id: "c" },
      ],
    };
    const { rows } = buildChartRows(data);
    expect(rows.map((r) => r.turn)).toEqual([1, 2, 3]);
  });
});
