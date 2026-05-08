import Link from "next/link";
import { getAgentData } from "@/lib/agent-data";

interface AgentsTabProps {
  simulationId: string;
  agents: string[];
}

export default function AgentsTab({ simulationId, agents }: AgentsTabProps) {
  if (agents.length === 0) {
    return (
      <p className="text-sm text-foreground/50">
        No agents participated in this simulation.
      </p>
    );
  }

  return (
    <div className="space-y-4" data-testid="agents-tab">
      <p className="text-xs text-foreground/40">
        {agents.length} agent{agents.length === 1 ? "" : "s"} participated. Click an
        agent to explore their memory, journal, and conversations within this run.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {agents.map((agentId) => {
          const data = getAgentData(agentId);
          return (
            <Link
              key={agentId}
              href={`/simulations/${simulationId}/agents/${agentId}`}
              className="block rounded border border-border bg-surface p-4 transition-colors hover:border-neon-cyan/40 hover:bg-surface-light"
            >
              <div className="flex items-center gap-3">
                <span
                  className="inline-block h-3 w-3 rounded-full"
                  style={{ backgroundColor: data?.color ?? "#666" }}
                  aria-hidden
                />
                <span className="font-medium text-foreground capitalize">
                  {data?.name ?? agentId}
                </span>
              </div>
              {data?.role && (
                <div className="mt-2 text-xs text-foreground/50">{data.role}</div>
              )}
              {data?.tagline && (
                <div className="mt-1 text-xs text-foreground/40 italic">
                  {data.tagline}
                </div>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
