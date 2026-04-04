"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import TabNav from "@/components/admin/TabNav";
import SummaryCard from "@/components/admin/SummaryCard";
import PersonalityChart from "@/components/admin/PersonalityChart";
import MemoryDiffView from "@/components/admin/MemoryDiffView";
import ArtifactDetail from "@/components/admin/ArtifactDetail";
import {
  fetchAgent,
  fetchAgentSystemPrompt,
  fetchAgentCoreMemory,
  fetchAgentRecallMemories,
  fetchAgentConversations,
  fetchAgentArtifacts,
  fetchAgentJournal,
  fetchAgentCosts,
} from "@/lib/admin-api";
import type {
  AgentDetail,
  SystemPromptResponse,
  CoreMemoryResponse,
  RecallMemory,
  AgentConversation,
  AgentArtifact,
  JournalEntry,
  AgentCostBreakdown,
  PaginatedResponse,
} from "@/types/admin";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "system-prompt", label: "System Prompt" },
  { id: "core-memory", label: "Core Memory" },
  { id: "recall", label: "Recall Memories" },
  { id: "conversations", label: "Conversations" },
  { id: "artifacts", label: "Artifacts" },
  { id: "journal", label: "Journal" },
  { id: "costs", label: "Costs" },
];

const PAGE_SIZE = 20;

