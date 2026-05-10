import type * as PhaserNS from "phaser";

const BUBBLE_BG = 0xffffff;
const BUBBLE_BORDER = 0x0b1020;
const NAME_COLOR = "#475569";
const TEXT_COLOR = "#0b1020";
const PADDING_X = 12;
const PADDING_Y = 10;
const NAME_HEIGHT = 18;
const MAX_LINES = 3;
const WORD_WRAP_WIDTH = 320;
const FONT_SIZE = "14px";
const FONT_FAMILY = "monospace";

/**
 * Speech bubble overlay anchored above an agent sprite.
 *
 * Renders a rounded rectangle background, the agent's display name in
 * small caps, and the cue text wrapped to ~320px with up to 3 lines (longer
 * text gets ellipsised). Positioning is handled by the caller via
 * ``setSpeakerPosition`` so the scene can clamp against the viewport.
 */
export class ReplaySpeechBubble {
  private container: PhaserNS.GameObjects.Container;
  private bg: PhaserNS.GameObjects.Graphics;
  private nameText: PhaserNS.GameObjects.Text;
  private bodyText: PhaserNS.GameObjects.Text;
  private bubbleW = 0;
  private bubbleH = 0;

  constructor(scene: PhaserNS.Scene, public readonly agentId: string) {
    this.container = scene.add.container(0, 0);
    this.container.setDepth(50);

    this.bg = scene.add.graphics();
    this.nameText = scene.add.text(PADDING_X, PADDING_Y, agentId.toUpperCase(), {
      color: NAME_COLOR,
      fontFamily: FONT_FAMILY,
      fontSize: "11px",
      fontStyle: "bold",
    });
    this.bodyText = scene.add.text(PADDING_X, PADDING_Y + NAME_HEIGHT, "", {
      color: TEXT_COLOR,
      fontFamily: FONT_FAMILY,
      fontSize: FONT_SIZE,
      wordWrap: { width: WORD_WRAP_WIDTH },
    });

    this.container.add([this.bg, this.nameText, this.bodyText]);
    this.container.setVisible(false);
  }

  /**
   * Update bubble text and re-measure. Truncates to MAX_LINES lines so
   * long replies don't push the bubble off the canvas.
   */
  setText(rawText: string): void {
    const truncated = truncateToLines(rawText, MAX_LINES, WORD_WRAP_WIDTH);
    this.bodyText.setText(truncated);
    this.redrawBackground();
  }

  /**
   * Position the bubble relative to a speaker world coordinate. ``x``/``y``
   * is the top-left of the bubble (caller is responsible for clamping
   * against viewport bounds via ``agentLayout.clampBubblePosition``).
   */
  setBubblePosition(x: number, y: number): void {
    this.container.setPosition(x, y);
  }

  setVisible(visible: boolean): void {
    this.container.setVisible(visible);
  }

  isVisible(): boolean {
    return this.container.visible;
  }

  getSize(): { w: number; h: number } {
    return { w: this.bubbleW, h: this.bubbleH };
  }

  destroy(): void {
    this.container.destroy();
  }

  private redrawBackground(): void {
    const bodyW = Math.max(this.bodyText.width, this.nameText.width);
    const bodyH = NAME_HEIGHT + this.bodyText.height;
    const w = Math.min(WORD_WRAP_WIDTH + PADDING_X * 2, bodyW + PADDING_X * 2);
    const h = bodyH + PADDING_Y * 2;
    this.bubbleW = w;
    this.bubbleH = h;

    this.bg.clear();
    this.bg.fillStyle(BUBBLE_BG, 0.96);
    this.bg.lineStyle(2, BUBBLE_BORDER, 1);
    this.bg.fillRoundedRect(0, 0, w, h, 8);
    this.bg.strokeRoundedRect(0, 0, w, h, 8);

    // Tiny tail at the bottom-centre — points at the speaker.
    const tailX = Math.max(12, Math.min(w - 12, w / 2));
    this.bg.fillStyle(BUBBLE_BG, 0.96);
    this.bg.fillTriangle(
      tailX - 6,
      h,
      tailX + 6,
      h,
      tailX,
      h + 8,
    );
    this.bg.lineStyle(2, BUBBLE_BORDER, 1);
    this.bg.lineBetween(tailX - 6, h, tailX, h + 8);
    this.bg.lineBetween(tailX + 6, h, tailX, h + 8);

    // Re-position children
    this.nameText.setPosition(PADDING_X, PADDING_Y);
    this.bodyText.setPosition(PADDING_X, PADDING_Y + NAME_HEIGHT);
  }
}

function truncateToLines(
  text: string,
  maxLines: number,
  approxLineWidth: number,
): string {
  // Rough char-per-line estimate at the configured font size — Phaser will
  // re-wrap on its own; this just keeps total length sane.
  const charsPerLine = Math.max(1, Math.floor(approxLineWidth / 8));
  const maxChars = charsPerLine * maxLines;
  if (text.length <= maxChars) return text;
  return text.slice(0, maxChars - 1).trimEnd() + "…";
}
