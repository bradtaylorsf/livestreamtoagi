import type { Metadata } from "next";
import SimulationWall from "@/components/SimulationWall";

export const metadata: Metadata = {
  title: "Wall of Simulations",
  description:
    "Live grid of every simulation currently running plus the last hour of completions.",
};

export default function SimulationsLivePage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">
        WALL OF SIMULATIONS
      </h1>
      <p className="text-foreground/60 mb-8">
        Every simulation currently running, plus runs that completed in the
        last hour. Updates live every 5 seconds.
      </p>

      <SimulationWall />
    </div>
  );
}
