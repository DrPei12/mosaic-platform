import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const account = process.env.MOSAIC_DEMO_EMAIL?.trim();
const password = process.env.MOSAIC_DEMO_PASSWORD;
const tenant = process.env.MOSAIC_DEMO_TENANT_SLUG?.trim() || "mosaic-demo";
if (!account || !password) {
  throw new Error("demo credentials are not configured");
}

const browserCandidates = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const executablePath = browserCandidates.find(existsSync);
const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
  args: ["--disable-extensions"],
});

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..", "..", "..");
const evidenceDirectory = path.join(repositoryRoot, "docs", "evidence", "screenshots");
mkdirSync(evidenceDirectory, { recursive: true });
const page = await browser.newPage({ viewport: { width: 1728, height: 1117 } });
const runtimeErrors = [];
page.on("pageerror", (error) => runtimeErrors.push(error.message));
page.on("console", (message) => {
  if (message.type() === "error") runtimeErrors.push(message.text());
});

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function hasVisibleNextDevIndicator() {
  return page.evaluate(() => {
    const portal = document.querySelector("nextjs-portal");
    const root = portal?.shadowRoot;
    if (!root) return false;
    return Array.from(root.querySelectorAll('button,[role="button"]')).some((element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    });
  });
}

try {
  await page.goto("http://127.0.0.1:3000/login", { waitUntil: "networkidle" });
  await page.getByRole("textbox", { name: "账户", exact: true }).fill(account);
  await page.getByRole("textbox", { name: "工作区标识（可选）", exact: true }).fill(tenant);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL(/\/models$/, { timeout: 20_000 });
  await page.getByTestId("model-card-grid").waitFor({ state: "visible" });

  const moduleNav = page.getByRole("navigation", { name: "产品模块" });
  await moduleNav.getByText("Agent", { exact: true }).waitFor();
  assert(await moduleNav.getByText("模型", { exact: true }).count() === 1, "模型模块缺失");
  assert(await moduleNav.getByText("应用", { exact: true }).count() === 0, "仍显示应用模块");
  assert(await moduleNav.getByText("订阅", { exact: true }).count() === 0, "仍显示订阅模块");
  assert(await moduleNav.getByText("体验", { exact: true }).count() === 0, "仍显示体验模块");

  const pageText = await page.locator("body").innerText();
  for (const removedText of [
    "华北2（北京）",
    "默认业务空间",
    "已连接真实 API 与持久化执行栈",
    "API 实时",
    "演示租户",
  ]) {
    assert(!pageText.includes(removedText), `仍显示多余文本：${removedText}`);
  }
  assert(await page.locator('article[data-testid^="model-card-"]').count() === 6, "可执行模型数量不是 6");
  assert(await page.getByTestId("model-card-qwen3-tts-base").count() === 0, "Base 仍被展示为可执行模型");
  assert(!(await hasVisibleNextDevIndicator()), "Next.js 开发悬浮入口仍存在");

  await page.screenshot({
    path: path.join(evidenceDirectory, "live-model-marketplace-aligned.png"),
    fullPage: true,
  });

  const studios = [
    ["image", "/studio/image/qwen-image-3-0-pro"],
    ["video", "/studio/video/wan-2-7"],
    ["audio", "/studio/audio/qwen3-tts-voice-design"],
  ];
  for (const [modality, route] of studios) {
    await page.goto(`http://127.0.0.1:3000${route}`, { waitUntil: "networkidle" });
    await page.getByTestId(`generation-studio-${modality}`).waitFor({ state: "visible" });
    assert(!(await hasVisibleNextDevIndicator()), `${modality} 工作台仍显示 Next.js 开发悬浮入口`);
    await page.screenshot({
      path: path.join(evidenceDirectory, `live-${modality}-studio-aligned.png`),
      fullPage: true,
    });
  }

  await page.goto("http://127.0.0.1:3000/models", { waitUntil: "networkidle" });
  await page.getByTestId("model-card-grid").waitFor({ state: "visible" });

  const textCard = page.getByTestId("model-card-qwen-3-5-plus");
  await textCard.getByRole("button", { name: /开始对话 Qwen 3\.5 Plus/ }).click();
  await page.waitForURL(/\/chat\//, { timeout: 20_000 });
  await page.getByTestId("chat-workspace").waitFor({ state: "visible" });
  await page.getByRole("heading", { name: "文本模型" }).waitFor();
  await page.getByTestId("chat-model-toolbar").getByText("Qwen 3.5 Plus").waitFor();

  const emptyComposerBox = await page.getByTestId("composer-panel").boundingBox();
  assert(emptyComposerBox !== null, "找不到空态输入框");
  assert(emptyComposerBox.height >= 110 && emptyComposerBox.height <= 132, "空态输入框高度未对齐 120px 原型");
  assert(!(await hasVisibleNextDevIndicator()), "聊天页仍显示 Next.js 开发悬浮入口");

  await page.getByRole("textbox", { name: "输入消息" }).fill("请用一句中文确认这是真实模型回复。 ");
  await page.getByRole("button", { name: "发送消息" }).click();
  const assistant = page.locator('article[data-role="assistant"]').last();
  await assistant.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForFunction(() => {
    const rows = document.querySelectorAll('article[data-role="assistant"]');
    const last = rows.item(rows.length - 1);
    return Boolean(last?.textContent && last.textContent.trim().length > 20);
  }, undefined, { timeout: 60_000 });

  const activeComposerBox = await page.getByTestId("composer-panel").boundingBox();
  assert(activeComposerBox !== null, "找不到会话输入框");
  assert(activeComposerBox.height <= 116, "会话输入框仍然过高");
  await page.screenshot({
    path: path.join(evidenceDirectory, "live-chat-aligned.png"),
    fullPage: true,
  });

  assert(runtimeErrors.length === 0, `浏览器运行时错误：${runtimeErrors.join(" | ")}`);
  console.log(JSON.stringify({
    status: "ok",
    model_cards: 6,
    empty_composer_height: Math.round(emptyComposerBox.height),
    active_composer_height: Math.round(activeComposerBox.height),
    real_chat_response_present: true,
    next_dev_indicator_present: false,
    screenshots: [
      "docs/evidence/screenshots/live-model-marketplace-aligned.png",
      "docs/evidence/screenshots/live-image-studio-aligned.png",
      "docs/evidence/screenshots/live-video-studio-aligned.png",
      "docs/evidence/screenshots/live-audio-studio-aligned.png",
      "docs/evidence/screenshots/live-chat-aligned.png",
    ],
  }));
} finally {
  await browser.close();
}
