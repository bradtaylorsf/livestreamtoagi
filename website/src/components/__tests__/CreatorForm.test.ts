import { readFileSync } from "fs";
import { resolve } from "path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  HYPOTHESIS_MAX_LENGTH,
  NAME_MAX_LENGTH,
  remainingBudget,
  validateAgentSelection,
  validateFaction,
  validateFactions,
  validateForm,
  validateHypothesis,
  validateMaxCost,
  validateMemorySeed,
  validateMemorySeedJson,
  validateName,
  type CreatorFormValues,
} from "@/components/simulationCreator/validation";
import {
  activeAgents,
  buildSubmitPayload,
  DEFAULT_LIFETIME_CAP_USD,
  emptyFaction,
  initialState,
  reseedForScenario,
  toggleAgent,
} from "@/components/simulationCreator/state";
import {
  CREATOR_DRAFT_STORAGE_KEY,
  clearCreatorDraft,
  loadCreatorDraft,
  saveCreatorDraft,
} from "@/components/simulationCreator/draftStorage";
import { filterScenarios } from "@/components/simulationCreator/ScenarioField";
import type { PublicScenarioMeta } from "@/lib/api";

const FORM_SOURCE = readFileSync(
  resolve(__dirname, "../simulationCreator/CreatorForm.tsx"),
  "utf8",
);
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, "../../app/simulations/new/page.tsx"),
  "utf8",
);
const SIGN_IN_SOURCE = readFileSync(
  resolve(__dirname, "../simulationCreator/SignInOverlay.tsx"),
  "utf8",
);
const FACTIONS_SOURCE = readFileSync(
  resolve(__dirname, "../simulationCreator/FactionsField.tsx"),
  "utf8",
);

function makeScenario(
  overrides: Partial<PublicScenarioMeta> = {},
): PublicScenarioMeta {
  return {
    filename: "dream_smoke_test.yaml",
    name: "Dream Smoke Test",
    description: "Minimal dream pipeline check",
    agents: ["vera", "rex", "aurora"],
    phase_count: 3,
    expected_max_cost: 3,
    expected_runtime_minutes: 10,
    ...overrides,
  };
}

function makeFormValues(
  overrides: Partial<CreatorFormValues> = {},
): CreatorFormValues {
  return {
    scenario_id: "dream_smoke_test.yaml",
    name: "My run",
    hypothesis: "",
    excluded_agents: [],
    scenario_agents: ["vera", "rex"],
    factions: [],
    memory_seed: { mode: "none" },
    memory_seed_raw_json: "{}",
    max_cost: 1,
    remaining_budget: 5,
    ...overrides,
  };
}

describe("validation.validateName", () => {
  it("rejects an empty name", () => {
    expect(validateName("").ok).toBe(false);
    expect(validateName("   ").ok).toBe(false);
  });
  it("accepts a name within the length limit", () => {
    expect(validateName("My run").ok).toBe(true);
  });
  it(`rejects names longer than ${NAME_MAX_LENGTH} chars`, () => {
    const long = "a".repeat(NAME_MAX_LENGTH + 1);
    expect(validateName(long).ok).toBe(false);
  });
});

describe("validation.validateHypothesis", () => {
  it("accepts empty / null hypothesis", () => {
    expect(validateHypothesis(null).ok).toBe(true);
    expect(validateHypothesis("").ok).toBe(true);
  });
  it(`rejects hypothesis over ${HYPOTHESIS_MAX_LENGTH} chars`, () => {
    expect(validateHypothesis("a".repeat(HYPOTHESIS_MAX_LENGTH + 1)).ok).toBe(false);
  });
});

describe("validation.validateMaxCost", () => {
  it("rejects values <= 0 or non-finite", () => {
    expect(validateMaxCost(0, 5).ok).toBe(false);
    expect(validateMaxCost(-1, 5).ok).toBe(false);
    expect(validateMaxCost(NaN, 5).ok).toBe(false);
  });
  it("rejects values that exceed the remaining budget", () => {
    expect(validateMaxCost(5.01, 5).ok).toBe(false);
  });
  it("accepts when remaining budget is null (anonymous)", () => {
    expect(validateMaxCost(1, null).ok).toBe(true);
  });
});

