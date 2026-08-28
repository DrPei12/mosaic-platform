"use client";

import { useEffect, useState } from "react";

export function NetworkStatus() {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);

    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);

    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  if (online) return null;

  return (
    <div
      role="status"
      className="border-b border-[var(--mosaic-color-warning)] bg-[color-mix(in_srgb,var(--mosaic-color-warning)_10%,var(--mosaic-color-surface))] px-4 py-2 text-sm text-[var(--mosaic-color-ink)]"
    >
      网络已断开。未提交内容会保留在当前页面。
    </div>
  );
}
