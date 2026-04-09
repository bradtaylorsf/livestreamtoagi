import { SpeechBubble, type BubbleTone } from "./SpeechBubble";
import { EventType, type ServerEvent } from "../types/events";
import type { WebSocketClient } from "../network/WebSocketClient";
import type { AgentSpriteManager } from "../agents/AgentSpriteManager";
import type { AudioManager } from "../audio/AudioManager";

const DEFAULT_DURATION_MS = 8000;
const BUBBLE_OFFSET_Y = -40;
/** How long to display an action description in the bubble before the next segment. */
const ACTION_DISPLAY_MS = 1500;

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
    .bubble-sarcastic .bubble-text::before { content: '\\201C'; }
    .bubble-sarcastic .bubble-text::after { content: '\\201D'; }
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

/** Remove common markdown formatting from text before displaying in a bubble. */
function stripMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/gs, "$1")  // **bold**
    .replace(/__(.+?)__/gs, "$1")       // __bold__
    .replace(/\*(.+?)\*/gs, "$1")       // *italic*
    .replace(/_(.+?)_/gs, "$1")         // _italic_
    .replace(/`(.+?)`/gs, "$1")         // `code`
    .replace(/^#{1,6}\s+/gm, "")        // ## headers
    .replace(/[*_]/g, "")               // stray asterisks/underscores
    .trim();
}

/** Remove [action]...[/action] tags from text. */
function stripActionTags(text: string): string {
  return text.replace(/\[action\].*?\[\/action\]/gis, "").replace(/\s+/g, " ").trim();
}

interface SegmentData {
  text: string;
  audio_url?: string;
  duration: number; // seconds
  action?: string;  // action description preceding this segment
}

/** Play an audio URL and resolve when it ends (or immediately on failure). */
function playAudioSegment(url: string, volume: number, fallbackMs: number): Promise<void> {
  return new Promise<void>((resolve) => {
    const audio = new Audio();
    audio.volume = Math.max(0, Math.min(1, volume));

    const cleanup = (fallback?: number) => {
      audio.src = "";
      if (fallback !== undefined) {
        setTimeout(resolve, fallback);
      } else {
        resolve();
      }
    };

    audio.addEventListener("ended", () => cleanup());
    audio.addEventListener("error", () => cleanup(fallbackMs));
    audio.src = url;
    audio.play().catch(() => cleanup(fallbackMs));
  });
}

/**
 * Orchestrates speech bubbles for all agents.
 * Creates DOM overlays positioned relative to the Phaser canvas.
 */
export class SpeechBubbleManager {
  private scene: Phaser.Scene;
  private agentSpriteManager: AgentSpriteManager;
  private audioManager: AudioManager | null;
  private bubbles: Map<string, SpeechBubble> = new Map();
  private container: HTMLDivElement;
  private unsubscribe: (() => void) | null = null;
  /** Monotonically increasing sequence number per agent, used to discard stale async results. */
  private pendingSeq: Map<string, number> = new Map();

  constructor(
    scene: Phaser.Scene,
    wsClient: WebSocketClient | null,
    agentSpriteManager: AgentSpriteManager,
    audioManager?: AudioManager | null,
  ) {
    this.scene = scene;
    this.agentSpriteManager = agentSpriteManager;
    this.audioManager = audioManager ?? null;

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
    const tone = (data.tone as BubbleTone) || "casual";

    // ── Segmented path ──────────────────────────────────────────
    // When the backend provides pre-split segments (one TTS file per dialogue
    // chunk between actions), play them sequentially with action text shown
    // between segments for visual context.
    const rawSegments = data.segments as SegmentData[] | undefined;
    if (rawSegments && rawSegments.length > 0) {
      const seq = (this.pendingSeq.get(agentId) ?? 0) + 1;
      this.pendingSeq.set(agentId, seq);
      void this.processSegments(agentId, rawSegments, tone, seq);
      return;
    }

    // ── Non-segmented path (backward compat) ───────────────────
    const rawText =
      (data.text as string) ||
      (data.dialogue as string) ||
      (data.content as string) ||
      "";
    // Strip markdown and action tags so the bubble shows clean readable text
    const text = stripMarkdown(stripActionTags(rawText));
    const audioUrl = data.audio_url as string | undefined;

    if (this.audioManager && audioUrl) {
      const seq = (this.pendingSeq.get(agentId) ?? 0) + 1;
      this.pendingSeq.set(agentId, seq);
      this.audioManager.getDuration(agentId, audioUrl, text).then((durationMs) => {
        if (this.pendingSeq.get(agentId) !== seq) return;
        this.showBubble(agentId, text, tone, durationMs);
      });
    } else {
      this.pendingSeq.set(agentId, (this.pendingSeq.get(agentId) ?? 0) + 1);
      const typewriterMs = text.length * SpeechBubble.CHAR_DELAY_MS;
      const duration =
        (data.duration as number) ||
        Math.max(DEFAULT_DURATION_MS, typewriterMs + 3500);
      this.showBubble(agentId, text, tone, duration);
    }
  }

