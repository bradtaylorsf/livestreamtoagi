"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { Challenge } from "@/types";
import { upvoteChallenge } from "@/lib/api";

const SORT_OPTIONS = [
  { value: "newest", label: "Newest" },
  { value: "most_upvoted", label: "Most Upvoted" },
];

interface ChallengeBoardProps {
  challenges: Challenge[];
  onFiltersChange: (filters: { tag?: string; sort: string }) => void;
  onChallengeUpdated: (challenge: Challenge) => void;
}

export function rerunHref(challengeId: number): string {
  return `/simulations/new?challenge_id=${challengeId}`;
}

export default function ChallengeBoard({
  challenges,
  onFiltersChange,
  onChallengeUpdated,
}: ChallengeBoardProps) {
  const [sort, setSort] = useState("newest");
  const [tagFilter, setTagFilter] = useState("");
  const [votingId, setVotingId] = useState<number | null>(null);

  const tagOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const c of challenges) {
      for (const t of c.tags ?? []) {
        if (t) seen.add(t);
      }
    }
    return Array.from(seen).sort();
  }, [challenges]);

  function handleFilterChange(newSort?: string, newTag?: string) {
    const s = newSort ?? sort;
    const t = newTag ?? tagFilter;
    setSort(s);
    setTagFilter(t);
    onFiltersChange({ sort: s, tag: t || undefined });
  }

  async function handleUpvote(id: number) {
    setVotingId(id);
    try {
      const updated = await upvoteChallenge(id);
      onChallengeUpdated(updated);
    } catch {
      // Silently handle (likely already voted or rate limited)
    } finally {
      setVotingId(null);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-6">
        <select
          value={sort}
          onChange={(e) => handleFilterChange(e.target.value, undefined)}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Sort challenges"
        >
          {SORT_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={tagFilter}
          onChange={(e) => handleFilterChange(undefined, e.target.value)}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by tag"
        >
          <option value="">All tags</option>
          {tagOptions.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      {challenges.length === 0 ? (
        <p className="text-foreground/50 text-sm">
          No shared challenges yet. Run a simulation, then share it from the
          replay page to seed the board.
        </p>
      ) : (
        <div className="space-y-4" data-testid="challenge-list">
          {challenges.map((challenge) => (
            <article
              key={challenge.id}
              data-testid="challenge-card"
              data-challenge-id={challenge.id}
              className="rounded border border-border bg-surface p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  {challenge.simulation_id && challenge.simulation_name && (
                    <Link
                      href={`/simulations/${challenge.simulation_id}`}
                      className="text-neon-cyan hover:underline font-pixel text-xs mb-1 inline-block"
                    >
                      {challenge.simulation_name}
                    </Link>
                  )}
                  <p className="text-sm text-foreground">
                    {challenge.description}
                  </p>
                  {challenge.tags && challenge.tags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {challenge.tags.map((tag) => (
                        <span
                          key={tag}
                          className="inline-block rounded bg-surface-light px-1.5 py-0.5 text-[10px] text-foreground/60"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-3 text-xs text-foreground/40">
                    {challenge.submitted_by && (
                      <span>by {challenge.submitted_by}</span>
                    )}
                    {challenge.shared_at && (
                      <time>
                        shared{" "}
                        {new Date(challenge.shared_at).toLocaleDateString()}
                      </time>
                    )}
                    <span>{challenge.simulation_total_turns} turns</span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {challenge.simulation_id && (
                      <Link
                        href={`/simulations/${challenge.simulation_id}`}
                        className="rounded border border-border bg-surface-light px-3 py-1.5 text-xs text-foreground/70 hover:border-neon-cyan hover:text-neon-cyan transition-colors"
                      >
                        Open simulation
                      </Link>
                    )}
                    <Link
                      href={rerunHref(challenge.id)}
                      className="rounded border border-neon-magenta/40 bg-neon-magenta/10 px-3 py-1.5 text-xs font-medium text-neon-magenta hover:bg-neon-magenta/20 transition-colors"
                    >
                      Re-run this challenge
                    </Link>
                  </div>
                </div>

                <button
                  onClick={() => handleUpvote(challenge.id)}
                  disabled={votingId === challenge.id}
                  className="flex flex-col items-center gap-1 rounded border border-border bg-surface-light px-3 py-2 text-foreground/70 hover:border-neon-cyan hover:text-neon-cyan transition-colors disabled:opacity-50"
                  aria-label={`Upvote challenge: ${challenge.votes} votes`}
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                  >
                    <path d="M8 4l4 5H4l4-5z" />
                  </svg>
                  <span className="text-xs font-medium">{challenge.votes}</span>
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
