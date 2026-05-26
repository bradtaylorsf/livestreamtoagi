"use client";

import { useEffect, useState } from "react";
import {
  getBuildIntents,
  type BuildIntentSummary,
} from "@/lib/api";

interface Props {
  simulationId: string;
}

export default function ProposalsTab({ simulationId }: Props) {
  const [intents, setIntents] = useState<BuildIntentSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getBuildIntents(simulationId)
      .then((data) => {
        if (!cancelled) setIntents(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load build intents");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId]);

  if (error) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }
  if (loading) {
    return <p className="text-sm text-foreground/50">Loading proposals…</p>;
  }
  if (!intents || intents.length === 0) {
    return (
      <p
        className="text-sm text-foreground/50"
        data-testid="proposals-empty"
      >
        No structured build proposals were recorded for this simulation.
      </p>
    );
  }
  return (
    <div className="space-y-4" data-testid="proposals-tab">
      <p className="text-xs text-foreground/40">{intents.length} build intents</p>
      <ul className="space-y-3">
        {intents.map((intent, idx) => (
          <li
            key={String(intent.intent_id ?? idx)}
            className="rounded border border-border bg-surface p-4 space-y-2"
            data-testid="proposal-card"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm text-neon-cyan">
                {String(intent.structure_type ?? "build")}
              </span>
              <span className="text-xs text-foreground/40">
                {String(intent.agent_id ?? "—")}
              </span>
            </div>
            {Array.isArray(intent.motivation_chain) &&
              intent.motivation_chain.length > 0 && (
                <ol className="space-y-1 border-l border-border pl-3">
                  {intent.motivation_chain.map((link, lIdx) => (
                    <li
                      key={lIdx}
                      className="text-xs text-foreground/70"
                    >
                      <span className="text-foreground/40 mr-1">
                        {link.kind}:
                      </span>
                      {link.description ?? "(no description)"}
                    </li>
                  ))}
                </ol>
              )}
            {intent.args && Object.keys(intent.args).length > 0 && (
              <pre className="overflow-x-auto rounded bg-surface-light p-2 text-[10px] text-foreground/60">
                {JSON.stringify(intent.args, null, 2)}
              </pre>
            )}
            {intent.compiled_script && (
              <div className="text-xs text-foreground/60">
                <span className="font-medium text-foreground/80">
                  Compiled script:
                </span>{" "}
                {String(
                  (intent.compiled_script as Record<string, unknown>).summary ??
                    `${Object.keys(intent.compiled_script).length} fields`,
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
