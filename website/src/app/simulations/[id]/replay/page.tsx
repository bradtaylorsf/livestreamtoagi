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

export default function ReplayPage() {
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const renderMode = search?.get("renderMode") === "1";

  const [cues, setCues] = useState<ReplayCue[] | null>(null);
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
    getReplayCues(params.id)
      .then((res) => {
        if (cancelled) return;
        setCues(res.cues);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "failed to load cues");
        // Empty cue list is still a valid render — the pipeline times out
        // on __replayReady, not on having no bubbles.
        setCues([]);
      });
    return () => {
      cancelled = true;
    };
  }, [params?.id]);

  if (cues === null) {
    return renderMode ? null : (
      <div style={{ padding: 24, color: "#94a3b8" }}>Loading replay…</div>
    );
  }

  return (
    <>
      {error && !renderMode && (
        <div
          style={{
            padding: 12,
            background: "#7f1d1d",
            color: "#fee2e2",
            fontSize: 14,
          }}
        >
          Replay loaded with errors: {error}
        </div>
      )}
      <ReplayStage cues={cues} renderMode={renderMode} />
    </>
  );
}
