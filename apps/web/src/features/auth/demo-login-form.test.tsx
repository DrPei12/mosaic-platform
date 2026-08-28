import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderToString } from "react-dom/server";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockPush = vi.hoisted(() => vi.fn());
const mockRefresh = vi.hoisted(() => vi.fn());
const mockSignIn = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockPush, refresh: mockRefresh }),
}));

vi.mock("@/services/create-service-registry", () => ({
  createBrowserServiceRegistry: () => ({
    auth: { signIn: mockSignIn },
  }),
}));

import { LoginForm } from "./login-form";

function DemoLoginForm() {
  return <LoginForm mode="demo" />;
}

describe("DemoLoginForm", () => {
  afterEach(() => {
    cleanup();
    mockPush.mockReset();
    mockRefresh.mockReset();
    mockSignIn.mockReset();
  });

  it("keeps the server-rendered form from submitting before hydration", async () => {
    const serverMarkup = renderToString(<DemoLoginForm />);
    const serverContainer = document.createElement("div");
    serverContainer.innerHTML = serverMarkup;

    const serverForm = serverContainer.querySelector("form");
    const serverButton = serverForm?.querySelector("button");
    expect(serverForm).not.toHaveAttribute("data-hydrated");
    expect(serverButton).toHaveAttribute("type", "button");
    expect(serverButton).toBeDisabled();

    render(<DemoLoginForm />);

    await waitFor(() => {
      const hydratedForm = document.querySelector("form[data-hydrated='true']");
      expect(hydratedForm).toHaveAttribute(
        "data-hydrated",
        "true",
      );
      expect(
        screen.getByRole("button", { name: "登录" }),
      ).toBeEnabled();
    });
    expect(
      screen.getByRole("button", { name: "登录" }),
    ).toHaveAttribute("type", "submit");
  });

  it("submits demo credentials with an abort signal and navigates on success", async () => {
    mockSignIn.mockResolvedValue({
      authenticated: true,
      passwordChangeRequired: false,
    });
    const user = userEvent.setup();

    render(<DemoLoginForm />);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(mockSignIn).toHaveBeenCalledWith(
      {
        account: "demo@mosaic.internal",
        password: "internal-demo",
      },
      expect.any(AbortSignal),
    );
    expect(mockPush).toHaveBeenCalledWith("/models");
    expect(mockRefresh).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "登录" }),
    ).not.toBeDisabled();
  });

  it("navigates and resets loading when rendered inside StrictMode", async () => {
    mockSignIn.mockResolvedValue({
      authenticated: true,
      passwordChangeRequired: false,
    });
    const user = userEvent.setup();

    render(
      <StrictMode>
        <DemoLoginForm />
      </StrictMode>,
    );
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(mockPush).toHaveBeenCalledWith("/models");
    expect(
      screen.getByRole("button", { name: "登录" }),
    ).not.toBeDisabled();
  });

  it("shows a visible error and resets loading after a non-abort failure", async () => {
    mockSignIn.mockRejectedValue(new Error("service unavailable"));
    const user = userEvent.setup();

    render(<DemoLoginForm />);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "登录服务暂时不可用，请稍后重试。",
    );
    expect(
      screen.getByRole("button", { name: "登录" }),
    ).not.toBeDisabled();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("uses blank credentials and production login copy in API mode", async () => {
    mockSignIn.mockResolvedValue({
      authenticated: false,
      passwordChangeRequired: false,
    });
    const user = userEvent.setup();

    render(<LoginForm mode="api" />);

    expect(screen.getByLabelText("账户")).toHaveValue("");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
    });
    expect(screen.queryByText(/演示/)).not.toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("账户"), "user@example.com");
    await user.type(screen.getByLabelText("密码"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(mockSignIn).toHaveBeenCalledWith(
      { account: "user@example.com", password: "wrong-password" },
      expect.any(AbortSignal),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "账号或密码不正确，请检查后重试。",
    );
  });

  it("returns to the validated protected route", async () => {
    mockSignIn.mockResolvedValue({
      authenticated: true,
      passwordChangeRequired: false,
    });
    const user = userEvent.setup();

    render(<LoginForm mode="demo" returnTo="/generations?status=running" />);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(mockPush).toHaveBeenCalledWith("/generations?status=running");
  });

  it("aborts the in-flight sign-in when unmounted", async () => {
    let signal: AbortSignal | undefined;
    mockSignIn.mockImplementation(
      (_input: unknown, requestSignal: AbortSignal) => {
        signal = requestSignal;
        return new Promise(() => undefined);
      },
    );
    const user = userEvent.setup();
    const view = render(<DemoLoginForm />);

    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(signal).toBeInstanceOf(AbortSignal);

    view.unmount();

    expect(signal?.aborted).toBe(true);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("ignores a duplicate submit while sign-in is in flight", () => {
    let signal: AbortSignal | undefined;
    mockSignIn.mockImplementation(
      (_input: unknown, requestSignal: AbortSignal) => {
        signal = requestSignal;
        return new Promise(() => undefined);
      },
    );

    render(<DemoLoginForm />);
    const form = document.querySelector("form");
    if (!form) throw new Error("expected login form");

    fireEvent.submit(form);
    fireEvent.submit(form);

    expect(mockSignIn).toHaveBeenCalledTimes(1);
    expect(signal?.aborted).toBe(false);
    expect(
      screen.getByRole("button", { name: "登录" }),
    ).toBeDisabled();
  });
});
