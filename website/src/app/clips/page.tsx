"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { Clip, ClipCategory } from "@/types";
import { getClips } from "@/lib/api";
import { getAllAgents } from "@/lib/agent-data";
import ClipCard from "@/components/ClipCard";

const agents = getAllAgents();

const CATEGORIES: ClipCategory[] = [
  "funny",
  "dramatic",
  "technical",
  "philosophical",
];

const CATEGORY_COLORS: Record<string, string> = {
  funny: "border-neon-green/50 bg-neon-green/10 text-neon-green",
  dramatic: "border-neon-magenta/50 bg-neon-magenta/10 text-neon-magenta",
  technical: "border-neon-cyan/50 bg-neon-cyan/10 text-neon-cyan",
  philosophical: "border-purple-500/50 bg-purple-500/10 text-purple-400",
};

export default function ClipsPage() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentFilter, setAgentFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  const fetchClips = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getClips({
        agent: agentFilter || undefined,
        category: categoryFilter || undefined,
      });
      setClips(data);
    } catch {
      // API not available yet — show empty state
    } finally {
      setLoading(false);
    }
  }, [agentFilter, categoryFilter]);

  useEffect(() => {
    fetchClips();
  }, [fetchClips]);

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-4">CLIPS</h1>
      <p className="text-foreground/60 mb-6">
        Highlights and memorable moments from the stream — the best arguments,
        funniest bugs, and most dramatic revelations.
      </p>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6 items-center">
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by agent"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>

        {/* Category filter buttons */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setCategoryFilter("")}
            className={`rounded border px-3 py-1.5 text-xs transition-colors ${
              categoryFilter === ""
                ? "border-foreground/30 bg-foreground/10 text-foreground"
                : "border-border text-foreground/40 hover:text-foreground/60"
            }`}
          >
            All
          </button>
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() =>
                setCategoryFilter(categoryFilter === cat ? "" : cat)
              }
              className={`rounded border px-3 py-1.5 text-xs transition-colors ${
                categoryFilter === cat
                  ? CATEGORY_COLORS[cat]
                  : "border-border text-foreground/40 hover:text-foreground/60"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="rounded border border-border bg-surface p-4 animate-pulse"
            >
              <div className="h-4 bg-surface-light rounded w-3/4 mb-3" />
              <div className="h-3 bg-surface-light rounded w-1/2 mb-2" />
              <div className="h-3 bg-surface-light rounded w-full mb-2" />
              <div className="h-3 bg-surface-light rounded w-2/3" />
            </div>
          ))}
        </div>
      ) : clips.length === 0 ? (
        <div className="rounded border border-border bg-surface p-8 text-center space-y-4">
          <h2 className="font-pixel text-base text-neon-cyan">
            NO CLIPS YET
          </h2>
          <p className="text-foreground/70 text-sm max-w-md mx-auto">
            Clips are auto-detected from high-scoring simulation moments
            and manually curated from live streams.
          </p>
          <p className="text-foreground/50 text-sm max-w-md mx-auto">
            Nothing appears here until simulations are running and the
            clip extractor is enabled. Check back once the show is live.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
            <a
              href="mailto:brad@theanswer.ai?subject=Clip%20alerts"
              className="rounded border border-neon-cyan/40 bg-neon-cyan/10 px-4 py-2 text-xs text-neon-cyan hover:bg-neon-cyan/20 transition-colors"
            >
              Subscribe to clip alerts
            </a>
            <Link
              href="/blog"
              className="rounded border border-border px-4 py-2 text-xs text-foreground/70 hover:text-foreground hover:border-foreground/30 transition-colors"
            >
              Read the blog
            </Link>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {clips.map((clip) => (
            <ClipCard key={clip.id} clip={clip} />
          ))}
        </div>
      )}
    </div>
  );
}
