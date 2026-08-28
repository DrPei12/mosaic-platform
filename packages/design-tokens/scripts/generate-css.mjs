import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tokensPath = resolve(packageRoot, "src/tokens.json");
const cssPath = resolve(packageRoot, "src/tokens.css");
const checkOnly = process.argv.includes("--check");

const tokens = JSON.parse(readFileSync(tokensPath, "utf8"));

const toKebabCase = (name) => name.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
const flattenLeaves = (value, path = []) => {
  if (typeof value !== "object" || value === null) {
    return [[path, String(value)]];
  }

  return Object.entries(value).flatMap(([name, child]) => flattenLeaves(child, [...path, name]));
};
const cssVariableName = (path) => `--mosaic-${path.map(toKebabCase).join("-")}`;
const durationPattern = /^\d+(?:\.\d+)?ms$/;
const leaves = flattenLeaves(tokens);
const durationLeaves = leaves.filter(([, value]) => durationPattern.test(value));
const lines = [":root {"];

for (const [path, value] of leaves) {
  lines.push(`  ${cssVariableName(path)}: ${value};`);
}

lines.push("}", "", "@media (prefers-reduced-motion: reduce) {", "  :root {");
for (const [path] of durationLeaves) {
  lines.push(`    ${cssVariableName(path)}: 0ms;`);
}
lines.push("  }", "}", "");

const generatedCss = lines.join("\n");

if (checkOnly) {
  let currentCss;
  try {
    currentCss = readFileSync(cssPath, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") {
      console.error(`Generated CSS is missing: ${cssPath}`);
      process.exitCode = 1;
    } else {
      throw error;
    }
  }

  if (currentCss !== undefined && currentCss !== generatedCss) {
    console.error(`Generated CSS is out of date: ${cssPath}`);
    process.exitCode = 1;
  }
} else {
  writeFileSync(cssPath, generatedCss, "utf8");
}
