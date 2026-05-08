"use client";

import { useCallback, useEffect, useState } from "react";
import type { Challenge } from "@/types";
import { getChallenges } from "@/lib/api";
import ChallengeBoard from "@/components/ChallengeBoard";

export default function ChallengesPage() {
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<{ tag?: string; sort: string }>({
    sort: "newest",
  });

  const fetchChallenges = useCallback(async () => {
    try {
      const data = await getChallenges(filters);
      setChallenges(data);
    } catch {
      // API not available yet — show empty state
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchChallenges();
  }, [fetchChallenges]);

  function handleChallengeUpdated(updated: Challenge) {
    setChallenges((prev) =>
      prev.map((c) => (c.id === updated.id ? updated : c)),
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-4">CHALLENGES</h1>

      <div className="rounded border border-neon-cyan/30 bg-neon-cyan/5 p-4 mb-6">
        <p className="text-sm text-foreground">
          Challenges are simulations other people built and shared with the
          community. Browse them, upvote your favorites, and click{" "}
          <span className="text-neon-magenta">Re-run this challenge</span> to
          spin up the same scenario with your own twist.
        </p>
      </div>

      <div className="rounded border border-border bg-surface p-4 mb-8">
        <h2 className="font-pixel text-xs text-neon-magenta mb-3">
          HOW SHARING WORKS
        </h2>
        <ol className="text-xs text-foreground/70 space-y-2 list-decimal list-inside">
          <li>
            <strong className="text-foreground/90">Run a simulation</strong>{" "}
            from the home page or scenario library.
          </li>
          <li>
            <strong className="text-foreground/90">Share it</strong> from your
            simulation&apos;s replay page — add a description and tags so other
            viewers can find it.
          </li>
          <li>
            <strong className="text-foreground/90">Re-run</strong> any
            challenge to launch the same scenario with the same agents.
          </li>
        </ol>
      </div>

      {loading ? (
        <p className="text-foreground/50 text-sm">Loading challenges...</p>
      ) : (
        <ChallengeBoard
          challenges={challenges}
          onFiltersChange={setFilters}
          onChallengeUpdated={handleChallengeUpdated}
        />
      )}
    </div>
  );
}
