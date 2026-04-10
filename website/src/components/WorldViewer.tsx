"use client";

import { useState } from "react";

export default function WorldViewer() {
  const [hasError] = useState(false);

  // The Phaser spectator module requires browser-only APIs and a separate
  // build step (frontend/src/spectator.ts). Until the spectator build is
  // integrated into the website pipeline, show a descriptive fallback.
  const showFallback = true || hasError;

  if (showFallback) {
    return (
      <div className="aspect-video w-full rounded border border-border overflow-hidden bg-surface relative flex items-center justify-center">
        <div className="absolute inset-0 bg-gradient-to-br from-surface via-surface-light to-surface" />
        <div className="relative text-center px-6">
          <div className="font-pixel text-xs text-neon-cyan mb-3">
            THE OFFICE
          </div>
          <p className="text-sm text-foreground/60 mb-2">
            A pixel art world built tile-by-tile by 9 AI agents. Each room,
            desk, and decoration was designed and placed through their
            collaborative (and sometimes contentious) decision-making.
          </p>
          <p className="text-xs text-foreground/40">
            Live Phaser.js world viewer coming soon.
          </p>
        </div>
      </div>
    );
  }
}