export default function AgentDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [error, setError] = useState<string | null>(null);

  // Lazy-loaded tab data
  const [systemPrompt, setSystemPrompt] = useState<SystemPromptResponse | null>(null);
  const [coreMemory, setCoreMemory] = useState<CoreMemoryResponse | null>(null);
  const [recallMemories, setRecallMemories] = useState<PaginatedResponse<RecallMemory> | null>(null);
  const [recallSearch, setRecallSearch] = useState("");
  const [recallOffset, setRecallOffset] = useState(0);
  const [conversations, setConversations] = useState<PaginatedResponse<AgentConversation> | null>(null);
  const [convOffset, setConvOffset] = useState(0);
  const [convSimFilter, setConvSimFilter] = useState("");
  const [artifacts, setArtifacts] = useState<PaginatedResponse<AgentArtifact> | null>(null);
  const [artOffset, setArtOffset] = useState(0);
  const [artTypeFilter, setArtTypeFilter] = useState("");
  const [artSimFilter, setArtSimFilter] = useState("");
  const [journal, setJournal] = useState<PaginatedResponse<JournalEntry> | null>(null);
  const [journalOffset, setJournalOffset] = useState(0);
  const [journalSimFilter, setJournalSimFilter] = useState("");
  const [costs, setCosts] = useState<AgentCostBreakdown | null>(null);

  // Track which tabs have been loaded
  const [loadedTabs, setLoadedTabs] = useState<Set<string>>(new Set(["overview"]));

  useEffect(() => {
    fetchAgent(id)
      .then(setAgent)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load agent"),
      );
  }, [id]);

  const loadTabData = useCallback(
    (tab: string) => {
      if (loadedTabs.has(tab)) return;
      setLoadedTabs((prev) => new Set(prev).add(tab));

      const onErr = (err: unknown) =>
        setTabError(err instanceof Error ? err.message : "Failed to load tab data");
      setTabError(null);

      switch (tab) {
        case "system-prompt":
          fetchAgentSystemPrompt(id).then(setSystemPrompt).catch(onErr);
          break;
        case "core-memory":
          fetchAgentCoreMemory(id).then(setCoreMemory).catch(onErr);
          break;
        case "recall":
          fetchAgentRecallMemories(id, { limit: PAGE_SIZE }).then(setRecallMemories).catch(onErr);
          break;
        case "conversations":
          fetchAgentConversations(id, { limit: PAGE_SIZE }).then(setConversations).catch(onErr);
          break;
        case "artifacts":
          fetchAgentArtifacts(id, { limit: PAGE_SIZE }).then(setArtifacts).catch(onErr);
          break;
        case "journal":
          fetchAgentJournal(id, { limit: PAGE_SIZE }).then(setJournal).catch(onErr);
          break;
        case "costs":
          fetchAgentCosts(id).then(setCosts).catch(onErr);
          break;
      }
    },
    [id, loadedTabs],
  );

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    loadTabData(tab);
  };

  // Tab-level error state
  const [tabError, setTabError] = useState<string | null>(null);

  // Recall memories: refetch on search/pagination change
  const refreshRecall = useCallback(() => {
    setTabError(null);
    fetchAgentRecallMemories(id, {
      search: recallSearch || undefined,
      offset: recallOffset,
      limit: PAGE_SIZE,
    })
      .then(setRecallMemories)
      .catch((err) => setTabError(err instanceof Error ? err.message : "Failed to load recall memories"));
  }, [id, recallSearch, recallOffset]);

  // Conversations: refetch on filter/pagination change
  const refreshConversations = useCallback(() => {
    setTabError(null);
    fetchAgentConversations(id, {
      simulation_id: convSimFilter || undefined,
      offset: convOffset,
      limit: PAGE_SIZE,
    })
      .then(setConversations)
      .catch((err) => setTabError(err instanceof Error ? err.message : "Failed to load conversations"));
  }, [id, convSimFilter, convOffset]);

  // Artifacts: refetch on filter/pagination change
  const refreshArtifacts = useCallback(() => {
    setTabError(null);
    fetchAgentArtifacts(id, {
      type: artTypeFilter || undefined,
      simulation_id: artSimFilter || undefined,
      offset: artOffset,
      limit: PAGE_SIZE,
    })
      .then(setArtifacts)
      .catch((err) => setTabError(err instanceof Error ? err.message : "Failed to load artifacts"));
  }, [id, artTypeFilter, artSimFilter, artOffset]);

  // Journal: refetch on filter/pagination change
  const refreshJournal = useCallback(() => {
    setTabError(null);
    fetchAgentJournal(id, {
      simulation_id: journalSimFilter || undefined,
      offset: journalOffset,
      limit: PAGE_SIZE,
    })
      .then(setJournal)
      .catch((err) => setTabError(err instanceof Error ? err.message : "Failed to load journal"));
  }, [id, journalSimFilter, journalOffset]);

  // Auto-refetch when pagination/filters change (replaces setTimeout pattern)
  useEffect(() => { if (loadedTabs.has("recall")) refreshRecall(); }, [recallOffset, refreshRecall, loadedTabs]);
  useEffect(() => { if (loadedTabs.has("conversations")) refreshConversations(); }, [convOffset, refreshConversations, loadedTabs]);
  useEffect(() => { if (loadedTabs.has("artifacts")) refreshArtifacts(); }, [artOffset, refreshArtifacts, loadedTabs]);
  useEffect(() => { if (loadedTabs.has("journal")) refreshJournal(); }, [journalOffset, refreshJournal, loadedTabs]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  if (!agent) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="max-w-6xl space-y-6">
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href="/admin/agents" className="hover:text-foreground/60">
          Agents
        </Link>
        {" / "}
        <span className="text-foreground/60">{agent.display_name}</span>
      </div>

      {/* Header */}
      <div className="flex items-center gap-3">
        <span
          className="inline-block h-4 w-4 rounded-full"
          style={{ backgroundColor: agent.color }}
        />
        <h1 className="font-pixel text-lg text-foreground">
          {agent.display_name}
        </h1>
        <span className="text-sm text-foreground/50">{agent.role}</span>
      </div>

      {/* Tabs */}
      <TabNav tabs={TABS} activeTab={activeTab} onTabChange={handleTabChange} />

      {/* Tab error */}
      {tabError && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400">
          {tabError}
        </div>
      )}

      {/* Tab content */}
      <div>
        {activeTab === "overview" && (
          <OverviewTab agent={agent} />
        )}
        {activeTab === "system-prompt" && (
          <SystemPromptTab data={systemPrompt} />
        )}
        {activeTab === "core-memory" && (
          <CoreMemoryTab data={coreMemory} />
        )}
        {activeTab === "recall" && (
          <RecallTab
            data={recallMemories}
            search={recallSearch}
            onSearchChange={(s) => { setRecallSearch(s); setRecallOffset(0); }}
            onSearch={refreshRecall}
            offset={recallOffset}
            onOffsetChange={setRecallOffset}
          />
        )}
        {activeTab === "conversations" && (
          <ConversationsTab
            data={conversations}
            simFilter={convSimFilter}
            onSimFilterChange={(v) => { setConvSimFilter(v); setConvOffset(0); }}
            onFilterChange={refreshConversations}
            offset={convOffset}
            onOffsetChange={setConvOffset}
          />
        )}
        {activeTab === "artifacts" && (
          <ArtifactsTab
            data={artifacts}
            typeFilter={artTypeFilter}
            onTypeFilterChange={(v) => { setArtTypeFilter(v); setArtOffset(0); }}
            simFilter={artSimFilter}
            onSimFilterChange={(v) => { setArtSimFilter(v); setArtOffset(0); }}
            onFilterChange={refreshArtifacts}
            offset={artOffset}
            onOffsetChange={setArtOffset}
          />
        )}
        {activeTab === "journal" && (
          <JournalTab
            data={journal}
            simFilter={journalSimFilter}
            onSimFilterChange={(v) => { setJournalSimFilter(v); setJournalOffset(0); }}
            onFilterChange={refreshJournal}
            offset={journalOffset}
            onOffsetChange={setJournalOffset}
          />
        )}
        {activeTab === "costs" && (
          <CostsTab data={costs} />
        )}
      </div>
    </div>
  );
}