  /**
   * Play segments sequentially, showing action text between them.
   *
   * Each segment's audio is played directly (bypassing AudioManager's queue)
   * so we can interleave action-display pauses between segments. Volume
   * settings are read from AudioManager when available.
   */
  private async processSegments(
    agentId: string,
    segments: SegmentData[],
    tone: BubbleTone,
    seq: number,
  ): Promise<void> {
    for (const seg of segments) {
      // Cancelled — a newer speak event arrived for this agent
      if (this.pendingSeq.get(agentId) !== seq) return;

      // Show action description briefly before this segment's dialogue
      if (seg.action) {
        const actionText = `[${seg.action}]`;
        this.showBubble(agentId, actionText, "casual", ACTION_DISPLAY_MS);
        await new Promise<void>((r) => setTimeout(r, ACTION_DISPLAY_MS));
        if (this.pendingSeq.get(agentId) !== seq) return;
      }

      // Compute display duration from audio duration (seconds → ms)
      const durationMs = seg.audio_url
        ? Math.round(seg.duration * 1000)
        : Math.max(DEFAULT_DURATION_MS, seg.text.length * SpeechBubble.CHAR_DELAY_MS + 3500);

      // Show the dialogue bubble — keep it up slightly longer than the audio
      this.showBubble(agentId, seg.text, tone, durationMs + 200);

      // Play audio directly, then advance to next segment
      if (seg.audio_url) {
        const vol = this.getSegmentVolume(agentId);
        await playAudioSegment(seg.audio_url, vol, durationMs);
      } else {
        await new Promise<void>((r) => setTimeout(r, durationMs));
      }
    }
  }

  /** Effective volume for direct segment audio playback, matching AudioManager settings. */
  private getSegmentVolume(agentId: string): number {
    if (!this.audioManager) return 0.8;
    const master = this.audioManager.getMasterVolume();
    const agentVol = this.audioManager.getAgentVolume(agentId);
    return Math.max(0, Math.min(1, master * agentVol));
  }

  private updateBubblePosition(agentId: string, bubble: SpeechBubble): void {
    const agentSprite = this.agentSpriteManager.getSprite(agentId);
    if (!agentSprite) return;

    const pos = agentSprite.getPosition();
    const camera = this.scene.cameras.main;
    const canvas = this.scene.game.canvas;

    // Phaser.Scale.FIT + CENTER_BOTH: the canvas is CSS-scaled and centered
    // inside the #game div. We must account for both the scale factor and the
    // canvas offset so the overlay aligns with the rendered sprites.
    const scaleX = canvas.clientWidth / canvas.width;
    const scaleY = canvas.clientHeight / canvas.height;
    const canvasOffsetX = canvas.offsetLeft;
    const canvasOffsetY = canvas.offsetTop;

    // World → canvas render-pixel
    const renderX =
      (pos.x - camera.worldView.x) *
      (camera.width / camera.worldView.width);
    const renderY =
      (pos.y - camera.worldView.y) *
      (camera.height / camera.worldView.height);

    // Canvas render-pixel → CSS pixel within the overlay div
    const screenX = canvasOffsetX + renderX * scaleX;
    const screenY = canvasOffsetY + renderY * scaleY + BUBBLE_OFFSET_Y;

    bubble.updatePosition(screenX, screenY);
  }
}
