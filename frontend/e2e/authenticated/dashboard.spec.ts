import { setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, test } from "@playwright/test";

// Runs with the saved e2e-user session (see playwright.config.ts's "chromium
// (authenticated)" project + e2e/auth.setup.ts).

test.beforeEach(async ({ page }) => {
  await setupClerkTestingToken({ page });
});

test("signed-in visitor reaches the dashboard, not the login redirect", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).not.toHaveURL(/\/login/);
  // This test account has no AWS role connected, so AWSGate shows its onboarding
  // screen rather than the live dashboard — that screen only renders past a real
  // Clerk session, so its presence is itself proof auth worked.
  await expect(page.getByRole("heading", { name: /Welcome to Nimbus AI/i })).toBeVisible({
    timeout: 10_000,
  });
});

test("chat page is reachable when signed in", async ({ page }) => {
  await page.goto("/chat");
  await expect(page).not.toHaveURL(/\/login/);
});
