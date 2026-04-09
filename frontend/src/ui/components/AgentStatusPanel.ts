import { AGENTS } from "../../agents";

export type AgentStatus = "idle" | "talking" | "building" | "sleeping" | "active" | "waiting" | "error";

interface AgentStatusEntry {
  element: HTMLDivElement;
  dotElement: HTMLSpanElement;
  status: AgentStatus;
}

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: "#888888",
  talking: "#44cc44",
  building: "#4488ff",
  sleeping: "#666666",
  active: "#44cc44",
  waiting: "#ffaa00",
  error: "#ff4444",
};

export class AgentStatusPanel {
  private element: HTMLDivElement;
  private entries: Map<string, AgentStatusEntry> = new Map();

  constructor() {
    this.element = document.createElement("div");
    this.element.className = "overlay-agents";

    const header = document.createElement("div");
    header.className = "overlay-agents-header";
    header.textContent = "Agents";
    this.element.appendChild(header);

    for (const agent of AGENTS) {
      if (agent.id === "management") continue;

      const row = document.createElement("div");
      row.className = "agent-status-row";

      const dot = document.createElement("span");
      dot.className = "agent-status-dot";
      dot.style.backgroundColor = STATUS_COLORS.idle;
      row.appendChild(dot);

      const name = document.createElement("span");
      name.className = "agent-status-name";
      name.textContent = agent.name;
      row.appendChild(name);

      this.element.appendChild(row);
      this.entries.set(agent.id, { element: row, dotElement: dot, status: "idle" });
    }
  }

  getElement(): HTMLDivElement {
    return this.element;
  }

  updateStatus(agentId: string, status: AgentStatus): void {
    const entry = this.entries.get(agentId);
    if (!entry) return;
    entry.status = status;
    entry.dotElement.style.backgroundColor = STATUS_COLORS[status];
  }

  getStatus(agentId: string): AgentStatus | undefined {
    return this.entries.get(agentId)?.status;
  }
}
