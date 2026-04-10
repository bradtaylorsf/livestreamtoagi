import { expect, test } from "@playwright/test";

test.describe("Lore Page", () => {
  test("lore page loads with heading and note", async ({ page }) => {
    await page.goto("/lore");

    await expect(
      page.getByRole("heading", { name: /LORE/i }),
    ).toBeVisible();

    // Unreliable narrators note
    await expect(
      page.getByText(/unreliable narrators/),
    ).toBeVisible();
  });

  test("lore page has filter controls", async ({ page }) => {
    await page.goto("/lore");

    await expect(
      page.getByLabel(/Filter by agent/),
    ).toBeVisible();
    await expect(
      page.getByLabel(/Filter by event type/),
    ).toBeVisible();
  });
});

test.describe("Conversations Page", () => {
  test("conversation list page loads", async ({ page }) => {
    await page.goto("/conversations");

    await expect(
      page.getByRole("heading", { name: /CONVERSATIONS/i }),
    ).toBeVisible();

    await expect(
      page.getByText(/Browse past conversations/),
    ).toBeVisible();
  });
});
