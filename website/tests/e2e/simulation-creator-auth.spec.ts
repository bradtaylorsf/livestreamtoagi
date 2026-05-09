import { expect, test, type Page } from "@playwright/test";

const SCENARIOS = [
  {
    filename: "dream_smoke_test.yaml",
    name: "Dream Smoke Test",
    description: "Minimal dream pipeline check",
    agents: ["vera", "rex", "aurora"],
    phase_count: 3,
    expected_max_cost: 1,
    expected_runtime_minutes: 10,
  },
  {
    filename: "lab_rivals.yaml",
    name: "Lab Rivals",
    description: "A public run about alliance drama in the lab.",
    agents: ["vera", "rex", "pixel"],
    phase_count: 4,
    expected_max_cost: 1,
    expected_runtime_minutes: 12,
  },
];

const AUTH_USER = {
  id: "00000000-0000-4000-8000-000000000479",
  email: "alice@example.com",
  simulations_submitted: 0,
  total_cost_spent: "0",
  created_at: "2026-05-09T00:00:00Z",
  last_login_at: "2026-05-09T00:00:00Z",
};

async function mockCreatorApis(page: Page) {
  let signedIn = false;
  let magicLinkBody: unknown = null;
  let submitBody: unknown = null;

  await page.route("**/api/scenarios", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SCENARIOS),
    });
  });

  await page.route("**/api/simulations?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, limit: 10, offset: 0 }),
    });
  });

  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: signedIn ? 200 : 401,
      contentType: "application/json",
      body: JSON.stringify(signedIn ? AUTH_USER : { message: "Unauthorized" }),
    });
  });

  await page.route("**/api/auth/magic-link", async (route) => {
    magicLinkBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    });
  });

  await page.route("**/api/simulations/submit", async (route) => {
    submitBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        simulation_id: "sim-479",
        status_url: "/api/simulations/sim-479",
        estimated_completion_time: "2026-05-09T00:15:00Z",
      }),
    });
  });

  return {
    signIn: () => {
      signedIn = true;
    },
    magicLinkBody: () => magicLinkBody,
    submitBody: () => submitBody,
  };
}

async function setRangeValue(page: Page, testId: string, value: string) {
  await page.getByTestId(testId).evaluate(
    (element, nextValue) => {
      const input = element as HTMLInputElement;
      const valueSetter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      valueSetter?.call(input, nextValue);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    },
    value,
  );
}

test.describe("signed-out simulation creator auth flow", () => {
  test("opens magic link outside the creator form and preserves the draft", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    const api = await mockCreatorApis(page);
    await page.goto("/simulations/new?scenario=dream_smoke_test.yaml");
    await expect(page.getByTestId("creator-form")).toBeVisible();

    await page.getByTestId("scenario-select").selectOption("lab_rivals.yaml");
    await page.getByTestId("creator-name").fill("Neon pact run");
    await page
      .getByTestId("creator-hypothesis")
      .fill("Pixel will recruit Vera before Rex notices.");
    await page.getByTestId("agent-checkbox-rex").uncheck();
    await page.getByTestId("faction-add").click();
    await page.getByTestId("faction-name-0").fill("Pixel Pact");
    await page.getByTestId("faction-0-member-vera").click();
    await page.getByTestId("faction-0-member-pixel").click();
    await page.getByTestId("faction-goal-0").fill("Ship the prop board");
    await page.getByTestId("memory-seed-mode-custom").check();
    await page
      .getByTestId("memory-seed-custom-json")
      .fill('{"pixel":[{"content":"remember neon"}]}');
    await page.getByTestId("config-max-cost").fill("0.75");
    await setRangeValue(page, "config-cadence", "1.5");
    await setRangeValue(page, "config-energy-vera", "62");
    await page.getByTestId("creator-publish-youtube").check();

    await page.getByTestId("creator-submit").click();
    await expect(page.getByTestId("sign-in-overlay")).toBeVisible();
    await expect(
      page.locator('[data-testid="creator-form"] [data-testid="sign-in-overlay"]'),
    ).toHaveCount(0);
    await expect(page.locator("form form")).toHaveCount(0);

    const magicResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/auth/magic-link") &&
        response.request().method() === "POST",
    );
    await page.getByTestId("sign-in-overlay-email").fill("alice@example.com");
    await page.getByTestId("sign-in-overlay-send").click();
    await magicResponse;
    await expect(page.getByTestId("sign-in-overlay-sent")).toBeVisible();

    expect(api.magicLinkBody()).toEqual({
      email: "alice@example.com",
      next: "/simulations/new?scenario=dream_smoke_test.yaml",
    });
    expect(api.submitBody()).toBeNull();

    await expect(page.getByTestId("scenario-select")).toHaveValue("lab_rivals.yaml");
    await expect(page.getByTestId("creator-name")).toHaveValue("Neon pact run");
    await expect(page.getByTestId("creator-hypothesis")).toHaveValue(
      "Pixel will recruit Vera before Rex notices.",
    );
    await expect(page.getByTestId("config-max-cost")).toHaveValue("0.75");
    await expect(page.getByTestId("creator-publish-youtube")).toBeChecked();
    await expect(page.getByTestId("memory-seed-custom-json")).toHaveValue(
      '{"pixel":[{"content":"remember neon"}]}',
    );

    api.signIn();
    await page.goto("/simulations/new?scenario=dream_smoke_test.yaml");
    await expect(page.getByTestId("scenario-select")).toHaveValue("lab_rivals.yaml");
    await expect(page.getByTestId("creator-name")).toHaveValue("Neon pact run");
    await expect(page.getByTestId("creator-hypothesis")).toHaveValue(
      "Pixel will recruit Vera before Rex notices.",
    );
    await expect(page.getByTestId("agent-checkbox-rex")).not.toBeChecked();
    await expect(page.getByTestId("faction-name-0")).toHaveValue("Pixel Pact");
    await expect(page.getByTestId("memory-seed-custom-json")).toHaveValue(
      '{"pixel":[{"content":"remember neon"}]}',
    );

    const nestingOrHydrationErrors = consoleErrors.filter((message) =>
      /hydration|validateDOMNesting|cannot contain a nested/i.test(message),
    );
    expect(nestingOrHydrationErrors).toEqual([]);

    const submitResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/simulations/submit") &&
        response.request().method() === "POST",
    );
    await page.getByTestId("creator-submit").click();
    await submitResponse;

    expect(api.submitBody()).toMatchObject({
      scenario_id: "lab_rivals.yaml",
      name: "Neon pact run",
      hypothesis: "Pixel will recruit Vera before Rex notices.",
      publish_to_youtube: true,
      params: {
        max_cost: 0.75,
        conversation_cadence: 1.5,
        agents: ["vera", "pixel"],
        excluded_agents: ["rex"],
        factions: [
          {
            name: "Pixel Pact",
            members: ["vera", "pixel"],
            goal: "Ship the prop board",
          },
        ],
        memory_seed: {
          mode: "custom",
          data: { pixel: [{ content: "remember neon" }] },
        },
      },
    });
    expect(
      (api.submitBody() as { params: { energy: Record<string, number> } }).params
        .energy.vera,
    ).toBe(62);
  });
});
