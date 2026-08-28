import { expect, test } from "@playwright/test";

import {
  expectModelCards,
  modelCard,
  signIn,
  waitForStablePage,
} from "./helpers/demo";

const canonicalNames = [
  "Qwen 3.5",
  "DeepSeek V4",
  "GLM 5.2",
  "Kimi K2.7 Code",
  "GPT-OSS",
  "Gemma 4",
  "Qwen Image",
  "FLUX 2",
  "HunyuanVideo 1.5",
  "Qwen3-TTS 1.7B VoiceDesign",
  "Qwen3-TTS 1.7B CustomVoice",
  "Qwen3-TTS 1.7B Base",
] as const;

const categoryCounts = {
  文本: 6,
  图像: 2,
  视频: 1,
  音频: 3,
} as const;

const forbiddenUiText = /(?:\b(?:provider|deployment|revision|quantization|precision|license|snapshot|open[- ]source)\b|提供商|部署|修订|量化|精度|许可证|快照|开源)/i;

test("catalog has the exact public demo set and reviewed viewport evidence", async ({
  page,
}, testInfo) => {
  await signIn(page);

  const names = await page
    .locator('[data-testid^="model-card-"] h2')
    .allTextContents();
  expect(names).toHaveLength(canonicalNames.length);
  expect([...new Set(names)].sort()).toEqual([...canonicalNames].sort());
  await expectModelCards(page, 12);
  const videoTitle = page.getByTestId("model-card-hunyuan-video-1-5").locator("h2");
  await expect(videoTitle).toHaveText("HunyuanVideo 1.5");
  await expect
    .poll(() => videoTitle.evaluate((element) => element.scrollWidth <= element.clientWidth + 1))
    .toBe(true);

  for (const [label, count] of Object.entries(categoryCounts)) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expectModelCards(page, count);
  }
  await page.getByRole("button", { name: "全部", exact: true }).click();
  await expectModelCards(page, 12);

  const bodyText = await page.locator("body").innerText();
  expect(bodyText).not.toMatch(forbiddenUiText);
  await page.mouse.move(0, 0);
  await waitForStablePage(page);
  await expect(page).toHaveScreenshot(`marketplace-${testInfo.project.name}.png`, {
    animations: "disabled",
  });
});

test("category and search filters intersect, then recover from an empty result", async ({
  page,
}) => {
  await signIn(page);
  await page.getByRole("button", { name: "文本", exact: true }).click();
  await expectModelCards(page, categoryCounts["文本"]);

  const search = page.getByRole("searchbox", { name: "搜索模型" });
  await search.fill("Qwen 3.5");
  await expectModelCards(page, 1);
  await expect(page.locator('[data-testid^="model-card-"] h2')).toHaveText([
    "Qwen 3.5",
  ]);

  await search.fill("不存在的模型");
  await expect(page.getByRole("status")).toContainText("没有找到匹配的模型");
  await expectModelCards(page, 0);

  await page.getByRole("button", { name: "清空搜索" }).click();
  await expectModelCards(page, categoryCounts["文本"]);
  await expect(search).toHaveValue("");
});

test("favorite state is exposed as aria-pressed and persists after reload", async ({
  page,
}) => {
  await signIn(page);
  const card = modelCard(page, "qwen-3-5");
  const favorite = card.locator('button[aria-pressed]');
  await expect(favorite).toHaveAttribute("aria-pressed", "false");
  await favorite.click();
  await expect(favorite).toHaveAttribute("aria-pressed", "true");

  await page.reload({ waitUntil: "networkidle" });
  await expectModelCards(page, 12);
  await expect(modelCard(page, "qwen-3-5").locator('button[aria-pressed]')).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("a non-hero Radix detail drawer closes with Escape and restores focus", async ({
  page,
}) => {
  await signIn(page);
  const trigger = modelCard(page, "deepseek-v4").getByRole("button", {
    name: "查看 DeepSeek V4 详情",
  });
  await trigger.focus();
  await trigger.press("Enter");
  const dialog = page.getByRole("dialog", { name: "DeepSeek V4" });
  await expect(dialog).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test("text model action creates a deterministic demo conversation route", async ({
  page,
}) => {
  await signIn(page);
  await modelCard(page, "qwen-3-5")
    .getByRole("button", { name: "开始对话 Qwen 3.5" })
    .click();
  await expect(page).toHaveURL(/\/chat\/conversation-[a-z0-9]+$/);
  await expect(page.getByTestId("chat-workspace")).toBeVisible();
  await expect(
    page.getByTestId("chat-header").getByRole("heading", {
      name: "文本模型",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByTestId("message-list-empty")).toBeVisible();
  const trigger = page.getByRole("button", { name: "打开会话列表" });
  await trigger.click();
  await expect(
    page.getByRole("dialog", { name: "会话列表" }).getByRole("button", { name: /产品规划讨论/ }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
});

test("media detail drawer CTAs route to the matching studio", async ({ page }) => {
  const mediaRoutes = [
    { id: "qwen-image", name: "Qwen Image", path: "/studio/image/qwen-image" },
    {
      id: "hunyuan-video-1-5",
      name: "HunyuanVideo 1.5",
      path: "/studio/video/hunyuan-video-1-5",
    },
    {
      id: "qwen3-tts-voice-design",
      name: "Qwen3-TTS 1.7B VoiceDesign",
      path: "/studio/audio/qwen3-tts-voice-design",
    },
  ] as const;

  await signIn(page);
  for (const route of mediaRoutes) {
    await page.goto("/models");
    await expectModelCards(page, 12);
    await modelCard(page, route.id)
      .getByRole("button", { name: `查看 ${route.name} 详情` })
      .click();
    const dialog = page.getByRole("dialog", { name: route.name });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "打开工作台" }).click();
    await expect(page).toHaveURL(new RegExp(`${route.path}$`));
  }
});
