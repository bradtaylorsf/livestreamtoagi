import type { AgentData } from "@/lib/agent-data";

interface Props {
  agent: AgentData;
}

export default function AgentProfile({ agent }: Props) {
  return (
    <div className="flex flex-col sm:flex-row gap-6">
      {/* Portrait placeholder */}
      <div
        className="w-32 h-32 sm:w-48 sm:h-48 rounded shrink-0 flex items-center justify-center font-pixel text-3xl text-white/80 mx-auto sm:mx-0"
        style={{ backgroundColor: agent.color }}
        role="img"
        aria-label={`${agent.name} avatar`}
      >
        {agent.name[0]}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1
            className="font-pixel text-xl"
            style={{ color: agent.color }}
          >
            {agent.name}
          </h1>
          <span className="text-foreground/50 text-sm">{agent.tagline}</span>
        </div>
        <p className="text-foreground/70 mt-1">{agent.role}</p>

        {/* Model badges */}
        <div className="flex flex-wrap gap-2 mt-3">
          <span className="text-xs rounded bg-surface-light border border-border px-2 py-1 text-foreground/50">
            Chat: {agent.models.conversation}
          </span>
          {agent.models.building && (
            <span className="text-xs rounded bg-surface-light border border-border px-2 py-1 text-foreground/50">
              Build: {agent.models.building}
            </span>
          )}
          {agent.voiceId && (
            <span className="text-xs rounded bg-surface-light border border-border px-2 py-1 text-foreground/50">
              Voice: {agent.voiceId}
            </span>
          )}
        </div>

        {/* Backstory */}
        <div className="mt-4">
          <h2 className="font-pixel text-xs text-neon-magenta mb-2">ABOUT</h2>
          <p className="text-sm text-foreground/70">{agent.backstory}</p>
        </div>

        {/* Personality traits */}
        <div className="mt-4">
          <h3 className="text-xs text-foreground/40 uppercase mb-2">
            Personality
          </h3>
          <ul className="list-disc list-inside text-sm text-foreground/60 space-y-1">
            {agent.personalityTraits.map((trait) => (
              <li key={trait}>{trait}</li>
            ))}
          </ul>
        </div>

        {/* Catchphrases */}
        <div className="mt-4">
          <h3 className="text-xs text-foreground/40 uppercase mb-2">
            Catchphrases
          </h3>
          <div className="flex flex-wrap gap-2">
            {agent.catchphrases.map((phrase) => (
              <span
                key={phrase}
                className="text-xs rounded bg-surface border border-border px-2 py-1 text-foreground/50 italic"
              >
                &ldquo;{phrase}&rdquo;
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
