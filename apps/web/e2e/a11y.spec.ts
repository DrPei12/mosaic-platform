import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { signIn } from "./helpers/demo";

for (const path of ["/", "/login"] as const) {
  test(`${path} has no serious accessibility violations`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator("body")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(
      (item) => item.impact === "serious" || item.impact === "critical",
    );
    expect(serious).toEqual([]);
  });
}

test("the authenticated marketplace keeps the old shell a11y gate honest", async ({
  page,
}) => {
  await signIn(page);
  await expect(page.getByTestId("model-marketplace")).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (item) => item.impact === "serious" || item.impact === "critical",
  );
  expect(serious).toEqual([]);
});
