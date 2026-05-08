"use client";

import { useEffect, useRef } from "react";
import type { ReplayCue } from "@/lib/api";
import {
  planReplay,
  type BubblePlan,
  type ReplayPlan,
} from "./playback";

const STAGE_W = 1280;
const STAGE_H = 720;

const KNOWN_AGENTS = [
  "vera",
  "rex",
  "aurora",
  "pixel",
  "fork",
  "sentinel",
  "grok",
  "management",
  "alpha",
];

const AGENT_COLORS_HEX: Record<string, number> = {
  vera: 0x7dd3fc,
  rex: 0xfca5a5,
  aurora: 0xfcd34d,
  pixel: 0x86efac,
  fork: 0xc4b5fd,
  sentinel: 0xfdba74,
  grok: 0xf0abfc,
  management: 0x94a3b8,
  alpha: 0xa3a3a3,
};

interface AgentSlot {
  id: string;
  x: number;
  y: number;
  color: number;
}

export function buildSlots(cues: ReplayCue[]): AgentSlot[] {
  const seen = new Set<string>();
  const order: string[] = [];
  for (const a of KNOWN_AGENTS) {
    if (cues.some((c) => c.agent_id === a)) {
      seen.add(a);
      order.push(a);
    }
  }
  for (const c of cues) {
    if (!seen.has(c.agent_id)) {
      seen.add(c.agent_id);
      order.push(c.agent_id);
    }
  }
  if (order.length === 0) return [];
  const cols = Math.min(3, order.length);
  const rows = Math.ceil(order.length / cols);
  const dx = STAGE_W / (cols + 1);
  const dy = STAGE_H / (rows + 1);
  return order.map((id, idx) => {
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    return {
      id,
      x: dx * (col + 1),
      y: dy * (row + 1),
      color: AGENT_COLORS_HEX[id] ?? 0xcbd5e1,
    };
  });
}

interface ReplayStageProps {
  cues: ReplayCue[];
  renderMode: boolean;
}

/**
 * Headless replay stage. Mounts a Phaser scene that paints agent tiles
 * and a single speech bubble synced to the cue timeline. Sets the global
 * ``__replayReady`` / ``__replayDone`` flags the render pipeline polls
 * for in ``core/video/render_pipeline.py``.
 */
export default function ReplayStage({ cues, renderMode }: ReplayStageProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  // We hold the Phaser game in a ref so the cleanup effect can destroy it.
  // Typed loosely because Phaser is a dynamic import.
  const gameRef = useRef<{ destroy: (removeCanvas: boolean) => void } | null>(
    null,
  );

  useEffect(() => {
    if (containerRef.current == null) return;
    let cancelled = false;
    const plan: ReplayPlan = planReplay(cues);
    const slots = buildSlots(cues);

    (async () => {
      const Phaser = (await import("phaser")).default;
      if (cancelled) return;

      class ReplayScene extends Phaser.Scene {
        startMs = 0;
        bubbleText?: Phaser.GameObjects.Text;
        bubbleBg?: Phaser.GameObjects.Rectangle;
        labelText?: Phaser.GameObjects.Text;

        constructor() {
          super("replay");
        }

        create() {
          this.cameras.main.setBackgroundColor("#0b1020");

          for (const slot of slots) {
            this.add.rectangle(slot.x, slot.y, 72, 72, slot.color);
            this.add
              .text(slot.x, slot.y, slot.id.toUpperCase().slice(0, 4), {
                color: "#0b1020",
                fontFamily: "monospace",
                fontSize: "16px",
              })
              .setOrigin(0.5);
          }

          this.bubbleBg = this.add
            .rectangle(0, 0, 320, 80, 0xffffff)
            .setOrigin(0, 0)
            .setVisible(false);
          this.labelText = this.add
            .text(0, 0, "", {
              color: "#475569",
              fontFamily: "monospace",
              fontSize: "12px",
              fontStyle: "bold",
            })
            .setVisible(false);
          this.bubbleText = this.add
            .text(0, 0, "", {
              color: "#0b1020",
              fontFamily: "sans-serif",
              fontSize: "16px",
              wordWrap: { width: 360 },
            })
            .setVisible(false);

          this.startMs = Date.now();

          // Flag readiness only once the scene has completed a frame.
          this.events.once(Phaser.Scenes.Events.POST_UPDATE, () => {
            if (typeof window !== "undefined") {
              (window as unknown as Record<string, unknown>).__replayReady =
                true;
            }
          });
        }

        update() {
          const elapsed = Date.now() - this.startMs;
          const active: BubblePlan | undefined = plan.bubbles.find(
            (b) => b.start_ms <= elapsed && elapsed < b.end_ms,
          );
          if (active && this.bubbleBg && this.bubbleText && this.labelText) {
            const slot = slots.find((s) => s.id === active.agent_id);
            const ax = slot ? Math.max(20, slot.x - 200) : 40;
            const ay = slot ? Math.max(20, slot.y - 160) : 40;
            this.bubbleBg.setPosition(ax, ay).setVisible(true);
            this.labelText
              .setText(active.agent_id.toUpperCase())
              .setPosition(ax + 12, ay + 8)
              .setVisible(true);
            this.bubbleText
              .setText(active.text)
              .setPosition(ax + 12, ay + 28)
              .setVisible(true);
            const h = Math.max(80, this.bubbleText.height + 48);
            this.bubbleBg.setSize(380, h);
          } else if (this.bubbleBg && this.bubbleText && this.labelText) {
            this.bubbleBg.setVisible(false);
            this.bubbleText.setVisible(false);
            this.labelText.setVisible(false);
          }

          if (
            elapsed >= plan.done_at_ms &&
            typeof window !== "undefined" &&
            (window as unknown as Record<string, unknown>).__replayDone !== true
          ) {
            (window as unknown as Record<string, unknown>).__replayDone = true;
          }
        }
      }

      const game = new Phaser.Game({
        type: Phaser.AUTO,
        parent: containerRef.current!,
        width: STAGE_W,
        height: STAGE_H,
        backgroundColor: "#0b1020",
        scene: ReplayScene,
      });
      gameRef.current = game;
    })().catch((err) => {
      // Surface load failures to the console so a missing Phaser package
      // doesn't silently leave __replayReady false (the pipeline will time
      // out on its own; this just makes diagnosis easier).
      // eslint-disable-next-line no-console
      console.error("[replay] failed to mount Phaser stage", err);
    });

    return () => {
      cancelled = true;
      if (gameRef.current) {
        try {
          gameRef.current.destroy(true);
        } catch {
          // ignore — best effort cleanup
        }
        gameRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
