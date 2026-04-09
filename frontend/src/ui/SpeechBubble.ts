export type BubbleTone = "casual" | "urgent" | "dramatic" | "sarcastic";

export interface SpeechBubbleOptions {
  agentId: string;
  text: string;
  tone: BubbleTone;
  duration: number;
  container: HTMLElement;
  isAlpha?: boolean;
}

/**
 * A single DOM-based speech bubble that appears above an agent sprite.
 * Supports typewriter text reveal and tone-based styling.
 */
export class SpeechBubble {
  static readonly CHAR_DELAY_MS = 30;
  static readonly FADE_DURATION_MS = 200;

  readonly agentId: string;
  private element: HTMLDivElement;
  private textElement: HTMLSpanElement;
  private typewriterTimer: ReturnType<typeof setInterval> | null = null;
  private dismissTimer: ReturnType<typeof setTimeout> | null = null;
  private charIndex = 0;
  private fullText: string;
  private _dismissed = false;

  constructor(options: SpeechBubbleOptions) {
    this.agentId = options.agentId;
    this.fullText = options.text;

    this.element = document.createElement("div");
    this.element.className = "speech-bubble";

    if (options.isAlpha) {
      this.element.classList.add("bubble-alpha");
      this.textElement = document.createElement("span");
      this.textElement.textContent = SpeechBubble.convertToEmoji(options.text);
      this.element.appendChild(this.textElement);
    } else {
      this.element.classList.add(`bubble-${options.tone}`);

      const tail = document.createElement("div");
      tail.className = "bubble-tail";
      this.element.appendChild(tail);

      this.textElement = document.createElement("span");
      this.textElement.className = "bubble-text";
      this.element.appendChild(this.textElement);

      this.startTypewriter();
    }

    options.container.appendChild(this.element);

    this.dismissTimer = setTimeout(() => {
      this.dismiss();
    }, options.duration);
  }

  updatePosition(x: number, y: number): void {
    this.element.style.left = `${x}px`;
    this.element.style.top = `${y}px`;
  }

  dismiss(): void {
    if (this._dismissed) return;
    this._dismissed = true;

    this.clearTimers();

    this.element.style.opacity = "0";
    this.element.style.transition = `opacity ${SpeechBubble.FADE_DURATION_MS}ms`;

    setTimeout(() => {
      this.destroy();
    }, SpeechBubble.FADE_DURATION_MS);
  }

  get dismissed(): boolean {
    return this._dismissed;
  }

  getElement(): HTMLDivElement {
    return this.element;
  }

  getDisplayedText(): string {
    return this.textElement.textContent || "";
  }

  destroy(): void {
    this.clearTimers();
    if (this.element.parentNode) {
      this.element.parentNode.removeChild(this.element);
    }
  }

  private startTypewriter(): void {
    this.charIndex = 0;
    this.textElement.textContent = "";
    this.typewriterTimer = setInterval(() => {
      if (this.charIndex < this.fullText.length) {
        this.charIndex++;
        this.textElement.textContent = this.fullText.slice(0, this.charIndex);
      } else {
        if (this.typewriterTimer) {
          clearInterval(this.typewriterTimer);
          this.typewriterTimer = null;
        }
      }
    }, SpeechBubble.CHAR_DELAY_MS);
  }

  private clearTimers(): void {
    if (this.typewriterTimer) {
      clearInterval(this.typewriterTimer);
      this.typewriterTimer = null;
    }
    if (this.dismissTimer) {
      clearTimeout(this.dismissTimer);
      this.dismissTimer = null;
    }
  }

  /** Convert text to small emoji symbols for Alpha's wolf sprite. */
  static convertToEmoji(text: string): string {
    const emojis = ["\u{1F43A}", "\u{1F4E6}", "\u{2728}", "\u{2757}", "\u{1F4A8}"];
    const count = Math.min(Math.ceil(text.length / 10), emojis.length);
    return emojis.slice(0, count).join("");
  }
}
