import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MobileBottomNavigation } from "./mobile-bottom-navigation";

describe("MobileBottomNavigation", () => {
  afterEach(() => cleanup());

  it("renders three equal mobile destinations with nested active state", () => {
    render(<MobileBottomNavigation pathname="/generations/job-42" />);

    const navigation = screen.getByRole("navigation", {
      name: "移动端主导航",
    });
    const links = within(navigation).getAllByRole("link");

    expect(links).toHaveLength(3);
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/models",
      "/generations",
      "/usage",
    ]);
    expect(within(navigation).getByRole("link", { name: "生成记录" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(navigation).getByRole("link", { name: "模型广场" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(navigation).getByRole("link", { name: "用量中心" })).not.toHaveAttribute(
      "aria-current",
    );
    for (const link of links) {
      expect(link).toHaveClass("h-full", "min-h-11");
    }
    expect(navigation.firstElementChild).toHaveClass(
      "grid-cols-3",
      "h-[var(--mosaic-layout-mobile-bottom-navigation)]",
    );
    expect(navigation).toHaveClass(
      "h-[calc(var(--mosaic-layout-mobile-bottom-navigation)+env(safe-area-inset-bottom))]",
      "pb-[env(safe-area-inset-bottom)]",
      "md:hidden",
    );
  });

  it("keeps account security out of the mobile navigation", () => {
    render(<MobileBottomNavigation pathname="/account/security" />);

    const navigation = screen.getByRole("navigation", {
      name: "移动端主导航",
    });
    expect(within(navigation).queryByRole("link", { name: "账户安全" })).not.toBeInTheDocument();
    expect(within(navigation).getAllByRole("link")).toHaveLength(3);
  });

  it("keeps model workspaces anchored to the model marketplace", () => {
    render(<MobileBottomNavigation pathname="/studio/video/wan-2-7" />);

    const navigation = screen.getByRole("navigation", {
      name: "移动端主导航",
    });
    expect(within(navigation).getByRole("link", { name: "模型广场" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
