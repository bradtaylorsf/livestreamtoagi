"use client";

import { useState, useEffect } from "react";
import { getAgentJournal } from "@/lib/api";
import type { JournalEntry } from "@/types";
import JournalIllustration from "@/components/JournalIllustration";
import { SkeletonCardList } from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";

const TYPE_COLORS: Record<string, string> = {
  "6hour": "bg-neon-cyan/10 text-neon-cyan",
  weekly: "bg-neon-magenta/10 text-neon-magenta",
  dream: "bg-neon-yellow/10 text-neon-yellow",
  conversation: "bg-neon-green/10 text-neon-green",
};

interface Props {
  agentId: string;
}

function formatJournalDate(createdAt: string | null): string {
  return createdAt ? new Date(createdAt).toLocaleString() : "Undated";
}

function formatReflectionType(type: string): string {
  return type === "6hour" ? "6-hour" : type;
}

export default function AgentJournal({ agentId }: Props) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentJournal(agentId)
      .then((data) => {
        if (!cancelled) setEntries(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load journal");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [agentId]);

  if (loading) {
    return showSkeleton ? <SkeletonCardList count={3} /> : null;
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400">Unable to load journal</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            getAgentJournal(agentId)
              .then(setEntries)
              .catch((err) =>
                setError(err instanceof Error ? err.message : "Failed to load journal")
              )
              .finally(() => setLoading(false));
          }}
          className="text-xs text-neon-cyan hover:text-neon-cyan/80 mt-2"
        >
          Retry
        </button>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8">
        No journal entries yet.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {entries.map((entry) => (
        <article
          key={entry.id}
          className="rounded border border-border bg-surface p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <time className="text-xs text-foreground/40">
              {formatJournalDate(entry.created_at)}
            </time>
            <span
              className={`text-xs rounded px-2 py-0.5 ${
                TYPE_COLORS[entry.reflection_type] ?? "bg-surface-light text-foreground/50"
              }`}
            >
              {formatReflectionType(entry.reflection_type)}
            </span>
          </div>
          <JournalIllustration
            imageUrl={entry.image_url}
            label={`${formatReflectionType(entry.reflection_type)} journal illustration`}
          />
          <p className="text-sm text-foreground/70 leading-relaxed">
            {entry.content}
          </p>
        </article>
      ))}
    </div>
  );
}
