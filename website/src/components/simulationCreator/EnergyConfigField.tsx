"use client";

import {
  DEFAULT_LIFETIME_CAP_USD,
  MAX_AGENT_ENERGY,
  MAX_CADENCE,
  MIN_AGENT_ENERGY,
  MIN_CADENCE,
} from "./state";

interface EnergyConfigFieldProps {
  maxCost: number;
  onMaxCost: (n: number) => void;
  cadence: number;
  onCadence: (n: number) => void;
  energy: Record<string, number>;
  onEnergy: (agent: string, value: number) => void;
  activeAgents: string[];
  perSubmissionCap: number;
  remainingBudget: number | null;
}

export default function EnergyConfigField({
  maxCost,
  onMaxCost,
  cadence,
  onCadence,
  energy,
  onEnergy,
  activeAgents,
  perSubmissionCap,
  remainingBudget,
}: EnergyConfigFieldProps) {
  const upperBound = remainingBudget == null
    ? perSubmissionCap
    : Math.max(0, Math.min(perSubmissionCap, remainingBudget));
  return (
    <fieldset className="space-y-3">
      <legend className="font-pixel text-xs text-neon-cyan">
        ENERGY &amp; CONFIG
      </legend>
      <label className="block">
        <span className="block text-xs text-foreground/70 mb-1">
          Max cost ($) — capped at ${perSubmissionCap.toFixed(2)} per submission
          {remainingBudget != null && (
            <> · ${remainingBudget.toFixed(2)} remaining of ${DEFAULT_LIFETIME_CAP_USD.toFixed(2)} lifetime</>
          )}
        </span>
        <input
          type="number"
          step="0.05"
          min={0.01}
          max={upperBound || perSubmissionCap}
          value={maxCost}
          onChange={(e) => onMaxCost(parseFloat(e.target.value) || 0)}
          className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
          data-testid="config-max-cost"
        />
      </label>
      <label className="block">
        <span className="flex items-center justify-between text-xs text-foreground/70 mb-1">
          <span>Conversation cadence</span>
          <span className="text-foreground/50 font-mono">
            {cadence.toFixed(2)}×
          </span>
        </span>
        <input
          type="range"
          min={MIN_CADENCE}
          max={MAX_CADENCE}
          step={0.05}
          value={cadence}
          onChange={(e) => onCadence(parseFloat(e.target.value))}
          className="w-full"
          data-testid="config-cadence"
          aria-label="Conversation cadence"
        />
        <span className="flex justify-between text-[10px] text-foreground/40">
          <span>slower</span>
          <span>1.0×</span>
          <span>faster</span>
        </span>
      </label>
      {activeAgents.length > 0 && (
        <div>
          <p className="text-xs text-foreground/70 mb-1">Initial energy</p>
          <div className="space-y-2">
            {activeAgents.map((a) => {
              const value = energy[a] ?? 75;
              return (
                <label key={a} className="block">
                  <span className="flex items-center justify-between text-xs text-foreground/60 mb-1">
                    <span>{a}</span>
                    <span className="font-mono text-foreground/50">{value}</span>
                  </span>
                  <input
                    type="range"
                    min={MIN_AGENT_ENERGY}
                    max={MAX_AGENT_ENERGY}
                    value={value}
                    onChange={(e) => onEnergy(a, parseInt(e.target.value, 10))}
                    className="w-full"
                    data-testid={`config-energy-${a}`}
                    aria-label={`${a} initial energy`}
                  />
                </label>
              );
            })}
          </div>
        </div>
      )}
    </fieldset>
  );
}
