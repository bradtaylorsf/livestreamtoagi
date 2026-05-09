import type { PublicSimulationDetail } from "@/lib/api";

interface VideoPlayerProps {
  src: string | null | undefined;
  youtubeUrl?: string | null;
  renderStatus?: PublicSimulationDetail["video_render_status"];
  simulationStatus?: string | null;
  failureReason?: string | null;
  cancellationReason?: string | null;
}

function renderStateCopy({
  src,
  renderStatus,
  simulationStatus,
  failureReason,
  cancellationReason,
}: Pick<
  VideoPlayerProps,
  | "src"
  | "renderStatus"
  | "simulationStatus"
  | "failureReason"
  | "cancellationReason"
>): { state: string; title: string; detail: string } | null {
  if (simulationStatus === "cancelled") {
    return {
      state: "cancelled",
      title: "Video render cancelled",
      detail:
        cancellationReason ??
        "The simulation stopped before a video render could start.",
    };
  }

  if (renderStatus === "failed") {
    return {
      state: "failed",
      title: "Video render failed",
      detail: failureReason ?? "The replay could not be rendered.",
    };
  }

  if (renderStatus === "skipped") {
    return {
      state: "skipped",
      title: "Video render skipped",
      detail: failureReason ?? "There was not enough replay data to render.",
    };
  }

  if (renderStatus === "rendering") {
    return {
      state: "rendering",
      title: "Rendering video",
      detail: "The replay is being exported now.",
    };
  }

  if (renderStatus === "pending") {
    return {
      state: "pending",
      title: "Video render queued",
      detail: "The replay export is waiting to start.",
    };
  }

  if (renderStatus === "done" && !src) {
    return {
      state: "done-missing",
      title: "Video render finished",
      detail: "The backend did not return a playable video URL.",
    };
  }

  if (!src) {
    return {
      state: "none",
      title: "No video render yet",
      detail: "The replay export has not started.",
    };
  }

  return null;
}

export default function VideoPlayer({
  src,
  youtubeUrl,
  renderStatus,
  simulationStatus,
  failureReason,
  cancellationReason,
}: VideoPlayerProps) {
  const stateCopy = renderStateCopy({
    src,
    renderStatus,
    simulationStatus,
    failureReason,
    cancellationReason,
  });

  if (stateCopy) {
    return (
      <div
        data-testid="video-player-empty"
        data-state={stateCopy.state}
        className="rounded border border-border bg-surface-light px-4 py-3 text-sm text-foreground/50"
      >
        <p className="font-medium text-foreground/70">{stateCopy.title}</p>
        <p className="mt-1">{stateCopy.detail}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="video-player">
      <video
        controls
        preload="metadata"
        src={src ?? undefined}
        className="w-full rounded border border-border bg-black"
      >
        Your browser does not support the video tag.
      </video>
      {youtubeUrl && (
        <p className="text-xs text-foreground/60">
          Also on{" "}
          <a
            href={youtubeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-neon-cyan hover:underline"
          >
            YouTube
          </a>
        </p>
      )}
    </div>
  );
}
