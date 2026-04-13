"use client";

import type { AssertionSummary } from "@/types/admin";

export default function AssertionSummaryBar({
  summary,
}: {
  summary: AssertionSummary;
}) {
  return (
    <div className="grid grid-cols-3 gap-4">
      {/* Passed */}
      <div className="rounded-lg border border-green-500/30 bg-green-500/10 p-4">
        <p className="text-xs text-green-400/70 mb-1">Passed</p>
        <p className="text-xl font-mono text-green-400 flex items-center gap-2">
          <span aria-hidden="true">&#10003;</span>
          {summary.passed ?? 0}
        </p>
      </div>

      {/* Failed */}
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
        <p className="text-xs text-red-400/70 mb-1">Failed</p>
        <p className="text-xl font-mono text-red-400 flex items-center gap-2">
          <span aria-hidden="true">&#10007;</span>
          {summary.failed ?? 0}
        </p>
      </div>

      {/* Warnings */}
      <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-4">
        <p className="text-xs text-yellow-400/70 mb-1">Warnings</p>
        <p className="text-xl font-mono text-yellow-400 flex items-center gap-2">
          <span aria-hidden="true">&#9888;</span>
          {summary.warnings ?? 0}
        </p>
      </div>
    </div>
  );
}
