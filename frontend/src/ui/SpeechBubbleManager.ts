import { SpeechBubble, type BubbleTone } from "./SpeechBubble";
import { EventType, type ServerEvent } from "../types/events";
import type { WebSocketClient } from "../network/WebSocketClient";
import type { AgentSpriteManager } from "../agents/AgentSpriteManager";

const DEFAULT_DURATION_MS = 5000;
const BUBBLE_OFFSET_Y = -40;

let stylesInjected = false;

function injectStyles(): void {
  if (stylesInjected) return;
  stylesInjected = true;

  const style = document.createElement("style");
  style.textContent = `
    #speech-bubbles {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      overflow: hidden;
      z-index: 5;
    }
    .speech-bubble {
      position: absolute;
      max-width: 200px;
      padding: 8px 12px;
      font-family: monospace;
      font-size: 12px;
      color: #1a1a2e;
      word-wrap: break-word;
      overflow-wrap: break-word;
      transform: translate(-50%, -100%);
      z-index: 5;
      opacity: 1;
    }
    .bubble-tail {
      position: absolute;
      bottom: -8px;
      left: 50%;
      transform: translateX(-50%);
      width: 0;
      height: 0;
      border-left: 8px solid transparent;
      border-right: 8px solid transparent;
      border-top: 8px solid #ffffff;
    }
    .bubble-casual {
      background: #ffffff;
      border-radius: 12px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    .bubble-urgent {
      background: #fff0f0;
      border: 2px solid #ff4444;
      border-radius: 4px;
      clip-path: polygon(
        0% 10%, 5% 0%, 15% 8%, 25% 0%, 35% 6%, 45% 0%, 55% 8%, 65% 0%,
        75% 6%, 85% 0%, 95% 8%, 100% 0%,
        100% 90%, 95% 100%, 85% 92%, 75% 100%, 65% 94%, 55% 100%,
        45% 92%, 35% 100%, 25% 94%, 15% 100%, 5% 92%, 0% 100%
      );
      padding: 14px 14px;
    }
    .bubble-urgent .bubble-tail { display: none; }
    .bubble-dramatic {
      background: #fffef0;
      border: 3px double #c9a227;
      border-radius: 8px;
      box-shadow: 0 2px 12px rgba(201,162,39,0.3);
    }
    .bubble-dramatic .bubble-tail {
      border-top-color: #fffef0;
    }
    .bubble-sarcastic {
      background: #f0f0f0;
      border: 2px solid #888888;
      border-radius: 2px;
    }
    .bubble-sarcastic .bubble-tail {
      border-top-color: #f0f0f0;
    }
    .bubble-alpha {
      background: none;
      font-size: 16px;
      padding: 0;
      text-align: center;
      max-width: none;
    }
  `;
  document.head.appendChild(style);
}

/** Reset style injection state (for testing). */
export function _resetStyles(): void {
  stylesInjected = false;
}

/**
 * Orchestrates speech bubbles for all agents.
 * Creates DOM overlays positioned relative to the Phaser canvas.
 */
export class SpeechBubbleManager {
  private scene: Phaser.Scene;
  private agentSpriteManager: AgentSpriteManager;
  private bubbles: Map<string, SpeechBubble> = new Map();
  private container: HTMLDivElement;
  private unsubscribe: (() => void) | null = null;

  constructor(
    scene: Phaser.Scene,
    wsClient: WebSocketClient | null,
    agentSpriteManager: AgentSpriteManager,
  ) {
    this.scene = scene;
    this.agentSpriteManager = agentSpriteManager;

    injectStyles();

    this.container = document.createElement("div");
    this.container.id = "speech-bubbles";
    const gameDiv = document.getElementById("game");
    if (gameDiv) {
      gameDiv.appendChild(this.container);
    }

    if (wsClient) {
      this.unsubscribe = wsClient.onEvent((event) => this.handleEvent(event));
    }
  }

  showBubble(
    agentId: string,
    text: string,
    tone: BubbleTone = "casual",
    duration: number = DEFAULT_DURATION_MS,
  ): void {
    // Management uses screen overlay (#49), not bubbles
    if (agentId === "management") return;

    // Dismiss existing bubble for this agent
    const existing = this.bubbles.get(agentId);
    if (existing) {
      existing.destroy();
      this.bubbles.delete(agentId);
    }

    const bubble = new SpeechBubble({
      agentId,
      text,
      tone,
      duration,
      container: this.container,
      isAlpha: agentId === "alpha",
    });

    this.bubbles.set(agentId, bubble);
    this.updateBubblePosition(agentId, bubble);
  }

  /** Called each frame from MainScene.update() to keep bubbles following sprites. */
  update(): void {
    for (const [agentId, bubble] of this.bubbles) {
      if (bubble.dismissed) {
        this.bubbles.delete(agentId);
        continue;
      }
      this.updateBubblePosition(agentId, bubble);
    }
  }

  getBubble(agentId: string): SpeechBubble | undefined {
    return this.bubbles.get(agentId);
  }

  getActiveBubbleCount(): number {
    return this.bubbles.size;
  }

  destroy(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
    }
    for (const bubble of this.bubbles.values()) {
      bubble.destroy();
    }
    this.bubbles.clear();
    if (this.container.parentNode) {
      this.container.parentNode.removeChild(this.container);
    }
  }

  private handleEvent(event: ServerEvent): void {
    if (event.event_type === EventType.AGENT_SPEAK) {
      this.handleSpeakEvent(event.data);
    }
  }

  private handleSpeakEvent(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const text = data.text as string;
    const tone = (data.tone as BubbleTone) || "casual";
    const duration = (data.duration as number) || DEFAULT_DURATION_MS;
    this.showBubble(agentId, text, tone, duration);
  }

  private updateBubblePosition(agentId: string, bubble: SpeechBubble): void {
    const agentSprite = this.agentSpriteManager.getSprite(agentId);
    if (!agentSprite) return;

    const pos = agentSprite.getPosition();
    const camera = this.scene.cameras.main;

    // Convert world coordinates to screen coordinates relative to overlay
    const screenX =
      (pos.x - camera.worldView.x) *
      (camera.width / camera.worldView.width);
    const screenY =
      (pos.y - camera.worldView.y) *
      (camera.height / camera.worldView.height) +
      BUBBLE_OFFSET_Y;

    bubble.updatePosition(screenX, screenY);
  }
}
