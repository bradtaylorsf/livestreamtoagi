import Phaser from "phaser";

/** Badge colors matching AgentSprite — used to color-match the delegation line. */
const AGENT_COLORS: Record<string, number> = {
  vera: 0x44cc44,
  rex: 0x4488ff,
  aurora: 0xff88cc,
  pixel: 0xffaa00,
  fork: 0xcc4444,
  sentinel: 0x888888,
  grok: 0xff44ff,
  alpha: 0xaaaa44,
};

const DOT_LENGTH = 4;
const GAP_LENGTH = 4;
const LINE_ALPHA = 0.5;

/**
 * Draws a dotted line between two sprites, updated each frame.
 * Used to visualize task delegation between a parent agent and Alpha.
 */
export class DelegationLink {
  private scene: Phaser.Scene;
  private graphics: Phaser.GameObjects.Graphics;
  private color: number;
  private updateHandler: () => void;
  private destroyed = false;

  constructor(
    scene: Phaser.Scene,
    private fromSprite: Phaser.GameObjects.Sprite,
    private toSprite: Phaser.GameObjects.Sprite,
    agentId: string,
  ) {
    this.scene = scene;
    this.color = AGENT_COLORS[agentId] ?? 0xffffff;
    this.graphics = scene.add.graphics();
    this.graphics.setDepth(1.5); // between furniture and sprites

    this.updateHandler = () => this.draw();
    scene.events.on("update", this.updateHandler);
    this.draw();
  }

  private draw(): void {
    if (this.destroyed) return;
    this.graphics.clear();

    const fromX = this.fromSprite.x;
    const fromY = this.fromSprite.y - this.fromSprite.height / 2;
    const toX = this.toSprite.x;
    const toY = this.toSprite.y - this.toSprite.height / 2;

    const dx = toX - fromX;
    const dy = toY - fromY;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 1) return;

    const nx = dx / dist;
    const ny = dy / dist;

    this.graphics.lineStyle(1, this.color, LINE_ALPHA);

    let traveled = 0;
    while (traveled < dist) {
      const segEnd = Math.min(traveled + DOT_LENGTH, dist);
      this.graphics.beginPath();
      this.graphics.moveTo(fromX + nx * traveled, fromY + ny * traveled);
      this.graphics.lineTo(fromX + nx * segEnd, fromY + ny * segEnd);
      this.graphics.strokePath();
      traveled = segEnd + GAP_LENGTH;
    }
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.scene.events.off("update", this.updateHandler);
    this.graphics.destroy();
  }
}