describe("validation.validateMemorySeedJson", () => {
  it("rejects invalid JSON", () => {
    expect(validateMemorySeedJson("not json").ok).toBe(false);
  });
  it("rejects empty/whitespace-only input", () => {
    expect(validateMemorySeedJson("   ").ok).toBe(false);
  });
  it("accepts well-formed JSON", () => {
    expect(validateMemorySeedJson('{"vera": []}').ok).toBe(true);
  });
});

describe("validation.validateMemorySeed", () => {
  it("requires simulation_id when inheriting", () => {
    expect(
      validateMemorySeed({ mode: "inherit", simulation_id: "" }).ok,
    ).toBe(false);
    expect(
      validateMemorySeed({ mode: "inherit", simulation_id: "abc" }).ok,
    ).toBe(true);
  });
});

describe("validation.validateFaction(s)", () => {
  it("requires a name, members, and a goal", () => {
    expect(
      validateFaction({ name: "", members: ["vera"], goal: "go" }).ok,
    ).toBe(false);
    expect(
      validateFaction({ name: "Coup", members: [], goal: "go" }).ok,
    ).toBe(false);
    expect(
      validateFaction({ name: "Coup", members: ["vera"], goal: "" }).ok,
    ).toBe(false);
    expect(
      validateFaction({ name: "Coup", members: ["vera"], goal: "go" }).ok,
    ).toBe(true);
  });
  it("validateFactions short-circuits on the first invalid faction", () => {
    const result = validateFactions([
      { name: "Coup", members: ["vera"], goal: "" },
    ]);
    expect(result.ok).toBe(false);
  });
});

describe("validation.validateAgentSelection", () => {
  it("rejects when every agent is excluded", () => {
    expect(
      validateAgentSelection(["vera", "rex"], ["vera", "rex"]).ok,
    ).toBe(false);
  });
  it("accepts when at least one remains", () => {
    expect(
      validateAgentSelection(["vera", "rex"], ["vera"]).ok,
    ).toBe(true);
  });
  it("accepts an empty scenario_agents list (no constraint)", () => {
    expect(validateAgentSelection([], []).ok).toBe(true);
  });
});

describe("validation.validateForm happy path", () => {
  it("accepts a fully-filled valid form", () => {
    expect(validateForm(makeFormValues()).ok).toBe(true);
  });
  it("rejects when name is empty", () => {
    expect(validateForm(makeFormValues({ name: "" })).ok).toBe(false);
  });
  it("rejects custom JSON memory seed when JSON is invalid", () => {
    const r = validateForm(
      makeFormValues({
        memory_seed: { mode: "custom", data: null },
        memory_seed_raw_json: "not json",
      }),
    );
    expect(r.ok).toBe(false);
  });
});

describe("validation.remainingBudget", () => {
  it("returns null when user is null", () => {
    expect(remainingBudget(null, 10)).toBeNull();
  });
  it("subtracts spent from cap", () => {
    expect(remainingBudget({ total_cost_spent: "3.5" }, 10)).toBe(6.5);
  });
  it("clamps to zero when spent exceeds cap", () => {
    expect(remainingBudget({ total_cost_spent: "20" }, 10)).toBe(0);
  });
});

describe("state.initialState", () => {
  it("uses the requested initial scenario when present", () => {
    const scenarios = [makeScenario(), makeScenario({ filename: "other.yaml", name: "Other" })];
    const s = initialState({
      scenarios,
      initialScenarioId: "other.yaml",
      remainingBudget: 5,
    });
    expect(s.scenario_id).toBe("other.yaml");
  });
  it("falls back to the first scenario when no initial is given", () => {
    const scenarios = [makeScenario()];
    const s = initialState({
      scenarios,
      initialScenarioId: null,
      remainingBudget: null,
    });
    expect(s.scenario_id).toBe("dream_smoke_test.yaml");
  });
  it("defaults max_cost to per-submission cap when budget allows", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: 5,
      perSubmissionCap: 1,
    });
    expect(s.max_cost).toBe(1);
  });
});

