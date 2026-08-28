import { expect, test, type Page } from "@playwright/test";

import { signIn, waitForStablePage } from "./helpers/demo";

async function expectTypography(
  page: Page,
  name: string,
  typography: { fontSize: string; lineHeight: string },
) {
  const heading = page.getByRole("heading", { name });
  await expect(heading).toBeVisible();
  await expect
    .poll(async () =>
      heading.evaluate((element) => {
        const style = window.getComputedStyle(element);
        return { fontSize: style.fontSize, lineHeight: style.lineHeight };
      }),
    )
    .toEqual(typography);
}

test("public, auth, and console routes render honest shell evidence", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "选择模型，开始创作。" }),
  ).toBeVisible();

  await page.goto("/login");
  await expectTypography(page, "登录你的账户", {
    fontSize: "40px",
    lineHeight: "48px",
  });

  await signIn(page);
  const marketplaceTypography = await page.evaluate(() =>
    window.innerWidth >= 1024
      ? { fontSize: "56px", lineHeight: "64px" }
      : { fontSize: "40px", lineHeight: "48px" },
  );
  await expectTypography(page, "选择能力，开始创作", marketplaceTypography);
  await expect(page.getByTestId("model-marketplace")).toBeVisible();
  await expect(page.getByText("demo_scaffolding")).not.toBeVisible();

  if (testInfo.project.name === "mobile" || testInfo.project.name === "mobile-large") {
    await expect(
      page.getByRole("navigation", { name: "移动端主导航" }),
    ).toBeVisible();
  } else {
    await expect(
      page.getByRole("navigation", { name: "桌面主导航" }),
    ).toBeVisible();
  }

  await page.mouse.move(0, 0);
  await waitForStablePage(page);
  await expect(page).toHaveScreenshot(`shell-${testInfo.project.name}.png`, {
    fullPage: true,
  });
});

test("all approved route skeletons are reachable", async ({ page }) => {
  await signIn(page);

  const routes = [
    { path: "/models", pathname: "/models", heading: "选择能力，开始创作", scaffold: false },
    {
      path: "/chat/conversation-qwen-3-5-001",
      pathname: "/chat/conversation-qwen-3-5-001",
      heading: "文本模型",
      scaffold: false,
    },
    {
      path: "/studio/image/qwen-image",
      pathname: "/studio/image/qwen-image",
      heading: "图片工作台",
      scaffold: true,
    },
    {
      path: "/studio/video/hunyuan-video-1-5",
      pathname: "/studio/video/hunyuan-video-1-5",
      heading: "视频工作台",
      scaffold: true,
    },
    {
      path: "/studio/audio/qwen3-tts-voice-design",
      pathname: "/studio/audio/qwen3-tts-voice-design",
      heading: "音频工作台",
      scaffold: true,
    },
    { path: "/generations", pathname: "/generations", heading: "生成记录", scaffold: true },
    {
      path: "/generations/demo-job",
      pathname: "/generations/demo-job",
      heading: "任务详情",
      scaffold: true,
    },
    { path: "/usage", pathname: "/usage", heading: "用量中心", scaffold: true },
    {
      path: "/account/security",
      pathname: "/account/security",
      heading: "账户安全",
      scaffold: true,
    },
  ] as const;

  for (const route of routes) {
    await page.goto(route.path);
    await expect
      .poll(() => new URL(page.url()).pathname)
      .toBe(route.pathname);
    await expect(page.getByRole("heading", { name: route.heading })).toBeVisible();
    await expect(page.getByText("demo_scaffolding")).not.toBeVisible();
  }
});

test("demo-gated routes redirect an unauthenticated demo session", async ({
  page,
}) => {
  await page.goto("/models");
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("heading", { name: "登录你的账户" }),
  ).toBeVisible();
});
