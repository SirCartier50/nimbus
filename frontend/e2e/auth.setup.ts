import { setupClerkTestingToken } from "@clerk/testing/playwright";
import { test as setup, expect } from "@playwright/test";
import path from "path";

// Dev/test-only account, created once by hand in the Clerk Dashboard (Users →
// Create user) — NOT via self-service signup. Two things ruled that out:
//   1. This instance's own client-side email validation rejects the
//      "+clerk_test" subaddress Clerk's docs describe for auto-verified test
//      signups (confirmed by hand: a plain email reaches
//      /signup/verify-email-address fine; the +clerk_test form is flagged
//      invalid before it ever submits).
//   2. A real signup needs a code delivered to a real inbox, which nothing
//      here has access to.
//
// This instance also has "sign in from a new device" email-code verification
// on. That's a distinct Clerk feature from bot detection — setupClerkTestingToken
// does NOT bypass it (confirmed by hand). The Backend API's experimental
// createAgentTestingTask was tried as a way around both the password AND this
// step entirely; abandoned after it reliably got stuck in this specific
// cross-domain dev-instance setup (either the single-use ticket got burned on a
// second, unexplained hit when combined with setupClerkTestingToken, or —
// without it — the ticket redirected all the way back to the app but the
// session never got picked up, landing back on /login). The plain sign-in form
// below is the standard, well-documented path and DOES work up to this one
// step, so it's the one worth debugging rather than the experimental API.
//
// First run needs a real code from the test account's inbox (one-time only —
// after this succeeds, the session is cached in `authFile` and reused).
const TEST_EMAIL = process.env.E2E_TEST_EMAIL ?? "e2e-test@nimbus.dev";
const TEST_PASSWORD = process.env.E2E_TEST_PASSWORD ?? "";
const TEST_DEVICE_CODE = process.env.E2E_TEST_DEVICE_CODE ?? "";

const authFile = path.join(__dirname, "../playwright/.clerk/user.json");

setup("authenticate as the e2e test user", async ({ page }) => {
  if (!TEST_PASSWORD) {
    throw new Error(
      "Set E2E_TEST_EMAIL / E2E_TEST_PASSWORD (frontend/.env.local) to the " +
        "Dashboard-created test account before running authenticated e2e specs."
    );
  }

  await setupClerkTestingToken({ page });

  await page.goto("/login");
  await page.getByPlaceholder("Enter your email address").fill(TEST_EMAIL);
  await page.getByPlaceholder("Enter your password").fill(TEST_PASSWORD);
  await page.getByRole("button", { name: "Continue" }).click();

  const needsDeviceCode = await page
    .waitForURL(/\/login\/factor-two/, { timeout: 8_000 })
    .then(() => true)
    .catch(() => false);

  if (needsDeviceCode) {
    if (!TEST_DEVICE_CODE) {
      throw new Error(
        "This account needs a one-time 'new device' verification code, sent to " +
          `${TEST_EMAIL}'s inbox. Set E2E_TEST_DEVICE_CODE (frontend/.env.local) to ` +
          "that code and rerun — this is only needed once; the session is cached " +
          "in playwright/.clerk/user.json after it succeeds."
      );
    }
    // .fill() sets the DOM value directly, which Clerk's OTP box doesn't pick up
    // (confirmed by hand: the field stayed empty, showing "Enter code."] —
    // it needs real keystroke events.
    const codeInput = page.getByRole("textbox", { name: "Enter verification code" });
    await codeInput.click();
    await codeInput.pressSequentially(TEST_DEVICE_CODE);
  }

  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  await page.context().storageState({ path: authFile });
});
