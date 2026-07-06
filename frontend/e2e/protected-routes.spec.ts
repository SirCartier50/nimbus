import { expect, test } from "@playwright/test";

test.describe("Route protection (no Clerk session)", () => {
  for (const path of ["/dashboard", "/chat"]) {
    test(`${path} redirects an unauthenticated visitor to /login`, async ({ page }) => {
      await page.goto(path);
      await page.waitForURL(/\/login/);
      expect(page.url()).toContain("/login");
    });
  }
});
