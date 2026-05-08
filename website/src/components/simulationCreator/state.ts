import type {
  PublicFaction,
  PublicMemorySeed,
  PublicScenarioMeta,
  PublicSubmitParams,
  PublicSubmitRequest,
} from "@/lib/api";

import type { CreatorFormValues } from "./validation";

export const DEFAULT_LIFETIME_CAP_USD = 10;
export const DEFAULT_MAX_COST_USD = 1;
export const MIN_CADENCE = 0.5;
export const MAX_CADENCE = 2.0;
export const DEFAULT_CADENCE = 1.0;
export const MIN_AGENT_ENERGY = 0;
export const MAX_AGENT_ENERGY = 100;
export const DEFAULT_AGENT_ENERGY = 75;

export function emptyFaction(): PublicFaction {
  return { name: "", members: [], goal: "" };
}

export function noneSeed(): PublicMemorySeed {
  return { mode: "none" };
}

export interface CreatorFormState extends CreatorFormValues {
  publish_to_youtube: boolean;
  conversation_cadence: number;
  energy: Record<string, number>;
}

export function initialState(opts: {
  scenarios: PublicScenarioMeta[];
  initialScenarioId: string | null;
  remainingBudget: number | null;
  perSubmissionCap?: number;
}): CreatorFormState {
  const { scenarios, initialScenarioId, remainingBudget } = opts;
  const perSubmissionCap = opts.perSubmissionCap ?? DEFAULT_MAX_COST_USD;
  const picked =
    scenarios.find((s) => s.filename === initialScenarioId) ??
    scenarios[0] ??
    null;
  const scenario_agents = picked?.agents ?? [];
  const cap = remainingBudget == null ? perSubmissionCap : Math.min(perSubmissionCap, remainingBudget);
  return {
    scenario_id: picked?.filename ?? "",
    name: picked ? `${picked.name} run` : "",
    hypothesis: "",
    excluded_agents: [],
    scenario_agents,
    factions: [],
    memory_seed: noneSeed(),
    memory_seed_raw_json: "{}",
    max_cost: Math.max(0.01, Math.min(perSubmissionCap, cap)),
    remaining_budget: remainingBudget,
    publish_to_youtube: false,
    conversation_cadence: DEFAULT_CADENCE,
    energy: Object.fromEntries(scenario_agents.map((a) => [a, DEFAULT_AGENT_ENERGY])),
  };
}

export function reseedForScenario(
  state: CreatorFormState,
  scenario: PublicScenarioMeta,
): CreatorFormState {
  const energy: Record<string, number> = {};
  for (const a of scenario.agents) {
    energy[a] = state.energy[a] ?? DEFAULT_AGENT_ENERGY;
  }
  return {
    ...state,
    scenario_id: scenario.filename,
    scenario_agents: scenario.agents,
    excluded_agents: state.excluded_agents.filter((a) => scenario.agents.includes(a)),
    energy,
    name: state.name.trim() ? state.name : `${scenario.name} run`,
  };
}

export function toggleAgent(state: CreatorFormState, agent: string): CreatorFormState {
  const excluded = state.excluded_agents.includes(agent)
    ? state.excluded_agents.filter((a) => a !== agent)
    : [...state.excluded_agents, agent];
  return { ...state, excluded_agents: excluded };
}

export function activeAgents(state: CreatorFormState): string[] {
  return state.scenario_agents.filter((a) => !state.excluded_agents.includes(a));
}

export function buildSubmitPayload(state: CreatorFormState): PublicSubmitRequest {
  const params: PublicSubmitParams = {
    max_cost: state.max_cost,
    conversation_cadence: state.conversation_cadence,
  };
  if (state.excluded_agents.length > 0) {
    params.excluded_agents = state.excluded_agents;
    params.agents = activeAgents(state);
  }
  if (state.factions.length > 0) {
    params.factions = state.factions;
  }
  if (state.memory_seed.mode === "inherit") {
    params.memory_seed = state.memory_seed;
  } else if (state.memory_seed.mode === "custom") {
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(state.memory_seed_raw_json);
    } catch {
      parsed = null;
    }
    params.memory_seed = { mode: "custom", data: parsed };
  } else {
    params.memory_seed = { mode: "none" };
  }
  if (state.scenario_agents.length > 0) {
    params.energy = { ...state.energy };
  }
  return {
    scenario_id: state.scenario_id,
    name: state.name.trim(),
    hypothesis: state.hypothesis.trim() ? state.hypothesis.trim() : undefined,
    publish_to_youtube: state.publish_to_youtube,
    params,
  };
}
