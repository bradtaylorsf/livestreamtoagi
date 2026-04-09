/**
 * DevPanel — floating button to trigger an in-process test conversation.
 *
 * Calls POST /api/dev/simulate which runs a ConversationEngine inside the
 * FastAPI server process, sharing the same event_bus that WebSocket clients
 * connect to. This means speech bubbles and audio appear in the browser.
 */

// Empty string → relative URL, proxied through Vite dev server to the backend.
// Set VITE_API_URL explicitly only if serving the frontend from a different origin.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

let panelStylesInjected = false;

function injectPanelStyles(): void {
  if (panelStylesInjected) return;
  panelStylesInjected = true;

  const style = document.createElement("style");
  style.id = "dev-panel-styles";
  style.textContent = `
    #dev-panel {
      position: absolute;
      bottom: 12px;
      right: 12px;
      z-index: 50;
      display: flex;
      align-items: center;
      gap: 8px;
      font-family: monospace;
      font-size: 11px;
    }
    .dev-btn {
      background: rgba(26, 26, 46, 0.92);
      border: 1px solid #444466;
      color: #aaaacc;
      padding: 5px 10px;
      cursor: pointer;
      border-radius: 3px;
      font-family: monospace;
      font-size: 11px;
      line-height: 1.4;
      transition: background 0.15s;
    }
    .dev-btn:hover:not(:disabled) {
      background: rgba(50, 50, 80, 0.95);
      color: #ffffff;
      border-color: #6666aa;
    }
    .dev-btn:disabled {
      opacity: 0.5;
      cursor: default;
    }
    .dev-status {
      color: #88aacc;
      font-size: 10px;
      max-width: 160px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .dev-status.error {
      color: #cc6666;
    }
  `;
  document.head.appendChild(style);
}

/** Reset style injection state (for testing). */
export function _resetDevPanelStyles(): void {
  panelStylesInjected = false;
}

interface SimulateResponse {
  ok: boolean;
  task_id: string;
  agents: string[];
  turns: number;
}

export class DevPanel {
  private container: HTMLDivElement;
  private btn: HTMLButtonElement;
  private statusEl: HTMLSpanElement;
  private clearTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    injectPanelStyles();

    this.container = document.createElement("div");
    this.container.id = "dev-panel";

    this.btn = document.createElement("button");
    this.btn.className = "dev-btn";
    this.btn.textContent = "Test Conversation";
    this.btn.title = "Trigger an in-process conversation so speech bubbles appear in browser";

    this.statusEl = document.createElement("span");
    this.statusEl.className = "dev-status";

    this.btn.addEventListener("click", () => void this.triggerConversation());

    this.container.appendChild(this.btn);
    this.container.appendChild(this.statusEl);

    const gameDiv = document.getElementById("game");
    if (gameDiv) {
      gameDiv.appendChild(this.container);
    }
  }

  private async triggerConversation(): Promise<void> {
    if (this.clearTimer !== null) {
      clearTimeout(this.clearTimer);
      this.clearTimer = null;
    }
    this.btn.disabled = true;
    this.statusEl.className = "dev-status";
    this.statusEl.textContent = "Starting…";

    try {
      const res = await fetch(`${API_BASE}/api/dev/simulate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turns: 5, test_type: "freeform" }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const json = (await res.json()) as SimulateResponse;

      if (json.ok) {
        const agentCount = json.agents?.length ?? "?";
        this.statusEl.textContent = `Running — ${agentCount} agents, ${json.turns} turns`;

        // Re-enable after conversation should be done (roughly 90s max)
        this.clearTimer = setTimeout(() => {
          this.statusEl.textContent = "";
          this.btn.disabled = false;
          this.clearTimer = null;
        }, 90_000);
      } else {
        this.setError("Server error");
      }
    } catch (err) {
      this.setError(err instanceof Error ? err.message : "Failed");
    }
  }

  private setError(msg: string): void {
    this.statusEl.className = "dev-status error";
    this.statusEl.textContent = msg;
    this.btn.disabled = false;
  }

  destroy(): void {
    if (this.clearTimer !== null) {
      clearTimeout(this.clearTimer);
      this.clearTimer = null;
    }
    if (this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
  }
}
