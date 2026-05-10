import Link from "next/link";
import type { PublicSimulationDetail } from "@/lib/api";
import AgentList from "./AgentList";
import SummaryGrid from "./SummaryGrid";
import VideoPlayer from "./VideoPlayer";

interface OverviewTabProps {
  sim: PublicSimulationDetail;
  simulationId: string;
  onJumpToHypothesis?: () => void;
}

function configStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export default function OverviewTab({
  sim,
  simulationId,
  onJumpToHypothesis,
}: OverviewTabProps) {
  const hypothesis = (sim.hypothesis ?? "").trim();
  const configuredRoster =
    configStringList(sim.config?.effective_agents).length > 0
      ? configStringList(sim.config.effective_agents)
      : configStringList(sim.config?.agents);
  const displayedAgents =
    configuredRoster.length > 0 ? configuredRoster : sim.agents_participated;

  return (
    <div className="space-y-8" data-testid="overview-tab">
      {/* Hero: hypothesis preview + video */}
      <section
        className="grid gap-6 lg:grid-cols-3"
        data-testid="overview-hero"
      >
        <div className="lg:col-span-2">
          <VideoPlayer src={sim.video_url} youtubeUrl={sim.youtube_url} />
        </div>
        <div className="rounded border border-border bg-surface p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-medium uppercase tracking-wide text-foreground/50">
              Hypothesis
            </h2>
            {onJumpToHypothesis ? (
              <button
                type="button"
                onClick={onJumpToHypothesis}
                className="text-xs text-neon-cyan hover:underline"
              >
                Edit →
              </button>
            ) : null}
          </div>
          {hypothesis ? (
            <p
              className="text-sm text-foreground/80 whitespace-pre-wrap"
              data-testid="overview-hypothesis"
            >
              {hypothesis}
            </p>
          ) : (
            <p className="text-sm text-foreground/40 italic">
              No hypothesis recorded yet.
            </p>
          )}
        </div>
      </section>

      <SummaryGrid
        total_conversations={sim.total_conversations}
        total_turns={sim.total_turns}
        total_tokens={sim.total_tokens}
        total_cost={sim.total_cost}
        total_artifacts={sim.total_artifacts}
        total_management_flags={sim.total_management_flags}
      />

      <AgentList
        agents={displayedAgents}
        linkPrefix={`/simulations/${simulationId}/agents`}
        title="Effective Agent Roster"
      />

      <div className="text-xs text-foreground/40">
        <Link
          href={`/simulations/${simulationId}?tab=conversations`}
          className="text-neon-cyan hover:underline"
        >
          View {sim.total_conversations} conversations →
        </Link>
      </div>
    </div>
  );
}
