import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { modelCard, signIn } from "./helpers/demo";

async function expectNoSeriousViolations(page: Parameters<typeof signIn>[0]) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (item) => item.impact === "serious" || item.impact === "critical",
  );
  expect(serious).toEqual([]);
}

test("marketplace has zero serious or critical axe violations", async ({ page }) => {
  await signIn(page);
  await expect(page.getByTestId("model-marketplace")).toBeVisible();
  await expectNoSeriousViolations(page);
});

test("chat has zero serious or critical axe violations", async ({ page }) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-001");
  await expect(page.getByTestId("chat-workspace")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "输入消息" })).toBeVisible();
  await expectNoSeriousViolations(page);
});

test("marketplace keyboard path covers categories, search, favorite and drawer Escape", async ({
  page,
}) => {
  await signIn(page);

  const textCategory = page.getByRole("button", { name: "文本", exact: true });
  await textCategory.focus();
  await textCategory.press("Enter");
  await expect(textCategory).toHaveAttribute("aria-pressed", "true");

  const search = page.getByRole("searchbox", { name: "搜索模型" });
  await search.focus();
  await search.fill("Qwen");
  await expect(page.getByTestId("model-card-qwen-3-5")).toBeVisible();

  const favorite = modelCard(page, "qwen-3-5").locator('button[aria-pressed]');
  await favorite.focus();
  await favorite.press("Enter");
  await expect(favorite).toHaveAttribute("aria-pressed", "true");

  await search.fill("");
  const drawerTrigger = modelCard(page, "deepseek-v4").getByRole("button", {
    name: "查看 DeepSeek V4 详情",
  });
  await drawerTrigger.focus();
  await drawerTrigger.press("Enter");
  await expect(page.getByRole("dialog", { name: "DeepSeek V4" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "DeepSeek V4" })).not.toBeVisible();
  await expect(drawerTrigger).toBeFocused();
});

test.describe("reduced motion", () => {
  test("core marketplace controls remain functional with reduced motion", async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await signIn(page);
    const textCategory = page.getByRole("button", { name: "文本", exact: true });
    await textCategory.click();
    await expect(textCategory).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("model-card-qwen-3-5")).toBeVisible();

    const drawerTrigger = modelCard(page, "deepseek-v4").getByRole("button", {
      name: "查看 DeepSeek V4 详情",
    });
    await drawerTrigger.click();
    await expect(page.getByRole("dialog", { name: "DeepSeek V4" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawerTrigger).toBeFocused();
  });
});
