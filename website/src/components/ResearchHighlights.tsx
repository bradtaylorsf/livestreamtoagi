const HIGHLIGHTS = [
  { value: "12", label: "Eval Categories" },
  { value: "62+", label: "Simulations Run" },
  { value: "9 Agents", label: "6 LLM Providers" },
  { value: "100%", label: "Open Source" },
];

export default function ResearchHighlights() {
  return (
    <section>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {HIGHLIGHTS.map((item) => (
          <div
            key={item.label}
            className="rounded border border-border bg-surface p-4 text-center"
          >
            <div className="font-pixel text-lg text-neon-cyan">{item.value}</div>
            <div className="text-xs text-foreground/50 mt-1">{item.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
