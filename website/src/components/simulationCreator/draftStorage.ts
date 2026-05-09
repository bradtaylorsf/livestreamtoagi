import type { PublicFaction, PublicMemorySeed, PublicScenarioMeta } from "@/lib/api";

import {
  DEFAULT_AGENT_ENERGY,
  DEFAULT_MAX_COST_USD,
  MAX_AGENT_ENERGY,
  MAX_CADENCE,
  MIN_AGENT_ENERGY,
  MIN_CADENCE,
  initialState,
  noneSeed,
  type CreatorFormState,
} from "./state";

const DRAFT_VERSION = 1;
export const CREATOR_DRAFT_STORAGE_KEY =
  "livestreamtoagi.simulationCreatorDraft.v1";

interface StoredCreatorDraft {
  version: typeof DRAFT_VERSION;
  saved_at: string;
  state: {
    scenario_id: string;
    name: string;
    hypothesis: string;
    excluded_agents: string[];
    factions: PublicFaction[];
    memory_seed: PublicMemorySeed;
    memory_seed_raw_json: string;
    max_cost: number;
    publish_to_youtube: boolean;
    conversation_cadence: number;
    energy: Record<string, number>;
  };
}

function getStorage(kind: "local" | "session"): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function getDraftStores(): Storage[] {
  const stores = [getStorage("local"), getStorage("session")].filter(
    (store): store is Storage => store !== null,
  );
  return [...new Set(stores)];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function readMemorySeed(value: unknown): PublicMemorySeed {
  if (!isRecord(value) || typeof value.mode !== "string") {
    return noneSeed();
  }
  if (value.mode === "inherit") {
    return typeof value.simulation_id === "string"
      ? { mode: "inherit", simulation_id: value.simulation_id }
      : { mode: "inherit", simulation_id: "" };
  }
  if (value.mode === "custom") {
    return "data" in value
      ? { mode: "custom", data: value.data }
      : { mode: "custom", data: null };
  }
  return noneSeed();
}

function readFactions(value: unknown): PublicFaction[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((item) => ({
      name: typeof item.name === "string" ? item.name : "",
      members: stringArray(item.members),
      goal: typeof item.goal === "string" ? item.goal : "",
    }));
}

function readEnergy(value: unknown, scenarioAgents: string[]): Record<string, number> {
  const source = isRecord(value) ? value : {};
  return Object.fromEntries(
    scenarioAgents.map((agent) => [
      agent,
      clamp(
        finiteNumber(source[agent], DEFAULT_AGENT_ENERGY),
        MIN_AGENT_ENERGY,
        MAX_AGENT_ENERGY,
      ),
    ]),
  );
}

function parseDraft(raw: string): StoredCreatorDraft | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.version !== DRAFT_VERSION) return null;
    if (!isRecord(parsed.state)) return null;

    const state = parsed.state;
    if (typeof state.scenario_id !== "string") return null;
    return {
      version: DRAFT_VERSION,
      saved_at: typeof parsed.saved_at === "string" ? parsed.saved_at : "",
      state: {
        scenario_id: state.scenario_id,
        name: typeof state.name === "string" ? state.name : "",
        hypothesis: typeof state.hypothesis === "string" ? state.hypothesis : "",
        excluded_agents: stringArray(state.excluded_agents),
        factions: readFactions(state.factions),
        memory_seed: readMemorySeed(state.memory_seed),
        memory_seed_raw_json:
          typeof state.memory_seed_raw_json === "string"
            ? state.memory_seed_raw_json
            : "{}",
        max_cost: finiteNumber(state.max_cost, DEFAULT_MAX_COST_USD),
        publish_to_youtube: state.publish_to_youtube === true,
        conversation_cadence: clamp(
          finiteNumber(state.conversation_cadence, 1),
          MIN_CADENCE,
          MAX_CADENCE,
        ),
        energy: isRecord(state.energy)
          ? Object.fromEntries(
              Object.entries(state.energy)
                .filter(([agent]) => typeof agent === "string")
                .map(([agent, value]) => [
                  agent,
                  clamp(
                    finiteNumber(value, DEFAULT_AGENT_ENERGY),
                    MIN_AGENT_ENERGY,
                    MAX_AGENT_ENERGY,
                  ),
                ]),
            )
          : {},
      },
    };
  } catch {
    return null;
  }
}

export function loadCreatorDraft(opts: {
  scenarios: PublicScenarioMeta[];
  remainingBudget: number | null;
}): CreatorFormState | null {
  const stores = getDraftStores();
  if (stores.length === 0) return null;

  let raw: string | null = null;
  for (const storage of stores) {
    raw = storage.getItem(CREATOR_DRAFT_STORAGE_KEY);
    if (raw) break;
  }
  if (!raw) return null;

  const draft = parseDraft(raw);
  if (!draft) {
    clearCreatorDraft();
    return null;
  }

  const scenario = opts.scenarios.find(
    (candidate) => candidate.filename === draft.state.scenario_id,
  );
  if (!scenario) {
    clearCreatorDraft();
    return null;
  }

  const baseline = initialState({
    scenarios: opts.scenarios,
    initialScenarioId: scenario.filename,
    remainingBudget: opts.remainingBudget,
  });

  return {
    ...baseline,
    ...draft.state,
    scenario_agents: scenario.agents,
    excluded_agents: draft.state.excluded_agents.filter((agent) =>
      scenario.agents.includes(agent),
    ),
    energy: readEnergy(draft.state.energy, scenario.agents),
    remaining_budget: opts.remainingBudget,
  };
}

export function saveCreatorDraft(state: CreatorFormState): void {
  const draft: StoredCreatorDraft = {
    version: DRAFT_VERSION,
    saved_at: new Date().toISOString(),
    state: {
      scenario_id: state.scenario_id,
      name: state.name,
      hypothesis: state.hypothesis,
      excluded_agents: state.excluded_agents,
      factions: state.factions,
      memory_seed: state.memory_seed,
      memory_seed_raw_json: state.memory_seed_raw_json,
      max_cost: state.max_cost,
      publish_to_youtube: state.publish_to_youtube,
      conversation_cadence: state.conversation_cadence,
      energy: state.energy,
    },
  };

  const serialized = JSON.stringify(draft);
  for (const storage of getDraftStores()) {
    try {
      storage.setItem(CREATOR_DRAFT_STORAGE_KEY, serialized);
      return;
    } catch {
      // Private browsing or quota errors should not block form submission.
    }
  }
}

export function clearCreatorDraft(): void {
  for (const storage of getDraftStores()) {
    try {
      storage.removeItem(CREATOR_DRAFT_STORAGE_KEY);
    } catch {
      // Storage is best-effort only.
    }
  }
}
