"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import CreatorForm from "@/components/simulationCreator/CreatorForm";

function CreatorFormWithQuery() {
  const params = useSearchParams();
  const scenario = params.get("scenario");
  return <CreatorForm initialScenario={scenario} />;
}

export default function NewSimulationPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-12">
      <header className="mb-6">
        <h1 className="font-pixel text-xl text-neon-cyan mb-2">
          NEW SIMULATION
        </h1>
        <p className="text-sm text-foreground/70">
          Pick a scenario, customise the cast and parameters, then run it.
          We&apos;ll redirect you to the simulation workspace once it queues.
        </p>
      </header>
      <Suspense
        fallback={
          <p className="text-sm text-foreground/50">Loading creator…</p>
        }
      >
        <CreatorFormWithQuery />
      </Suspense>
    </div>
  );
}
