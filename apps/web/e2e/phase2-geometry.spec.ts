import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  expectChatReady,
  expectModelCards,
  modelCards,
  signIn,
} from "./helpers/demo";

const mobileProjects = new Set(["mobile", "mobile-large"]);

async function box(locator: Locator) {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      borderWidth: style.borderWidth,
      borderRadius: style.borderRadius,
      display: style.display,
    };
  });
}

async function expectControlsAtLeast44(page: Page): Promise<void> {
  const undersized = await page.evaluate(() => {
    const controls = Array.from(
      document.querySelectorAll<HTMLElement>("button, a, input, select, textarea"),
    );
    return controls
      .filter((element) => {
        if (element.matches('a[href="#main-content"]')) return false;
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      })
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          label: element.getAttribute("aria-label") ?? element.textContent?.trim().slice(0, 32) ?? element.tagName,
          width: rect.width,
          height: rect.height,
        };
      })
      .filter(({ width, height }) => width < 44 || height < 44);
  });
  expect(undersized).toEqual([]);
}

async function expectDesignTokens(page: Page): Promise<void> {
  await expect
    .poll(() =>
      page.evaluate(() => {
        const style = window.getComputedStyle(document.documentElement);
        const normalize = (value: string): string => {
          const compact = value.trim().toLowerCase();
          if (/^#[0-9a-f]{3}$/.test(compact)) {
            return `#${compact.slice(1).split("").map((part) => `${part}${part}`).join("")}`;
          }
          return compact;
        };
        return {
          canvas: normalize(style.getPropertyValue("--mosaic-color-canvas")),
          surface: normalize(style.getPropertyValue("--mosaic-color-surface")),
          line: normalize(style.getPropertyValue("--mosaic-color-line")),
          accent: normalize(style.getPropertyValue("--mosaic-color-accent")),
        };
      }),
    )
    .toEqual({
      canvas: "#f5f6f8",
      surface: "#ffffff",
      line: "#d7dce3",
      accent: "#2f5bea",
    });
}

test("marketplace runtime geometry matches desktop/wide and mobile contracts", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await expectModelCards(page, 12);
  await expectDesignTokens(page);

  const topBar = page.locator("header").filter({ hasText: "MOSAIC" }).first();
  const heading = page.getByRole("heading", { name: "选择能力，开始创作" });
  const grid = page.getByTestId("model-card-grid");
  await expect(topBar).toBeVisible();
  await expect(grid).toBeVisible();

  const isMobile = mobileProjects.has(testInfo.project.name);
  const topBarBox = await box(topBar);
  const headingBox = await box(heading);
  const headingStyle = await heading.evaluate((element) => {
    const style = window.getComputedStyle(element);
    return { fontSize: style.fontSize, lineHeight: style.lineHeight };
  });
  expect(topBarBox.height).toBeCloseTo(64, 0);
  expect(headingStyle).toEqual(
    isMobile
      ? { fontSize: "40px", lineHeight: "48px" }
      : { fontSize: "56px", lineHeight: "64px" },
  );
  expect(headingBox.height).toBeGreaterThan(0);
  await expectControlsAtLeast44(page);

  const cards = modelCards(page);
  const firstCard = await box(cards.nth(0));
  const secondCard = await box(cards.nth(1));
  const firstCardStyle = await box(cards.nth(0));
  const cardHeadingStyle = await cards.nth(0).locator("h2").evaluate((element) => {
    const style = window.getComputedStyle(element);
    return { fontSize: style.fontSize, lineHeight: style.lineHeight };
  });
  expect(cardHeadingStyle).toEqual({ fontSize: "22px", lineHeight: "28px" });
  expect(firstCardStyle.borderWidth).toBe("1px");
  expect(firstCardStyle.borderRadius).toBe("12px");
  if (!isMobile) {
    const videoCard = page.getByTestId("model-card-hunyuan-video-1-5");
    const videoCardBox = await box(videoCard);
    const videoFavoriteBox = await box(videoCard.locator('button[aria-pressed]'));
    const videoTitleBox = await box(videoCard.locator("h2"));
    expect(videoFavoriteBox.width).toBeGreaterThanOrEqual(44);
    expect(videoFavoriteBox.height).toBeGreaterThanOrEqual(44);
    expect(videoFavoriteBox.x + videoFavoriteBox.width).toBeLessThanOrEqual(videoCardBox.x + videoCardBox.width + 1);
    expect(videoFavoriteBox.y).toBeLessThanOrEqual(videoCardBox.y + 52);
    expect(videoTitleBox.y).toBeGreaterThanOrEqual(videoFavoriteBox.y + videoFavoriteBox.height - 1);
  }

  if (isMobile) {
    const columns = await grid.evaluate((element) => window.getComputedStyle(element).gridTemplateColumns);
    expect(columns.trim().split(/\s+/)).toHaveLength(1);
    expect(Math.abs(firstCard.x - secondCard.x)).toBeLessThanOrEqual(1);
    await expect(page.getByRole("navigation", { name: "移动端主导航" })).toBeVisible();
    const bottomNav = page.getByRole("navigation", { name: "移动端主导航" });
    const bottomNavBox = await box(bottomNav);
    expect(bottomNavBox.height).toBeGreaterThanOrEqual(76);
    expect(await bottomNav.getAttribute("class")).toContain("safe-area-inset-bottom");

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const lastCardBottom = await cards.last().evaluate((element) => element.getBoundingClientRect().bottom);
    const bottomNavTop = (await box(bottomNav)).y;
    expect(lastCardBottom).toBeLessThanOrEqual(bottomNavTop + 1);
  } else {
    const rail = page.getByRole("navigation", { name: "桌面主导航" }).locator("..");
    expect((await box(rail)).width).toBeCloseTo(240, 0);
    const columns = await grid.evaluate((element) => window.getComputedStyle(element).gridTemplateColumns);
    const columnWidths = columns.trim().split(/\s+/).map((value) => Number.parseFloat(value));
    expect(columnWidths).toHaveLength(2);
    expect(columnWidths[0]! / columnWidths[1]!).toBeCloseTo(1.1, 1);
    expect(Math.abs(firstCard.y - secondCard.y)).toBeLessThanOrEqual(1);
    await expect(page.getByRole("navigation", { name: "桌面主导航" })).toBeVisible();
  }
});

