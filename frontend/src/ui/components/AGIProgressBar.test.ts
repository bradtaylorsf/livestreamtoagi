// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { AGIProgressBar } from "./AGIProgressBar";

describe("AGIProgressBar", () => {
  it("creates a DOM element", () => {
    const bar = new AGIProgressBar();
    expect(bar.getElement()).toBeInstanceOf(HTMLDivElement);
    expect(bar.getElement().className).toBe("overlay-agi");
  });

  it("starts at 0%", () => {
    const bar = new AGIProgressBar();
    expect(bar.getElement().textContent).toContain("0%");
    const fill = bar.getElement().querySelector(".agi-fill") as HTMLDivElement;
    expect(fill.style.width).toBe("0%");
  });

  it("updates fill width and label", () => {
    const bar = new AGIProgressBar();
    bar.update(42.7, 5);
    expect(bar.getElement().textContent).toContain("43% across 5 categories");
    const fill = bar.getElement().querySelector(".agi-fill") as HTMLDivElement;
    expect(fill.style.width).toBe("42.7%");
  });

  it("clamps percent to 0-100", () => {
    const bar = new AGIProgressBar();
    bar.update(150, 3);
    const fill = bar.getElement().querySelector(".agi-fill") as HTMLDivElement;
    expect(fill.style.width).toBe("100%");

    bar.update(-10, 3);
    expect(fill.style.width).toBe("0%");
  });
});
