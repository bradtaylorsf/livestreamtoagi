"use client";

import { useEffect, useRef } from "react";
import type { ReplayCue } from "@/lib/api";
import { planReplay } from "./playback";

const STAGE_W = 1280;
const STAGE_H = 720;

interface ReplayStageProps {
  cues: ReplayCue[];
  renderMode: boolean;
}

/**
 * Mounts the headless office replay scene. Sets the global
 * ``__replayReady`` / ``__replayDone`` flags the render pipeline
 * (``core/video/render_pipeline.py``) polls for via Playwright.
 */
export default function ReplayStage({ cues, renderMode }: ReplayStageProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Game ref typed loosely because Phaser is dynamically imported.
  const gameRef = useRef<{ destroy: (removeCanvas: boolean) => void } | null>(
    null,
  );

  useEffect(() => {
    if (containerRef.current == null) return;
    let cancelled = false;
    const plan = planReplay(cues);

    if (typeof window !== "undefined") {
      const w = window as unknown as Record<string, unknown>;
      w.__replayReady = false;
      w.__replayDone = false;
      w.__replayHadBubble = false;
      w.__replayMountedAt = Date.now();
    }

    (async () => {
      const Phaser = (await import("phaser")).default;
      const { OfficeReplayScene, pickVisibleAgents } = await import(
        "./OfficeReplayScene"
      );
      if (cancelled) return;

      const visibleAgents = pickVisibleAgents(cues.map((c) => c.agent_id));

      const setReady = () => {
        if (typeof window !== "undefined") {
          (window as unknown as Record<string, unknown>).__replayReady = true;
        }
      };
      const setDone = () => {
        if (typeof window !== "undefined") {
          (window as unknown as Record<string, unknown>).__replayDone = true;
        }
      };

      const scene = new OfficeReplayScene({
        plan,
        visibleAgents,
        onReady: setReady,
        onDone: setDone,
      });

      const game = new Phaser.Game({
        type: Phaser.AUTO,
        parent: containerRef.current!,
        width: STAGE_W,
        height: STAGE_H,
        backgroundColor: "#000",
        pixelArt: true,
        scene,
      });
      gameRef.current = game;
    })().catch((err) => {
      // Surface load failures so the pipeline timeout has a console trace
      // to point at, rather than a silent ``__replayReady`` never flipping.
      console.error("[replay] failed to mount Phaser stage", err);
    });

    return () => {
      cancelled = true;
      if (gameRef.current) {
        try {
          gameRef.current.destroy(true);
        } catch {
          // best-effort cleanup
        }
        gameRef.current = null;
      }
    };
  }, [cues]);

  const wrapStyle: React.CSSProperties = renderMode
    ? {
        position: "fixed",
        inset: 0,
        background: "#000",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }
    : {
        position: "relative",
        margin: "0 auto",
        background: "#000",
      };

  return (
    <div style={wrapStyle} data-render-mode={renderMode ? "1" : "0"}>
      <div
        ref={containerRef}
        data-testid="replay-stage"
        style={{ width: STAGE_W, height: STAGE_H }}
        role="img"
        aria-label="Simulation replay"
      />
    </div>
  );
}
