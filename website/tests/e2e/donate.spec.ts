import { expect, test } from "@playwright/test";

test.describe("Donate Page", () => {
  test("page loads with all sections", async ({ page }) => {
    await page.goto("/donate");

    // Hero heading
    await expect(
      page.getByRole("heading", { name: /SUPPORT THE RESEARCH/i }),
    ).toBeVisible();

    // All section headings
    await expect(
      page.getByRole("heading", { name: /WHY SUPPORT THIS PROJECT/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^DONATE$/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /COST TRANSPARENCY/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /RESEARCH MISSION/i }),
    ).toBeVisible();
  });

  test("donation links are present and functional", async ({ page }) => {
    await page.goto("/donate");

    // GitHub Sponsors link
    const sponsorLink = page.getByTestId("donate-github-sponsors");
    await expect(sponsorLink).toBeVisible();
    await expect(sponsorLink).toHaveAttribute(
      "href",
      "https://github.com/sponsors/bradtaylor",
    );
    await expect(sponsorLink).toHaveAttribute("target", "_blank");

    // Ko-fi link
    const kofiLink = page.getByTestId("donate-kofi");
    await expect(kofiLink).toBeVisible();
    await expect(kofiLink).toHaveAttribute("target", "_blank");
  });

  test("navigation links to donate page", async ({ page }) => {
    await page.goto("/");

    // Open About dropdown (desktop nav)
    const aboutButton = page.locator("nav button", { hasText: "About" });
    if (await aboutButton.isVisible()) {
      await aboutButton.click();
      const donateLink = page.getByRole("menuitem", { name: "Donate" });
      await expect(donateLink).toBeVisible();
    }
  });

  test("page is mobile responsive", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/donate");

    await expect(
      page.getByRole("heading", { name: /SUPPORT THE RESEARCH/i }),
    ).toBeVisible();
    await expect(
      page.getByTestId("donate-github-sponsors"),
    ).toBeVisible();
  });
});
