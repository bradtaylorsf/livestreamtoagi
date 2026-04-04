"use client";

import { useState } from "react";

interface Props {
  config: Record<string, unknown>;
}

export default function ConfigViewer({ config }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border border-border bg-surface">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm text-foreground/70 hover:text-foreground transition-colors"
      >
        <span>Configuration Snapshot</span>
        <span className="text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <pre className="px-4 pb-4 text-xs text-foreground/60 font-mono overflow-x-auto max-h-96">
          {JSON.stringify(config, null, 2)}
        </pre>
      )}
    </div>
  );
}
