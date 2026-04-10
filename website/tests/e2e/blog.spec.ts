import { expect, test } from "@playwright/test";

test.describe("Blog", () => {
  test("blog list page loads with posts", async ({ page }) => {
    await page.goto("/blog");

    await expect(
      page.getByRole("heading", { name: /BLOG/i }),
    ).toBeVisible();

    // At least one post should be visible
    await expect(
      page.getByText(/Tongue-in-Cheek/i).first(),
    ).toBeVisible();

    // Tag filter bar should be visible
    await expect(page.getByTestId("tag-filter")).toBeVisible();
  });

  test("individual post renders from MDX", async ({ page }) => {
    await page.goto("/blog/why-agi-is-tongue-in-cheek");

    // Post title
    await expect(
      page.getByText(/Tongue-in-Cheek/i).first(),
    ).toBeVisible();

    // Author and date
    await expect(page.getByText("Brad Taylor")).toBeVisible();

    // Back link
    await expect(
      page.getByRole("link", { name: /Back to blog/i }),
    ).toBeVisible();

    // MDX content rendered
    await expect(
      page.getByText(/Artificial General Action Intelligence/i),
    ).toBeVisible();
  });

  test("tag filtering works", async ({ page }) => {
    await page.goto("/blog");

    // Click a tag to filter
    const researchTag = page.getByTestId("tag-filter").getByText("research");
    await researchTag.click();

    await expect(page).toHaveURL(/tag=research/);

    // Should still show the research-tagged post
    await expect(
      page.getByText(/Tongue-in-Cheek/i).first(),
    ).toBeVisible();
  });
});
