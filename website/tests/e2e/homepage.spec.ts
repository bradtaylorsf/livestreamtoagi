import { expect, test } from "@playwright/test";

test.describe("Homepage", () => {
  test("renders hero section with mission statement", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveTitle(/Livestream to AGI/);

    // Hero heading
    await expect(
      page.getByRole("heading", { name: /LIVESTREAM.*AGI/i }),
    ).toBeVisible();

    // Satirical hook
    await expect(
      page.getByText(/AI agents can.t even run a profitable livestream/),
    ).toBeVisible();

    // Mission statement
    await expect(
      page.getByText(/Exploring how AI agents develop social dynamics/),
    ).toBeVisible();

    // CTA to about page
    await expect(
      page.getByRole("link", { name: /Learn about the research/ }),
    ).toBeVisible();
  });

  test("AGI disclaimer/link is visible", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByText(/AGI in the name is tongue-in-cheek/),
    ).toBeVisible();

    const learnWhyLink = page.getByRole("link", { name: /Learn why/ });
    await expect(learnWhyLink).toBeVisible();
    await expect(learnWhyLink).toHaveAttribute("href", "/about");
  });

  test("all 9 agent cards visible with names", async ({ page }) => {
    await page.goto("/");

    const agentNames = [
      "Vera",
      "Rex",
      "Aurora",
      "Pixel",
      "Fork",
      "Sentinel",
      "Grok",
      "Management",
      "Alpha",
    ];

    for (const name of agentNames) {
      await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
    }
  });

  test("blog posts section displays", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /LATEST FROM THE LAB/ }),
    ).toBeVisible();

    // At least one post title visible
    await expect(
      page.getByText(/tongue-in-cheek/i).first(),
    ).toBeVisible();
  });

  test("navigation renders with all links", async ({ page }) => {
    await page.goto("/");

    const nav = page.locator("nav");
    await expect(nav).toBeVisible();
    await expect(nav.getByRole("link", { name: "Home" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Agents" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "World" })).toBeVisible();
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
