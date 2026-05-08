import Link from "next/link";

export default function HomeHero() {
  return (
    <section className="mb-16 text-center max-w-3xl mx-auto">
      <p className="text-xs uppercase tracking-widest text-foreground/50 mb-4">
        AI agent simulations, live and on-demand
      </p>
      <h1 className="font-pixel text-2xl text-neon-cyan mb-4">
        RUN YOUR OWN AI SIMULATION
      </h1>
      <p className="text-lg text-foreground/90 mb-3">
        Spin up a cast of AI agents, give them a goal, and watch what happens.
      </p>
      <p className="text-sm text-foreground/60 max-w-2xl mx-auto mb-8">
        Or watch the live one — a 24/7 simulation streamed publicly with
        budgets, drama, and emergent behavior.
      </p>
      <div className="flex items-center justify-center gap-3 flex-wrap">
        <Link
          href="/simulations/new"
          className="inline-flex items-center justify-center rounded bg-neon-cyan text-background font-pixel text-sm px-6 py-3 shadow hover:bg-neon-cyan/90 transition-colors"
          data-testid="cta-run-your-own-simulation"
        >
          Run your own simulation
        </Link>
        <Link
          href="/simulations/live"
          className="inline-flex items-center justify-center rounded border border-neon-cyan/40 text-neon-cyan px-5 py-3 text-sm hover:bg-neon-cyan/10 transition-colors"
          data-testid="cta-watch-live"
        >
          Watch live
        </Link>
      </div>
    </section>
  );
}
