import { expect, test } from "@playwright/test";

test.describe("About Page", () => {
  test("loads with all major sections", async ({ page }) => {
    await page.goto("/about");

    await expect(page).toHaveTitle(/About/);

    // Hero
    await expect(
      page.getByRole("heading", { name: /ABOUT THE RESEARCH/i }),
    ).toBeVisible();
    await expect(
      page.getByText(
        /AI agents can.t even run a profitable livestream/,
      ),
    ).toBeVisible();

    // Vision
    await expect(
      page.getByRole("heading", { name: /VISION/i }),
    ).toBeVisible();

    // AGI Framing
    await expect(
      page.getByText(/tongue-in-cheek/i).first(),
    ).toBeVisible();
    await expect(
      page.getByText(/Artificial General Action Intelligence/),
    ).toBeVisible();

    // Research Questions
    await expect(
      page.getByRole("heading", { name: /RESEARCH QUESTIONS/i }),
    ).toBeVisible();

    // Methodology
    await expect(
      page.getByRole("heading", { name: /METHODOLOGY/i }),
    ).toBeVisible();

    // Architecture
    await expect(
      page.getByText(/SYSTEM ARCHITECTURE/i),
    ).toBeVisible();

    // Related Work
    await expect(
      page.getByRole("heading", { name: /RELATED WORK/i }),
    ).toBeVisible();

    // Audience & Ethics
    await expect(
      page.getByRole("heading", { name: /AUDIENCE/i }),
    ).toBeVisible();

    // About Brad
    await expect(
      page.getByRole("heading", { name: /ABOUT BRAD/i }),
    ).toBeVisible();

    // Open Source / GitHub link
    await expect(
      page.getByRole("link", { name: /GitHub/i }),
    ).toBeVisible();

    // Glossary
    await expect(
      page.getByRole("heading", { name: /GLOSSARY/i }),
    ).toBeVisible();
  });

  test("navigation link works", async ({ page }) => {
    await page.goto("/");

    const aboutLink = page.locator("nav").getByRole("link", { name: "About" });
    await expect(aboutLink).toBeVisible();
    await aboutLink.click();
    await expect(page).toHaveURL("/about");
    await expect(
      page.getByRole("heading", { name: /ABOUT THE RESEARCH/i }),
    ).toBeVisible();
  });

  test("limitations section is visible and not collapsed", async ({ page }) => {
    await page.goto("/about");

    const limitations = page.getByTestId("limitations");
    await expect(limitations).toBeVisible();

    // All 6 limitations should be visible
    await expect(page.getByText("No control group")).toBeVisible();
    await expect(page.getByText("LLM-as-judge")).toBeVisible();
    await expect(page.getByText("Designed vs. emergent")).toBeVisible();
    await expect(page.getByText("Multi-model confound")).toBeVisible();
    await expect(page.getByText("Reproducibility")).toBeVisible();
    await expect(
      page.getByText("Content filter shapes behavior"),
    ).toBeVisible();
  });
});
