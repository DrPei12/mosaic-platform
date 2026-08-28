import { expect, test } from "@playwright/test";

import {
  expectChatReady,
  signIn,
  waitForStablePage,
} from "./helpers/demo";

const firstPrompt = "帮我把新产品的验证路径拆成几步。";
const firstReply = "可以从目标用户、核心任务和最小验证开始，再安排可观测的反馈节点。";
const secondPrompt = "第二步应该先做功能还是先做访谈？";
const secondReply = "先做小样本访谈更稳妥，它能帮助你缩小功能范围，再用原型验证关键路径。";

function assistantMessages(page: Parameters<typeof expectChatReady>[0]) {
  return page.locator('[data-testid^="message-"][data-role="assistant"]');
}

function userMessages(page: Parameters<typeof expectChatReady>[0]) {
  return page.locator('[data-testid^="message-"][data-role="user"]');
}

test("seeded Qwen 3.5 sessions support two deterministic streamed turns", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-001");
  await expectChatReady(page);
  await expect(page.getByRole("heading", { name: "文本模型" })).toBeVisible();
  const historyTrigger = page.getByRole("button", { name: "打开会话列表" });
  await historyTrigger.click();
  const historyDialog = page.getByRole("dialog", { name: "会话列表" });
  await expect(historyDialog.getByRole("button", { name: /产品规划讨论/ })).toBeVisible();
  await expect(historyDialog.getByRole("button", { name: /研究摘要整理/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(userMessages(page)).toHaveCount(2);

  const input = page.getByRole("textbox", { name: "输入消息" });
  await input.fill(firstPrompt);
  await input.press("Enter");
  await expect(page.getByTestId("chat-workspace")).toHaveAttribute(
    "data-stream-status",
    "streaming",
  );
  await expect(assistantMessages(page).last()).toContainText(firstReply, {
    timeout: 15000,
  });
  await expect(page.getByTestId("chat-workspace")).toHaveAttribute(
    "data-stream-status",
    "idle",
  );

  await input.fill(secondPrompt);
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(assistantMessages(page).last()).toContainText(secondReply, {
    timeout: 15000,
  });
  await expect(page.getByTestId("chat-workspace")).toHaveAttribute(
    "data-stream-status",
    "idle",
  );
  await expect(userMessages(page)).toHaveCount(4);
});

test("chat seeded viewport is stable on every responsive project", async ({
  page,
}, testInfo) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-001");
  await expectChatReady(page);
  const historyTrigger = page.getByRole("button", { name: "打开会话列表" });
  await historyTrigger.click();
  const historyDialog = page.getByRole("dialog", { name: "会话列表" });
  await expect(historyDialog.getByRole("button", { name: /产品规划讨论/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("第二步应该先做功能还是先做访谈？")).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.mouse.move(0, 0);
  await waitForStablePage(page);
  await expect(page).toHaveScreenshot(`chat-${testInfo.project.name}.png`, {
    animations: "disabled",
  });
});

test("empty text workspace centers the model heading and large composer", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/models");
  await page.getByRole("button", { name: "开始对话 Qwen 3.5" }).click();
  await page.waitForURL(/\/chat\//);
  await expectChatReady(page);
  await expect(page.getByRole("heading", { name: "开始使用 Qwen 3.5" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "输入消息" })).toBeVisible();
  const composer = page.getByTestId("composer-panel");
  const composerHeight = await composer.evaluate((element) => element.getBoundingClientRect().height);
  expect(composerHeight).toBeGreaterThanOrEqual(118);
  expect(composerHeight).toBeLessThanOrEqual(140);
  await expect(page.getByTestId("message-list-empty")).toHaveAttribute("data-state", "empty");
});

test("stop preserves the first observable delta and marks the request stopped", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-002");
  await expectChatReady(page);
  const beforeUsers = await userMessages(page).count();
  const input = page.getByRole("textbox", { name: "输入消息" });
  await input.fill("演示停止响应");
  await page.getByRole("button", { name: "发送消息" }).click();

  await expect(assistantMessages(page).last()).toContainText("先输出已确认的", {
    timeout: 15000,
  });
  const stop = page.getByRole("button", { name: "停止生成" });
  await expect(stop).toBeVisible();
  await stop.focus();
  await stop.press("Enter");
  await expect(page.getByText("已停止生成，以上为已保留内容。")).toBeVisible({
    timeout: 15000,
  });
  await expect(assistantMessages(page).last()).toContainText("先输出已确认的");
  await expect(userMessages(page)).toHaveCount(beforeUsers + 1);
  await expect(page.getByTestId("chat-workspace")).toHaveAttribute(
    "data-stream-status",
    "idle",
  );
});

test("regenerate targets the latest assistant without duplicating the user turn", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-001");
  await expectChatReady(page);
  const beforeUsers = await userMessages(page).count();
  const regenerate = page.getByRole("button", { name: "重新生成" });
  await expect(regenerate).toBeVisible();
  await regenerate.focus();
  await regenerate.press("Enter");
  await expect(assistantMessages(page).last()).toContainText(secondReply, {
    timeout: 15000,
  });
  await expect(userMessages(page)).toHaveCount(beforeUsers);
  await expect(page.getByTestId("chat-workspace")).toHaveAttribute(
    "data-stream-status",
    "idle",
  );
});

test("refresh resumes after a visible delta without duplicating chunks", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-001");
  await expectChatReady(page);
  const input = page.getByRole("textbox", { name: "输入消息" });
  await input.fill("刷新恢复演示");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(assistantMessages(page).last()).toContainText("基于前面的讨论，", {
    timeout: 15000,
  });

  await page.reload({ waitUntil: "networkidle" });
  await expectChatReady(page);
  const resumed = assistantMessages(page).last();
  await expect(resumed).toContainText(
    "基于前面的讨论，我会把这个问题拆成可执行的下一步。",
    { timeout: 15000 },
  );
  const content = await resumed.innerText();
  expect(content.match(/基于前面的讨论，/g) ?? []).toHaveLength(1);
  await expect(page.getByTestId("chat-workspace")).toHaveAttribute(
    "data-stream-status",
    "idle",
  );
});

