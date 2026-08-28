import { expect, type Page } from "@playwright/test";

const readinessTimeout = 15_000;

const demoStateKeys = [
  "mosaic.demo-state.v2",
  "mosaic.demo-state.v1",
] as const;

/**
 * Start every browser scenario from the same deterministic demo seed.
 * Clearing these keys resets the invitation credential flow for each browser
 * scenario; it does not claim server-side sign-out or protected persistence.
 */
export async function resetDemoState(page: Page): Promise<void> {
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.evaluate((keys) => {
    for (const key of keys) window.localStorage.removeItem(key);
  }, demoStateKeys);
}

export async function signIn(page: Page): Promise<void> {
  await resetDemoState(page);
  await expect(
    page.getByRole("heading", { name: "登录你的账户" }),
  ).toBeVisible({ timeout: readinessTimeout });
  const loginForm = page.locator('form[data-hydrated="true"]');
  await expect(loginForm).toBeVisible({ timeout: readinessTimeout });
  const submitButton = loginForm.getByRole("button", {
    name: "登录",
  });
  await expect(submitButton).toBeEnabled({ timeout: readinessTimeout });
  await submitButton.click();
  await expect(page).toHaveURL(/\/(?:account\/security|models)(?:\?.*)?$/, {
    timeout: 15000,
  });
  if (new URL(page.url()).pathname === "/account/security") {
    await expect(page.getByRole("heading", { name: "账户安全" })).toBeVisible({
      timeout: readinessTimeout,
    });
    await page.getByLabel("当前密码").fill("internal-demo");
    await page.getByLabel("新密码", { exact: true }).fill("internal-demo-new");
    await page.getByLabel("确认新密码", { exact: true }).fill("internal-demo-new");
    await page.getByRole("button", { name: "保存密码" }).click();
  }
  await expect(page).toHaveURL(/\/models$/, { timeout: 15000 });
  const destination = new URL(page.url());
  expect(destination.searchParams.has("account")).toBe(false);
  expect(destination.searchParams.has("password")).toBe(false);
  await expect(page.getByTestId("model-marketplace")).toBeVisible({
    timeout: readinessTimeout,
  });
  await expect(page.getByTestId("model-card-grid")).toBeVisible({
    timeout: readinessTimeout,
  });
  await expectModelCards(page, 12);
  await waitForStablePage(page);
}

/** Wait for assets/fonts without introducing wall-clock sleeps in tests. */
export async function waitForStablePage(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle", { timeout: readinessTimeout });
  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready;
    const images = Array.from(document.images);
    await Promise.all(
      images.map(async (image) => {
        if (image.complete) {
          if (image.naturalWidth === 0) return;
          return;
        }
        await new Promise<void>((resolve) => {
          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener("error", () => resolve(), { once: true });
        });
      }),
    );
  });
}

export async function expectModelCards(page: Page, count: number): Promise<void> {
  await expect
    .poll(
      () => page.locator('article[data-testid^="model-card-"]').count(),
      { timeout: readinessTimeout },
    )
    .toBe(count);
}

export function modelCards(page: Page) {
  return page.locator('article[data-testid^="model-card-"]');
}

export function modelCard(page: Page, productModelId: string) {
  return page.getByTestId(`model-card-${productModelId}`);
}

export async function expectChatReady(page: Page): Promise<void> {
  await expect(page.getByTestId("chat-workspace")).toBeVisible({
    timeout: readinessTimeout,
  });
  await expect(page.getByTestId("composer-panel")).toBeVisible({
    timeout: readinessTimeout,
  });
  await expect(page.getByRole("textbox", { name: "输入消息" })).toBeVisible({
    timeout: readinessTimeout,
  });
  await waitForStablePage(page);
}
