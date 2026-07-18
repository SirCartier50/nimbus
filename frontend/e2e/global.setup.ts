import { clerkSetup } from "@clerk/testing/playwright";
import { test as setup } from "@playwright/test";

// Fetches a Clerk Testing Token once per suite run (needs CLERK_SECRET_KEY, already
// in .env). The token lets later tests bypass Clerk's Cloudflare bot-detection
// challenge — confirmed necessary by hand: a plain automated form-fill against
// /signup silently stalls behind a Cloudflare Turnstile preload with no visible
// error. Must run before any test that touches a Clerk-protected page.
setup.describe.configure({ mode: "serial" });
setup("global setup", async () => {
  await clerkSetup();
});
