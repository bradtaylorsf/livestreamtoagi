import { expect, test } from "@playwright/test";

test.describe("Clips Page", () => {
  test("renders heading and description", async ({ page }) => {
    await page.goto("/clips");

    await expect(
      page.getByRole("heading", { name: "CLIPS" }),
    ).toBeVisible();

    await expect(
      page.getByText(/Highlights and memorable moments/),
    ).toBeVisible();
  });

  test("shows coming soon state when no clips exist", async ({ page }) => {
    await page.goto("/clips");

    // Wait for loading to finish
    await expect(
      page.getByRole("heading", { name: /COMING SOON/i }),
    ).toBeVisible();

    await expect(
      page.getByText(/Curated highlights from agent conversations/),
    ).toBeVisible();
  });

  test("category filter buttons are present", async ({ page }) => {
    await page.goto("/clips");

    await expect(page.getByRole("button", { name: "All" })).toBeVisible();
    await expect(page.getByRole("button", { name: "funny" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "dramatic" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "technical" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "philosophical" }),
    ).toBeVisible();
  });

  test("agent filter dropdown is present", async ({ page }) => {
    await page.goto("/clips");

    const agentSelect = page.getByLabel("Filter by agent");
    await expect(agentSelect).toBeVisible();

    // Should have "All Agents" as default
    await expect(agentSelect).toHaveValue("");
  });
});
