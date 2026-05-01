"use client";

import { useState } from "react";
import type { CoreMemoryVersion } from "@/types/admin";

interface Props {
  versions: CoreMemoryVersion[];
}

function computeDiff(
  oldText: string,
  newText: string,
): { type: "same" | "added" | "removed"; line: string }[] {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const result: { type: "same" | "added" | "removed"; line: string }[] = [];

  const oldSet = new Set(oldLines);
  const newSet = new Set(newLines);

  // Show removed lines first, then new lines with matches
  let oi = 0;
  let ni = 0;
  while (oi < oldLines.length || ni < newLines.length) {
    if (oi < oldLines.length && ni < newLines.length) {
      if (oldLines[oi] === newLines[ni]) {
        result.push({ type: "same", line: oldLines[oi] });
        oi++;
        ni++;
      } else if (!newSet.has(oldLines[oi])) {
        result.push({ type: "removed", line: oldLines[oi] });
        oi++;
      } else if (!oldSet.has(newLines[ni])) {
        result.push({ type: "added", line: newLines[ni] });
        ni++;
      } else {
        result.push({ type: "removed", line: oldLines[oi] });
        oi++;
      }
    } else if (oi < oldLines.length) {
      result.push({ type: "removed", line: oldLines[oi] });
      oi++;
    } else {
      result.push({ type: "added", line: newLines[ni] });
      ni++;
    }
  }

  return result;
}

export default function MemoryDiffView({ versions }: Props) {
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);

  if (versions.length === 0) {
    return (
      <p className="text-sm text-foreground/50">No version history available.</p>
    );
  }

  return (
    <div className="space-y-2">
      {versions.map((version, index) => {
        const isExpanded = expandedVersion === version.version;
        const prevVersion = index < versions.length - 1 ? versions[index + 1] : null;

        return (
          <div
            key={version.version}
            className="rounded border border-border bg-surface"
          >
            <button
              onClick={() =>
                setExpandedVersion(isExpanded ? null : version.version)
              }
              className="w-full flex items-center justify-between px-3 py-2 text-sm text-left hover:bg-surface-light transition-colors"
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-foreground/50">
                  v{version.version}
                </span>
                <span className="text-xs text-foreground/40">
                  {new Date(version.changed_at).toLocaleString()}
                </span>
                {version.change_reason && (
                  <span className="text-xs text-foreground/50">
                    — {version.change_reason}
                  </span>
                )}
              </div>
              <span className="text-foreground/30">
                {isExpanded ? "▲" : "▼"}
              </span>
            </button>
            {isExpanded && (
              <div className="border-t border-border px-3 py-2 overflow-x-auto">
                {prevVersion ? (
                  <pre className="text-xs font-mono leading-relaxed">
                    {computeDiff(prevVersion.content, version.content).map(
                      (line, i) => (
                        <div
                          key={i}
                          className={
                            line.type === "added"
                              ? "text-green-400 bg-green-500/10"
                              : line.type === "removed"
                                ? "text-red-400 bg-red-500/10"
                                : "text-foreground/60"
                          }
                        >
                          {line.type === "added"
                            ? "+"
                            : line.type === "removed"
                              ? "-"
                              : " "}
                          {" "}
                          {line.line}
                        </div>
                      ),
                    )}
                  </pre>
                ) : (
                  <pre className="text-xs font-mono text-foreground/60 leading-relaxed">
                    {version.content}
                  </pre>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
