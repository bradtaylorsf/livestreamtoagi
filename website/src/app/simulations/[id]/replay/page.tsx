"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { getReplayCues, type ReplayCue } from "@/lib/api";

// Phaser cannot run server-side; force a client-only mount so SSR doesn't
// try to evaluate the WebGL renderer.
const ReplayStage = dynamic(
  () => import("@/components/replay/ReplayStage"),
  { ssr: false, loading: () => null },
);

interface LoadedReplay {
  cues: ReplayCue[];
  agentRoster: string[];
}

function cueLoadErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "failed to load cues";
}

function exposeReplayError(message: string) {
  if (typeof window === "undefined") return;
  const w = window as unknown as Record<string, unknown>;
  w.__replayReady = false;
  w.__replayDone = false;
  w.__replayError = `Replay cue load failed: ${message}`;
}

export default function ReplayPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const renderMode = search?.get("renderMode") === "1";

  const [replay, setReplay] = useState<LoadedReplay | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Mark <html> so globals.css can hide global chrome (skip link, nav,
  // footer) from the DOM — not just visually occlude it. The render
  // pipeline scrapes the page snapshot, so chrome must be display:none,
  // not just behind a higher-z-index canvas.
  useEffect(() => {
    if (!renderMode) return;
    const root = document.documentElement;
    root.dataset.renderMode = "1";
    return () => {
      delete root.dataset.renderMode;
    };
  }, [renderMode]);

  useEffect(() => {
    let cancelled = false;
    if (!params?.id) return;
    setReplay(null);
    setError(null);
    if (typeof window !== "undefined") {
      const w = window as unknown as Record<string, unknown>;
      delete w.__replayError;
    }
    getReplayCues(params.id)
      .then((res) => {
        if (cancelled) return;
        setReplay({
          cues: res.cues,
          agentRoster: res.agent_roster ?? [],
        });
      })
      .catch((err) => {
        if (cancelled) return;
        const message = cueLoadErrorMessage(err);
        setError(message);
        exposeReplayError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [params?.id]);

  if (error) {
    return (
      <div
        data-testid="replay-error"
        style={{
          minHeight: renderMode ? "100vh" : undefined,
          padding: renderMode ? 24 : 12,
          background: renderMode ? "#020617" : "#7f1d1d",
          color: "#fee2e2",
          fontSize: 14,
        }}
      >
        Replay failed to load: {error}
      </div>
    );
  }

  if (replay === null) {
    return renderMode ? null : (
      <div style={{ padding: 24, color: "#94a3b8" }}>Loading replay…</div>
    );
  }

  return (
    <ReplayStage
      cues={replay.cues}
      agentRoster={replay.agentRoster}
      renderMode={renderMode}
    />
  );
}
