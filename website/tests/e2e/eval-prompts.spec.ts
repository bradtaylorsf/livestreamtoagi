import { expect, test } from "@playwright/test";

test.describe("Eval Prompts Page", () => {
  test("page loads with header and explanation", async ({ page }) => {
    await page.goto("/evals/prompts");

    await expect(
      page.getByRole("heading", { name: /EVALUATION PROMPTS/i }),
    ).toBeVisible();

    // LLM-as-judge explanation
    await expect(
      page.getByRole("heading", { name: /HOW LLM-AS-JUDGE WORKS/i }),
    ).toBeVisible();

    // Contribution section
    await expect(
      page.getByRole("heading", { name: /HOW TO CONTRIBUTE/i }),
    ).toBeVisible();
  });

  test("category prompts render with system prompt and rubric", async ({
    page,
  }) => {
    await page.goto("/evals/prompts");

    // Check for the creativity category (always present in YAML files)
    const creativityCard = page.getByTestId("prompt-creativity");

    // If backend is running, cards should be visible
    // If not, there should be an empty state
    const hasCards = await creativityCard.isVisible().catch(() => false);
    if (hasCards) {
      // System prompt present
      await expect(
        page.getByTestId("system-prompt-creativity"),
      ).toBeVisible();

      // Rubric present
      await expect(page.getByTestId("rubric-creativity")).toBeVisible();

      // Sub-scores present
      await expect(
        page.getByTestId("sub-scores-creativity"),
      ).toBeVisible();

      // GitHub source link present
      const githubLink = page.getByTestId("github-link-creativity");
      await expect(githubLink).toBeVisible();
      await expect(githubLink).toHaveAttribute(
        "href",
        /evals\/prompts\/creativity\.yaml/,
      );
    } else {
      // Empty state when backend is not available
      await expect(
        page.getByText(/No eval prompts available/),
      ).toBeVisible();
    }
  });

  test("breadcrumb navigation works", async ({ page }) => {
    await page.goto("/evals/prompts");

    const evalsLink = page.getByRole("link", { name: "Evals" });
    await expect(evalsLink).toBeVisible();
    await expect(evalsLink).toHaveAttribute("href", "/evals");
  });

  test("evals methodology links to prompts page", async ({ page }) => {
    await page.goto("/evals");

    const promptsLink = page.getByRole("link", {
      name: /View all evaluation prompts/,
    });
    await expect(promptsLink).toBeVisible();
    await expect(promptsLink).toHaveAttribute("href", "/evals/prompts");
  });
});
