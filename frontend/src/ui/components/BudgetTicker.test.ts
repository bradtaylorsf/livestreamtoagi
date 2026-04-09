// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { BudgetTicker } from "./BudgetTicker";

describe("BudgetTicker", () => {
  it("creates a DOM element", () => {
    const ticker = new BudgetTicker();
    expect(ticker.getElement()).toBeInstanceOf(HTMLDivElement);
    expect(ticker.getElement().className).toBe("overlay-budget");
  });

  it("shows default text", () => {
    const ticker = new BudgetTicker();
    expect(ticker.getElement().textContent).toContain("$0.00 / $150.00");
  });

  it("updates displayed values", () => {
    const ticker = new BudgetTicker();
    ticker.update(42.5, 150);
    expect(ticker.getElement().textContent).toContain("$42.50 / $150.00");
  });

  it("adds warning class at 80% spend", () => {
    const ticker = new BudgetTicker();
    ticker.update(120, 150);
    expect(ticker.getElement().classList.contains("budget-warning")).toBe(true);
  });

  it("removes warning class when below 80%", () => {
    const ticker = new BudgetTicker();
    ticker.update(120, 150);
    expect(ticker.getElement().classList.contains("budget-warning")).toBe(true);
    ticker.update(50, 150);
    expect(ticker.getElement().classList.contains("budget-warning")).toBe(false);
  });
});