test("chat runtime geometry preserves the dedicated workspace on every project", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-001");
  await expectChatReady(page);
  await expectDesignTokens(page);

  const workspace = page.getByTestId("chat-workspace");
  const header = page.getByTestId("chat-header");
  const composerPanel = page.getByTestId("composer-panel");
  const messageList = page.getByTestId("message-list");
  const workspaceBox = await box(workspace);
  const headerBox = await box(header);
  const composerBox = await box(composerPanel);
  const messageListBox = await box(messageList);
  const messageRail = messageList.locator(":scope > div");
  const messageRailBox = await box(messageRail);
  const isMobile = mobileProjects.has(testInfo.project.name);

  expect(workspaceBox.y).toBeCloseTo(64, 0);
  expect(workspaceBox.height).toBeCloseTo(
    await page.evaluate(() => window.innerHeight - 64),
    0,
  );
  expect(headerBox.height).toBeCloseTo(64, 0);
  expect(composerBox.height).toBeCloseTo(104, 0);
  expect(messageListBox.y + messageListBox.height).toBeLessThanOrEqual(composerBox.y + 1);
  if (!isMobile) {
    expect(messageRailBox.width).toBeGreaterThanOrEqual(760);
    expect(messageRailBox.width).toBeLessThanOrEqual(880);
  } else {
    expect(messageRailBox.width).toBeLessThanOrEqual(880);
  }
  await expectControlsAtLeast44(page);
  await expect(page.locator('nav[aria-label="移动端主导航"]')).toHaveCount(0);

  const historyTrigger = page.getByRole("button", { name: "打开会话列表" });
  await expect(historyTrigger).toBeVisible();
  await expect(page.getByTestId("conversation-list")).not.toBeAttached();
  await historyTrigger.click();
  const historyDialog = page.getByRole("dialog", { name: "会话列表" });
  await expect(historyDialog).toBeVisible();
  const historyBox = await box(page.getByTestId("conversation-list"));
  expect(historyBox.width).toBeLessThanOrEqual(420);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("conversation-list")).not.toBeAttached();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
