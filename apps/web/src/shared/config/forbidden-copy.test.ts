import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const sourceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const uiRoots = ["app", "features", "shared/config", "shared/layout", "shared/ui"];

const forbiddenCopy = [
  { label: "coming-soon copy", pattern: /即将支持|即将开放/ },
  { label: "API status copy", pattern: /真实\s*API/i },
  { label: "demo copy", pattern: /演示/ },
  { label: "model experience copy", pattern: /体验模型|模型体验/ },
  { label: "generic possibility copy", pattern: /无限可能|激发创意/ },
  { label: "internal navigation copy", pattern: /\bAgent\b|模型调试/ },
  { label: "provider-stack explanation", pattern: /模型部署|算力时长|provider\s+(?:stack|adapter)/i },
  { label: "unsupported reference control", pattern: /参考图|参考媒体/ },
  { label: "internal delivery phase", pattern: /第三计划|后续计划/ },
  { label: "secondary explanatory copy", pattern: /按任务直接使用|查看最近生成|开始第一次对话|生成完成后可|可直接生成/ },
  { label: "metadata explanatory copy", pattern: /面向专业创作团队/ },
  { label: "catalog explanatory copy", pattern: /product\.description/ },
  { label: "generation explanatory copy", pattern: /提交状态暂无法确认|状态会自动更新|结果已生成，可/ },
] as const;

function collectUiSourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const filePath = join(root, entry.name);
    if (entry.isDirectory()) return collectUiSourceFiles(filePath);
    if (!entry.isFile() || !/\.(?:tsx?|jsx?)$/.test(entry.name)) return [];
    if (/\.test\.[cm]?[jt]sx?$/.test(entry.name)) return [];
    return [filePath];
  });
}

describe("production UI copy", () => {
  it("does not reintroduce forbidden explanatory or placeholder phrases", () => {
    const sourceFiles = uiRoots.flatMap((root) => collectUiSourceFiles(resolve(sourceRoot, root)));
    const violations = sourceFiles.flatMap((filePath) => {
      const source = readFileSync(filePath, "utf8");
      return forbiddenCopy.flatMap(({ label, pattern }) =>
        pattern.test(source) ? [`${relative(sourceRoot, filePath)}: ${label}`] : [],
      );
    });

    expect(violations).toEqual([]);
  });
});
