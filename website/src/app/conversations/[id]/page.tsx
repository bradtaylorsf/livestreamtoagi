"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import type { ConversationDetail, SelectionLogEntry } from "@/types";
import { getConversation, getConversationSelections } from "@/lib/api";
import ConversationReplay from "@/components/ConversationReplay";

export default function ConversationReplayPage() {
  const params = useParams();
  const id = params.id as string;

  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [selections, setSelections] = useState<SelectionLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Parse initial turn from URL hash
  const [initialTurn, setInitialTurn] = useState(1);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const hash = window.location.hash;
      const match = hash.match(/^#turn-(\d+)$/);
      if (match) {
        setInitialTurn(parseInt(match[1], 10));
      }
    }
  }, []);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [conv, sels] = await Promise.all([
          getConversation(id),
          getConversationSelections(id),
        ]);
        setConversation(conv);
        setSelections(sels);
      } catch {
        setError("Failed to load conversation");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p className="text-foreground/50 text-sm">Loading conversation...</p>
      </div>
    );
  }

  if (error || !conversation) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <h1 className="font-pixel text-xl text-neon-cyan mb-4">
          CONVERSATION REPLAY
        </h1>
        <p className="text-red-400 text-sm">{error || "Conversation not found"}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-4">
        CONVERSATION REPLAY
      </h1>

      <ConversationReplay
        conversation={conversation}
        selections={selections}
        initialTurn={initialTurn}
      />
    </div>
  );
}
