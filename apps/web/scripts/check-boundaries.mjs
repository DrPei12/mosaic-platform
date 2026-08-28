import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const defaultProjectRoot = resolve(scriptDirectory, "..");
export const CONSUMER_ROOTS = [
  "src/app",
  "src/features",
  "src/shared/ui",
  "src/shared/layout",
];
const SKIPPED_DIRECTORIES = new Set([
  ".next",
  "build",
  "coverage",
  "dist",
  "node_modules",
  "out",
]);
const GLOBAL_OBJECTS = new Set(["global", "globalThis", "self", "window"]);

function isConcreteServiceSpecifier(specifier) {
  const normalized = specifier.replaceAll("\\", "/");
  return /(?:^|\/)services\/(?:demo|api)-/.test(normalized);
}

function isForbiddenDemoSpecifier(specifier) {
  const normalized = specifier.replaceAll("\\", "/");
  return /(?:^|\/)shared\/demo\/(?:demo-scenario|demo-state-store)(?:\.|\/|$)/.test(
    normalized,
  );
}

function isFetchExpression(expression) {
  if (ts.isIdentifier(expression)) return expression.text === "fetch";
  if (ts.isPropertyAccessExpression(expression)) {
    return expression.name.text === "fetch";
  }
  if (ts.isElementAccessExpression(expression)) {
    const argument = expression.argumentExpression;
    return ts.isStringLiteral(argument) && argument.text === "fetch";
  }
  return false;
}

function isFetchIdentifierReference(node) {
  if (!ts.isIdentifier(node) || node.text !== "fetch") return false;

  const parent = node.parent;
  if (ts.isPropertyAccessExpression(parent) && parent.name === node) {
    return (
      ts.isIdentifier(parent.expression) &&
      GLOBAL_OBJECTS.has(parent.expression.text)
    );
  }
  if (
    (ts.isQualifiedName(parent) && parent.right === node) ||
    (ts.isPropertyAssignment(parent) && parent.name === node) ||
    (ts.isVariableDeclaration(parent) && parent.name === node) ||
    (ts.isParameter(parent) && parent.name === node) ||
    (ts.isBindingElement(parent) &&
      (parent.name === node || parent.propertyName === node)) ||
    (ts.isImportSpecifier(parent) &&
      (parent.name === node || parent.propertyName === node)) ||
    (ts.isExportSpecifier(parent) &&
      (parent.name === node || parent.propertyName === node)) ||
    (ts.isFunctionDeclaration(parent) && parent.name === node) ||
    (ts.isClassDeclaration(parent) && parent.name === node) ||
    (ts.isInterfaceDeclaration(parent) && parent.name === node) ||
    (ts.isTypeAliasDeclaration(parent) && parent.name === node) ||
    (ts.isEnumDeclaration(parent) && parent.name === node) ||
    (ts.isModuleDeclaration(parent) && parent.name === node) ||
    (ts.isMethodDeclaration(parent) && parent.name === node) ||
    (ts.isMethodSignature(parent) && parent.name === node) ||
    (ts.isPropertyDeclaration(parent) && parent.name === node) ||
    (ts.isPropertySignature(parent) && parent.name === node) ||
    (ts.isGetAccessorDeclaration(parent) && parent.name === node) ||
    (ts.isSetAccessorDeclaration(parent) && parent.name === node) ||
    (ts.isLabeledStatement(parent) && parent.label === node)
  ) {
    return false;
  }

  return true;
}

function isGlobalFetchElementAccess(node) {
  if (!ts.isElementAccessExpression(node)) return false;

  const argument = node.argumentExpression;
  return (
    ts.isStringLiteralLike(argument) &&
    argument.text === "fetch" &&
    ts.isIdentifier(node.expression) &&
    GLOBAL_OBJECTS.has(node.expression.text)
  );
}

function moduleSpecifier(node) {
  return node && ts.isStringLiteralLike(node) ? node.text : undefined;
}

function hasBoundaryViolation(contents, filePath) {
  const scriptKind = filePath.endsWith(".tsx")
    ? ts.ScriptKind.TSX
    : ts.ScriptKind.TS;
  const sourceFile = ts.createSourceFile(
    filePath,
    contents,
    ts.ScriptTarget.Latest,
    true,
    scriptKind,
  );
  let violation = false;

  function visit(node) {
    if (violation) return;

    if (
      isGlobalFetchElementAccess(node) ||
      isFetchIdentifierReference(node)
    ) {
      violation = true;
      return;
    }

    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      const specifier = moduleSpecifier(node.moduleSpecifier);
      if (
        specifier &&
        (isConcreteServiceSpecifier(specifier) ||
          isForbiddenDemoSpecifier(specifier))
      ) {
        violation = true;
        return;
      }
    }

    if (ts.isCallExpression(node)) {
      if (isFetchExpression(node.expression)) {
        violation = true;
        return;
      }

      const dynamicImport = node.expression.kind === ts.SyntaxKind.ImportKeyword;
      const requireCall =
        ts.isIdentifier(node.expression) && node.expression.text === "require";
      if (dynamicImport || requireCall) {
        const specifier = moduleSpecifier(node.arguments[0]);
        if (
          specifier &&
          (isConcreteServiceSpecifier(specifier) ||
            isForbiddenDemoSpecifier(specifier))
        ) {
          violation = true;
          return;
        }
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return violation;
}

function isDirectory(path) {
  return statSync(path, { throwIfNoEntry: false })?.isDirectory() ?? false;
}

export function scanBoundaries({
  projectRoot = defaultProjectRoot,
  consumerRoots = CONSUMER_ROOTS,
} = {}) {
  const sourceFiles = [];
  const violations = [];
  const resolvedRoots = consumerRoots.map((relativePath) => ({
    relativePath,
    absolutePath: resolve(projectRoot, relativePath),
  }));

  for (const root of resolvedRoots) {
    if (!isDirectory(root.absolutePath)) {
      throw new Error(
        `Boundary scan failed: expected consumer root is missing (${root.relativePath}).`,
      );
    }
  }

  function visit(directory) {
    const entries = readdirSync(directory, { withFileTypes: true }).sort((left, right) =>
      left.name < right.name ? -1 : left.name > right.name ? 1 : 0,
    );

    for (const entry of entries) {
      if (entry.isDirectory() && SKIPPED_DIRECTORIES.has(entry.name)) continue;

      const fullPath = resolve(directory, entry.name);
      if (entry.isDirectory()) {
        visit(fullPath);
        continue;
      }
      if (!entry.isFile() || !/\.(ts|tsx)$/.test(entry.name)) continue;

      sourceFiles.push(fullPath);
      const contents = readFileSync(fullPath, "utf8");
      if (hasBoundaryViolation(contents, fullPath)) violations.push(fullPath);
    }
  }

  for (const root of resolvedRoots) visit(root.absolutePath);
  sourceFiles.sort();
  violations.sort();
  return { sourceFiles, violations };
}

export function runBoundaryCheck(options) {
  const result = scanBoundaries(options);
  if (result.violations.length > 0) {
    throw new Error(
      `Boundary violations in consumer source:\n${result.violations.join("\n")}`,
    );
  }
  return result;
}

const invokedScript = process.argv[1]
  ? resolve(process.argv[1])
  : undefined;
const thisScript = resolve(fileURLToPath(import.meta.url));
if (invokedScript === thisScript) {
  const result = runBoundaryCheck();
  console.log(
    `Boundary scan passed: checked ${result.sourceFiles.length} consumer source files.`,
  );
}
