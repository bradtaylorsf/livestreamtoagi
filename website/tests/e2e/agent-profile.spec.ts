import { expect, test } from "@playwright/test";

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
