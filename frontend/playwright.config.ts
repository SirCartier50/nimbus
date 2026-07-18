import { defineConfig, devices } from "@playwright/test";

const authFile = "playwright/.clerk/user.json";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    // NOT 3000: Docker Desktop + WSL relay squat on that port on this machine,
    // so Playwright's reuseExistingServer picked up the wrong service and every
    // Clerk agent-task redirect (localhost:3000/dashboard) hit a dead end —
    // burning the single-use ticket without ever reaching the app. Confirmed by
    // hand via the resulting "agent task has already been used" error.
    baseURL: "http://localhost:3100",
    trace: "on-first-retry",
  },
  projects: [
    // Runs once per suite: fetches a Clerk Testing Token (bot-detection bypass).
    { name: "global setup", testMatch: /global\.setup\.ts/ },
    // Runs once per suite, after the token exists: signs in (or signs up on first
    // run) the dev-only e2e test user and saves the session to authFile.
    {
      name: "clerk setup",
      testMatch: /auth\.setup\.ts/,
      dependencies: ["global setup"],
    },
    // Unauthenticated specs — landing page, route-protection redirects, etc.
    // Excludes both setup files and anything under e2e/authenticated/.
    {
      name: "chromium",
      testMatch: /.*\.spec\.ts/,
      testIgnore: /authenticated\//,
      use: { ...devices["Desktop Chrome"] },
    },
    // Specs that need a signed-in session reuse the saved storage state instead
    // of re-authenticating per test.
    {
      name: "chromium (authenticated)",
      testMatch: /authenticated\/.*\.spec\.ts/,
      dependencies: ["clerk setup"],
      use: { ...devices["Desktop Chrome"], storageState: authFile },
    },
  ],
  webServer: {
    command: "npm run dev -- --port 3100",
    url: "http://localhost:3100",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
