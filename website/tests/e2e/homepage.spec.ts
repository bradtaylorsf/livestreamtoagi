import { expect, test } from "@playwright/test";

test.describe("Homepage", () => {
  test("loads successfully with title and navigation", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle(/Livestream to AGI/);

    // Navigation renders with all links
    const nav = page.locator("nav");
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("link", { name: "Home" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Agents" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "World" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Challenges" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Lore" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Clips" })).toBeVisible();

    // Hero heading
    await expect(
      page.getByRole("heading", { name: /LIVESTREAM.*AGI/i }),
    ).toBeVisible();

    // Agent cards render
    await expect(page.getByText("Vera")).toBeVisible();
    await expect(page.getByText("Rex")).toBeVisible();
  });

  test("has no console errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        errors.push(msg.text());
      }
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    expect(errors).toEqual([]);
  });

  test("navigation links work", async ({ page }) => {
    await page.goto("/");

    await page.getByRole("link", { name: "Agents" }).click();
    await expect(page).toHaveURL("/agents");
    await expect(
      page.getByRole("heading", { name: "AGENTS" }),
    ).toBeVisible();

    await page.getByRole("link", { name: "World" }).click();
    await expect(page).toHaveURL("/world");
  });
});
