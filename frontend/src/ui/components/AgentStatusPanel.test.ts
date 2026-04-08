// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { AgentStatusPanel } from "./AgentStatusPanel";

describe("AgentStatusPanel", () => {
  it("creates a DOM element", () => {
    const panel = new AgentStatusPanel();
    expect(panel.getElement()).toBeInstanceOf(HTMLDivElement);
    expect(panel.getElement().className).toBe("overlay-agents");
  });

  it("lists all agents except management", () => {
    const panel = new AgentStatusPanel();
    const rows = panel.getElement().querySelectorAll(".agent-status-row");
    // 9 agents minus management = 8
    expect(rows.length).toBe(8);
  });

  it("shows agent names", () => {
    const panel = new AgentStatusPanel();
    const text = panel.getElement().textContent;
    expect(text).toContain("Vera");
    expect(text).toContain("Rex");
    expect(text).toContain("Alpha");
    expect(text).not.toContain("The Management");
  });

  it("defaults all agents to idle", () => {
    const panel = new AgentStatusPanel();
    expect(panel.getStatus("vera")).toBe("idle");
    expect(panel.getStatus("rex")).toBe("idle");
  });

  it("updates agent status", () => {
    const panel = new AgentStatusPanel();
    panel.updateStatus("vera", "talking");
    expect(panel.getStatus("vera")).toBe("talking");
  });

  it("changes dot color on status update", () => {
    const panel = new AgentStatusPanel();
    panel.updateStatus("vera", "building");
    const rows = panel.getElement().querySelectorAll(".agent-status-row");
    const veraDot = rows[0].querySelector(".agent-status-dot") as HTMLSpanElement;
    expect(veraDot.style.backgroundColor).toBe("rgb(68, 136, 255)");
  });

  it("ignores unknown agent", () => {
    const panel = new AgentStatusPanel();
    panel.updateStatus("nonexistent", "talking");
    expect(panel.getStatus("nonexistent")).toBeUndefined();
  });
});
