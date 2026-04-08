// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { TopicDisplay } from "./TopicDisplay";

describe("TopicDisplay", () => {
  it("creates a DOM element", () => {
    const td = new TopicDisplay();
    expect(td.getElement()).toBeInstanceOf(HTMLDivElement);
    expect(td.getElement().className).toBe("overlay-topic");
  });

  it("shows default placeholder", () => {
    const td = new TopicDisplay();
    expect(td.getElement().textContent).toContain("--");
  });

  it("updates topic text", () => {
    const td = new TopicDisplay();
    td.update("Budget allocation debate");
    expect(td.getElement().textContent).toContain("Budget allocation debate");
  });
});
