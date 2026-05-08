"use client";

import { useState } from "react";
import {
  updateSimulationResearch,
  type LearningEntry,
  type PublicSimulationDetail,
} from "@/lib/api";

interface LearningsTabProps {
  sim: PublicSimulationDetail;
  simulationId: string;
  onUpdated?: (sim: PublicSimulationDetail) => void;
}

function entryText(entry: LearningEntry): string {
  return String(entry.text ?? entry.body ?? "").trim();
}

export default function LearningsTab({
  sim,
  simulationId,
  onUpdated,
}: LearningsTabProps) {
  const learnings = sim.learnings ?? [];
  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    const text = draft.trim();
    if (!text) return;
    setSubmitting(true);
    setError(null);
    try {
      const newEntry: LearningEntry = {
        author: "user",
        text,
        created_at: new Date().toISOString(),
      };
      const next = [...learnings, newEntry];
      const res = await updateSimulationResearch(simulationId, {
        learnings: next,
      });
      setDraft("");
      if (onUpdated) {
        onUpdated({ ...sim, learnings: res.learnings ?? next });
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to save learning";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="learnings-tab">
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-foreground/80">Learnings</h2>
        {learnings.length === 0 ? (
          <p className="text-sm text-foreground/40 italic">
            No learnings recorded yet — capture insights as you watch.
          </p>
        ) : (
          <ul className="space-y-2">
            {learnings.map((entry, idx) => (
              <li
                key={idx}
                className="rounded border border-border bg-surface-light p-3"
              >
                <div className="flex items-center justify-between gap-3 mb-1">
                  <span className="text-xs text-foreground/60">
                    {entry.author ?? "user"}
                  </span>
                  <span className="text-xs text-foreground/40">
                    {entry.created_at
                      ? new Date(entry.created_at).toLocaleString()
                      : ""}
                  </span>
                </div>
                <p className="text-sm text-foreground/80 whitespace-pre-wrap">
                  {entryText(entry) || "(empty)"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <label
          htmlFor="learning-draft"
          className="block text-xs font-medium uppercase tracking-wide text-foreground/50"
        >
          Add learning
        </label>
        <textarea
          id="learning-draft"
          data-testid="learning-textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          placeholder="What did you learn from watching this run?"
          className="w-full rounded border border-border bg-surface-light px-3 py-2 text-sm text-foreground"
        />
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={submitting || !draft.trim()}
            onClick={handleAdd}
            data-testid="learning-add"
            className="rounded bg-neon-cyan px-3 py-1.5 text-xs font-medium text-black hover:opacity-90 disabled:opacity-30"
          >
            {submitting ? "Adding…" : "Add learning"}
          </button>
          {error && <span className="text-xs text-red-400">{error}</span>}
        </div>
      </section>
    </div>
  );
}
