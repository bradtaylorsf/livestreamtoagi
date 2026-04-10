"use client";

import { useState } from "react";
import type { Challenge } from "@/types";
import { upvoteChallenge } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/20 text-yellow-400",
  in_progress: "bg-blue-500/20 text-blue-400",
  completed: "bg-green-500/20 text-green-400",
  failed: "bg-red-500/20 text-red-400",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  in_progress: "In Progress",
  completed: "Completed",
  failed: "Failed",
};

const SORT_OPTIONS = [
  { value: "newest", label: "Newest" },
  { value: "most_upvoted", label: "Most Upvoted" },
  { value: "status", label: "Status" },
];

const STATUS_FILTER_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "pending", label: "Pending" },
  { value: "in_progress", label: "In Progress" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

const CATEGORY_OPTIONS = [
  { value: "", label: "All Categories" },
  { value: "building", label: "Building" },
  { value: "creative", label: "Creative" },
  { value: "social", label: "Social" },
  { value: "technical", label: "Technical" },
  { value: "other", label: "Other" },
];

interface ChallengeBoardProps {
  challenges: Challenge[];
  onFiltersChange: (filters: {
    status?: string;
    category?: string;
    sort: string;
  }) => void;
  onChallengeUpdated: (challenge: Challenge) => void;
}

export default function ChallengeBoard({
  challenges,
  onFiltersChange,
  onChallengeUpdated,
}: ChallengeBoardProps) {
  const [sort, setSort] = useState("newest");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [votingId, setVotingId] = useState<number | null>(null);

  function handleFilterChange(
    newSort?: string,
    newStatus?: string,
    newCategory?: string,
  ) {
    const s = newSort ?? sort;
    const st = newStatus ?? statusFilter;
    const cat = newCategory ?? categoryFilter;
    setSort(s);
    setStatusFilter(st);
    setCategoryFilter(cat);
    onFiltersChange({
      sort: s,
      status: st || undefined,
      category: cat || undefined,
    });
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
      {/* Filter controls */}
      <div className="flex flex-wrap gap-3 mb-6">
        <select
          value={sort}
          onChange={(e) => handleFilterChange(e.target.value, undefined, undefined)}
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
          value={statusFilter}
          onChange={(e) => handleFilterChange(undefined, e.target.value, undefined)}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by status"
        >
          {STATUS_FILTER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={categoryFilter}
          onChange={(e) => handleFilterChange(undefined, undefined, e.target.value)}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by category"
        >
          {CATEGORY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Challenge list */}
      {challenges.length === 0 ? (
        <p className="text-foreground/50 text-sm">
          No challenges yet. Be the first to submit one!
        </p>
      ) : (
        <div className="space-y-4">
          {challenges.map((challenge) => (
            <div
              key={challenge.id}
              className="rounded border border-border bg-surface p-4"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[challenge.status] || "bg-gray-500/20 text-gray-400"}`}
                    >
                      {STATUS_LABELS[challenge.status] || challenge.status}
                    </span>
                    {challenge.category && (
                      <span className="inline-block rounded bg-surface-light px-2 py-0.5 text-xs text-foreground/60">
                        {challenge.category}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-foreground">{challenge.description}</p>
                  <div className="mt-2 flex flex-wrap gap-3 text-xs text-foreground/40">
                    {challenge.submitted_by && (
                      <span>by {challenge.submitted_by}</span>
                    )}
                    {challenge.created_at && (
                      <time>
                        {new Date(challenge.created_at).toLocaleDateString()}
                      </time>
                    )}
                    {challenge.assigned_agents &&
                      challenge.assigned_agents.length > 0 && (
                        <span>
                          Agents: {challenge.assigned_agents.join(", ")}
                        </span>
                      )}
                    {challenge.actual_cost != null && (
                      <span>Cost: ${challenge.actual_cost.toFixed(4)}</span>
                    )}
                  </div>
                  {challenge.result && (
                    <p className="mt-2 text-xs text-foreground/60 border-t border-border pt-2">
                      Result: {challenge.result}
                    </p>
                  )}
                </div>

                {/* Upvote button */}
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
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