describe("state.toggleAgent", () => {
  it("excludes when previously included and vice versa", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: 5,
    });
    const off = toggleAgent(s, "rex");
    expect(off.excluded_agents).toContain("rex");
    const on = toggleAgent(off, "rex");
    expect(on.excluded_agents).not.toContain("rex");
  });
});

describe("state.activeAgents", () => {
  it("subtracts excluded from scenario list", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: 5,
    });
    const off = toggleAgent(s, "rex");
    expect(activeAgents(off)).toEqual(["vera", "aurora"]);
  });
});

describe("state.reseedForScenario", () => {
  it("replaces agent list and prunes excluded agents that don't apply", () => {
    const s0 = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: null,
    });
    const after = reseedForScenario(toggleAgent(s0, "rex"), makeScenario({
      filename: "other.yaml",
      name: "Other",
      agents: ["pixel", "fork"],
    }));
    expect(after.scenario_agents).toEqual(["pixel", "fork"]);
    expect(after.excluded_agents).toEqual([]);
  });
});

describe("state.buildSubmitPayload", () => {
  it("threads scenario_id, name, hypothesis, params into the request body", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: null,
    });
    const payload = buildSubmitPayload({
      ...s,
      hypothesis: "Rex and Aurora ally",
      max_cost: 0.5,
      conversation_cadence: 1.5,
    });
    expect(payload.scenario_id).toBe("dream_smoke_test.yaml");
    expect(payload.hypothesis).toBe("Rex and Aurora ally");
    expect(payload.params?.max_cost).toBe(0.5);
    expect(payload.params?.conversation_cadence).toBe(1.5);
    expect(payload.params?.agents).toEqual(["vera", "rex", "aurora"]);
    expect(payload.params?.excluded_agents).toEqual([]);
    expect(payload.params?.energy).toBeTruthy();
  });
  it("omits hypothesis when blank", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: null,
    });
    expect(buildSubmitPayload(s).hypothesis).toBeUndefined();
  });
  it("emits factions only when at least one is configured", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: null,
    });
    expect(buildSubmitPayload(s).params?.factions).toBeUndefined();
    const withFactions = {
      ...s,
      factions: [{ name: "Coup", members: ["vera"], goal: "win" }],
    };
    expect(buildSubmitPayload(withFactions).params?.factions).toHaveLength(1);
  });
  it("emits excluded_agents and reduced agents list when any are excluded", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: null,
    });
    const off = toggleAgent(s, "rex");
    const payload = buildSubmitPayload(off);
    expect(payload.params?.excluded_agents).toEqual(["rex"]);
    expect(payload.params?.agents).toEqual(["vera", "aurora"]);
  });
  it("filters energy and faction members to the active roster", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: null,
    });
    const payload = buildSubmitPayload({
      ...toggleAgent(s, "rex"),
      factions: [
        {
          name: "Show team",
          members: ["vera", "rex", "aurora"],
          goal: "make the run entertaining",
        },
      ],
      energy: {
        vera: 80,
        rex: 10,
        aurora: 90,
      },
    });

    expect(payload.params?.agents).toEqual(["vera", "aurora"]);
    expect(payload.params?.energy).toEqual({ vera: 80, aurora: 90 });
    expect(payload.params?.factions).toEqual([
      {
        name: "Show team",
        members: ["vera", "aurora"],
        goal: "make the run entertaining",
      },
    ]);
  });
  it("parses custom-mode memory seed JSON when valid", () => {
    const s = initialState({
      scenarios: [makeScenario()],
      initialScenarioId: null,
      remainingBudget: null,
    });
    const payload = buildSubmitPayload({
      ...s,
      memory_seed: { mode: "custom", data: null },
      memory_seed_raw_json: '{"vera": [1, 2]}',
    });
    expect(payload.params?.memory_seed).toEqual({
      mode: "custom",
      data: { vera: [1, 2] },
    });
  });
});

