import { expect, test, type Page } from "@playwright/test";

const JOURNAL_IMAGE_DATA_URI = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`
  <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
    <rect width="64" height="64" fill="#111827"/>
    <rect x="8" y="8" width="48" height="48" fill="#7c3aed"/>
    <rect x="16" y="16" width="12" height="12" fill="#f8fafc"/>
    <rect x="36" y="16" width="12" height="12" fill="#f8fafc"/>
    <rect x="20" y="40" width="24" height="8" fill="#22d3ee"/>
  </svg>
`)}`;

async function mockJournalIllustrationApis(page: Page) {
  await page.route("**/api/agents/vera/journal**", async (route) => {
    await route.fulfill({
      json: [
        {
          id: 4811,
          agent_id: "vera",
          reflection_type: "6hour",
          content: "The studio finally produced a visible journal illustration.",
          token_count: 9,
          image_url: JOURNAL_IMAGE_DATA_URI,
          created_at: "2026-05-09T12:00:00Z",
        },
        {
          id: 4812,
          agent_id: "vera",
          reflection_type: "weekly",
          content: "Image generation was disabled locally, but my journal still reads cleanly.",
          token_count: 11,
          image_url: null,
          created_at: "2026-05-09T13:00:00Z",
        },
        {
          id: 4813,
          agent_id: "vera",
          reflection_type: "dream",
          content: "This entry points to an image URL that fails to load.",
          token_count: 10,
          image_url: "/broken-journal-illustration.png",
          created_at: "2026-05-09T14:00:00Z",
        },
      ],
    });
  });

  await page.route("**/broken-journal-illustration.png", async (route) => {
    await route.fulfill({ status: 404, body: "not found" });
  });

  await page.route("**/api/simulations?**", async (route) => {
    await route.fulfill({
      json: { items: [], total: 0, limit: 100, offset: 0 },
    });
  });

  await page.route("**/api/agents/vera/conversations**", async (route) => {
    await route.fulfill({
      json: { items: [], total: 0, limit: 1, offset: 0 },
    });
  });

  await page.route("**/api/agents/vera/artifacts**", async (route) => {
    await route.fulfill({
      json: { items: [], total: 0, limit: 1, offset: 0 },
    });
  });

  await page.route("**/api/agents/vera/costs**", async (route) => {
    await route.fulfill({
      json: {
        by_day: [],
        by_type: [],
        total: "0",
        total_input_tokens: 0,
        total_output_tokens: 0,
      },
    });
  });
}

test.describe("Agent Profile Pages", () => {
  test("profile loads for vera", async ({ page }) => {
    await page.goto("/agents/vera");

    await expect(page.getByText("Vera")).toBeVisible();
    await expect(page.getByText("Showrunner/Coordinator")).toBeVisible();
    await expect(page.getByText(/ABOUT/)).toBeVisible();
    await expect(page.getByText(/First agent initialized/)).toBeVisible();
  });

  test("profile loads for rex", async ({ page }) => {
    await page.goto("/agents/rex");

    await expect(page.getByText("Rex")).toBeVisible();
    await expect(page.getByText("Engineer/Builder")).toBeVisible();
  });

  test("journal tab displays entries", async ({ page }) => {
    await page.goto("/agents/vera");

    // Journal tab should be active by default
    const journalTab = page.getByRole("button", { name: "Journal" });
    await expect(journalTab).toBeVisible();

    // Journal entries should be visible
    await expect(page.getByText(/morning meeting/i).first()).toBeVisible();
  });

  test("journal illustration states render image, text-only, and broken fallback", async ({ page }) => {
    await mockJournalIllustrationApis(page);

    await page.goto("/agents/vera?tab=journal");

    await expect(page.getByText("The studio finally produced a visible journal illustration."))
      .toBeVisible();
    await expect(page.getByAltText("6-hour journal illustration")).toBeVisible();
    await expect(page.locator('[data-illustration-status="image"]')).toHaveCount(1);

    await expect(
      page.getByText("Image generation was disabled locally, but my journal still reads cleanly."),
    ).toBeVisible();
    await expect(page.locator('[data-illustration-status="missing"]')).toHaveText(
      /Text-only journal/,
    );

    await expect(page.getByText("This entry points to an image URL that fails to load."))
      .toBeVisible();
    const failedFrame = page.locator('[data-illustration-status="failed"]');
    await expect(failedFrame).toHaveText(/Illustration unavailable/);

    const frames = await page.locator("[data-illustration-status]").evaluateAll((elements) =>
      elements.map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      }),
    );
    expect(frames).toHaveLength(3);
    for (const frame of frames) {
      expect(frame.width).toBeGreaterThan(0);
      expect(frame.height).toBe(frame.width);
    }
  });

  test("tab navigation works across all tabs", async ({ page }) => {
    await page.goto("/agents/vera");

    // Click relationships tab
    await page.getByRole("button", { name: "Relationships" }).click();
    await expect(page.getByText("Sentinel")).toBeVisible();

    // Click conversations tab
    await page.getByRole("button", { name: "Conversations" }).click();
    await expect(page.getByText(/standup/i).first()).toBeVisible();

    // Click evolution tab
    await page.getByRole("button", { name: "Evolution" }).click();
    await expect(page.getByText(/configuration/i).first()).toBeVisible();

    // Click creations tab
    await page.getByRole("button", { name: "Creations" }).click();
    await expect(page.getByText(/renderer/i).first()).toBeVisible();
  });

  test("personality radar section is visible", async ({ page }) => {
    await page.goto("/agents/vera");

    await expect(page.getByText("PERSONALITY")).toBeVisible();
  });

  test("relationship graph renders for vera", async ({ page }) => {
    await page.goto("/agents/vera");

    await page.getByRole("button", { name: "Relationships" }).click();

    // Vera has relationships with other agents
    await expect(page.getByText("Sentinel")).toBeVisible();
    await expect(page.getByText("Rex")).toBeVisible();
  });
});