// ── Tab Components ──────────────────────────────────────────────

function OverviewTab({ agent }: { agent: AgentDetail }) {
  return (
    <div className="space-y-6">
      {/* Agent info */}
      <div className="rounded-lg border border-border bg-surface p-4 space-y-3">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-foreground/40">Voice: </span>
            <span className="text-foreground/70">{agent.voice || "—"}</span>
          </div>
          <div>
            <span className="text-foreground/40">Status: </span>
            <span className="text-foreground/70">{agent.status}</span>
          </div>
          <div>
            <span className="text-foreground/40">Conversation Model: </span>
            <span className="font-mono text-xs text-foreground/70">
              {agent.conversation_model}
            </span>
          </div>
          <div>
            <span className="text-foreground/40">Building Model: </span>
            <span className="font-mono text-xs text-foreground/70">
              {agent.building_model}
            </span>
          </div>
        </div>
      </div>

      {/* Personality */}
      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-medium text-foreground/70 mb-2">
          Personality Traits
        </h3>
        <PersonalityChart traits={agent.personality_traits} />
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <SummaryCard label="Conversations" value={agent.conversation_count} />
        <SummaryCard label="Messages" value={agent.message_count} />
        <SummaryCard
          label="Cost"
          value={`$${parseFloat(agent.total_cost || "0").toFixed(4)}`}
        />
        <SummaryCard label="Artifacts" value={agent.artifact_count} />
        <SummaryCard label="Status" value={agent.status} />
      </div>
    </div>
  );
}

