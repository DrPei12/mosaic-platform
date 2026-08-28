"use client";

import { AuthGate, type AuthGateProps } from "./auth-gate";

export type DemoAuthGateProps = Omit<AuthGateProps, "mode">;

/** Compatibility export for callers that intentionally request the demo gate. */
export function DemoAuthGate(props: DemoAuthGateProps) {
  return <AuthGate {...props} mode="demo" />;
}
