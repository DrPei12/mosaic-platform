import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { tokens } from "./index.js";
import tokensJson from "./tokens.json";

const packageRoot = resolve(import.meta.dirname, "..");
const toKebabCase = (name: string) => name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);

const flattenLeaves = (value: unknown, path: string[] = []): Array<[string[], string]> => {
  if (typeof value === "string") {
    return [[path, value]];
  }

  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`Expected a token object or string at ${path.join(".")}`);
  }

  return Object.entries(value).flatMap(([key, child]) => flattenLeaves(child, [...path, key]));
};

const cssVariableName = (path: string[]) => `--mosaic-${path.map(toKebabCase).join("-")}`;

describe("MOSAIC design tokens", () => {
  it("locks the approved palette", () => {
    expect(tokens.color).toEqual({
      canvas: "#F5F6F8",
      surface: "#FFFFFF",
      surfaceMuted: "#ECEFF3",
      ink: "#15171A",
      inkMuted: "#667085",
      line: "#D7DCE3",
      accent: "#2F5BEA",
      danger: "#C63C45",
      warning: "#A66616",
      success: "#227A53",
    });
  });

  it("locks the approved radius scale", () => {
    expect(tokens.radius).toEqual({
      control: "8px",
      surface: "12px",
      media: "10px",
      pill: "999px",
    });
  });

  it("locks motion, layout, typography, spacing, grid, border, and focus values", () => {
    expect(tokens.motion).toEqual({
      fast: "180ms",
      normal: "240ms",
      page: "360ms",
      ease: "cubic-bezier(0.16, 1, 0.3, 1)",
    });
    expect(tokens.layout).toEqual({
      content: "1280px",
      workspace: "1440px",
      nav: "240px",
      compactBreakpoint: "1024px",
      singleColumnBreakpoint: "768px",
      topBarMobile: "64px",
      topBarDesktop: "64px",
      mobileBottomNavigation: "76px",
      conversationColumn: "328px",
      composerPanel: "104px",
      taskHeader: "64px",
      taskInteraction: "920px",
      taskMessage: "880px",
      taskComposer: "120px",
    });
    expect(tokens.typography).toEqual({
      display: { fontSize: "56px", lineHeight: "64px" },
      h1: { fontSize: "40px", lineHeight: "48px" },
      h2: { fontSize: "30px", lineHeight: "38px" },
      h3: { fontSize: "22px", lineHeight: "28px" },
      body: { fontSize: "16px", lineHeight: "24px" },
      small: { fontSize: "14px", lineHeight: "20px" },
      meta: { fontSize: "12px", lineHeight: "16px" },
      micro: { fontSize: "11px", lineHeight: "16px" },
    });
    expect(tokens.spacing).toEqual({
      "4": "4px",
      "8": "8px",
      "12": "12px",
      "16": "16px",
      "24": "24px",
      "32": "32px",
      "40": "40px",
      "48": "48px",
      "64": "64px",
      "96": "96px",
    });
    expect(tokens.grid).toEqual({ columns: "12", desktopGutter: "24px", mobileGutter: "16px" });
    expect(tokens.border).toEqual({ width: "1px" });
    expect(tokens.focus).toEqual({ ringWidth: "3px", offset: "2px" });
  });

  it("emits every JSON leaf exactly once and reduces every duration", () => {
    execFileSync(process.execPath, [resolve(packageRoot, "scripts/generate-css.mjs"), "--check"], {
      cwd: packageRoot,
      stdio: "pipe",
    });

    const css = readFileSync(resolve(packageRoot, "src/tokens.css"), "utf8");
    const rootEnd = css.indexOf("\n}\n\n@media");
    expect(rootEnd).toBeGreaterThan(0);
    const rootCss = css.slice(0, rootEnd);
    const rootDeclarations = Array.from(rootCss.matchAll(/^\s+(--mosaic-[\w-]+): ([^;]+);$/gm), ([, name, value]) => [
      name,
      value,
    ] as const);
    expect(tokens).toEqual(tokensJson);
    const expectedDeclarations = flattenLeaves(tokensJson).map(([path, value]) => [cssVariableName(path), value] as const);

    expect(rootDeclarations).toEqual(expectedDeclarations);
    for (const [name, value] of expectedDeclarations) {
      expect(rootCss).toContain(`${name}: ${value};`);
    }

    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
    const reducedCss = css.slice(rootEnd);
    const durationDeclarations = expectedDeclarations.filter(([, value]) => /^\d+(?:\.\d+)?ms$/.test(value));
    const reducedDeclarations = Array.from(
      reducedCss.matchAll(/^\s+(--mosaic-[\w-]+): ([^;]+);$/gm),
      ([, name, value]) => [name, value] as const,
    );
    expect(reducedDeclarations).toEqual(durationDeclarations.map(([name]) => [name, "0ms"] as const));
  });
});
