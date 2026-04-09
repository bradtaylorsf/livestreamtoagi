import { EventType, type ServerEvent } from "../types/events";
import type { WebSocketClient } from "../network/WebSocketClient";

let overlayManagerStylesInjected = false;

function injectOverlayManagerStyles(): void {
  if (overlayManagerStylesInjected) return;
  overlayManagerStylesInjected = true;

  const style = document.createElement("style");
  style.id = "overlay-manager-styles";
  style.textContent = `
    .overlay-notification {
      position: absolute;
      pointer-events: none;
      font-family: monospace;
      font-size: 12px;
      color: #e0e0e0;
      z-index: 20;
      transition: opacity 0.5s ease;
    }
    .overlay-poll {
      bottom: 60px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(26, 26, 46, 0.92);
      border: 2px solid #444466;
      border-radius: 6px;
      padding: 12px 16px;
      min-width: 240px;
      max-width: 400px;
    }
    .overlay-poll-question {
      font-size: 13px;
      color: #ffffff;
      margin-bottom: 8px;
      font-weight: bold;
    }
    .overlay-poll-option {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 3px 0;
      font-size: 11px;
    }
    .overlay-poll-bar {
      height: 6px;
      background: #44cc44;
      border-radius: 2px;
      transition: width 0.3s ease;
    }
    .overlay-poll-bar-track {
      flex: 1;
      height: 6px;
      background: #222244;
      border-radius: 2px;
      overflow: hidden;
    }
    .overlay-poll-winner {
      color: #44cc44;
      font-weight: bold;
    }
    .overlay-toast {
      position: absolute;
      top: 50px;
      right: 130px;
      background: rgba(26, 26, 46, 0.92);
      border: 1px solid #444466;
      border-radius: 4px;
      padding: 8px 12px;
      font-size: 11px;
      color: #e0e0e0;
      max-width: 250px;
      z-index: 20;
      pointer-events: none;
      transition: opacity 0.5s ease;
    }
  `;
  document.head.appendChild(style);
}

/** Reset style injection state (for testing). */
export function _resetOverlayManagerStyles(): void {
  overlayManagerStylesInjected = false;
}

/**
 * DOM-based overlay manager for transient notifications: polls, artifacts, etc.
 * Sits on top of the game canvas alongside StreamOverlay.
 */
export class OverlayManager {
  private container: HTMLDivElement;
  private activePoll: HTMLDivElement | null = null;
  private pollDismissTimer: ReturnType<typeof setTimeout> | null = null;
  private toasts: HTMLDivElement[] = [];
  private unsubscribe: (() => void) | null = null;

  constructor(wsClient: WebSocketClient | null) {
    injectOverlayManagerStyles();

    this.container = document.createElement("div");
    this.container.id = "overlay-manager";
    this.container.style.cssText =
      "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:20;";

    const gameDiv = document.getElementById("game");
    if (gameDiv) {
      gameDiv.appendChild(this.container);
    }

    if (wsClient) {
      this.unsubscribe = wsClient.onEvent((event) => this.handleEvent(event));
    }
  }

  getContainer(): HTMLDivElement {
    return this.container;
  }

  destroy(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    if (this.pollDismissTimer) {
      clearTimeout(this.pollDismissTimer);
    }
    for (const toast of this.toasts) {
      toast.remove();
    }
    this.toasts = [];
    if (this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
  }

  private handleEvent(event: ServerEvent): void {
    switch (event.event_type) {
      case EventType.POLL_CREATED:
        this.showPoll(event.data);
        break;
      case EventType.POLL_RESULT:
        this.showPollResult(event.data);
        break;
      case EventType.ARTIFACT_CREATED:
        this.showArtifactToast(event.data);
        break;
    }
  }

  private showPoll(data: Record<string, unknown>): void {
    // Remove existing poll if any
    this.removePoll();

    const question = data.question as string;
    const options = data.options as string[];

    const poll = document.createElement("div");
    poll.className = "overlay-notification overlay-poll";

    const questionEl = document.createElement("div");
    questionEl.className = "overlay-poll-question";
    questionEl.textContent = question;
    poll.appendChild(questionEl);

    for (const option of options) {
      const row = document.createElement("div");
      row.className = "overlay-poll-option";
      row.textContent = option;
      poll.appendChild(row);
    }

    this.container.appendChild(poll);
    this.activePoll = poll;

    // Auto-dismiss after 30s
    this.pollDismissTimer = setTimeout(() => this.removePoll(), 30000);
  }

  private showPollResult(data: Record<string, unknown>): void {
    this.removePoll();

    const results = data.results as Record<string, number>;
    const winner = data.winner as string;

    const poll = document.createElement("div");
    poll.className = "overlay-notification overlay-poll";

    const header = document.createElement("div");
    header.className = "overlay-poll-question";
    header.textContent = "Poll Results";
    poll.appendChild(header);

    const totalVotes = Object.values(results).reduce((a, b) => a + b, 0) || 1;

    for (const [option, votes] of Object.entries(results)) {
      const row = document.createElement("div");
      row.className = "overlay-poll-option";
      if (option === winner) {
        row.classList.add("overlay-poll-winner");
      }

      const label = document.createElement("span");
      label.textContent = `${option} (${votes})`;
      row.appendChild(label);

      const track = document.createElement("div");
      track.className = "overlay-poll-bar-track";
      const bar = document.createElement("div");
      bar.className = "overlay-poll-bar";
      bar.style.width = `${(votes / totalVotes) * 100}%`;
      track.appendChild(bar);
      row.appendChild(track);

      poll.appendChild(row);
    }

    this.container.appendChild(poll);
    this.activePoll = poll;

    // Auto-dismiss after 10s
    this.pollDismissTimer = setTimeout(() => this.removePoll(), 10000);
  }

  private showArtifactToast(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const name = data.name as string;

    const toast = document.createElement("div");
    toast.className = "overlay-toast";
    toast.textContent = `New artifact: ${name} (by ${agentId})`;

    // Stack toasts below previous ones
    const offset = 50 + this.toasts.length * 40;
    toast.style.top = `${offset}px`;

    this.container.appendChild(toast);
    this.toasts.push(toast);

    // Auto-dismiss after 5s with fade
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => {
        toast.remove();
        const idx = this.toasts.indexOf(toast);
        if (idx >= 0) this.toasts.splice(idx, 1);
      }, 500);
    }, 5000);
  }

  private removePoll(): void {
    if (this.pollDismissTimer) {
      clearTimeout(this.pollDismissTimer);
      this.pollDismissTimer = null;
    }
    if (this.activePoll) {
      this.activePoll.remove();
      this.activePoll = null;
    }
  }
}
