import { expect, test } from "@playwright/test";

test.describe("World Page", () => {
  test("world page loads with viewer fallback", async ({ page }) => {
    await page.goto("/world");

    await expect(
      page.getByRole("heading", { name: "WORLD" }),
    ).toBeVisible();

    // Fallback should be visible since Phaser spectator isn't built yet
    await expect(
      page.getByText(/pixel art world/i).first(),
    ).toBeVisible();
  });

  test("agent markers section is present", async ({ page }) => {
    await page.goto("/world");

    await expect(page.getByText("AGENT POSITIONS")).toBeVisible();

    // Check some agents are listed
    await expect(page.getByText("Vera")).toBeVisible();
    await expect(page.getByText("Rex")).toBeVisible();
    await expect(page.getByText("Alpha")).toBeVisible();
  });

  test("world evolution timeline displays", async ({ page }) => {
    await page.goto("/world");

    await expect(page.getByText("WORLD EVOLUTION")).toBeVisible();
    await expect(page.getByText("The Office Appears")).toBeVisible();
  });

  test("build progression gallery displays", async ({ page }) => {
    await page.goto("/world");

    await expect(page.getByText("BUILD PROGRESSION")).toBeVisible();
  });
});
