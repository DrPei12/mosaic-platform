import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { tokens } from "@mosaic/design-tokens";

import {
  Button,
  type NativeButtonProps,
  type SlottedButtonProps,
} from "./button";
import { EmptyState, ErrorState, Skeleton } from "./feedback-state";
import { InputField } from "./input-field";
import { StatusBadge } from "./status-badge";

describe("shared UI primitives", () => {
  afterEach(() => {
    cleanup();
  });

  it("keeps native and slotted handler targets type-safe", () => {
    const nativeProps: NativeButtonProps = {
      children: "Native",
      onClick: (event) => {
        event.currentTarget.disabled = true;
      },
    };
    const slottedProps: SlottedButtonProps = {
      asChild: true,
      children: <a href="/models">Link</a>,
      onClick: (event) => {
        // @ts-expect-error Slotted handlers must not assume a button target.
        event.currentTarget.disabled = true;
      },
    };

    expect(nativeProps).toBeDefined();
    expect(slottedProps).toBeDefined();
  });

  it("prevents activation while a button is loading and keeps its accessible name", () => {
    const action = vi.fn();

    render(
      <Button loading onClick={action}>
        保存
      </Button>,
    );

    const button = screen.getByRole("button", { name: "保存" });
    fireEvent.click(button);

    expect(action).not.toHaveBeenCalled();
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAccessibleName("保存");
    expect(button).toHaveClass("min-h-11");
    expect(button.className).toMatch(/focus-visible/);
    expect(button.className).not.toMatch(/outline-3|outline-offset-2/);
  });

  it("defaults native buttons to type button", () => {
    render(<Button>继续</Button>);

    expect(screen.getByRole("button", { name: "继续" })).toHaveAttribute(
      "type",
      "button",
    );
  });

  it("forwards native and slotted refs to their actual DOM elements", () => {
    const nativeRef = createRef<HTMLButtonElement>();
    const slottedRef = createRef<HTMLElement>();
    const { rerender } = render(<Button ref={nativeRef}>继续</Button>);

    expect(nativeRef.current).toBe(
      screen.getByRole("button", { name: "继续" }),
    );

    rerender(
      <Button asChild ref={slottedRef}>
        <a href="/models">模型</a>
      </Button>,
    );

    expect(slottedRef.current).toBe(screen.getByRole("link", { name: "模型" }));
  });

  it("uses aria-disabled and suppresses activation for a disabled slotted link", () => {
    const action = vi.fn();

    render(
      <Button asChild loading onClick={action}>
        <a href="/models" onClick={action}>
          打开模型
        </a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "打开模型" });
    fireEvent.click(link);

    expect(action).not.toHaveBeenCalled();
    expect(link).not.toHaveAttribute("disabled");
    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAttribute("aria-busy", "true");
  });

  it("suppresses pointer and keyboard activation for a disabled slotted anchor", () => {
    const action = vi.fn();

    render(
      <Button asChild disabled>
        <a
          href="/models"
          onClick={action}
          onKeyDown={action}
          onPointerDown={action}
        >
          打开模型
        </a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "打开模型" });
    fireEvent.pointerDown(link);
    fireEvent.keyDown(link, { key: "Enter", code: "Enter" });
    fireEvent.click(link);

    expect(action).not.toHaveBeenCalled();
    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).not.toHaveAttribute("type");
  });

  it("accepts a slotted anchor without leaking native button attributes", () => {
    render(
      <Button asChild>
        <a href="/models">模型</a>
      </Button>,
    );

    const link = screen.getByRole("link", { name: "模型" });
    expect(link).not.toHaveAttribute("disabled");
    expect(link).not.toHaveAttribute("type");
  });

  it("rejects a native button supplied through asChild", () => {
    expect(() =>
      render(
        <Button asChild>
          <button type="submit">嵌套按钮</button>
        </Button>,
      ),
    ).toThrow(/asChild.*button/i);
  });

  it("associates the visible input label, description, and error text", () => {
    render(
      <InputField
        id="email"
        label="邮箱"
        description="仅用于演示登录"
        error="请输入有效邮箱"
      />,
    );

    const input = screen.getByRole("textbox", { name: "邮箱" });

    expect(screen.getByText("邮箱")).toBeVisible();
    expect(input).toHaveAttribute(
      "aria-describedby",
      "email-description email-error",
    );
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("仅用于演示登录 请输入有效邮箱");
    expect(input).toHaveClass("min-h-11");
    expect(input.className).not.toMatch(/outline-3|outline-offset-2/);
  });

  it("merges caller and generated description IDs in order without duplicates", () => {
    render(
      <InputField
        id="email"
        label="邮箱"
        description="仅用于演示登录"
        error="请输入有效邮箱"
        aria-describedby="custom email-error custom"
      />,
    );

    expect(screen.getByRole("textbox", { name: "邮箱" })).toHaveAttribute(
      "aria-describedby",
      "custom email-error email-description",
    );
  });

  it("forwards an input ref to the focusable DOM node", () => {
    const ref = createRef<HTMLInputElement>();

    render(<InputField id="account" label="账户" ref={ref} />);

    const input = screen.getByRole("textbox", { name: "账户" });
    expect(ref.current).toBe(input);

    ref.current?.focus();
    expect(document.activeElement).toBe(input);
  });

  it("provides alert semantics and a recovery action for errors", () => {
    const recovery = vi.fn();

    render(
      <ErrorState
        title="加载失败"
        description="请重试"
        action={<button onClick={recovery}>重试</button>}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("加载失败");
    expect(alert).toHaveTextContent("请重试");

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(recovery).toHaveBeenCalledOnce();
  });

  it("supports an action in an empty state", () => {
    const action = vi.fn();

    render(
      <EmptyState
        title="没有项目"
        description="创建一个项目开始工作。"
        action={<button onClick={action}>创建项目</button>}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "创建项目" }));
    expect(action).toHaveBeenCalledOnce();
  });

  it("announces a busy skeleton and respects reduced motion", () => {
    render(<Skeleton label="正在加载模型" />);

    const skeleton = screen.getByRole("status", { name: "正在加载模型" });
    expect(skeleton).toHaveAttribute("aria-busy", "true");
    expect(skeleton).toHaveClass("motion-reduce:animate-none");
  });

  it("renders generic status tones with textual content", () => {
    const tones = ["neutral", "info", "success", "warning", "danger"] as const;

    render(
      <div>
        {tones.map((tone) => (
          <StatusBadge key={tone} tone={tone}>
            {tone} status
          </StatusBadge>
        ))}
      </div>,
    );

    for (const tone of tones) {
      expect(screen.getByText(`${tone} status`)).toBeVisible();
    }
  });

  it("keeps warning and danger badge text at AA contrast on tinted backgrounds", () => {
    const relativeLuminance = (hex: string) => {
      const channels = hex
        .slice(1)
        .match(/../g)!
        .map((channel) => Number.parseInt(channel, 16) / 255)
        .map((channel) =>
          channel <= 0.03928
            ? channel / 12.92
            : ((channel + 0.055) / 1.055) ** 2.4,
        );

      return (
        0.2126 * channels[0]! +
        0.7152 * channels[1]! +
        0.0722 * channels[2]!
      );
    };
    const mixWithSurface = (semanticHex: string, ratio: number) => {
      const semantic = semanticHex
        .slice(1)
        .match(/../g)!
        .map((channel) => Number.parseInt(channel, 16));
      const surface = tokens.color.surface
        .slice(1)
        .match(/../g)!
        .map((channel) => Number.parseInt(channel, 16));

      return `#${semantic
        .map((channel, index) =>
          Math.round(channel * ratio + surface[index]! * (1 - ratio))
            .toString(16)
            .padStart(2, "0"),
        )
        .join("")}`;
    };
    const contrastRatio = (foreground: string, background: string) => {
      const foregroundLuminance = relativeLuminance(foreground);
      const backgroundLuminance = relativeLuminance(background);
      return (
        (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) /
        (Math.min(foregroundLuminance, backgroundLuminance) + 0.05)
      );
    };

    for (const tone of ["warning", "danger"] as const) {
      expect(
        contrastRatio(
          tokens.color.ink,
          mixWithSurface(tokens.color[tone], 0.1),
        ),
      ).toBeGreaterThanOrEqual(4.5);
    }

    render(
      <div>
        <StatusBadge tone="warning">warning text</StatusBadge>
        <StatusBadge tone="danger">danger text</StatusBadge>
      </div>,
    );

    expect(screen.getByText("warning text")).toHaveClass(
      "text-[var(--mosaic-color-ink)]",
    );
    expect(screen.getByText("danger text")).toHaveClass(
      "text-[var(--mosaic-color-ink)]",
    );
  });
});
