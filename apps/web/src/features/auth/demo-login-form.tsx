"use client";

import { LoginForm, type LoginFormProps } from "./login-form";

export type DemoLoginFormProps = Omit<LoginFormProps, "mode">;

/** Compatibility export for callers that intentionally request the demo UI. */
export function DemoLoginForm(props: DemoLoginFormProps) {
  return <LoginForm {...props} mode="demo" />;
}
