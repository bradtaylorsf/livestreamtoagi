import Link from "next/link";
import type { AgentSummary } from "@/types/admin";

interface Props {
  agent: AgentSummary;
}

const TRAIT_KEYS = [
  "chattiness",
  "initiative",
  "interrupt_tendency",
  "eavesdrop_tendency",
  "closing_weight",
] as const;

const TRAIT_LABELS: Record<string, string> = {
  chattiness: "Chat",
  initiative: "Init",
  interrupt_tendency: "Intr",
  eavesdrop_tendency: "Eavs",
  closing_weight: "Clos",
};

export default function AgentCard({ agent }: Props) {
  return (
    <Link
      href={`/admin/agents/${agent.id}`}
      className="block rounded-lg border border-border bg-surface p-4 hover:bg-surface-light transition-colors"
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span
          className="inline-block h-3 w-3 rounded-full"
          style={{ backgroundColor: agent.color }}
        />
        <span className="font-medium text-foreground">{agent.display_name}</span>
        <span className="text-xs text-foreground/40">{agent.role}</span>
      </div>

      {/* Models */}
      <div className="text-xs text-foreground/50 mb-3 space-y-0.5">
        <div>Conv: {agent.conversation_model}</div>
        <div>Build: {agent.building_model}</div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-2 text-center mb-3">
        <div>
          <p className="text-xs text-foreground/40">Cost</p>
          <p className="text-sm font-mono text-foreground">
            ${parseFloat(agent.total_cost || "0").toFixed(4)}
          </p>
        </div>
        <div>
          <p className="text-xs text-foreground/40">Convos</p>
          <p className="text-sm font-mono text-foreground">
            {agent.conversation_count}
          </p>
        </div>
        <div>
          <p className="text-xs text-foreground/40">Artifacts</p>
          <p className="text-sm font-mono text-foreground">
            {agent.artifact_count}
          </p>
        </div>
      </div>

      {/* Mini personality bars */}
      <div className="space-y-1">
        {TRAIT_KEYS.map((key) => {
          const value = agent.personality_traits[key] ?? 0;
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="text-[10px] text-foreground/40 w-7">
                {TRAIT_LABELS[key]}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-border overflow-hidden">
                <div
                  className="h-full rounded-full bg-neon-cyan/60"
                  style={{ width: `${value * 100}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Link>
  );
}
