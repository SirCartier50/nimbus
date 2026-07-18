import { expect, test } from "@playwright/test";

test.describe("Landing page", () => {
  test("renders the hero with the Nimbus AI brand", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Nimbus AI").first()).toBeVisible();
  });

  test("signed-out visitor sees a Start Building CTA pointing at /login", async ({ page }) => {
    await page.goto("/");
    // Copy is "Start Building", not "Get Started" — verified against the actual
    // hero/nav buttons in app/page.tsx.
    const cta = page.getByRole("link", { name: "Start Building" }).first();
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "/login");
  });

  test("footer no longer references the hackathon", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/hackathon/i)).toHaveCount(0);
  });
});
