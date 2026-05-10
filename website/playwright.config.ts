import { defineConfig, devices } from "@playwright/test";

const specArgs = process.argv.filter((arg) =>
  /(?:^|[/\\])[^/\\]+\.spec\.ts$/.test(arg),
);
const runningReplayHarnessSpecOnly =
  specArgs.length === 1 &&
  /(?:^|[/\\])replay-harness\.spec\.ts$/.test(specArgs[0]);

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  ...(runningReplayHarnessSpecOnly
    ? {}
    : {
        webServer: {
          command: "npm run dev",
          url: "http://localhost:3000",
          reuseExistingServer: !process.env.CI,
        },
      }),
});
