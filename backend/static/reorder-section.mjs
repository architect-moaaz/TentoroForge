#!/usr/bin/env node
/**
 * Reorder a JSX section within a page file using Babel AST.
 *
 * Usage:
 *   node reorder-section.mjs <filePath> <sourceLine> <targetLine> <position>
 *
 * position: "before" | "after"
 *
 * Outputs JSON:
 *   { "reordered": true/false }
 */

import { readFileSync, writeFileSync } from "fs";
import { parse } from "@babel/parser";
import _traverse from "@babel/traverse";
import _generate from "@babel/generator";
import * as t from "@babel/types";

const traverse = _traverse.default || _traverse;
const generate = _generate.default || _generate;

const [filePath, sourceLineStr, targetLineStr, position] = process.argv.slice(2);

if (!filePath || !sourceLineStr || !targetLineStr || !position) {
  console.error(
    "Usage: node reorder-section.mjs <filePath> <sourceLine> <targetLine> <position>",
  );
  process.exit(1);
}

const sourceLine = parseInt(sourceLineStr, 10);
const targetLine = parseInt(targetLineStr, 10);

if (sourceLine === targetLine) {
  console.log(JSON.stringify({ reordered: false }));
  process.exit(0);
}

let source;
try {
  source = readFileSync(filePath, "utf-8");
} catch {
  console.log(JSON.stringify({ reordered: false }));
  process.exit(0);
}

let ast;
try {
  ast = parse(source, {
    sourceType: "module",
    plugins: ["typescript", "jsx"],
  });
} catch {
  console.log(JSON.stringify({ reordered: false }));
  process.exit(0);
}

let reordered = false;

traverse(ast, {
  JSXElement(path) {
    // Only process elements that contain both source and target as children
    const children = path.node.children.filter((c) => t.isJSXElement(c));
    if (children.length < 2) return;

    let sourceIdx = -1;
    let targetIdx = -1;
    let sourceChild = null;

    for (let i = 0; i < path.node.children.length; i++) {
      const child = path.node.children[i];
      if (!t.isJSXElement(child)) continue;

      const childLine = child.openingElement?.loc?.start?.line;
      if (childLine === sourceLine) {
        sourceIdx = i;
        sourceChild = child;
      }
      if (childLine === targetLine) {
        targetIdx = i;
      }
    }

    if (sourceIdx === -1 || targetIdx === -1 || !sourceChild) return;

    // Remove source element
    path.node.children.splice(sourceIdx, 1);

    // Adjust target index after removal
    let newTargetIdx = targetIdx;
    if (sourceIdx < targetIdx) {
      newTargetIdx--;
    }

    // Find the actual target position in the (now shorter) children array
    let insertIdx;
    if (position === "before") {
      insertIdx = newTargetIdx;
    } else {
      insertIdx = newTargetIdx + 1;
    }

    // Find the real index in the full children array (including whitespace/text)
    let realInsertIdx = 0;
    let jsxCount = 0;
    for (let i = 0; i < path.node.children.length; i++) {
      if (jsxCount === insertIdx) {
        realInsertIdx = i;
        break;
      }
      if (t.isJSXElement(path.node.children[i])) {
        jsxCount++;
      }
      realInsertIdx = i + 1;
    }

    // Insert at new position
    path.node.children.splice(realInsertIdx, 0, sourceChild);
    reordered = true;
    path.stop();
  },

  JSXFragment(path) {
    // Same logic for fragments
    const children = path.node.children.filter((c) => t.isJSXElement(c));
    if (children.length < 2) return;

    let sourceIdx = -1;
    let targetIdx = -1;
    let sourceChild = null;

    for (let i = 0; i < path.node.children.length; i++) {
      const child = path.node.children[i];
      if (!t.isJSXElement(child)) continue;

      const childLine = child.openingElement?.loc?.start?.line;
      if (childLine === sourceLine) {
        sourceIdx = i;
        sourceChild = child;
      }
      if (childLine === targetLine) {
        targetIdx = i;
      }
    }

    if (sourceIdx === -1 || targetIdx === -1 || !sourceChild) return;

    path.node.children.splice(sourceIdx, 1);

    let newTargetIdx = targetIdx;
    if (sourceIdx < targetIdx) {
      newTargetIdx--;
    }

    let insertIdx = position === "before" ? newTargetIdx : newTargetIdx + 1;

    let realInsertIdx = 0;
    let jsxCount = 0;
    for (let i = 0; i < path.node.children.length; i++) {
      if (jsxCount === insertIdx) {
        realInsertIdx = i;
        break;
      }
      if (t.isJSXElement(path.node.children[i])) {
        jsxCount++;
      }
      realInsertIdx = i + 1;
    }

    path.node.children.splice(realInsertIdx, 0, sourceChild);
    reordered = true;
    path.stop();
  },
});

if (reordered) {
  const output = generate(ast, { retainLines: true }, source);
  writeFileSync(filePath, output.code);
}

console.log(JSON.stringify({ reordered }));
