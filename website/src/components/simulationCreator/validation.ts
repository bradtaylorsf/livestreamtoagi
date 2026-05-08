import type { PublicFaction, PublicMemorySeed } from "@/lib/api";

export interface ValidationResult {
  ok: boolean;
  error?: string;
}

export const NAME_MAX_LENGTH = 100;
export const HYPOTHESIS_MAX_LENGTH = 2000;

export function validateName(raw: string): ValidationResult {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) {
    return { ok: false, error: "Name is required" };
  }
  if (trimmed.length > NAME_MAX_LENGTH) {
    return {
      ok: false,
      error: `Name must be ${NAME_MAX_LENGTH} characters or fewer`,
    };
  }
  return { ok: true };
}

export function validateHypothesis(raw: string | null | undefined): ValidationResult {
  if (raw == null) return { ok: true };
  if (raw.length > HYPOTHESIS_MAX_LENGTH) {
    return {
      ok: false,
      error: `Hypothesis must be ${HYPOTHESIS_MAX_LENGTH} characters or fewer`,
    };
  }
  return { ok: true };
}

export function validateMaxCost(
  value: number,
  remainingBudget: number | null,
): ValidationResult {
  if (!Number.isFinite(value) || value <= 0) {
    return { ok: false, error: "Max cost must be greater than 0" };
  }
  if (remainingBudget !== null && value > remainingBudget) {
    return {
      ok: false,
      error: `Max cost ($${value.toFixed(2)}) exceeds your remaining budget ($${remainingBudget.toFixed(2)})`,
    };
  }
  return { ok: true };
}

export function validateMemorySeedJson(raw: string): ValidationResult {
  if (!raw.trim()) {
    return { ok: false, error: "Memory seed JSON cannot be empty" };
  }
  try {
    JSON.parse(raw);
    return { ok: true };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? `Invalid JSON: ${err.message}` : "Invalid JSON",
    };
  }
}

export function validateMemorySeed(seed: PublicMemorySeed): ValidationResult {
  if (seed.mode === "none") return { ok: true };
  if (seed.mode === "inherit") {
    if (!seed.simulation_id) {
      return { ok: false, error: "Pick a simulation to inherit memory from" };
    }
    return { ok: true };
  }
  if (seed.mode === "custom") {
    return { ok: true };
  }
  return { ok: true };
}

export function validateFaction(faction: PublicFaction): ValidationResult {
  const name = (faction.name ?? "").trim();
  if (!name) {
    return { ok: false, error: "Faction name is required" };
  }
  if (faction.members.length === 0) {
    return {
      ok: false,
      error: `Faction "${name}" must have at least one member`,
    };
  }
  if (!(faction.goal ?? "").trim()) {
    return {
      ok: false,
      error: `Faction "${name}" must have a goal`,
    };
  }
  return { ok: true };
}

export function validateFactions(factions: PublicFaction[]): ValidationResult {
  for (const f of factions) {
    const r = validateFaction(f);
    if (!r.ok) return r;
  }
  return { ok: true };
}

export function validateAgentSelection(
  scenarioAgents: string[],
  excludedAgents: string[],
): ValidationResult {
  if (scenarioAgents.length === 0) return { ok: true };
  const remaining = scenarioAgents.filter((a) => !excludedAgents.includes(a));
  if (remaining.length === 0) {
    return {
      ok: false,
      error: "At least one agent must remain selected",
    };
  }
  return { ok: true };
}

export interface CreatorFormValues {
  scenario_id: string;
  name: string;
  hypothesis: string;
  excluded_agents: string[];
  scenario_agents: string[];
  factions: PublicFaction[];
  memory_seed: PublicMemorySeed;
  memory_seed_raw_json: string;
  max_cost: number;
  remaining_budget: number | null;
}

export function validateForm(values: CreatorFormValues): ValidationResult {
  if (!values.scenario_id) {
    return { ok: false, error: "Pick a scenario to run" };
  }
  const checks: ValidationResult[] = [
    validateName(values.name),
    validateHypothesis(values.hypothesis),
    validateAgentSelection(values.scenario_agents, values.excluded_agents),
    validateFactions(values.factions),
    validateMaxCost(values.max_cost, values.remaining_budget),
    validateMemorySeed(values.memory_seed),
  ];
  if (values.memory_seed.mode === "custom") {
    checks.push(validateMemorySeedJson(values.memory_seed_raw_json));
  }
  for (const c of checks) {
    if (!c.ok) return c;
  }
  return { ok: true };
}

export function remainingBudget(
  user: { total_cost_spent: string } | null,
  lifetimeCap: number,
): number | null {
  if (!user) return null;
  const spent = parseFloat(user.total_cost_spent);
  if (!Number.isFinite(spent)) return lifetimeCap;
  return Math.max(0, lifetimeCap - spent);
}
