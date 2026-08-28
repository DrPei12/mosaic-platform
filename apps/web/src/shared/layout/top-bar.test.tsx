import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BRAND } from "@/shared/config/brand";
import { TopBar } from "./top-bar";

describe("TopBar", () => {
  afterEach(() => cleanup());

  it("renders only functional product navigation", () => {
    render(<TopBar pathname="/models" />);

    const banner = screen.getByRole("banner");
    expect(banner).toHaveClass(
      "h-[var(--mosaic-layout-top-bar-mobile)]",
      "md:h-[var(--mosaic-layout-top-bar-desktop)]",
    );
    expect(screen.getByRole("link", { name: BRAND.name })).toHaveAttribute("href", "/models");
    const modules = screen.getByRole("navigation", { name: "产品模块" });
    expect(within(modules).getByRole("link", { name: "模型" })).toHaveAttribute("href", "/models");
    expect(within(modules).getAllByRole("link")).toHaveLength(1);
    expect(screen.queryByText("Agent")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "文档" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "API 参考" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "通知" })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "账户" })).not.toBeInTheDocument();
  });

  it("offers a real desktop rail toggle", () => {
    const onToggleRail = vi.fn();
    render(<TopBar pathname="/chat/demo" onToggleRail={onToggleRail} />);

    const toggle = screen.getByRole("button", { name: "收起侧栏" });
    toggle.click();
    expect(onToggleRail).toHaveBeenCalledTimes(1);
  });
});
