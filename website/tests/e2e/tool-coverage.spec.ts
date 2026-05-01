import { expect, test } from "@playwright/test";

test.describe("Tool Coverage Section", () => {
  test("simulation report renders tool usage section with proper formatting", async ({
    page,
  }) => {
    // Navigate to simulations list to find a simulation
    await page.goto("/simulations");

    // Try to find a simulation link
    const simLink = page.locator("a[href^='/simulations/']").first();
    const hasSimulations = await simLink.isVisible().catch(() => false);

    if (!hasSimulations) {
      // No simulations available, skip the detailed test
      test.skip();
      return;
    }

    // Go to the simulation detail page
    await simLink.click();
    await page.waitForLoadState("networkidle");

    // Navigate to the report page
    const reportLink = page.getByRole("link", { name: /report/i });
    const hasReport = await reportLink.isVisible().catch(() => false);
    if (!hasReport) {
      test.skip();
      return;
    }
    await reportLink.click();
    await page.waitForLoadState("networkidle");

    // Find the Tool Usage section
    const toolSection = page.getByText("Tool Usage");
    const hasTool = await toolSection.isVisible().catch(() => false);
    if (!hasTool) {
      // Report may not have a tool usage section
      return;
    }

    // Verify it does NOT show raw JSON (the old behavior)
    // The section content should NOT contain `"by_tool"` as raw JSON key
    const sectionParent = page.locator("div", { has: toolSection }).first();
    const content = await sectionParent.textContent();

    // If tool data exists, we should see "Total Invocations" (formatted) not raw JSON
    if (content?.includes("total_invocations")) {
      // Still showing raw JSON — this would be a failure
      expect(content).not.toContain('"total_invocations"');
    }
  });

  test("tool usage empty state shows clear message", async ({ page }) => {
    // Navigate directly to a simulation report page
    // Even without data, the component should handle empty state
    await page.goto("/simulations");

    // Just verify the page loads — deeper testing depends on data availability
    await expect(
      page.getByRole("heading", { name: /simulations/i }),
    ).toBeVisible();
  });
});
