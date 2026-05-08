interface VideoPlayerProps {
  src: string | null | undefined;
  youtubeUrl?: string | null;
}

export default function VideoPlayer({ src, youtubeUrl }: VideoPlayerProps) {
  if (!src) {
    return (
      <div
        data-testid="video-player-empty"
        className="rounded border border-border bg-surface-light px-4 py-3 text-sm text-foreground/50"
      >
        Video render not available yet.
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="video-player">
      <video
        controls
        preload="metadata"
        src={src}
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
