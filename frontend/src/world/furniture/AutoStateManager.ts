import type { FurnitureInstance } from "./FurnitureInstance";
import type { StatusType } from "../../agents/AgentSprite";

/** Statuses that count as "active" for auto-state electronics. */
const ACTIVE_STATUSES: StatusType[] = ["building", "thinking", "speaking"];

/** Delay in ms before reverting electronics to "off" when agent goes idle. */
const IDLE_OFF_DELAY_MS = 2500;

/**
 * Manages automatic on/off state transitions for electronics furniture
 * based on agent activity status. When an agent is active, electronics
 * in their workspace switch to "on"; when idle, they revert after a delay.
 */
export class AutoStateManager {
  private workspaceFurniture: Map<string, FurnitureInstance[]>;
  private pendingOffTimers: Map<string, ReturnType<typeof setTimeout>> = new Map();

  constructor(workspaceFurniture: Map<string, FurnitureInstance[]>) {
    this.workspaceFurniture = workspaceFurniture;
  }

  /**
   * Called when an agent's status changes. Activates or deactivates
   * stateful electronics in the agent's workspace.
   */
  onAgentStatusChange(agentId: string, status: StatusType): void {
    const furniture = this.workspaceFurniture.get(agentId);
    if (!furniture) return;

    const isActive = ACTIVE_STATUSES.includes(status);

    if (isActive) {
      // Cancel any pending off timer
      this.cancelOffTimer(agentId);
      // Switch stateful electronics to "on"
      for (const instance of furniture) {
        if (instance.manifest.states && "on" in instance.manifest.states) {
          instance.setState("on");
        }
      }
    } else {
      // Start delayed off transition
      this.scheduleOff(agentId, furniture);
    }
  }

  private scheduleOff(agentId: string, furniture: FurnitureInstance[]): void {
    // Cancel existing timer if any
    this.cancelOffTimer(agentId);

    const timer = setTimeout(() => {
      for (const instance of furniture) {
        if (instance.manifest.states && "off" in instance.manifest.states) {
          instance.setState("off");
        }
      }
      this.pendingOffTimers.delete(agentId);
    }, IDLE_OFF_DELAY_MS);

    this.pendingOffTimers.set(agentId, timer);
  }

  private cancelOffTimer(agentId: string): void {
    const timer = this.pendingOffTimers.get(agentId);
    if (timer) {
      clearTimeout(timer);
      this.pendingOffTimers.delete(agentId);
    }
  }

  destroy(): void {
    for (const timer of this.pendingOffTimers.values()) {
      clearTimeout(timer);
    }
    this.pendingOffTimers.clear();
  }
}
