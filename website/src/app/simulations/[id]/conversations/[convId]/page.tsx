"use client";

import { useEffect, useState } from "react";
import { notFound, useParams } from "next/navigation";
import Link from "next/link";
import { getConversation } from "@/lib/api";
import type { ConversationDetail } from "@/types";

/**
 * Lightweight scoped conversation page. Validates that the conversation's
 * simulation_id matches the URL simulation segment; otherwise calls
 * notFound(). For the full replay UI (transcript, energy graph, etc.) the
 * canonical page is /conversations/[id]; this page links there with the
 * sim context preserved.
 */
export default function ScopedConversationPage() {
  const params = useParams<{ id: string; convId: string }>();
  const simId = params.id;
  const convId = params.convId;

  const [conv, setConv] = useState<ConversationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [mismatched, setMismatched] = useState(false);

  useEffect(() => {
    setLoading(true);
    getConversation(convId)
      .then((data) => {
        if (data.simulation_id && data.simulation_id !== simId) {
          setMismatched(true);
        }
        setConv(data);
      })
      .catch(() => {
        setConv(null);
      })
      .finally(() => setLoading(false));
  }, [convId, simId]);

  if (mismatched) {
    notFound();
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p className="text-sm text-foreground/50 animate-pulse">Loading...</p>
      </div>
    );
  }

  if (!conv) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <h1 className="font-pixel text-lg text-neon-cyan mb-4">
          Conversation not found
        </h1>
        <Link
          href={`/simulations/${simId}/conversations`}
          className="text-neon-cyan text-sm hover:underline"
        >
          Back to conversations →
        </Link>
      </div>
    );
  }

  const shortId = conv.id.slice(0, 8);

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-6">
      <nav className="text-xs text-foreground/40" aria-label="Breadcrumb">
        <Link
          href={`/simulations/${simId}`}
          className="hover:text-foreground/60"
        >
          Simulation {simId.slice(0, 8)}
        </Link>
        {" / "}
        <Link
          href={`/simulations/${simId}/conversations`}
          className="hover:text-foreground/60"
        >
          Conversations
        </Link>
        {" / "}
        <span className="text-foreground/60">{shortId}</span>
      </nav>

      <h1 className="font-pixel text-lg text-neon-cyan">
        Conversation {shortId}
      </h1>

      <div className="rounded border border-border bg-surface p-4 text-sm text-foreground/70 space-y-2">
        <div>Trigger: {conv.trigger_type}</div>
        <div>Turns: {conv.turn_count}</div>
        <div>Participants: {conv.participating_agents.join(", ")}</div>
        {conv.started_at && (
          <div className="text-xs text-foreground/40">
            Started {new Date(conv.started_at).toLocaleString()}
          </div>
        )}
      </div>

      <Link
        href={`/conversations/${conv.id}`}
        className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
      >
        Open full transcript →
      </Link>
    </div>
  );
}
