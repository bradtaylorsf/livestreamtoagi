import { expect, test } from "@playwright/test";

test.describe("Safety Page", () => {
  test("loads with hero and all major sections", async ({ page }) => {
    await page.goto("/safety");

    await expect(page).toHaveTitle(/Safety/);

    // Hero
    const hero = page.getByTestId("safety-hero");
    await expect(hero).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /SAFETY REPORT/i }),
    ).toBeVisible();
    await expect(
      page.getByText(/24\/7 livestream can.t hide its failures/),
    ).toBeVisible();

    // Content Filtering
    const filtering = page.getByTestId("content-filtering");
    await expect(filtering).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /CONTENT FILTERING/i }),
    ).toBeVisible();
    await expect(page.getByText("LAYER 1")).toBeVisible();
    await expect(page.getByText("LAYER 2")).toBeVisible();
    await expect(page.getByText("LAYER 3")).toBeVisible();

    // Severity Scale
    const severity = page.getByTestId("severity-scale");
    await expect(severity).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /SEVERITY SCALE/i }),
    ).toBeVisible();

    // Red-Teaming
    const redTeaming = page.getByTestId("red-teaming");
    await expect(redTeaming).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /RED-TEAMING/i }),
    ).toBeVisible();

    // Kill Switch
    const killSwitch = page.getByTestId("kill-switch");
    await expect(killSwitch).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /KILL SWITCH/i }),
    ).toBeVisible();

    // Jailbreak Resistance
    const jailbreak = page.getByTestId("jailbreak-resistance");
    await expect(jailbreak).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /JAILBREAK RESISTANCE/i }),
    ).toBeVisible();
  });

  test("severity levels all render", async ({ page }) => {
    await page.goto("/safety");

    await expect(page.getByText("LEVEL 1")).toBeVisible();
    await expect(page.getByText("Trivial")).toBeVisible();
    await expect(page.getByText("LEVEL 2")).toBeVisible();
    await expect(page.getByText("Minor")).toBeVisible();
    await expect(page.getByText("LEVEL 3")).toBeVisible();
    await expect(page.getByText("Moderate")).toBeVisible();
    await expect(page.getByText("LEVEL 4")).toBeVisible();
    await expect(page.getByText("Severe")).toBeVisible();
    await expect(page.getByText("LEVEL 5")).toBeVisible();
    await expect(page.getByText("Critical")).toBeVisible();
  });

  test("cross-links to related pages", async ({ page }) => {
    await page.goto("/safety");

    const livingDoc = page.getByTestId("living-document");
    await expect(livingDoc).toBeVisible();

    await expect(
      livingDoc.getByRole("link", { name: /About the research/i }),
    ).toHaveAttribute("href", "/about");
    await expect(
      livingDoc.getByRole("link", { name: /Ethics/i }),
    ).toHaveAttribute("href", "/ethics");
    await expect(
      livingDoc.getByRole("link", { name: /Eval dashboard/i }),
    ).toHaveAttribute("href", "/evals");
  });

  test("navigation link to safety page exists", async ({ page }) => {
    await page.goto("/");

    const safetyLink = page
      .locator("nav")
      .getByRole("link", { name: "Safety" });
    await expect(safetyLink).toBeVisible();
  });
});
