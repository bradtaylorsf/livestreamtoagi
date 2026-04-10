"use client";

export default function StreamEmbed() {
  const streamUrl = process.env.NEXT_PUBLIC_STREAM_URL;

  if (streamUrl) {
    return (
      <div className="aspect-video w-full rounded border border-border overflow-hidden bg-surface">
        <iframe
          src={streamUrl}
          className="w-full h-full"
          allowFullScreen
          title="Live stream"
        />
      </div>
    );
  }

  return (
    <div className="aspect-video w-full rounded border border-border overflow-hidden bg-surface relative flex items-center justify-center">
      <div className="absolute inset-0 bg-gradient-to-br from-surface via-surface-light to-surface" />
      <div className="relative text-center px-4">
        <div className="font-pixel text-xs text-neon-cyan mb-2">
          PIXEL WORLD
        </div>
        <p className="text-sm text-foreground/50">
          Live world viewer launching soon. The agents are getting settled in.
        </p>
      </div>
    </div>
  );
}
