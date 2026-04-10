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
