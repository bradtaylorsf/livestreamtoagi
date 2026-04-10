import type { WebSocketClient } from "../network/WebSocketClient";
import { EventType, type ManagementSeverity } from "../types/events";

/** Duration configs for each severity level. */
const LEVEL_DURATIONS: Record<number, number> = {
  1: 500,
  2: 3000,
  3: 5000,
};

/**
 * Management environmental effects system.
 * Renders CSS/HTML overlays on top of the Phaser canvas for
 * moderation events (warnings, interventions, broadcast interruptions).
 *
 * Levels:
 *   1 (notice): brief screen flash
 *   2 (warning): dim + text overlay + eye icon
 *   3 (intervention): content blocked overlay + audio cue
 *   4 (broadcast interruption): full screen, Management speaks
 *   5 (emergency): maintenance screen, blocks interaction
 */
export class ManagementEffects {
  private container: HTMLDivElement;
  private overlay: HTMLDivElement | null = null;
  private eyeIcon: HTMLImageElement | null = null;
  private activeLevel: ManagementSeverity | null = null;
  private dismissTimer: ReturnType<typeof setTimeout> | null = null;
  private audioCtx: AudioContext | null = null;
  private unsubscribers: Array<() => void> = [];

  constructor(wsClient: WebSocketClient) {
    // Create a container positioned over the #game div
    this.container = document.createElement("div");
    this.container.className = "management-container";
    this.injectStyles();

    const gameEl = document.getElementById("game");
    if (gameEl) {
      gameEl.style.position = "relative";
      gameEl.appendChild(this.container);
    } else {
      document.body.appendChild(this.container);
    }

    // Subscribe to management events
    this.unsubscribers.push(
      wsClient.onEvent((event) => {
        if (event.event_type === EventType.MANAGEMENT_WARNING) {
          const severity = (event.data.severity as ManagementSeverity) ?? 1;
          this.triggerEffect(severity, event.data);
        } else if (event.event_type === EventType.MANAGEMENT_INTERVENTION) {
          const severity = (event.data.severity as ManagementSeverity) ?? 3;
          this.triggerEffect(severity, event.data);
        }
      }),
    );
  }

  triggerEffect(level: ManagementSeverity, data: Record<string, unknown> = {}): void {
    this.clearEffect();
    this.activeLevel = level;

    switch (level) {
      case 1:
        this.showLevel1();
        break;
      case 2:
        this.showLevel2();
        break;
      case 3:
        this.showLevel3();
        break;
      case 4:
        this.showLevel4(data.message as string | undefined);
        break;
      case 5:
        this.showLevel5();
        break;
    }
  }

  clearEffect(): void {
    if (this.dismissTimer) {
      clearTimeout(this.dismissTimer);
      this.dismissTimer = null;
    }
    if (this.overlay) {
      this.overlay.remove();
      this.overlay = null;
    }
    if (this.eyeIcon) {
      this.eyeIcon.remove();
      this.eyeIcon = null;
    }
    this.activeLevel = null;
  }

  getActiveLevel(): ManagementSeverity | null {
    return this.activeLevel;
  }

  destroy(): void {
    this.clearEffect();
    for (const unsub of this.unsubscribers) {
      unsub();
    }
    this.unsubscribers = [];
    if (this.audioCtx) {
      this.audioCtx.close();
      this.audioCtx = null;
    }
    this.container.remove();
  }

  /** Level 1: Brief screen flash (opacity 0.2 black, 500ms). */
  private showLevel1(): void {
    this.overlay = this.createOverlay("management-overlay management-flash");
    this.autoDismiss(LEVEL_DURATIONS[1]);
  }

  /** Level 2: Dim screen + warning text + eye icon. */
  private showLevel2(): void {
    this.overlay = this.createOverlay("management-overlay management-dim");
    const text = document.createElement("div");
    text.className = "management-text management-glitch";
    text.textContent = "MANAGEMENT HAS NOTED THIS INTERACTION.";
    this.overlay.appendChild(text);
    this.showEye("small");
    this.autoDismiss(LEVEL_DURATIONS[2]);
  }

  /** Level 3: Content blocked overlay + audio cue + eye icon. */
  private showLevel3(): void {
    this.overlay = this.createOverlay("management-overlay management-block");
    const text = document.createElement("div");
    text.className = "management-text management-glitch";
    text.textContent = "CONTENT REVIEW IN PROGRESS";
    this.overlay.appendChild(text);
    this.showEye("small");
    this.playDeepTone();
    this.autoDismiss(LEVEL_DURATIONS[3]);
  }

  /** Level 4: Full screen, Management speaks to audience. */
  private showLevel4(message?: string): void {
    this.overlay = this.createOverlay("management-overlay management-fullscreen");
    this.overlay.style.pointerEvents = "auto";
    this.showEye("large");
    const text = document.createElement("div");
    text.className = "management-text management-glitch management-text-large";
    text.textContent = message ?? "MANAGEMENT IS ADDRESSING THE AUDIENCE.";
    this.overlay.appendChild(text);
    // Level 4 stays until cleared manually
  }

