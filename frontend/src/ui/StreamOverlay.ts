import { BudgetTicker } from "./components/BudgetTicker";
import { AGIProgressBar } from "./components/AGIProgressBar";
import { ViewerCount } from "./components/ViewerCount";
import { TopicDisplay } from "./components/TopicDisplay";
import { AgentStatusPanel } from "./components/AgentStatusPanel";
import { EventType, type ServerEvent } from "../types/events";
import type { WebSocketClient } from "../network/WebSocketClient";

let overlayStylesInjected = false;

function injectOverlayStyles(): void {
  if (overlayStylesInjected) return;
  overlayStylesInjected = true;

  const style = document.createElement("style");
  style.id = "stream-overlay-styles";
  style.textContent = `
    #stream-overlay {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 10;
      font-family: monospace;
      font-size: 12px;
      color: #e0e0e0;
    }
    .overlay-top-bar {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 8px 12px;
      background: rgba(26, 26, 46, 0.85);
      border-bottom: 2px solid #333355;
      box-shadow: inset 0 -1px 0 #444466;
    }
    .overlay-label {
      color: #aaaacc;
    }
    .overlay-value {
      color: #ffffff;
    }
    .overlay-icon {
      color: #aaaacc;
    }
    .overlay-budget.budget-warning .overlay-value {
      color: #ff6666;
    }
    .overlay-agi {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .agi-track {
      width: 80px;
      height: 8px;
      background: #222244;
      border: 1px solid #444466;
      border-radius: 2px;
      overflow: hidden;
    }
    .agi-fill {
      height: 100%;
      background: linear-gradient(90deg, #44cc44, #88ff44);
      transition: width 0.5s ease;
    }
    .overlay-right-sidebar {
      position: absolute;
      top: 40px;
      right: 0;
      width: 120px;
      padding: 8px;
      background: rgba(26, 26, 46, 0.85);
      border-left: 2px solid #333355;
      border-bottom: 2px solid #333355;
      border-radius: 0 0 0 4px;
    }
    .overlay-agents-header {
      font-size: 11px;
      color: #aaaacc;
      margin-bottom: 6px;
      border-bottom: 1px solid #333355;
      padding-bottom: 4px;
    }
    .agent-status-row {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 2px 0;
      font-size: 11px;
    }
    .agent-status-dot {
      display: inline-block;
      width: 6px;
      height: 6px;
      border-radius: 50%;
    }
    .agent-status-name {
      color: #ccccee;
    }
  `;
  document.head.appendChild(style);
}

/** Reset style injection state (for testing). */
export function _resetOverlayStyles(): void {
  overlayStylesInjected = false;
}

export class StreamOverlay {
  private container: HTMLDivElement;
  private budgetTicker: BudgetTicker;
  private agiProgressBar: AGIProgressBar;
  private viewerCount: ViewerCount;
  private topicDisplay: TopicDisplay;
  private agentStatusPanel: AgentStatusPanel;
  private unsubscribe: (() => void) | null = null;

  constructor(wsClient: WebSocketClient | null) {
    injectOverlayStyles();

    this.budgetTicker = new BudgetTicker();
    this.agiProgressBar = new AGIProgressBar();
    this.viewerCount = new ViewerCount();
    this.topicDisplay = new TopicDisplay();
    this.agentStatusPanel = new AgentStatusPanel();

    this.container = document.createElement("div");
    this.container.id = "stream-overlay";

    // Top bar with budget, AGI progress, viewers, topic
    const topBar = document.createElement("div");
    topBar.className = "overlay-top-bar";
    topBar.appendChild(this.budgetTicker.getElement());
    topBar.appendChild(this.agiProgressBar.getElement());
    topBar.appendChild(this.viewerCount.getElement());
    topBar.appendChild(this.topicDisplay.getElement());
    this.container.appendChild(topBar);

    // Right sidebar with agent statuses
    const sidebar = document.createElement("div");
    sidebar.className = "overlay-right-sidebar";
    sidebar.appendChild(this.agentStatusPanel.getElement());
    this.container.appendChild(sidebar);

    const gameDiv = document.getElementById("game");
    if (gameDiv) {
      gameDiv.appendChild(this.container);
    }

    if (wsClient) {
      this.unsubscribe = wsClient.onEvent((event) => this.handleEvent(event));
    }
  }

  getBudgetTicker(): BudgetTicker {
    return this.budgetTicker;
  }

  getAGIProgressBar(): AGIProgressBar {
    return this.agiProgressBar;
  }

  getViewerCount(): ViewerCount {
    return this.viewerCount;
  }

  getTopicDisplay(): TopicDisplay {
    return this.topicDisplay;
  }

  getAgentStatusPanel(): AgentStatusPanel {
    return this.agentStatusPanel;
  }

  getContainer(): HTMLDivElement {
    return this.container;
  }

  destroy(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    if (this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
  }

  private handleEvent(event: ServerEvent): void {
    switch (event.event_type) {
      case EventType.BUDGET_UPDATE:
        this.budgetTicker.update(
          event.data.total_spent as number,
          event.data.daily_limit as number,
        );
        break;
      case EventType.VIEWER_COUNT:
        this.viewerCount.update(event.data.count as number);
        break;
      case EventType.AGENT_SPEAK:
        this.agentStatusPanel.updateStatus(event.data.agent_id as string, "talking");
        if (event.data.topic) {
          this.topicDisplay.update(event.data.topic as string);
        }
        break;
      case EventType.AGENT_ACTION: {
        const action = event.data.action as string;
        if (action === "building" || action === "coding") {
          this.agentStatusPanel.updateStatus(event.data.agent_id as string, "building");
        } else {
          this.agentStatusPanel.updateStatus(event.data.agent_id as string, "idle");
        }
        break;
      }
    }
  }
}
