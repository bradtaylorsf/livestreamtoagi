"use client";

import { useState } from "react";
import type { AssertionResult } from "@/types/admin";

const STATUS_BADGE: Record<AssertionResult["status"], string> = {
  pass: "bg-green-500/20 text-green-400 border-green-500/40",
  fail: "bg-red-500/20 text-red-400 border-red-500/40",
  warning: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
};

function StatusBadge({ status }: { status: AssertionResult["status"] }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${STATUS_BADGE[status]}`}
    >
      {status}
    </span>
  );
}

function PhaseGroup({
  phaseName,
  assertions,
}: {
  phaseName: string;
  assertions: AssertionResult[];
}) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="border-b border-border last:border-0">
      {/* Phase header row */}
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between px-4 py-2 bg-surface-light text-left hover:bg-surface transition-colors"
        aria-expanded={expanded}
      >
        <span className="text-xs font-medium text-foreground/70 uppercase tracking-wide">
          {phaseName}
        </span>
        <span className="flex items-center gap-2 text-xs text-foreground/40">
          <span>{assertions.length} assertion{assertions.length !== 1 ? "s" : ""}</span>
          <span aria-hidden="true">{expanded ? "▲" : "▼"}</span>
        </span>
      </button>

      {/* Assertion rows */}
      {expanded && (
        <div>
          {assertions.map((assertion) => (
            <div
              key={assertion.id}
              className="border-t border-border px-4 py-3"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm text-foreground">
                      {assertion.assertion_name}
                    </span>
                    <StatusBadge status={assertion.status} />
                    <span className="text-xs text-foreground/40">
                      {assertion.severity}
                    </span>
                  </div>
                  {assertion.message && (
                    <p className="mt-1 text-xs text-foreground/60">
                      {assertion.message}
                    </p>
                  )}
                  {assertion.status === "fail" && (
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                      <div className="rounded border border-red-500/30 bg-red-500/5 p-2">
                        <span className="text-foreground/50">Expected:</span>
                        <pre className="mt-1 text-red-300 whitespace-pre-wrap break-all">
                          {assertion.expected}
                        </pre>
                      </div>
                      <div className="rounded border border-border bg-surface-light p-2">
                        <span className="text-foreground/50">Actual:</span>
                        <pre className="mt-1 text-foreground/70 whitespace-pre-wrap break-all">
                          {assertion.actual}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AssertionTable({
  results,
  severityFilter,
}: {
  results: AssertionResult[];
  severityFilter: string;
}) {
  const filtered =
    severityFilter === "all"
      ? results
      : results.filter((r) => r.severity === severityFilter);

  if (filtered.length === 0) {
    return (
      <p className="text-sm text-foreground/50 text-center py-8">
        No assertions match the current filter.
      </p>
    );
  }

  // Group by phase_name preserving insertion order
  const grouped = filtered.reduce<Record<string, AssertionResult[]>>(
    (acc, result) => {
      const phase = result.phase_name || "Unknown Phase";
      if (!acc[phase]) acc[phase] = [];
      acc[phase].push(result);
      return acc;
    },
    {},
  );

  return (
    <div className="rounded-lg border border-border bg-surface overflow-x-auto">
      {Object.entries(grouped).map(([phaseName, assertions]) => (
        <PhaseGroup
          key={phaseName}
          phaseName={phaseName}
          assertions={assertions}
        />
      ))}
    </div>
  );
}