function SystemPromptTab({ data }: { data: SystemPromptResponse | null }) {
  const [expandedLayer, setExpandedLayer] = useState<string | null>(null);

  if (!data) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="space-y-6">
      {/* Total token count */}
      <div className="text-xs text-foreground/40">
        Total tokens: ~{data.total_tokens.toLocaleString()}
      </div>

      {/* Layer breakdown */}
      <div className="space-y-2">
        <h3 className="text-sm font-medium text-foreground/70">Layers</h3>
        {data.layers.map((layer) => (
          <div
            key={layer.name}
            className="rounded border border-border bg-surface"
          >
            <button
              onClick={() =>
                setExpandedLayer(
                  expandedLayer === layer.name ? null : layer.name,
                )
              }
              className="w-full flex items-center justify-between px-3 py-2 text-sm text-left hover:bg-surface-light transition-colors"
            >
              <span className="text-foreground/70">{layer.name}</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-foreground/40">
                  ~{layer.token_count.toLocaleString()} tokens
                </span>
                <span className="text-foreground/30">
                  {expandedLayer === layer.name ? "▲" : "▼"}
                </span>
              </div>
            </button>
            {expandedLayer === layer.name && (
              <div className="border-t border-border px-3 py-2">
                <pre className="text-xs font-mono text-foreground/60 whitespace-pre-wrap overflow-x-auto max-h-96">
                  {layer.content}
                </pre>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Full assembled prompt */}
      <div>
        <h3 className="text-sm font-medium text-foreground/70 mb-2">
          Assembled Prompt
        </h3>
        <pre className="rounded-lg border border-border bg-surface p-4 text-xs font-mono text-foreground/60 whitespace-pre-wrap overflow-x-auto max-h-[600px]">
          {data.assembled_prompt}
        </pre>
      </div>
    </div>
  );
}

function CoreMemoryTab({ data }: { data: CoreMemoryResponse | null }) {
  if (!data) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="space-y-6">
      {/* Current content */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h3 className="text-sm font-medium text-foreground/70">
            Current Content
          </h3>
          <span className="text-xs text-foreground/40">
            v{data.current_version} · ~{data.token_count} tokens
          </span>
          {data.last_updated && (
            <span className="text-xs text-foreground/40">
              Updated: {new Date(data.last_updated).toLocaleString()}
            </span>
          )}
        </div>
        <pre className="rounded-lg border border-border bg-surface p-4 text-xs font-mono text-foreground/60 whitespace-pre-wrap overflow-x-auto max-h-96">
          {data.current_content}
        </pre>
      </div>

      {/* Version history */}
      <div>
        <h3 className="text-sm font-medium text-foreground/70 mb-2">
          Version History
        </h3>
        <MemoryDiffView versions={data.version_history} />
      </div>
    </div>
  );
}

function RecallTab({
  data,
  search,
  onSearchChange,
  onSearch,
  offset,
  onOffsetChange,
}: {
  data: PaginatedResponse<RecallMemory> | null;
  search: string;
  onSearchChange: (s: string) => void;
  onSearch: () => void;
  offset: number;
  onOffsetChange: (n: number) => void;
}) {
  if (!data) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Search memories..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
          className="flex-1 rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground placeholder:text-foreground/30"
        />
        <button
          onClick={onSearch}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground/70 hover:text-foreground transition-colors"
        >
          Search
        </button>
      </div>

      {/* Results */}
      {data.items.length === 0 ? (
        <p className="text-sm text-foreground/50">No recall memories found.</p>
      ) : (
        <div className="space-y-2">
          {data.items.map((memory) => (
            <div
              key={memory.id}
              className="rounded border border-border bg-surface px-3 py-2"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono text-foreground/40">
                  {memory.event_type}
                </span>
                <span className="text-xs text-neon-cyan/70">
                  importance: {memory.importance_score.toFixed(2)}
                </span>
                <span className="text-xs text-foreground/30 ml-auto">
                  {new Date(memory.created_at).toLocaleString()}
                </span>
              </div>
              <p className="text-sm text-foreground/70">{memory.summary}</p>
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      <PaginationControls
        total={data.total}
        offset={offset}
        limit={PAGE_SIZE}
        onOffsetChange={onOffsetChange}
      />
    </div>
  );
}

function ConversationsTab({
  data,
  simFilter,
  onSimFilterChange,
  onFilterChange,
  offset,
  onOffsetChange,
}: {
  data: PaginatedResponse<AgentConversation> | null;
  simFilter: string;
  onSimFilterChange: (v: string) => void;
  onFilterChange: () => void;
  offset: number;
  onOffsetChange: (n: number) => void;
}) {
  if (!data) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="space-y-4">
      {/* Filter */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Filter by simulation ID..."
          value={simFilter}
          onChange={(e) => onSimFilterChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onFilterChange()}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground placeholder:text-foreground/30"
        />
        <button
          onClick={onFilterChange}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground/70 hover:text-foreground transition-colors"
        >
          Filter
        </button>
      </div>

      {/* Table */}
      {data.items.length === 0 ? (
        <p className="text-sm text-foreground/50">No conversations found.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th className="px-4 py-2 font-medium">Topic</th>
                <th className="px-4 py-2 font-medium">Participants</th>
                <th className="px-4 py-2 font-medium text-right">Turns</th>
                <th className="px-4 py-2 font-medium text-right">Agent Turns</th>
                <th className="px-4 py-2 font-medium">Date</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((convo) => (
                <tr
                  key={convo.id}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2">
                    <Link
                      href={`/admin/conversations/${convo.id}`}
                      className="text-neon-cyan hover:underline"
                    >
                      {convo.trigger_type}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-foreground/50">
                    {convo.participating_agents.join(", ")}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {convo.turn_count}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {convo.turn_count}
                  </td>
                  <td className="px-4 py-2 text-foreground/40 text-xs">
                    {new Date(convo.started_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <PaginationControls
        total={data.total}
        offset={offset}
        limit={PAGE_SIZE}
        onOffsetChange={onOffsetChange}
      />
    </div>
  );
}

function ArtifactsTab({
  data,
  typeFilter,
  onTypeFilterChange,
  simFilter,
  onSimFilterChange,
  onFilterChange,
  offset,
  onOffsetChange,
}: {
  data: PaginatedResponse<AgentArtifact> | null;
  typeFilter: string;
  onTypeFilterChange: (v: string) => void;
  simFilter: string;
  onSimFilterChange: (v: string) => void;
  onFilterChange: () => void;
  offset: number;
  onOffsetChange: (n: number) => void;
}) {
  if (!data) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  // Collect unique artifact types for filter
  const types = [...new Set(data.items.map((a) => a.artifact_type))].sort();

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-2">
        <select
          value={typeFilter}
          onChange={(e) => {
            onTypeFilterChange(e.target.value);
            onFilterChange();
          }}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-xs text-foreground"
        >
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Simulation ID..."
          value={simFilter}
          onChange={(e) => onSimFilterChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onFilterChange()}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground placeholder:text-foreground/30"
        />
        <button
          onClick={onFilterChange}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground/70 hover:text-foreground transition-colors"
        >
          Filter
        </button>
      </div>

      {/* Artifacts list */}
      {data.items.length === 0 ? (
        <p className="text-sm text-foreground/50">No artifacts found.</p>
      ) : (
        <div className="space-y-2">
          {data.items.map((artifact) => (
            <ArtifactDetail key={artifact.id} artifact={artifact} />
          ))}
        </div>
      )}

      <PaginationControls
        total={data.total}
        offset={offset}
        limit={PAGE_SIZE}
        onOffsetChange={onOffsetChange}
      />
    </div>
  );
}

function JournalTab({
  data,
  simFilter,
  onSimFilterChange,
  onFilterChange,
  offset,
  onOffsetChange,
}: {
  data: PaginatedResponse<JournalEntry> | null;
  simFilter: string;
  onSimFilterChange: (v: string) => void;
  onFilterChange: () => void;
  offset: number;
  onOffsetChange: (n: number) => void;
}) {
  if (!data) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="space-y-4">
      {/* Filter */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Filter by simulation ID..."
          value={simFilter}
          onChange={(e) => onSimFilterChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onFilterChange()}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground placeholder:text-foreground/30"
        />
        <button
          onClick={onFilterChange}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground/70 hover:text-foreground transition-colors"
        >
          Filter
        </button>
      </div>

      {/* Entries */}
      {data.items.length === 0 ? (
        <p className="text-sm text-foreground/50">No journal entries found.</p>
      ) : (
        <div className="space-y-3">
          {data.items.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg border border-border bg-surface p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-block rounded border border-border bg-surface-light px-2 py-0.5 text-xs font-medium text-foreground/60">
                  {entry.reflection_type}
                </span>
                <span className="text-xs text-foreground/30">
                  {new Date(entry.created_at).toLocaleString()}
                </span>
              </div>
              <pre className="text-sm text-foreground/70 whitespace-pre-wrap font-mono">
                {entry.content}
              </pre>
            </div>
          ))}
        </div>
      )}

      <PaginationControls
        total={data.total}
        offset={offset}
        limit={PAGE_SIZE}
        onOffsetChange={onOffsetChange}
      />
    </div>
  );
}

function CostsTab({ data }: { data: AgentCostBreakdown | null }) {
  if (!data) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <SummaryCard
          label="Total Cost"
          value={`$${parseFloat(data.total || "0").toFixed(4)}`}
        />
        <SummaryCard
          label="Input Tokens"
          value={data.total_input_tokens.toLocaleString()}
        />
        <SummaryCard
          label="Output Tokens"
          value={data.total_output_tokens.toLocaleString()}
        />
      </div>

      {/* Cost by day */}
      {data.by_day.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-foreground/70 mb-3">
            Cost by Day
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th className="px-4 py-2 font-medium">Date</th>
                  <th className="px-4 py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.by_day.map((entry) => (
                  <tr
                    key={entry.date}
                    className="border-b border-border last:border-0"
                  >
                    <td className="px-4 py-2 text-foreground/70">
                      {entry.date}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      ${parseFloat(entry.cost || "0").toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Cost by type */}
      {data.by_type.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-foreground/70 mb-3">
            Cost by Type
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium text-right">Tokens</th>
                  <th className="px-4 py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.by_type.map((entry) => (
                  <tr
                    key={entry.type}
                    className="border-b border-border last:border-0"
                  >
                    <td className="px-4 py-2 text-foreground/70">
                      {entry.type}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-foreground/50">
                      {entry.tokens.toLocaleString()}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      ${parseFloat(entry.cost || "0").toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Shared Pagination ───────────────────────────────────────────

function PaginationControls({
  total,
  offset,
  limit,
  onOffsetChange,
}: {
  total: number;
  offset: number;
  limit: number;
  onOffsetChange: (n: number) => void;
}) {
  if (total <= limit) return null;

  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  return (
    <div className="flex items-center justify-between text-xs text-foreground/50">
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex gap-2">
        <button
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          className="rounded border border-border px-2 py-1 disabled:opacity-30 hover:bg-surface-light transition-colors"
        >
          Prev
        </button>
        <span className="px-2 py-1">
          {page} / {totalPages}
        </span>
        <button
          disabled={offset + limit >= total}
          onClick={() => onOffsetChange(offset + limit)}
          className="rounded border border-border px-2 py-1 disabled:opacity-30 hover:bg-surface-light transition-colors"
        >
          Next
        </button>
      </div>
    </div>
  );
}
