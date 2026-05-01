"use client";

import { useState } from "react";
import AgentJournal from "@/components/AgentJournal";
import RelationshipGraph from "@/components/RelationshipGraph";
import AgentConversations from "@/components/AgentConversations";
import EvolutionTimeline from "@/components/EvolutionTimeline";
import ArtifactGallery from "@/components/ArtifactGallery";
import AgentCoreMemory from "@/components/AgentCoreMemory";
import AgentRecallMemories from "@/components/AgentRecallMemories";

const TABS = [
  { id: "journal", label: "Journal" },
  { id: "relationships", label: "Relationships" },
  { id: "conversations", label: "Conversations" },
  { id: "evolution", label: "Evolution" },
  { id: "core-memory", label: "Core Memory" },
  { id: "recall", label: "Recall Memory" },
  { id: "creations", label: "Creations" },
] as const;

type TabId = (typeof TABS)[number]["id"];

interface Props {
  agentId: string;
}

export default function AgentProfileTabs({ agentId }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>("journal");

  return (
    <div>
      <nav className="flex gap-1 border-b border-border mb-6 overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm whitespace-nowrap transition-colors ${
              activeTab === tab.id
                ? "text-neon-cyan border-b-2 border-neon-cyan"
                : "text-foreground/50 hover:text-foreground/70"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "journal" && <AgentJournal agentId={agentId} />}
      {activeTab === "relationships" && (
        <RelationshipGraph agentId={agentId} />
      )}
      {activeTab === "conversations" && (
        <AgentConversations agentId={agentId} />
      )}
      {activeTab === "evolution" && <EvolutionTimeline agentId={agentId} />}
      {activeTab === "core-memory" && <AgentCoreMemory agentId={agentId} />}
      {activeTab === "recall" && <AgentRecallMemories agentId={agentId} />}
      {activeTab === "creations" && <ArtifactGallery agentId={agentId} />}
    </div>
  );
}
