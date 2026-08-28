import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { tokens } from "@mosaic/design-tokens";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell, MOBILE_NAVIGATION_DIALOG_ID } from "./app-shell";
import { NetworkStatus } from "./network-status";

describe("AppShell", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders semantic navigation and responsive class contracts; visibility is Task8 browser geometry", () => {
    render(
      <AppShell pathname="/models">
        <h1>模型广场</h1>
      </AppShell>,
    );

    const desktopNavigation = screen.getByRole("navigation", { name: "桌面主导航" });
    expect(desktopNavigation).toBeInTheDocument();
    expect(desktopNavigation.parentElement).toHaveClass(
      "hidden",
      "lg:block",
      "top-[var(--mosaic-layout-top-bar-desktop)]",
    );
    const mobileNavigation = screen.getByRole("navigation", { name: "移动端主导航" });
    expect(mobileNavigation).toBeInTheDocument();
    expect(mobileNavigation).toHaveClass("md:hidden");
    expect(screen.getByRole("navigation", { name: "产品模块" })).toBeVisible();
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { name: "模型广场" }),
    );
    expect(screen.getByRole("link", { name: "跳到主要内容" })).toHaveAttribute(
      "href",
      "#main-content",
    );
    expect(screen.getByRole("button", { name: "打开导航" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: "打开导航" })).toHaveAttribute(
      "aria-haspopup",
      "dialog",
    );
    expect(screen.getByRole("button", { name: "打开导航" })).not.toHaveAttribute(
      "aria-controls",
    );
    expect(screen.queryByRole("img", { name: "账户" })).not.toBeInTheDocument();

    expect(screen.getByRole("banner")).toHaveClass(
      "h-[var(--mosaic-layout-top-bar-mobile)]",
      "md:h-[var(--mosaic-layout-top-bar-desktop)]",
    );

    expect(within(mobileNavigation).getAllByRole("link")).toHaveLength(3);
    expect(within(mobileNavigation).getByRole("link", { name: "模型广场" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("keeps Tailwind md=768px and lg=1024px mapped to layout tokens", () => {
    // Tailwind's default md/lg media queries are the responsive contracts used by AppShell.
    expect(tokens.layout.singleColumnBreakpoint).toBe("768px");
    expect(tokens.layout.compactBreakpoint).toBe("1024px");
  });

  it("marks the current console route and nested route as current", () => {
    render(
      <AppShell pathname="/generations/job-42">
        <h1>生成记录</h1>
      </AppShell>,
    );

    const mobileNavigation = screen.getByRole("navigation", {
      name: "移动端主导航",
    });
    expect(within(mobileNavigation).getByRole("link", { name: "生成记录" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(mobileNavigation).getByRole("link", { name: "模型广场" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("uses the full-width scrollable studio shell and keeps model navigation active", () => {
    render(
      <AppShell pathname="/studio/image/qwen-image">
        <h1>图片工作台</h1>
      </AppShell>,
    );

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("data-shell-mode", "studio");
    expect(main).toHaveClass("max-w-none", "p-0", "md:pb-0");
    expect(main).not.toHaveClass("h-[100dvh]", "overflow-hidden");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "移动端主导航" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "桌面主导航" })).getByRole(
        "link",
        { name: "模型广场" },
      ),
    ).toHaveAttribute("aria-current", "page");
  });

  it("moves focus to main content when the skip link is activated", async () => {
    const user = userEvent.setup();
    render(
      <AppShell pathname="/models">
        <h1>模型广场</h1>
      </AppShell>,
    );

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("tabindex", "-1");

    await user.click(screen.getByRole("link", { name: "跳到主要内容" }));

    expect(document.activeElement).toBe(main);
  });

  it("opens and closes compact navigation with Escape and restores trigger focus", async () => {
    const user = userEvent.setup();
    render(
      <AppShell pathname="/models">
        <h1>模型广场</h1>
      </AppShell>,
    );

    const trigger = screen.getByRole("button", { name: "打开导航" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "移动导航" });
    expect(dialog).toBeVisible();
    expect(dialog).toHaveAttribute("id", MOBILE_NAVIGATION_DIALOG_ID);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute(
      "aria-controls",
      MOBILE_NAVIGATION_DIALOG_ID,
    );
    expect(screen.getByRole("navigation", { name: "移动端抽屉导航" })).toBeVisible();
    const navigationLabels = screen.getAllByRole("navigation").map((element) =>
      element.getAttribute("aria-label"),
    );
    expect(new Set(navigationLabels).size).toBe(navigationLabels.length);

    await user.click(screen.getByRole("button", { name: "关闭导航" }));
    expect(
      screen.queryByRole("dialog", { name: "移动导航" }),
    ).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("dialog", { name: "移动导航" }),
    ).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("keeps the global product bar while chat uses a dedicated viewport", () => {
    render(
      <AppShell pathname="/chat/demo-conversation">
        <h1>文本对话</h1>
      </AppShell>,
    );

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "移动端主导航" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveClass(
      "h-[calc(100dvh-var(--mosaic-layout-top-bar-mobile))]",
      "md:h-[calc(100dvh-var(--mosaic-layout-top-bar-desktop))]",
      "max-w-none",
      "overflow-hidden",
      "p-0",
    );
    expect(screen.getByRole("main")).toHaveAttribute("data-shell-mode", "chat");
    expect(
      within(screen.getByRole("navigation", { name: "桌面主导航" })).getByRole(
        "link",
        { name: "模型广场" },
      ),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { name: "文本对话" }),
    );
  });

  it("collapses and restores the desktop rail without changing the route", async () => {
    const user = userEvent.setup();
    render(
      <AppShell pathname="/models">
        <h1>模型广场</h1>
      </AppShell>,
    );

    const toggle = screen.getByRole("button", { name: "收起侧栏" });
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "展开侧栏" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("navigation", { name: "桌面主导航" }).parentElement).toHaveClass(
      "lg:hidden",
    );
  });

  it("shows the honest offline indicator and cleans up event listeners", () => {
    const addEventListener = vi.spyOn(window, "addEventListener");
    const removeEventListener = vi.spyOn(window, "removeEventListener");
    const originalOnline = navigator.onLine;
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: false,
    });
    const view = render(<NetworkStatus />);
    const onlineListener = addEventListener.mock.calls.find(
      ([eventName]) => eventName === "online",
    )?.[1];
    const offlineListener = addEventListener.mock.calls.find(
      ([eventName]) => eventName === "offline",
    )?.[1];

    expect(onlineListener).toEqual(expect.any(Function));
    expect(offlineListener).toEqual(expect.any(Function));

    expect(screen.getByRole("status")).toHaveTextContent(
      "网络已断开。未提交内容会保留在当前页面。",
    );

    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    fireEvent(window, new Event("online"));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    view.unmount();
    expect(removeEventListener).toHaveBeenCalledWith(
      "online",
      onlineListener,
    );
    expect(removeEventListener).toHaveBeenCalledWith(
      "offline",
      offlineListener,
    );
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: originalOnline,
    });
  });
});
