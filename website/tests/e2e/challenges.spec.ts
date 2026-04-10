import { expect, test } from "@playwright/test";

test.describe("Challenges Page", () => {
  test("challenge page loads with banner and form", async ({ page }) => {
    await page.goto("/challenges");

    // Page heading
    await expect(
      page.getByRole("heading", { name: /CHALLENGES/i }),
    ).toBeVisible();

    // Banner explaining challenges
    await expect(
      page.getByText(/how the audience influences what the agents work on/),
    ).toBeVisible();

    // Research note callout
    await expect(
      page.getByText(/RESEARCH NOTE/),
    ).toBeVisible();
    await expect(
      page.getByText(/agent autonomy metrics/),
    ).toBeVisible();

    // Submit form
    await expect(
      page.getByText(/SUBMIT A CHALLENGE/),
    ).toBeVisible();
    await expect(
      page.getByLabel(/What should the agents work on/),
    ).toBeVisible();
  });

  test("submit form has required fields", async ({ page }) => {
    await page.goto("/challenges");

    // Description textarea
    const textarea = page.getByLabel(/What should the agents work on/);
    await expect(textarea).toBeVisible();

    // Category select
    const categorySelect = page.getByLabel(/Category/);
    await expect(categorySelect).toBeVisible();

    // Submitter name input
    const nameInput = page.getByLabel(/Your name/);
    await expect(nameInput).toBeVisible();

    // Submit button
    const submitBtn = page.getByRole("button", { name: /Submit Challenge/ });
    await expect(submitBtn).toBeVisible();
  });

  test("sort and filter controls are visible", async ({ page }) => {
    await page.goto("/challenges");

    await expect(
      page.getByLabel(/Sort challenges/),
    ).toBeVisible();
    await expect(
      page.getByLabel(/Filter by status/),
    ).toBeVisible();
    await expect(
      page.getByLabel(/Filter by category/),
    ).toBeVisible();
  });
});
