import { describe, expect, it } from "vitest";

import { BRAND } from "./brand";

describe("BRAND", () => {
  it("exposes the canonical MOSAIC identity", () => {
    expect(BRAND).toEqual({
      name: "MOSAIC",
      defaultTitle: "MOSAIC 多模态模型工作台",
    });
  });
});
