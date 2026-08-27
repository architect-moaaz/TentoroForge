#!/usr/bin/env node
/**
 * AST-based source annotation for JSX files.
 *
 * Usage:
 *   node annotate-source.mjs annotate <rootDir>
 *   node annotate-source.mjs strip <rootDir>
 *
 * Annotate: adds data-source-file and data-source-line to every JSX opening
 * element in src/app and src/components .tsx files.
 *
 * Strip: removes all data-source-* attributes.
 *
 * Outputs JSON to stdout:
 *   { "annotated": N, "files": [...] }  or  { "stripped": N }
 */

import { readFileSync, writeFileSync, readdirSync, existsSync } from "fs";
import { resolve, relative } from "path";
import { parse } from "@babel/parser";
import _traverse from "@babel/traverse";
import _generate from "@babel/generator";
import * as t from "@babel/types";

// Handle CJS default export interop
const traverse = _traverse.default || _traverse;
const generate = _generate.default || _generate;

const SKIP_TAGS = new Set(["html", "head"]);
const SOURCE_ATTR_PREFIX = "data-source-";
const SCAN_DIRS = ["src/app", "src/components"];

// --- File discovery ---

function walkDirectory(dir, results) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const fullPath = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      walkDirectory(fullPath, results);
    } else if (entry.isFile() && entry.name.endsWith(".tsx")) {
      results.push(fullPath);
    }
  }
}

function findTsxFiles(rootDir) {
  const files = [];
  for (const dir of SCAN_DIRS) {
    const baseDir = resolve(rootDir, dir);
    if (existsSync(baseDir)) {
      walkDirectory(baseDir, files);
    }
  }
  return files;
}

// --- Annotate ---

function annotateFile(filePath, rootDir) {
  const source = readFileSync(filePath, "utf-8");
  const relPath = relative(rootDir, filePath);

  // Skip if already annotated
  if (source.includes("data-source-file=")) return null;

  let ast;
  try {
    ast = parse(source, {
      sourceType: "module",
      plugins: ["typescript", "jsx"],
    });
  } catch {
    return null;
  }

  let count = 0;

  traverse(ast, {
    JSXOpeningElement(path) {
      const nameNode = path.node.name;

      // Get tag name for skip check
      let tagName = null;
      if (t.isJSXIdentifier(nameNode)) {
        tagName = nameNode.name;
      }

      // Skip <html>, <head>
      if (tagName && SKIP_TAGS.has(tagName.toLowerCase())) return;

      // Skip already-annotated elements
      const hasAttr = path.node.attributes.some(
        (attr) =>
          t.isJSXAttribute(attr) &&
          t.isJSXIdentifier(attr.name) &&
          attr.name.name === "data-source-file",
      );
      if (hasAttr) return;

      const loc = path.node.loc;
      if (!loc) return;

      path.node.attributes.push(
        t.jsxAttribute(
          t.jsxIdentifier("data-source-file"),
          t.stringLiteral(relPath),
        ),
        t.jsxAttribute(
          t.jsxIdentifier("data-source-line"),
          t.stringLiteral(String(loc.start.line)),
        ),
      );

      count++;
    },
  });

  if (count === 0) return null;

  const output = generate(ast, { retainLines: true }, source);
  writeFileSync(filePath, output.code);
  return count;
}

// --- Strip ---

function stripFile(filePath) {
  const source = readFileSync(filePath, "utf-8");
  if (!source.includes("data-source-file=")) return false;

  let ast;
  try {
    ast = parse(source, {
      sourceType: "module",
      plugins: ["typescript", "jsx"],
    });
  } catch {
    // Fall back to regex strip if AST parsing fails
    let cleaned = source;
    cleaned = cleaned.replace(/\s+data-source-file="[^"]*"/g, "");
    cleaned = cleaned.replace(/\s+data-source-line="[^"]*"/g, "");
    cleaned = cleaned.replace(/\s+data-source-component="[^"]*"/g, "");
    if (cleaned !== source) {
      writeFileSync(filePath, cleaned);
      return true;
    }
    return false;
  }

  let modified = false;

  traverse(ast, {
    JSXOpeningElement(path) {
      path.node.attributes = path.node.attributes.filter((attr) => {
        if (
          t.isJSXAttribute(attr) &&
          t.isJSXIdentifier(attr.name) &&
          attr.name.name.startsWith(SOURCE_ATTR_PREFIX)
        ) {
          modified = true;
          return false;
        }
        return true;
      });
    },
  });

  if (!modified) return false;

  const output = generate(ast, { retainLines: true }, source);
  writeFileSync(filePath, output.code);
  return true;
}

// --- Main ---

const [mode, rootDir] = process.argv.slice(2);

if (!mode || !rootDir) {
  console.error("Usage: node annotate-source.mjs <annotate|strip> <rootDir>");
  process.exit(1);
}

const absRoot = resolve(rootDir);
const files = findTsxFiles(absRoot);

if (mode === "annotate") {
  let totalAnnotated = 0;
  const annotatedFiles = [];

  for (const file of files) {
    const count = annotateFile(file, absRoot);
    if (count) {
      totalAnnotated += count;
      annotatedFiles.push(relative(absRoot, file));
    }
  }

  console.log(
    JSON.stringify({ annotated: totalAnnotated, files: annotatedFiles }),
  );
} else if (mode === "strip") {
  let stripped = 0;

  for (const file of files) {
    if (stripFile(file)) stripped++;
  }

  console.log(JSON.stringify({ stripped }));
} else {
  console.error(`Unknown mode: ${mode}. Use "annotate" or "strip".`);
  process.exit(1);
}
