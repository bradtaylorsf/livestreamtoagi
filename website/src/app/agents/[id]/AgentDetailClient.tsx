"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import PersonalityRadar from "@/components/PersonalityRadar";
import RelationshipGraph from "@/components/RelationshipGraph";
import EvolutionTimeline from "@/components/EvolutionTimeline";
import type { AgentData } from "@/lib/agent-data";
import {
  getAgentSystemPrompt,
  getAgentCoreMemory,
  getAgentRecallMemories,
  getAgentConversations,
  getAgentArtifacts,
  getAgentJournal,
  getAgentCosts,
} from "@/lib/api";
import {
  getCurrentSimulationId,
  setCurrentSimulationId,
} from "@/lib/simulation-store";
import type {
  SystemPromptResponse,
  AgentCostBreakdown,
} from "@/lib/api";
import type {
  CoreMemoryPublic,
  CoreMemoryVersion,
  RecallMemoryPublic,
  AgentConversation,
  AgentArtifactResponse,
  JournalEntry,
  PaginatedResponse,
} from "@/types";

// -- Constants ---------------------------------------------------------------

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "system-prompt", label: "System Prompt" },
  { id: "core-memory", label: "Core Memory" },
  { id: "recall", label: "Recall Memories" },
  { id: "conversations", label: "Conversations" },
  { id: "artifacts", label: "Artifacts" },
  { id: "journal", label: "Journal" },
  { id: "relationships", label: "Relationships" },
  { id: "evolution", label: "Evolution" },
  { id: "costs", label: "Costs" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const PAGE_SIZE = 20;

// -- Props -------------------------------------------------------------------

interface Props {
  agent: AgentData;
}

// -- Main client component ---------------------------------------------------

export default function AgentDetailClient({ agent }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = agent.id;

  // Active tab from URL query param (defaults to "overview")
  const tabParam = searchParams.get("tab") as TabId | null;
  const activeTab: TabId =
    tabParam && TABS.some((t) => t.id === tabParam) ? tabParam : "overview";

  const setActiveTab = useCallback(
    (tab: TabId) => {
      const sp = new URLSearchParams(searchParams.toString());
      sp.set("tab", tab);
      router.replace(`?${sp.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  // -- Lazy-loaded tab data state -------------------------------------------

  const [systemPrompt, setSystemPrompt] = useState<SystemPromptResponse | null>(null);
  const [coreMemory, setCoreMemory] = useState<CoreMemoryPublic | null>(null);

  const [recallMemories, setRecallMemories] = useState<PaginatedResponse<RecallMemoryPublic> | null>(null);
  const [recallSearch, setRecallSearch] = useState("");
  const [recallOffset, setRecallOffset] = useState(0);

  const [conversations, setConversations] = useState<PaginatedResponse<AgentConversation> | null>(null);
  const [convOffset, setConvOffset] = useState(0);
  const [convSimFilter, setConvSimFilter] = useState(
    () => getCurrentSimulationId() ?? "",
  );

  const [artifacts, setArtifacts] = useState<PaginatedResponse<AgentArtifactResponse> | null>(null);
  const [artOffset, setArtOffset] = useState(0);
  const [artTypeFilter, setArtTypeFilter] = useState("");
  const [artSimFilter, setArtSimFilter] = useState(
    () => getCurrentSimulationId() ?? "",
  );

  const [journal, setJournal] = useState<JournalEntry[] | null>(null);
  const [journalSimFilter, setJournalSimFilter] = useState(
    () => getCurrentSimulationId() ?? "",
  );

  const [costs, setCosts] = useState<AgentCostBreakdown | null>(null);

  // -- Overview stats (fetched eagerly) -------------------------------------

  const [overviewStats, setOverviewStats] = useState<{
    conversations: number | null;
    artifacts: number | null;
    cost: string | null;
  }>({ conversations: null, artifacts: null, cost: null });

  // -- Tab loading tracking -------------------------------------------------

  const [loadedTabs, setLoadedTabs] = useState<Set<string>>(new Set(["overview"]));
  const [tabLoading, setTabLoading] = useState<Set<string>>(new Set());
  const [tabError, setTabError] = useState<string | null>(null);

  const markLoading = (tab: string) =>
    setTabLoading((prev) => new Set(prev).add(tab));
  const clearLoading = (tab: string) =>
    setTabLoading((prev) => {
      const next = new Set(prev);
      next.delete(tab);
      return next;
    });

  // Load overview stats on mount.
  // Scope is intentionally lifetime (no simulation_id) so all three numbers
  // reflect the same "across every simulation this agent has participated in"
  // view. Once Epic 2 ships an active-simulation provider, swap in the
  // selected sim id here so all three queries scope together.
  useEffect(() => {
    Promise.allSettled([
      getAgentConversations(id, { limit: 1, offset: 0 }),
      getAgentArtifacts(id, { limit: 1, offset: 0 }),
      getAgentCosts(id),
    ]).then(([convResult, artResult, costResult]) => {
      setOverviewStats({
        conversations:
          convResult.status === "fulfilled" ? convResult.value.total : null,
        artifacts:
          artResult.status === "fulfilled" ? artResult.value.total : null,
        cost:
          costResult.status === "fulfilled"
            ? `$${parseFloat(costResult.value.total || "0").toFixed(4)}`
            : null,
      });
    });
  }, [id]);

  // -- Tab data loaders -----------------------------------------------------

  const loadTabData = useCallback(
    (tab: string) => {
      if (loadedTabs.has(tab)) return;
      setLoadedTabs((prev) => new Set(prev).add(tab));
      setTabError(null);
      markLoading(tab);

      const onErr = (err: unknown) => {
        setTabError(
          err instanceof Error ? err.message : "Failed to load tab data",
        );
        clearLoading(tab);
      };
      const done = () => clearLoading(tab);

      switch (tab) {
        case "system-prompt":
          getAgentSystemPrompt(id).then((d) => { setSystemPrompt(d); done(); }).catch(onErr);
          break;
        case "core-memory":
          getAgentCoreMemory(id).then((d) => { setCoreMemory(d); done(); }).catch(onErr);
          break;
        case "recall":
          getAgentRecallMemories(id, { limit: PAGE_SIZE }).then((d) => { setRecallMemories(d); done(); }).catch(onErr);
          break;
        case "conversations":
          getAgentConversations(id, { limit: PAGE_SIZE }).then((d) => { setConversations(d); done(); }).catch(onErr);
          break;
        case "artifacts":
          getAgentArtifacts(id, { limit: PAGE_SIZE }).then((d) => { setArtifacts(d); done(); }).catch(onErr);
          break;
        case "journal":
          getAgentJournal(id, { limit: PAGE_SIZE }).then((d) => { setJournal(d); done(); }).catch(onErr);
          break;
        case "costs":
          getAgentCosts(id).then((d) => { setCosts(d); done(); }).catch(onErr);
          break;
        // relationships + evolution are self-loading components
      }
    },
    [id, loadedTabs],
  );

  const handleTabChange = (tab: TabId) => {
    setActiveTab(tab);
    loadTabData(tab);
  };

  // Load initial tab data if deep-linked to a non-overview tab
  useEffect(() => {
    if (activeTab !== "overview") {
      loadTabData(activeTab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -- Recall: refetch on search/pagination ---------------------------------

  const refreshRecall = useCallback(() => {
    setTabError(null);
    markLoading("recall");
    getAgentRecallMemories(id, {
      search: recallSearch || undefined,
      offset: recallOffset,
      limit: PAGE_SIZE,
    })
      .then((d) => { setRecallMemories(d); clearLoading("recall"); })
      .catch((err) => {
        setTabError(err instanceof Error ? err.message : "Failed to load recall memories");
        clearLoading("recall");
      });
  }, [id, recallSearch, recallOffset]);

  // -- Conversations: refetch on filter/pagination --------------------------

  const refreshConversations = useCallback(() => {
    setTabError(null);
    markLoading("conversations");
    getAgentConversations(id, {
      simulation_id: convSimFilter || undefined,
      offset: convOffset,
      limit: PAGE_SIZE,
    })
      .then((d) => { setConversations(d); clearLoading("conversations"); })
      .catch((err) => {
        setTabError(err instanceof Error ? err.message : "Failed to load conversations");
        clearLoading("conversations");
      });
  }, [id, convSimFilter, convOffset]);

  // -- Artifacts: refetch on filter/pagination ------------------------------

  const refreshArtifacts = useCallback(() => {
    setTabError(null);
    markLoading("artifacts");
    getAgentArtifacts(id, {
      type: artTypeFilter || undefined,
      simulation_id: artSimFilter || undefined,
      offset: artOffset,
      limit: PAGE_SIZE,
    })
      .then((d) => { setArtifacts(d); clearLoading("artifacts"); })
      .catch((err) => {
        setTabError(err instanceof Error ? err.message : "Failed to load artifacts");
        clearLoading("artifacts");
      });
  }, [id, artTypeFilter, artSimFilter, artOffset]);

  // -- Journal: refetch on filter -------------------------------------------

  const refreshJournal = useCallback(() => {
    setTabError(null);
    markLoading("journal");
    getAgentJournal(id, {
      simulation_id: journalSimFilter || undefined,
      limit: PAGE_SIZE,
    })
      .then((d) => { setJournal(d); clearLoading("journal"); })
      .catch((err) => {
        setTabError(err instanceof Error ? err.message : "Failed to load journal");
        clearLoading("journal");
      });
  }, [id, journalSimFilter]);

  // Auto-refetch when pagination/filters change
  useEffect(() => {
    if (loadedTabs.has("recall")) refreshRecall();
  }, [recallOffset, refreshRecall, loadedTabs]);
  useEffect(() => {
    if (loadedTabs.has("conversations")) refreshConversations();
  }, [convOffset, refreshConversations, loadedTabs]);
  useEffect(() => {
    if (loadedTabs.has("artifacts")) refreshArtifacts();
  }, [artOffset, refreshArtifacts, loadedTabs]);

  // -- Render ---------------------------------------------------------------

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 space-y-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-foreground/40" aria-label="Breadcrumb">
        <Link href="/agents" className="hover:text-foreground/60">
          Agents
        </Link>
        {" / "}
        <span className="text-foreground/60">{agent.name}</span>
      </nav>

      {/* Header Section */}
      <AgentHeader agent={agent} />

      {/* Tab Navigation */}
      <div
        className="flex gap-1 border-b border-border overflow-x-auto"
        role="tablist"
        aria-label="Agent detail tabs"
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls={`panel-${tab.id}`}
            onClick={() => handleTabChange(tab.id)}
            className={`px-4 py-2 text-sm whitespace-nowrap transition-colors border-b-2 -mb-px ${
              activeTab === tab.id
                ? "border-neon-cyan text-neon-cyan"
                : "border-transparent text-foreground/50 hover:text-foreground/70"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab-level error */}
      {tabError && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400">
          {tabError}
        </div>
      )}

      {/* Tab Panels */}
      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
      >
        {activeTab === "overview" && (
          <OverviewTab agent={agent} stats={overviewStats} />
        )}

        {activeTab === "system-prompt" && (
          <SystemPromptTab
            data={systemPrompt}
            loading={tabLoading.has("system-prompt")}
          />
        )}

        {activeTab === "core-memory" && (
          <CoreMemoryTab
            data={coreMemory}
            loading={tabLoading.has("core-memory")}
          />
        )}

        {activeTab === "recall" && (
          <RecallTab
            data={recallMemories}
            loading={tabLoading.has("recall")}
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
            loading={tabLoading.has("conversations")}
            simFilter={convSimFilter}
            onSimFilterChange={(v) => {
              setConvSimFilter(v);
              setCurrentSimulationId(v || null);
              setConvOffset(0);
            }}
            onFilterChange={refreshConversations}
            offset={convOffset}
            onOffsetChange={setConvOffset}
          />
        )}

        {activeTab === "artifacts" && (
          <ArtifactsTab
            data={artifacts}
            loading={tabLoading.has("artifacts")}
            typeFilter={artTypeFilter}
            onTypeFilterChange={(v) => { setArtTypeFilter(v); setArtOffset(0); }}
            simFilter={artSimFilter}
            onSimFilterChange={(v) => {
              setArtSimFilter(v);
              setCurrentSimulationId(v || null);
              setArtOffset(0);
            }}
            onFilterChange={refreshArtifacts}
            offset={artOffset}
            onOffsetChange={setArtOffset}
          />
        )}

        {activeTab === "journal" && (
          <JournalTab
            data={journal}
            loading={tabLoading.has("journal")}
            simFilter={journalSimFilter}
            onSimFilterChange={(v) => {
              setJournalSimFilter(v);
              setCurrentSimulationId(v || null);
            }}
            onFilterChange={refreshJournal}
          />
        )}

        {activeTab === "relationships" && (
          <RelationshipGraph agentId={id} />
        )}

        {activeTab === "evolution" && (
          <EvolutionTimeline agentId={id} />
        )}

        {activeTab === "costs" && (
          <CostsTab data={costs} loading={tabLoading.has("costs")} />
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Sub-components
// ============================================================================

// -- Header ------------------------------------------------------------------

function AgentHeader({ agent }: { agent: AgentData }) {
  return (
    <div className="flex flex-col sm:flex-row gap-6">
      {/* Colored circle avatar */}
      <div
        className="w-24 h-24 sm:w-32 sm:h-32 rounded-full shrink-0 flex items-center justify-center font-pixel text-3xl text-white/80 mx-auto sm:mx-0"
        style={{ backgroundColor: agent.color }}
        role="img"
        aria-label={`${agent.name} avatar`}
      >
        {agent.name[0]}
      </div>

      <div className="flex-1 min-w-0">
        {/* Name, tagline, role */}
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="font-pixel text-xl" style={{ color: agent.color }}>
            {agent.name}
          </h1>
          <span className="text-foreground/50 text-sm">{agent.tagline}</span>
        </div>
        <p className="text-foreground/70 mt-1">{agent.role}</p>

        {/* Model / voice badges */}
        <div className="flex flex-wrap gap-2 mt-3">
          <ModelBadge label="Chat" value={agent.models.conversation} />
          {agent.models.building && (
            <ModelBadge label="Build" value={agent.models.building} />
          )}
          {agent.voiceId && <ModelBadge label="Voice" value={agent.voiceId} />}
        </div>

        {/* Backstory */}
        <div className="mt-4">
          <h2 className="font-pixel text-xs text-neon-magenta mb-2">ABOUT</h2>
          <p className="text-sm text-foreground/70">{agent.backstory}</p>
        </div>

        {/* Personality trait badges */}
        <div className="mt-4">
          <h3 className="text-xs text-foreground/40 uppercase mb-2">
            Personality
          </h3>
          <div className="flex flex-wrap gap-2">
            {agent.personalityTraits.map((trait) => (
              <span
                key={trait}
                className="text-xs rounded-full bg-surface-light border border-border px-3 py-1 text-foreground/60"
              >
                {trait}
              </span>
            ))}
          </div>
        </div>

        {/* Catchphrases */}
        <div className="mt-4">
          <h3 className="text-xs text-foreground/40 uppercase mb-2">
            Catchphrases
          </h3>
          <div className="flex flex-wrap gap-2">
            {agent.catchphrases.map((phrase) => (
              <span
                key={phrase}
                className="text-xs rounded bg-surface border border-border px-2 py-1 text-foreground/50 italic"
              >
                &ldquo;{phrase}&rdquo;
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ModelBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-xs rounded bg-surface-light border border-border px-2 py-1 text-foreground/50">
      {label}: {value}
    </span>
  );
}

// -- Loading Spinner ---------------------------------------------------------

function TabSpinner() {
  return (
    <div className="flex justify-center py-12">
      <span className="text-sm text-foreground/40 animate-pulse">
        Loading...
      </span>
    </div>
  );
}

// -- Overview Tab -------------------------------------------------------------

function OverviewTab({
  agent,
  stats,
}: {
  agent: AgentData;
  stats: {
    conversations: number | null;
    artifacts: number | null;
    cost: string | null;
  };
}) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h2 className="font-pixel text-xs text-neon-magenta mb-3">
            PERSONALITY
          </h2>
          <div className="rounded border border-border bg-surface p-4">
            <PersonalityRadar traits={agent.traits} color={agent.color} />
          </div>
        </div>

        <div>
          <h2 className="font-pixel text-xs text-neon-magenta mb-3">STATS</h2>
          <div className="grid grid-cols-2 gap-3">
            <StatCard
              label="Conversations"
              value={stats.conversations != null ? String(stats.conversations) : "..."}
              loading={stats.conversations == null}
            />
            <StatCard
              label="Artifacts"
              value={stats.artifacts != null ? String(stats.artifacts) : "..."}
              loading={stats.artifacts == null}
            />
            <StatCard
              label="Total Cost"
              value={stats.cost ?? "..."}
              loading={stats.cost == null}
            />
            <StatCard label="Status" value="Active" loading={false} />
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  loading,
}: {
  label: string;
  value: string;
  loading: boolean;
}) {
  return (
    <div className="rounded border border-border bg-surface p-3 text-center">
      <div
        className={`font-pixel text-sm text-neon-cyan ${loading ? "animate-pulse" : ""}`}
      >
        {value}
      </div>
      <div className="text-xs text-foreground/40 mt-1">{label}</div>
    </div>
  );
}

// -- System Prompt Tab -------------------------------------------------------

function SystemPromptTab({
  data,
  loading,
}: {
  data: SystemPromptResponse | null;
  loading: boolean;
}) {
  const [expandedLayer, setExpandedLayer] = useState<string | null>(null);

  if (loading || !data) return <TabSpinner />;

  return (
    <div className="space-y-6">
      <div className="text-xs text-foreground/40">
        Total tokens: ~{data.total_tokens.toLocaleString()}
      </div>

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
              aria-expanded={expandedLayer === layer.name}
            >
              <span className="text-foreground/70">{layer.name}</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-foreground/40">
                  ~{layer.token_count.toLocaleString()} tokens
                </span>
                <span className="text-foreground/30">
                  {expandedLayer === layer.name ? "\u25B2" : "\u25BC"}
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

// -- Core Memory Tab ---------------------------------------------------------

function CoreMemoryTab({
  data,
  loading,
}: {
  data: CoreMemoryPublic | null;
  loading: boolean;
}) {
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null);

  if (loading || !data) return <TabSpinner />;

  return (
    <div className="space-y-6">
      {/* Current content */}
      <div>
        <div className="flex items-center gap-3 mb-2 flex-wrap">
          <h3 className="text-sm font-medium text-foreground/70">
            Current Content
          </h3>
          <span className="text-xs text-foreground/40">
            v{data.current_version} &middot; ~{data.token_count} tokens
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
        {data.version_history.length === 0 ? (
          <p className="text-sm text-foreground/50">
            No version history available.
          </p>
        ) : (
          <div className="space-y-2">
            {data.version_history.map((version: CoreMemoryVersion) => {
              const isExpanded = expandedVersion === version.version;
              return (
                <div
                  key={version.version}
                  className="rounded border border-border bg-surface"
                >
                  <button
                    onClick={() =>
                      setExpandedVersion(isExpanded ? null : version.version)
                    }
                    className="w-full flex items-center justify-between px-3 py-2 text-sm text-left hover:bg-surface-light transition-colors"
                    aria-expanded={isExpanded}
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-foreground/50">
                        v{version.version}
                      </span>
                      {version.changed_at && (
                        <span className="text-xs text-foreground/40">
                          {new Date(version.changed_at).toLocaleString()}
                        </span>
                      )}
                      {version.change_reason && (
                        <span className="text-xs text-foreground/50">
                          &mdash; {version.change_reason}
                        </span>
                      )}
                    </div>
                    <span className="text-foreground/30">
                      {isExpanded ? "\u25B2" : "\u25BC"}
                    </span>
                  </button>
                  {isExpanded && (
                    <div className="border-t border-border px-3 py-2">
                      <pre className="text-xs font-mono text-foreground/60 whitespace-pre-wrap overflow-x-auto max-h-64">
                        {version.content}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// -- Recall Memories Tab -----------------------------------------------------

function RecallTab({
  data,
  loading,
  search,
  onSearchChange,
  onSearch,
  offset,
  onOffsetChange,
}: {
  data: PaginatedResponse<RecallMemoryPublic> | null;
  loading: boolean;
  search: string;
  onSearchChange: (s: string) => void;
  onSearch: () => void;
  offset: number;
  onOffsetChange: (n: number) => void;
}) {
  if (loading && !data) return <TabSpinner />;
  if (!data) return <TabSpinner />;

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
                {memory.event_type && (
                  <span className="text-xs font-mono text-foreground/40">
                    {memory.event_type}
                  </span>
                )}
                {memory.importance_score != null && (
                  <span className="text-xs text-neon-cyan/70">
                    importance: {memory.importance_score.toFixed(2)}
                  </span>
                )}
                {memory.created_at && (
                  <span className="text-xs text-foreground/30 ml-auto">
                    {new Date(memory.created_at).toLocaleString()}
                  </span>
                )}
              </div>
              <p className="text-sm text-foreground/70">{memory.summary}</p>
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

// -- Conversations Tab -------------------------------------------------------

function ConversationsTab({
  data,
  loading,
  simFilter,
  onSimFilterChange,
  onFilterChange,
  offset,
  onOffsetChange,
}: {
  data: PaginatedResponse<AgentConversation> | null;
  loading: boolean;
  simFilter: string;
  onSimFilterChange: (v: string) => void;
  onFilterChange: () => void;
  offset: number;
  onOffsetChange: (n: number) => void;
}) {
  if (loading && !data) return <TabSpinner />;
  if (!data) return <TabSpinner />;

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
                <th scope="col" className="px-4 py-2 font-medium">Date</th>
                <th scope="col" className="px-4 py-2 font-medium">Participants</th>
                <th scope="col" className="px-4 py-2 font-medium">Topics</th>
                <th scope="col" className="px-4 py-2 font-medium text-right">Turns</th>
                <th scope="col" className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {data.items.map((convo) => (
                <tr
                  key={convo.id}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2 text-foreground/40 text-xs whitespace-nowrap">
                    {convo.started_at
                      ? new Date(convo.started_at).toLocaleString()
                      : "\u2014"}
                  </td>
                  <td className="px-4 py-2 text-foreground/50 text-xs">
                    {convo.participating_agents.join(", ")}
                  </td>
                  <td className="px-4 py-2 text-foreground/50 text-xs">
                    {convo.topics_discussed?.join(", ") || convo.trigger_type}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {convo.turn_count}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Link
                      href={`/conversations/${convo.id}`}
                      className="text-neon-cyan hover:underline text-xs"
                    >
                      View &rarr;
                    </Link>
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

// -- Artifacts Tab -----------------------------------------------------------

function ArtifactsTab({
  data,
  loading,
  typeFilter,
  onTypeFilterChange,
  simFilter,
  onSimFilterChange,
  onFilterChange,
  offset,
  onOffsetChange,
}: {
  data: PaginatedResponse<AgentArtifactResponse> | null;
  loading: boolean;
  typeFilter: string;
  onTypeFilterChange: (v: string) => void;
  simFilter: string;
  onSimFilterChange: (v: string) => void;
  onFilterChange: () => void;
  offset: number;
  onOffsetChange: (n: number) => void;
}) {
  if (loading && !data) return <TabSpinner />;
  if (!data) return <TabSpinner />;

  const types = [...new Set(data.items.map((a) => a.artifact_type))].sort();

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
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

      {/* Artifact cards */}
      {data.items.length === 0 ? (
        <p className="text-sm text-foreground/50">No artifacts found.</p>
      ) : (
        <div className="space-y-2">
          {data.items.map((artifact) => (
            <ArtifactCard key={artifact.id} artifact={artifact} />
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

function ArtifactCard({ artifact }: { artifact: AgentArtifactResponse }) {
  const statusClass =
    artifact.status === "success" || artifact.status === "executed"
      ? "bg-green-500/10 text-green-400"
      : artifact.status === "error" || artifact.status === "failed"
        ? "bg-red-500/10 text-red-400"
        : "bg-yellow-500/10 text-yellow-400";

  return (
    <div className="rounded border border-border bg-surface px-3 py-2">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-mono text-foreground/70">
          {artifact.tool_name}
        </span>
        <span className="text-xs text-foreground/30">
          {artifact.artifact_type}
        </span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${statusClass}`}>
          {artifact.status}
        </span>
        {artifact.created_at && (
          <span className="text-xs text-foreground/30 ml-auto">
            {new Date(artifact.created_at).toLocaleString()}
          </span>
        )}
      </div>
      {artifact.summary && (
        <p className="text-xs text-foreground/50 truncate">{artifact.summary}</p>
      )}
    </div>
  );
}

// -- Journal Tab -------------------------------------------------------------

function JournalTab({
  data,
  loading,
  simFilter,
  onSimFilterChange,
  onFilterChange,
}: {
  data: JournalEntry[] | null;
  loading: boolean;
  simFilter: string;
  onSimFilterChange: (v: string) => void;
  onFilterChange: () => void;
}) {
  if (loading && !data) return <TabSpinner />;
  if (!data) return <TabSpinner />;

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
      {data.length === 0 ? (
        <p className="text-sm text-foreground/50">No journal entries found.</p>
      ) : (
        <div className="space-y-3">
          {data.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg border border-border bg-surface p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-block rounded border border-border bg-surface-light px-2 py-0.5 text-xs font-medium text-foreground/60">
                  {entry.mood}
                </span>
                <span className="text-xs text-foreground/30">
                  {new Date(entry.timestamp).toLocaleString()}
                </span>
              </div>
              <p className="text-sm text-foreground/70 whitespace-pre-wrap">
                {entry.content}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// -- Costs Tab ---------------------------------------------------------------

function CostsTab({
  data,
  loading,
}: {
  data: AgentCostBreakdown | null;
  loading: boolean;
}) {
  if (loading || !data) return <TabSpinner />;

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <CostSummaryCard
          label="Total Cost"
          value={`$${parseFloat(data.total || "0").toFixed(4)}`}
        />
        <CostSummaryCard
          label="Input Tokens"
          value={data.total_input_tokens.toLocaleString()}
        />
        <CostSummaryCard
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
                  <th scope="col" className="px-4 py-2 font-medium">Date</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Cost</th>
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
                  <th scope="col" className="px-4 py-2 font-medium">Type</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Tokens</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Cost</th>
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

function CostSummaryCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-light p-4">
      <p className="text-xs text-foreground/50 mb-1">{label}</p>
      <p className="text-xl font-mono text-foreground">{value}</p>
    </div>
  );
}

// -- Pagination Controls -----------------------------------------------------

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
        {offset + 1}&ndash;{Math.min(offset + limit, total)} of {total}
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
