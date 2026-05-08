"use client";

import type { PublicFaction } from "@/lib/api";
import { emptyFaction } from "./state";

interface FactionsFieldProps {
  factions: PublicFaction[];
  activeAgents: string[];
  onChange: (factions: PublicFaction[]) => void;
}

export default function FactionsField({
  factions,
  activeAgents,
  onChange,
}: FactionsFieldProps) {
  function update(idx: number, patch: Partial<PublicFaction>) {
    onChange(
      factions.map((f, i) => (i === idx ? { ...f, ...patch } : f)),
    );
  }
  function remove(idx: number) {
    onChange(factions.filter((_, i) => i !== idx));
  }
  function add() {
    onChange([...factions, emptyFaction()]);
  }
  function toggleMember(idx: number, agent: string) {
    const f = factions[idx];
    const members = f.members.includes(agent)
      ? f.members.filter((m) => m !== agent)
      : [...f.members, agent];
    update(idx, { members });
  }

  return (
    <fieldset className="space-y-3">
      <legend className="font-pixel text-xs text-neon-cyan">
        FACTIONS (OPTIONAL)
      </legend>
      <p className="text-xs text-foreground/50">
        Group agents into factions with shared goals. Leave empty for a
        free-form run.
      </p>
      {factions.map((f, idx) => (
        <div
          key={idx}
          data-testid={`faction-block-${idx}`}
          className="rounded border border-border bg-surface p-3 space-y-2"
        >
          <div className="flex items-start gap-2">
            <input
              type="text"
              value={f.name}
              onChange={(e) => update(idx, { name: e.target.value })}
              placeholder="Faction name"
              aria-label={`Faction ${idx + 1} name`}
              className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm text-foreground"
              data-testid={`faction-name-${idx}`}
            />
            <button
              type="button"
              onClick={() => remove(idx)}
              className="rounded border border-red-500/40 px-2 py-1 text-xs text-red-400 hover:bg-red-500/10"
              data-testid={`faction-remove-${idx}`}
            >
              Remove
            </button>
          </div>
          <div>
            <p className="text-xs text-foreground/60 mb-1">Members</p>
            <div className="flex flex-wrap gap-1">
              {activeAgents.length === 0 && (
                <span className="text-xs text-foreground/40">
                  No active agents — uncheck fewer agents above.
                </span>
              )}
              {activeAgents.map((a) => {
                const checked = f.members.includes(a);
                return (
                  <button
                    type="button"
                    key={a}
                    onClick={() => toggleMember(idx, a)}
                    aria-pressed={checked}
                    data-testid={`faction-${idx}-member-${a}`}
                    className={`rounded border px-2 py-0.5 text-xs ${
                      checked
                        ? "border-neon-cyan/50 bg-neon-cyan/10 text-neon-cyan"
                        : "border-border bg-surface-light text-foreground/70 hover:border-neon-cyan/30"
                    }`}
                  >
                    {a}
                  </button>
                );
              })}
            </div>
          </div>
          <textarea
            value={f.goal}
            onChange={(e) => update(idx, { goal: e.target.value })}
            placeholder="Shared goal — what is this faction trying to accomplish?"
            rows={2}
            aria-label={`Faction ${idx + 1} goal`}
            className="w-full rounded border border-border bg-background px-2 py-1 text-sm text-foreground"
            data-testid={`faction-goal-${idx}`}
          />
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="rounded border border-neon-cyan/40 bg-neon-cyan/10 px-3 py-1.5 text-xs font-medium text-neon-cyan hover:bg-neon-cyan/20 transition-colors"
        data-testid="faction-add"
      >
        + Add faction
      </button>
    </fieldset>
  );
}
