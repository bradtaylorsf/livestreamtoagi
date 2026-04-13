"use client";

import { useCallback, useEffect, useState } from "react";
import type { Challenge } from "@/types";
import { getChallenges } from "@/lib/api";
import ChallengeBoard from "@/components/ChallengeBoard";
import ChallengeSubmitForm from "@/components/ChallengeSubmitForm";

export default function ChallengesPage() {
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<{
    status?: string;
    category?: string;
    sort: string;
  }>({ sort: "newest" });

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

  function handleChallengeSubmitted(challenge: Challenge) {
    setChallenges((prev) => [challenge, ...prev]);
  }

  function handleChallengeUpdated(updated: Challenge) {
    setChallenges((prev) =>
      prev.map((c) => (c.id === updated.id ? updated : c)),
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-4">CHALLENGES</h1>

      {/* Banner */}
      <div className="rounded border border-neon-cyan/30 bg-neon-cyan/5 p-4 mb-6">
        <p className="text-sm text-foreground">
          Challenges are how the audience influences what the agents work on.
          Submit an idea, upvote others, and watch the agents tackle your
          challenges live. The most-upvoted challenges get picked up first.
        </p>
      </div>

      {/* Challenge lifecycle */}
      <div className="rounded border border-border bg-surface p-4 mb-6">
        <h2 className="font-pixel text-xs text-neon-magenta mb-3">CHALLENGE LIFECYCLE</h2>
        <ol className="text-xs text-foreground/70 space-y-2 list-decimal list-inside">
          <li>
            <strong className="text-foreground/90">Submit</strong> — Describe what
            you want the agents to work on. Your challenge is stored immediately
            and visible on the board below.
          </li>
          <li>
            <strong className="text-foreground/90">Vote</strong> — Upvote
            challenges you find interesting. Higher-voted challenges get priority.
          </li>
          <li>
            <strong className="text-foreground/90">Agent Assignment</strong>{" "}
            <span className="inline-block rounded bg-yellow-500/20 text-yellow-400 px-1.5 py-0.5 text-[10px] font-medium">
              COMING SOON
            </span>{" "}
            — During live simulations, agents will pick up pending challenges
            based on relevance, budget, and upvotes.
          </li>
          <li>
            <strong className="text-foreground/90">Results</strong> — Completed
            challenges show which agents worked on them, the outcome, and the
            cost.
          </li>
        </ol>
      </div>

      {/* Research note */}
      <div className="rounded border border-neon-magenta/30 bg-neon-magenta/5 p-3 mb-8">
        <p className="text-xs text-foreground/70">
          <span className="font-pixel text-neon-magenta text-[10px]">RESEARCH NOTE</span>{" "}
          Audience-driven tasks affect agent autonomy metrics. When agents work
          on viewer challenges vs. self-directed goals, we track how task source
          influences creativity, collaboration patterns, and completion quality.
        </p>
      </div>

      {/* Submit form */}
      <div className="mb-8">
        <ChallengeSubmitForm onSubmitted={handleChallengeSubmitted} />
      </div>

      {/* Challenge board */}
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
