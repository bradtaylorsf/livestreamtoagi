import { expect, test, type Page, type Route } from "@playwright/test";

const SIM_ID = "00000000-0000-4000-8000-000000000480";
const ACTIVE_AGENTS = ["vera", "rex", "aurora"];
const SCENARIO_AGENTS = [...ACTIVE_AGENTS, "pixel"];
const EXCLUDED_AGENTS = ["pixel"];
const DEFAULT_ROSTER_EXTRAS = ["fork", "grok", "sentinel"];

const scenarioFixture = [
  {
    filename: "small_cast.yaml",
    name: "Small Cast",
    description: "Four speaking agents test the public submit roster path.",
    agents: SCENARIO_AGENTS,
    phase_count: 3,
    expected_max_cost: 0.5,
    expected_runtime_minutes: 5,
  },
  {
    filename: "full_day.yaml",
    name: "Full Day",
    description: "Default full-roster run.",
    agents: [...SCENARIO_AGENTS, ...DEFAULT_ROSTER_EXTRAS],
    phase_count: 12,
    expected_max_cost: 1,
    expected_runtime_minutes: 20,
  },
];

function simulationFixture() {
  return {
    id: SIM_ID,
    name: "Small Cast run",
    description: null,
    config: {
      scenario_id: "small_cast.yaml",
      scenario_agents: SCENARIO_AGENTS,
      excluded_agents: EXCLUDED_AGENTS,
      effective_agents: ACTIVE_AGENTS,
      agents: ACTIVE_AGENTS,
      source: "public_submit",
    },
    status: "queued",
    started_at: null,
    completed_at: null,
    real_duration: null,
    simulated_duration: null,
    total_conversations: 0,
    total_turns: 0,
    total_tokens: 0,
    total_cost: "0",
    total_artifacts: 0,
    total_management_flags: 0,
    agents_participated: ACTIVE_AGENTS,
    hypothesis: null,
    outcomes: null,
    learnings: null,
    factions: [],
    is_featured: false,
    video_url: null,
    youtube_url: null,
    youtube_publish_status: null,
    publish_to_youtube: false,
    submitter_display_name: "qa",
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockPublicSimulationFlow(page: Page) {
  let submitBody: Record<string, unknown> | null = null;

  await page.route("**/api/scenarios", async (route) => {
    await fulfillJson(route, scenarioFixture);
  });
  await page.route("**/api/auth/me", async (route) => {
    await fulfillJson(route, {
      id: "user-480",
      email: "qa@example.com",
      simulations_submitted: 0,
      total_cost_spent: "0",
      created_at: "2026-05-10T00:00:00Z",
      last_login_at: "2026-05-10T00:00:00Z",
    });
  });
  await page.route("**/api/simulations/submit", async (route) => {
    submitBody = (await route.request().postDataJSON()) as Record<string, unknown>;
    await fulfillJson(route, {
      simulation_id: SIM_ID,
      status_url: `/api/simulations/${SIM_ID}`,
      estimated_completion_time: "2026-05-10T00:05:00Z",
    });
  });
  await page.route(`**/api/simulations/${SIM_ID}`, async (route) => {
    await fulfillJson(route, simulationFixture());
  });

  return {
    getSubmitBody: () => submitBody,
  };
}

test.describe("public simulation submission", () => {
  test("submits the selected roster and shows the effective workspace roster", async ({
    page,
  }) => {
    const flow = await mockPublicSimulationFlow(page);

    await page.goto("/simulations/new?scenario=small_cast.yaml");

    await expect(page.getByTestId("creator-form")).toBeVisible();
    await expect(page.getByTestId("scenario-select")).toHaveValue("small_cast.yaml");
    for (const agent of SCENARIO_AGENTS) {
      await expect(page.getByTestId(`agent-checkbox-${agent}`)).toBeVisible();
    }
    for (const agent of DEFAULT_ROSTER_EXTRAS) {
      await expect(page.getByTestId(`agent-checkbox-${agent}`)).toHaveCount(0);
    }

    await page.getByTestId("agent-checkbox-pixel").uncheck();
    await expect(page.getByTestId("agent-checkbox-pixel")).not.toBeChecked();
    await page.getByTestId("creator-submit").click();

    await expect(page).toHaveURL(new RegExp(`/simulations/${SIM_ID}\\?queued=1$`));

    const submitBody = flow.getSubmitBody();
    expect(submitBody).not.toBeNull();

    const params = submitBody?.params as Record<string, unknown>;
    expect(submitBody).toMatchObject({
      scenario_id: "small_cast.yaml",
      name: "Small Cast run",
      publish_to_youtube: false,
    });
    expect(params.agents).toEqual(ACTIVE_AGENTS);
    expect(params.excluded_agents).toEqual(EXCLUDED_AGENTS);
    expect(params.energy).toEqual({
      vera: 75,
      rex: 75,
      aurora: 75,
    });

    for (const agent of [...EXCLUDED_AGENTS, ...DEFAULT_ROSTER_EXTRAS]) {
      expect(params.agents).not.toContain(agent);
    }

    await expect(page.getByTestId("simulation-queued-banner")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Effective Agent Roster" }),
    ).toBeVisible();

    const rosterLinks = page.locator(`a[href^="/simulations/${SIM_ID}/agents/"]`);
    await expect(rosterLinks).toHaveText(ACTIVE_AGENTS);
  });
});
