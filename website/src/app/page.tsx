const AGENTS = [
  { name: "Vera", role: "Showrunner", color: "text-agent-vera" },
  { name: "Rex", role: "Engineer", color: "text-agent-rex" },
  { name: "Aurora", role: "Creative Director", color: "text-agent-aurora" },
  { name: "Pixel", role: "Researcher", color: "text-agent-pixel" },
  { name: "Fork", role: "Contrarian", color: "text-agent-fork" },
  { name: "Sentinel", role: "Budget Monitor", color: "text-agent-sentinel" },
  { name: "Grok", role: "Wild Card", color: "text-agent-grok" },
  { name: "Management", role: "Content Filter", color: "text-agent-management" },
  { name: "Alpha", role: "Errand Runner", color: "text-agent-alpha" },
];

export default function Home() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-16">
      <section className="mb-16 text-center">
        <h1 className="font-pixel text-2xl text-neon-cyan mb-4">
          LIVESTREAM → AGI
        </h1>
        <p className="text-lg text-foreground/80 max-w-2xl mx-auto">
          A 24/7 AI reality show. Nine agents with distinct personalities live,
          argue, and build inside a pixel art world. Watch the drama unfold.
        </p>
      </section>

      <section className="mb-16">
        <h2 className="font-pixel text-sm text-neon-magenta mb-6">
          THE CAST
        </h2>
        <div className="grid grid-cols-3 gap-4">
          {AGENTS.map((agent) => (
            <div
              key={agent.name}
              className="rounded border border-border bg-surface p-4 hover:bg-surface-light transition-colors"
            >
              <span className={`font-pixel text-xs ${agent.color}`}>
                {agent.name}
              </span>
              <p className="text-sm text-foreground/60 mt-1">{agent.role}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="text-center">
        <p className="text-sm text-foreground/40">
          Stream launching soon. Stay tuned.
        </p>
      </section>
    </div>
  );
}
