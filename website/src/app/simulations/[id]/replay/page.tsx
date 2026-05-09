"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { getReplayCues, type ReplayCue } from "@/lib/api";

// Phaser cannot run server-side; force client-only mount.
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
        // No cues is still valid — render an empty stage so the pipeline
        // can finish its 1s minimum playback rather than time out.
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