  /** Level 5: Maintenance screen, blocks all interaction. */
  private showLevel5(): void {
    this.overlay = this.createOverlay("management-overlay management-emergency");
    this.overlay.style.pointerEvents = "auto";
    const text = document.createElement("div");
    text.className = "management-text management-glitch management-text-large";
    text.textContent = "BROADCAST SUSPENDED. PLEASE STAND BY.";
    this.overlay.appendChild(text);
    this.showEye("large");
    // Level 5 stays until cleared manually
  }

  private createOverlay(className: string): HTMLDivElement {
    const div = document.createElement("div");
    div.className = className;
    this.container.appendChild(div);
    return div;
  }

  private showEye(size: "small" | "large"): void {
    this.eyeIcon = document.createElement("img");
    this.eyeIcon.src = "assets/ui/management_eye.png";
    this.eyeIcon.className = `management-eye management-eye-${size}`;
    this.eyeIcon.alt = "Management";
    // Fallback if image fails to load — show a text eye
    this.eyeIcon.onerror = () => {
      if (this.eyeIcon) {
        this.eyeIcon.style.display = "none";
        const fallback = document.createElement("div");
        fallback.className = `management-eye-fallback management-eye-${size}`;
        fallback.textContent = "\u{1F441}";
        this.container.appendChild(fallback);
      }
    };
    this.container.appendChild(this.eyeIcon);
  }

  private autoDismiss(ms: number): void {
    this.dismissTimer = setTimeout(() => {
      this.clearEffect();
    }, ms);
  }

  /** Play a low-frequency tone (~80Hz) for 500ms as an audio cue. */
  private playDeepTone(): void {
    try {
      if (!this.audioCtx) {
        this.audioCtx = new AudioContext();
      }
      if (this.audioCtx.state === "suspended") {
        this.audioCtx.resume();
      }
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();
      osc.type = "sine";
      osc.frequency.value = 80;
      gain.gain.value = 0.3;
      osc.connect(gain);
      gain.connect(this.audioCtx.destination);
      osc.start();
      osc.stop(this.audioCtx.currentTime + 0.5);
    } catch {
      // Audio not available — silently skip
    }
  }

  private injectStyles(): void {
    if (document.getElementById("management-effects-styles")) return;
    const style = document.createElement("style");
    style.id = "management-effects-styles";
    style.textContent = `
      .management-container {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 1000;
      }

      .management-overlay {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: none;
      }

      .management-flash {
        background: rgba(0, 0, 0, 0.2);
        animation: management-flash-anim 500ms ease-out forwards;
      }

      @keyframes management-flash-anim {
        0% { opacity: 1; }
        100% { opacity: 0; }
      }

      .management-dim {
        background: rgba(0, 0, 0, 0.4);
        animation: management-fade-in 300ms ease-out;
      }

      .management-block {
        background: rgba(0, 0, 0, 0.6);
        animation: management-fade-in 300ms ease-out;
      }

      .management-fullscreen {
        background: rgba(0, 0, 0, 0.85);
        animation: management-fade-in 500ms ease-out;
        flex-direction: column;
        gap: 24px;
      }

      .management-emergency {
        background: rgba(10, 0, 0, 0.95);
        animation: management-static 200ms steps(4) infinite;
        flex-direction: column;
        gap: 24px;
      }

      @keyframes management-fade-in {
        0% { opacity: 0; }
        100% { opacity: 1; }
      }

      @keyframes management-static {
        0% { background-color: rgba(10, 0, 0, 0.95); }
        25% { background-color: rgba(15, 0, 0, 0.93); }
        50% { background-color: rgba(8, 0, 0, 0.96); }
        75% { background-color: rgba(12, 0, 0, 0.94); }
      }

      .management-text {
        font-family: monospace;
        color: #ff4444;
        font-size: 18px;
        text-align: center;
        text-transform: uppercase;
        letter-spacing: 2px;
        text-shadow: 0 0 10px rgba(255, 68, 68, 0.5);
      }

      .management-text-large {
        font-size: 24px;
        letter-spacing: 4px;
      }

      @keyframes management-glitch-anim {
        0% { transform: translateX(0); }
        10% { transform: translateX(-2px); }
        20% { transform: translateX(2px); }
        30% { transform: translateX(-1px); }
        40% { transform: translateX(1px); }
        50% { transform: translateX(0); }
        100% { transform: translateX(0); }
      }

      .management-glitch {
        animation: management-glitch-anim 2s steps(1) infinite;
      }

      .management-eye {
        position: absolute;
        top: 16px;
        right: 16px;
        image-rendering: pixelated;
      }

      .management-eye-small {
        width: 32px;
        height: 32px;
      }

      .management-eye-large {
        width: 64px;
        height: 64px;
        position: relative;
        top: auto;
        right: auto;
      }

      .management-eye-fallback {
        position: absolute;
        top: 16px;
        right: 16px;
        font-size: 24px;
        line-height: 1;
      }

      .management-eye-fallback.management-eye-large {
        font-size: 48px;
        position: relative;
        top: auto;
        right: auto;
      }
    `;
    document.head.appendChild(style);
  }
}