test("offline send retains the draft and reload restores the demo draft", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-002");
  await expectChatReady(page);
  const beforeUsers = await userMessages(page).count();
  const input = page.getByRole("textbox", { name: "输入消息" });
  await page.evaluate(() => {
    Object.defineProperty(window.navigator, "onLine", {
      configurable: true,
      get: () => false,
    });
    window.dispatchEvent(new Event("offline"));
  });
  await input.fill("离线演示草稿");
  await expect(page.getByTestId("draft-status")).toContainText("草稿自动保存");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.locator('span[role="alert"]')).toContainText("草稿已保留");
  await expect(input).toHaveValue("离线演示草稿");
  await expect(userMessages(page)).toHaveCount(beforeUsers);

  await page.evaluate(() => {
    Object.defineProperty(window.navigator, "onLine", {
      configurable: true,
      get: () => true,
    });
    window.dispatchEvent(new Event("online"));
  });
  await page.reload({ waitUntil: "networkidle" });
  await expectChatReady(page);
  await expect(page.getByRole("textbox", { name: "输入消息" })).toHaveValue(
    "离线演示草稿",
  );
});

test("keyboard conversation switching and history dialog remain usable", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/chat/conversation-qwen-3-5-001");
  await expectChatReady(page);

  const trigger = page.getByRole("button", { name: "打开会话列表" });
  await trigger.focus();
  await trigger.press("Enter");
  const dialog = page.getByRole("dialog", { name: "会话列表" });
  await expect(dialog).toBeVisible();
  const secondConversation = dialog.getByRole("button", { name: /研究摘要整理/ });
  await secondConversation.focus();
  await secondConversation.press("Enter");
  await expect(page).toHaveURL(/\/chat\/conversation-qwen-3-5-002$/);
  await expect(page.getByRole("heading", { name: "文本模型" })).toBeVisible();

  await page.goto("/chat/conversation-qwen-3-5-001");
  await expectChatReady(page);
  await trigger.focus();
  await trigger.press("Enter");
  await expect(page.getByRole("dialog", { name: "会话列表" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "会话列表" })).not.toBeVisible();
  await expect(trigger).toBeFocused();
});
