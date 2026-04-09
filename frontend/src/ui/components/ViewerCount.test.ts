// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { ViewerCount } from "./ViewerCount";

describe("ViewerCount", () => {
  it("creates a DOM element", () => {
    const vc = new ViewerCount();
    expect(vc.getElement()).toBeInstanceOf(HTMLDivElement);
    expect(vc.getElement().className).toBe("overlay-viewers");
  });

  it("shows default count", () => {
    const vc = new ViewerCount();
    expect(vc.getElement().textContent).toContain("0 viewers");
  });

  it("updates count", () => {
    const vc = new ViewerCount();
    vc.update(1234);
    expect(vc.getElement().textContent).toContain("1234 viewers");
  });

  it("uses singular for 1 viewer", () => {
    const vc = new ViewerCount();
    vc.update(1);
    expect(vc.getElement().textContent).toContain("1 viewer");
    expect(vc.getElement().textContent).not.toContain("viewers");
  });
});
