"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Unhandled error:", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-xl px-4 py-24 text-center">
      <h2 className="font-pixel text-sm text-neon-magenta mb-6">
        Something went wrong
      </h2>
      <p className="text-foreground/70 mb-8">
        An unexpected error occurred. This has been logged for investigation.
      </p>
      <button
        onClick={reset}
        className="rounded border border-neon-cyan px-6 py-3 text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
      >
        Try Again
      </button>
    </div>
  );
}
