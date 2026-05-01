import { expect, test } from "@playwright/test";

test.describe("Agents Listing Page", () => {
  test("renders heading and description", async ({ page }) => {
    await page.goto("/agents");

    await expect(page).toHaveTitle(/Agents/);

    await expect(
      page.getByRole("heading", { name: "AGENTS" }),
    ).toBeVisible();

    await expect(
      page.getByText(/Meet the 9 AI agents/),
    ).toBeVisible();

    await expect(
      page.getByText(/Click any agent to see their full profile/),
    ).toBeVisible();
  });

  test("agent grid renders all 9 agents", async ({ page }) => {
    await page.goto("/agents");

    const agentNames = [
      "Vera",
      "Rex",
      "Aurora",
      "Pixel",
      "Fork",
      "Sentinel",
      "Grok",
      "Management",
      "Alpha",
    ];

    for (const name of agentNames) {
      await expect(
        page.getByText(name, { exact: true }).first(),
      ).toBeVisible();
    }
  });

  test("agent cards link to profile pages", async ({ page }) => {
    await page.goto("/agents");

    // Click the first agent card and verify navigation
    const firstCard = page.getByRole("link", { name: /Vera/ }).first();
    await expect(firstCard).toBeVisible();
    await firstCard.click();

    await expect(page).toHaveURL(/\/agents\/vera/);
    await expect(
      page.getByRole("heading", { name: /Vera/i }),
    ).toBeVisible();
  });

  test("THE CAST section heading is visible", async ({ page }) => {
    await page.goto("/agents");

    await expect(
      page.getByRole("heading", { name: /THE CAST/i }),
    ).toBeVisible();
  });
});
