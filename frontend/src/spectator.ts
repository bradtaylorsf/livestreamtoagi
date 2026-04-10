/**
 * Spectator mode entry point for embedding the Phaser world in the website.
 * Creates a read-only Phaser game instance with no player controls.
 *
 * Usage:
 *   import { createSpectatorGame } from './spectator';
 *   const game = createSpectatorGame(containerElement, { width: 800, height: 450 });
 *   // Later: game.destroy(true);
 */
import Phaser from "phaser";
import { MainScene } from "./scenes/MainScene";

export interface SpectatorConfig {
  width?: number;
  height?: number;
  wsUrl?: string;
}

export function createSpectatorGame(
  container: HTMLElement,
  config: SpectatorConfig = {},
): Phaser.Game {
  const { width = 1280, height = 720 } = config;

  const gameConfig: Phaser.Types.Core.GameConfig = {
    type: Phaser.AUTO,
    width,
    height,
    parent: container,
    pixelArt: true,
    scene: [MainScene],
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    input: {
      // Disable keyboard/mouse input for spectator mode
      keyboard: false,
      mouse: { preventDefaultWheel: false },
    },
    audio: {
      noAudio: true,
    },
  };

  return new Phaser.Game(gameConfig);
}
