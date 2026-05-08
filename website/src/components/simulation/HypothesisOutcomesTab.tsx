"use client";

import { useState } from "react";
import {
  updateSimulationResearch,
  type PublicSimulationDetail,
} from "@/lib/api";

interface HypothesisOutcomesTabProps {
  sim: PublicSimulationDetail;
  simulationId: string;
  onUpdated?: (sim: PublicSimulationDetail) => void;
}

export function formatOutcomeValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function splitOutcomes(
  outcomes: Record<string, unknown> | null | undefined,
): { entries: [string, unknown][]; verdict: string } {
  if (!outcomes || typeof outcomes !== "object") {
    return { entries: [], verdict: "" };
  }
  const verdict =
    "verdict" in outcomes
      ? String((outcomes as Record<string, unknown>).verdict ?? "")
      : "";
  const entries = Object.entries(outcomes).filter(([key]) => key !== "verdict");
  return { entries, verdict };
}

interface OutcomesViewProps {
  outcomes: Record<string, unknown> | null | undefined;
}

export function OutcomesView({ outcomes }: OutcomesViewProps) {
  const { entries, verdict } = splitOutcomes(outcomes);
  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-foreground/80">Outcomes</h2>
        {entries.length === 0 && !verdict ? (
          <p className="text-sm text-foreground/40 italic">
            Outcomes will appear here once the simulation finishes and the
            evaluator records what happened.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {entries.map(([key, value]) => (
              <div
                key={key}
                className="rounded border border-border bg-surface-light p-3"
                data-testid={`outcome-card-${key}`}
              >
                <div className="text-xs text-foreground/50 mb-1">
                  {key.replace(/_/g, " ")}
                </div>
                <pre className="whitespace-pre-wrap font-mono text-xs text-foreground/80">
                  {formatOutcomeValue(value)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-foreground/80">
          Compare to hypothesis
        </h2>
        <div
          className="rounded border border-border bg-surface p-4 text-sm text-foreground/80"
          data-testid="hypothesis-verdict"
        >
          {verdict || "Pending — run the eval to populate the verdict."}
        </div>
      </section>
    </div>
  );
}

interface HypothesisEditorProps {
  value: string;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  savedAt: string | null;
  onChange: (next: string) => void;
  onSave: () => void;
}

export function HypothesisEditor({
  value,
  dirty,
  saving,
  error,
  savedAt,
  onChange,
  onSave,
}: HypothesisEditorProps) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-foreground/80">Hypothesis</h2>
      <p className="text-xs text-foreground/40">
        What did you expect to happen? You can refine this after watching the
        simulation.
      </p>
      <textarea
        aria-label="Hypothesis"
        data-testid="hypothesis-textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={5}
        className="w-full rounded border border-border bg-surface-light px-3 py-2 text-sm text-foreground"
        placeholder="My hypothesis for this run is..."
      />
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={!dirty || saving}
          onClick={onSave}
          data-testid="hypothesis-save"
          className="rounded bg-neon-cyan px-3 py-1.5 text-xs font-medium text-black hover:opacity-90 disabled:opacity-30"
        >
          {saving ? "Saving…" : "Save hypothesis"}
        </button>
        {savedAt && !dirty && !error && (
          <span className="text-xs text-foreground/50">Saved {savedAt}</span>
        )}
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </section>
  );
}

export default function HypothesisOutcomesTab({
  sim,
  simulationId,
  onUpdated,
}: HypothesisOutcomesTabProps) {
  const initial = sim.hypothesis ?? "";
  const [value, setValue] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const dirty = initial !== value;

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await updateSimulationResearch(simulationId, {
        hypothesis: value.trim(),
      });
      setSavedAt(new Date().toLocaleTimeString());
      if (onUpdated) {
        onUpdated({ ...sim, hypothesis: res.hypothesis });
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to save hypothesis";
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-8" data-testid="hypothesis-outcomes-tab">
      <HypothesisEditor
        value={value}
        dirty={dirty}
        saving={saving}
        error={error}
        savedAt={savedAt}
        onChange={setValue}
        onSave={handleSave}
      />
      <OutcomesView outcomes={sim.outcomes} />
    </div>
  );
}
