"use client";

import { useEffect, useState } from "react";
import type { PublicMemorySeed, PublicSimulation } from "@/lib/api";
import { getSimulations } from "@/lib/api";
import { validateMemorySeedJson } from "./validation";

interface MemorySeedFieldProps {
  value: PublicMemorySeed;
  rawJson: string;
  onChange: (seed: PublicMemorySeed, rawJson: string) => void;
}

export default function MemorySeedField({
  value,
  rawJson,
  onChange,
}: MemorySeedFieldProps) {
  const [completedSims, setCompletedSims] = useState<PublicSimulation[]>([]);
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    if (value.mode !== "inherit") return;
    let cancelled = false;
    getSimulations({ status: "completed", limit: 50 })
      .then((res) => {
        if (cancelled) return;
        setCompletedSims(res.items);
      })
      .catch(() => {
        // Non-fatal — picker just stays empty.
      });
    return () => {
      cancelled = true;
    };
  }, [value.mode]);

  function setMode(mode: PublicMemorySeed["mode"]) {
    if (mode === "none") onChange({ mode: "none" }, rawJson);
    else if (mode === "inherit") onChange({ mode: "inherit", simulation_id: "" }, rawJson);
    else onChange({ mode: "custom", data: null }, rawJson);
    setJsonError(null);
  }

  function setInheritSim(id: string) {
    onChange({ mode: "inherit", simulation_id: id }, rawJson);
  }

  function setRawJson(next: string) {
    onChange(value, next);
  }

  function handleJsonBlur() {
    if (value.mode !== "custom") return;
    const r = validateMemorySeedJson(rawJson);
    setJsonError(r.ok ? null : r.error ?? null);
  }

  return (
    <fieldset className="space-y-2">
      <legend className="font-pixel text-xs text-neon-cyan">MEMORY SEED</legend>
      <div className="flex flex-wrap gap-3 text-sm">
        {(["none", "inherit", "custom"] as const).map((mode) => (
          <label key={mode} className="flex items-center gap-2 text-foreground/80">
            <input
              type="radio"
              name="memory-seed-mode"
              checked={value.mode === mode}
              onChange={() => setMode(mode)}
              data-testid={`memory-seed-mode-${mode}`}
            />
            <span>
              {mode === "none" && "None"}
              {mode === "inherit" && "Inherit from sim"}
              {mode === "custom" && "Custom JSON"}
            </span>
          </label>
        ))}
      </div>
      {value.mode === "inherit" && (
        <div>
          <label
            htmlFor="memory-seed-inherit-sim"
            className="block text-xs text-foreground/60 mb-1"
          >
            Inherit memory from
          </label>
          <select
            id="memory-seed-inherit-sim"
            value={value.simulation_id}
            onChange={(e) => setInheritSim(e.target.value)}
            className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
            data-testid="memory-seed-inherit-select"
          >
            <option value="">Select a completed simulation…</option>
            {completedSims.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {s.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </div>
      )}
      {value.mode === "custom" && (
        <div>
          <textarea
            value={rawJson}
            onChange={(e) => setRawJson(e.target.value)}
            onBlur={handleJsonBlur}
            rows={6}
            placeholder='{"vera": [{"content": "..."}]}'
            aria-label="Custom memory seed JSON"
            className="w-full rounded border border-border bg-background px-3 py-2 font-mono text-xs text-foreground"
            data-testid="memory-seed-custom-json"
          />
          {jsonError && (
            <p className="mt-1 text-xs text-red-400" data-testid="memory-seed-json-error">
              {jsonError}
            </p>
          )}
        </div>
      )}
    </fieldset>
  );
}
