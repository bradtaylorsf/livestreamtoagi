import Phaser from "phaser";

/** Placeholder scene — renders a loading screen until the real world is built. */
class BootScene extends Phaser.Scene {
  constructor() {
    super({ key: "BootScene" });
  }

  create(): void {
    this.cameras.main.setBackgroundColor("#1a1a2e");
    this.add
      .text(
        this.cameras.main.centerX,
        this.cameras.main.centerY,
        "Livestream to AGI\nInitializing...",
        {
          fontFamily: "monospace",
          fontSize: "18px",
          color: "#00ffcc",
          align: "center",
        },
      )
      .setOrigin(0.5);
  }
}

const config: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  width: 960,
  height: 540,
  parent: "game",
  pixelArt: true,
  scene: [BootScene],
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
};

new Phaser.Game(config);
