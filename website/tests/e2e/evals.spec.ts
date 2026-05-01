import { expect, test } from "@playwright/test";

test.describe("Evals Dashboard", () => {
  test("page loads with category cards", async ({ page }) => {
    await page.goto("/evals");

    await expect(
      page.getByRole("heading", { name: /EVALUATION DASHBOARD/i }),
    ).toBeVisible();

    // Category grid should be visible with 12 categories
    const grid = page.getByTestId("category-grid");
    await expect(grid).toBeVisible();

    // At least some category names should be visible
    await expect(page.getByText("creativity").first()).toBeVisible();
    await expect(page.getByText("entertainment").first()).toBeVisible();
    await expect(page.getByText("safety").first()).toBeVisible();
  });

  test("score history chart section renders", async ({ page }) => {
    await page.goto("/evals");

    await expect(
      page.getByRole("heading", { name: /SCORE TRENDS/i }),
    ).toBeVisible();

    // Chart area or empty state should be visible
    const chartOrEmpty = page
      .getByText(/No eval history available|entertainment/i)
      .first();
    await expect(chartOrEmpty).toBeVisible();
  });

  test("category drill-down works", async ({ page }) => {
    await page.goto("/evals");

    // Click on a category card (they are links)
    await page.getByText("creativity").first().click();

    await expect(page).toHaveURL(/\/evals\/creativity/);
    await expect(
      page.getByRole("heading", { name: /creativity/i }),
    ).toBeVisible();

    // Back link
    await expect(
      page.getByRole("link", { name: /Back to dashboard/i }),
    ).toBeVisible();
  });

  test("simulation runs table shows with simulation column", async ({ page }) => {
    await page.goto("/evals");

    // The runs table should exist (might be empty)
    await expect(
      page.getByRole("heading", { name: /SIMULATION RUNS/i }),
    ).toBeVisible();

    // Simulation column should be visible in the table header
    const table = page.locator("table");
    const tableExists = await table.isVisible().catch(() => false);
    if (tableExists) {
      await expect(
        table.getByRole("columnheader", { name: /Simulation/ }),
      ).toBeVisible();
    }
  });

  test("raw data export buttons exist", async ({ page }) => {
    await page.goto("/evals");

    await expect(page.getByTestId("export-json")).toBeVisible();
    await expect(page.getByTestId("export-csv")).toBeVisible();
  });

  test("LLM-as-judge disclaimer is visible", async ({ page }) => {
    await page.goto("/evals");

    const disclaimer = page.getByTestId("llm-judge-disclaimer");
    await expect(disclaimer).toBeVisible();
    await expect(disclaimer).toContainText("LLM-as-judge");
  });
});