describe("draftStorage", () => {
  let localStorageData: Record<string, string>;
  let sessionStorageData: Record<string, string>;

  function makeStorage(storage: Record<string, string>) {
    return {
      getItem: (key: string) => (key in storage ? storage[key] : null),
      setItem: (key: string, value: string) => {
        storage[key] = value;
      },
      removeItem: (key: string) => {
        delete storage[key];
      },
    };
  }

  beforeEach(() => {
    localStorageData = {};
    sessionStorageData = {};
    vi.stubGlobal("window", {
      localStorage: makeStorage(localStorageData),
      sessionStorage: makeStorage(sessionStorageData),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves user-entered draft fields while refreshing scenario metadata", () => {
    const scenario = makeScenario({
      filename: "lab_rivals.yaml",
      name: "Lab Rivals",
      agents: ["vera", "rex", "pixel"],
    });
    const state = initialState({
      scenarios: [scenario],
      initialScenarioId: "lab_rivals.yaml",
      remainingBudget: null,
    });

    saveCreatorDraft({
      ...state,
      name: "Neon pact run",
      hypothesis: "Pixel will recruit Vera before Rex notices.",
      excluded_agents: ["rex", "missing-agent"],
      factions: [
        {
          name: "Pixel Pact",
          members: ["vera", "pixel"],
          goal: "Ship the prop board",
        },
      ],
      memory_seed: { mode: "custom", data: null },
      memory_seed_raw_json: '{"pixel":[{"content":"remember neon"}]}',
      max_cost: 0.75,
      publish_to_youtube: true,
      conversation_cadence: 1.5,
      energy: { vera: 62, rex: 44, pixel: 91 },
    });

    const restored = loadCreatorDraft({
      scenarios: [
        makeScenario({
          filename: "lab_rivals.yaml",
          name: "Lab Rivals",
          agents: ["vera", "rex", "pixel", "fork"],
        }),
      ],
      remainingBudget: 8,
    });

    expect(restored).toMatchObject({
      scenario_id: "lab_rivals.yaml",
      name: "Neon pact run",
      hypothesis: "Pixel will recruit Vera before Rex notices.",
      excluded_agents: ["rex"],
      max_cost: 0.75,
      remaining_budget: 8,
      publish_to_youtube: true,
      conversation_cadence: 1.5,
      scenario_agents: ["vera", "rex", "pixel", "fork"],
      factions: [
        {
          name: "Pixel Pact",
          members: ["vera", "pixel"],
          goal: "Ship the prop board",
        },
      ],
      memory_seed: { mode: "custom", data: null },
      memory_seed_raw_json: '{"pixel":[{"content":"remember neon"}]}',
    });
    expect(restored?.energy).toMatchObject({ vera: 62, rex: 44, pixel: 91 });
    expect(restored?.energy.fork).toBe(75);
    expect(localStorageData[CREATOR_DRAFT_STORAGE_KEY]).toBeTruthy();
    expect(sessionStorageData[CREATOR_DRAFT_STORAGE_KEY]).toBeUndefined();
  });

  it("loads legacy session drafts when local storage is empty", () => {
    sessionStorageData[CREATOR_DRAFT_STORAGE_KEY] = JSON.stringify({
      version: 1,
      saved_at: "2026-05-09T00:00:00Z",
      state: {
        scenario_id: "dream_smoke_test.yaml",
        name: "Session draft run",
        hypothesis: "",
        excluded_agents: [],
        factions: [],
        memory_seed: { mode: "none" },
        memory_seed_raw_json: "{}",
        max_cost: 0.5,
        publish_to_youtube: false,
        conversation_cadence: 1,
        energy: { vera: 70, rex: 60, aurora: 80 },
      },
    });

    const restored = loadCreatorDraft({
      scenarios: [makeScenario()],
      remainingBudget: null,
    });

    expect(restored?.name).toBe("Session draft run");
    expect(restored?.max_cost).toBe(0.5);
  });

  it("clears invalid or stale drafts instead of throwing", () => {
    localStorageData[CREATOR_DRAFT_STORAGE_KEY] = JSON.stringify({
      version: 1,
      state: { scenario_id: "missing.yaml" },
    });

    const restored = loadCreatorDraft({
      scenarios: [makeScenario()],
      remainingBudget: null,
    });

    expect(restored).toBeNull();
    expect(localStorageData[CREATOR_DRAFT_STORAGE_KEY]).toBeUndefined();
  });

  it("clears the persisted draft on request", () => {
    localStorageData[CREATOR_DRAFT_STORAGE_KEY] = "draft";
    sessionStorageData[CREATOR_DRAFT_STORAGE_KEY] = "legacy draft";
    clearCreatorDraft();
    expect(localStorageData[CREATOR_DRAFT_STORAGE_KEY]).toBeUndefined();
    expect(sessionStorageData[CREATOR_DRAFT_STORAGE_KEY]).toBeUndefined();
  });
});

describe("emptyFaction", () => {
  it("starts with empty fields", () => {
    expect(emptyFaction()).toEqual({ name: "", members: [], goal: "" });
  });
});

describe("ScenarioField.filterScenarios", () => {
  const scenarios = [
    makeScenario({ filename: "a.yaml", name: "Alpha", description: "alpha desc" }),
    makeScenario({ filename: "b.yaml", name: "Bravo", description: "bravo desc" }),
  ];
  it("returns all scenarios for empty query", () => {
    expect(filterScenarios(scenarios, "").length).toBe(2);
  });
  it("matches name/description/filename case-insensitively", () => {
    expect(filterScenarios(scenarios, "BRAVO").map((s) => s.filename)).toEqual([
      "b.yaml",
    ]);
    expect(filterScenarios(scenarios, "alpha desc").map((s) => s.filename)).toEqual([
      "a.yaml",
    ]);
    expect(filterScenarios(scenarios, "B.yaml").map((s) => s.filename)).toEqual([
      "b.yaml",
    ]);
  });
});

describe("CreatorForm component source", () => {
  it("submits to /api/simulations/submit via submitPublicSimulation", () => {
    expect(FORM_SOURCE).toMatch(/submitPublicSimulation/);
  });
  it("redirects to /simulations/[id]?queued=1 on success", () => {
    expect(FORM_SOURCE).toMatch(/router\.push\(`\/simulations\/\$\{res\.simulation_id\}\?queued=1`\)/);
  });
  it("shows the SignInOverlay when no user is loaded", () => {
    expect(FORM_SOURCE).toMatch(/SignInOverlay/);
  });
  it("renders all six required form sections", () => {
    expect(FORM_SOURCE).toMatch(/ScenarioField/);
    expect(FORM_SOURCE).toMatch(/AgentsField/);
    expect(FORM_SOURCE).toMatch(/FactionsField/);
    expect(FORM_SOURCE).toMatch(/MemorySeedField/);
    expect(FORM_SOURCE).toMatch(/EnergyConfigField/);
    expect(FORM_SOURCE).toMatch(/Run simulation/);
  });
  it("shows the lifetime budget remaining hint", () => {
    expect(FORM_SOURCE).toMatch(/lifetime budget/);
  });
});

describe("/simulations/new page", () => {
  it("reads the scenario query param via useSearchParams", () => {
    expect(PAGE_SOURCE).toMatch(/useSearchParams/);
    expect(PAGE_SOURCE).toMatch(/params\.get\("scenario"\)/);
  });
  it("wraps the search-param consumer in Suspense", () => {
    expect(PAGE_SOURCE).toMatch(/Suspense/);
  });
  it("renders the CreatorForm", () => {
    expect(PAGE_SOURCE).toMatch(/<CreatorForm/);
  });
});

describe("SignInOverlay component source", () => {
  it("posts to /api/auth/magic-link via requestMagicLink", () => {
    expect(SIGN_IN_SOURCE).toMatch(/requestMagicLink/);
  });
  it("shows a 'Check your email' confirmation state", () => {
    expect(SIGN_IN_SOURCE).toMatch(/Check your email/);
  });
});

describe("FactionsField component source", () => {
  it("exposes Add and Remove controls so users can build faction blocks", () => {
    expect(FACTIONS_SOURCE).toMatch(/data-testid="faction-add"/);
    expect(FACTIONS_SOURCE).toMatch(/faction-remove-/);
  });
  it("renders members as a multi-select limited to active agents", () => {
    expect(FACTIONS_SOURCE).toMatch(/activeAgents\.map/);
  });
});

describe("DEFAULT_LIFETIME_CAP_USD", () => {
  it("matches the public lifetime cap default ($10)", () => {
    expect(DEFAULT_LIFETIME_CAP_USD).toBe(10);
  });
});
