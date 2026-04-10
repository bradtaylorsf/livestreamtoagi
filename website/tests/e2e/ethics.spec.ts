import { expect, test } from "@playwright/test";

test.describe("Ethics Page", () => {
  test("loads with all major sections", async ({ page }) => {
    await page.goto("/ethics");

    await expect(page).toHaveTitle(/Ethics/);

    // Header
    await expect(
      page.getByRole("heading", { name: /ETHICS & DATA POLICY/i }),
    ).toBeVisible();

    // Data We Collect
    const collected = page.getByTestId("data-collected");
    await expect(collected).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /DATA WE COLLECT/i }),
    ).toBeVisible();
    await expect(page.getByText("Chat messages")).toBeVisible();
    await expect(page.getByText("Vote responses")).toBeVisible();
    await expect(page.getByText("Challenge submissions")).toBeVisible();
    await expect(page.getByText("Viewing metrics")).toBeVisible();

    // How Data Is Used
    const usage = page.getByTestId("data-usage");
    await expect(usage).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /HOW DATA IS USED/i }),
    ).toBeVisible();

    // What We Don't Collect
    const notCollected = page.getByTestId("data-not-collected");
    await expect(notCollected).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /WHAT WE DON'T COLLECT/i }),
    ).toBeVisible();
    await expect(
      page.getByText(/No selling or sharing/),
    ).toBeVisible();

    // Data Removal
    const removal = page.getByTestId("data-removal");
    await expect(removal).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /DATA REMOVAL/i }),
    ).toBeVisible();

    // Research Use
    const research = page.getByTestId("research-use");
    await expect(research).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /RESEARCH USE/i }),
    ).toBeVisible();
  });

  test("navigation link to ethics page exists", async ({ page }) => {
    await page.goto("/");

    const ethicsLink = page
      .locator("nav")
      .getByRole("link", { name: "Ethics" });
    await expect(ethicsLink).toBeVisible();
  });

  test("footer link to ethics page exists", async ({ page }) => {
    await page.goto("/");

    const footerLink = page
      .locator("footer")
      .getByRole("link", { name: "Ethics" });
    await expect(footerLink).toBeVisible();
  });

  test("cross-links work", async ({ page }) => {
    await page.goto("/ethics");

    // Should have links to safety, about, and evals
    await expect(
      page.getByRole("link", { name: /Safety report/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /About the project/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Eval dashboard/i }),
    ).toBeVisible();
  });
});
