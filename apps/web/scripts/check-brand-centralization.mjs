import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDirectory, "..");
const sourceRoot = resolve(projectRoot, "src");
const allowedBrandFiles = new Set([
  resolve(sourceRoot, "shared/config/brand.ts"),
  resolve(sourceRoot, "shared/config/brand.test.ts"),
]);
const sourceFiles = [];
const violations = [];
const brandLiterals = ["MOSAIC", "NEXUS AI"];

function visit(directory) {
  const entries = readdirSync(directory, { withFileTypes: true }).sort((left, right) =>
    left.name < right.name ? -1 : left.name > right.name ? 1 : 0,
  );

  for (const entry of entries) {
    const fullPath = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      visit(fullPath);
      continue;
    }
    if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name)) continue;

    sourceFiles.push(fullPath);
    const contents = readFileSync(fullPath, "utf8");
    if (
      !allowedBrandFiles.has(fullPath) &&
      brandLiterals.some((literal) => contents.includes(literal))
    ) {
      violations.push(fullPath);
    }
  }
}

if (!statSync(sourceRoot, { throwIfNoEntry: false })?.isDirectory()) {
  throw new Error(`Brand scan failed: source directory is missing (${sourceRoot}).`);
}

visit(sourceRoot);

if (violations.length > 0) {
  throw new Error(
    `Brand literals outside centralized configuration:\n${violations.join("\n")}`,
  );
}

console.log(`Brand scan passed: checked ${sourceFiles.length} TypeScript source files.`);
