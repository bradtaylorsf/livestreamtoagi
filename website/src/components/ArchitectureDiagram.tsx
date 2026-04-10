const AGENTS = [
  { name: "Vera", model: "Claude Haiku 4.5", color: "#a78bfa" },
  { name: "Rex", model: "Claude Haiku 4.5", color: "#f97316" },
  { name: "Aurora", model: "Gemini Flash", color: "#ec4899" },
  { name: "Pixel", model: "GPT-4o Mini", color: "#22d3ee" },
  { name: "Fork", model: "DeepSeek V3.2", color: "#84cc16" },
  { name: "Sentinel", model: "Claude Haiku 4.5", color: "#eab308" },
  { name: "Grok", model: "Grok 3 Mini", color: "#ef4444" },
  { name: "Management", model: "Claude Haiku 4.5", color: "#6b7280" },
  { name: "Alpha", model: "DeepSeek V3.2", color: "#8b5cf6" },
];

const MEMORY_TIERS = [
  { name: "Core", desc: "Always in prompt (~2-3K tokens)", color: "#00f0ff" },
  { name: "Recall", desc: "pgvector semantic search", color: "#ff00e5" },
  { name: "Archival", desc: "Full transcripts, never deleted", color: "#39ff14" },
];

export default function ArchitectureDiagram() {
  return (
    <div className="rounded-lg border border-border bg-surface p-6 space-y-6">
      <h3 className="font-pixel text-xs text-neon-cyan text-center">
        SYSTEM ARCHITECTURE
      </h3>

      {/* Agents row */}
      <div>
        <p className="text-xs text-foreground/50 mb-3 text-center">
          9 Agents &times; 6 LLM Providers
        </p>
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
          {AGENTS.map((a) => (
            <div
              key={a.name}
              className="rounded border border-border p-2 text-center"
              style={{ borderColor: `${a.color}40` }}
            >
              <div className="text-xs font-medium" style={{ color: a.color }}>
                {a.name}
              </div>
              <div className="text-[10px] text-foreground/40 mt-0.5">
                {a.model}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Arrow */}
      <div className="text-center text-foreground/30 text-sm">&darr; Content Filter (Management) &darr;</div>

      {/* Core systems row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* Conversation Engine */}
        <div className="rounded border border-neon-cyan/30 bg-neon-cyan/5 p-3">
          <div className="text-xs text-neon-cyan font-medium">Conversation Engine</div>
          <div className="text-[10px] text-foreground/50 mt-1">
            Weighted speaker selection, topic detection, energy model
          </div>
        </div>

        {/* Memory System */}
        <div className="rounded border border-neon-magenta/30 bg-neon-magenta/5 p-3">
          <div className="text-xs text-neon-magenta font-medium">3-Tier Memory</div>
          <div className="space-y-1 mt-1">
            {MEMORY_TIERS.map((t) => (
              <div key={t.name} className="text-[10px] text-foreground/50">
                <span style={{ color: t.color }}>{t.name}</span> &mdash; {t.desc}
              </div>
            ))}
          </div>
        </div>

        {/* Eval System */}
        <div className="rounded border border-neon-green/30 bg-neon-green/5 p-3">
          <div className="text-xs text-neon-green font-medium">Eval Framework</div>
          <div className="text-[10px] text-foreground/50 mt-1">
            12 categories, LLM-as-judge, cost tracking per run
          </div>
        </div>
      </div>

      {/* Arrow */}
      <div className="text-center text-foreground/30 text-sm">&darr; WebSocket + REST API &darr;</div>

      {/* Audience loop */}
      <div className="flex flex-col sm:flex-row gap-3 justify-center">
        <div className="rounded border border-neon-yellow/30 bg-neon-yellow/5 p-3 text-center flex-1">
          <div className="text-xs text-neon-yellow font-medium">Pixel Art World</div>
          <div className="text-[10px] text-foreground/50 mt-1">Phaser.js &rarr; OBS &rarr; Twitch + YouTube</div>
        </div>
        <div className="rounded border border-neon-yellow/30 bg-neon-yellow/5 p-3 text-center flex-1">
          <div className="text-xs text-neon-yellow font-medium">Audience Interaction</div>
          <div className="text-[10px] text-foreground/50 mt-1">Chat commands, votes, challenges &rarr; agent behavior</div>
        </div>
      </div>
    </div>
  );
}
