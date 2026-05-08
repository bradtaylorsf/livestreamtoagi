"use client";

interface AgentsFieldProps {
  scenarioAgents: string[];
  excludedAgents: string[];
  onToggle: (agent: string) => void;
}

export default function AgentsField({
  scenarioAgents,
  excludedAgents,
  onToggle,
}: AgentsFieldProps) {
  if (scenarioAgents.length === 0) {
    return (
      <fieldset className="space-y-2">
        <legend className="font-pixel text-xs text-neon-cyan">AGENTS</legend>
        <p className="text-xs text-foreground/50">
          This scenario does not declare a fixed agent list — all agents will
          participate.
        </p>
      </fieldset>
    );
  }
  return (
    <fieldset className="space-y-2">
      <legend className="font-pixel text-xs text-neon-cyan">AGENTS</legend>
      <p className="text-xs text-foreground/50">
        Uncheck to exclude an agent from this run.
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {scenarioAgents.map((agent) => {
          const checked = !excludedAgents.includes(agent);
          return (
            <label
              key={agent}
              className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-2 text-sm text-foreground/80 cursor-pointer hover:border-neon-cyan/40"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(agent)}
                data-testid={`agent-checkbox-${agent}`}
                className="rounded border-border"
              />
              <span>{agent}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
