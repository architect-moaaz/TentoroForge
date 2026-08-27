#!/usr/bin/env node
/**
 * Parse top-level JSX sections from a page file.
 *
 * Usage:
 *   node parse-sections.mjs <filePath> <rootDir>
 *
 * Outputs JSON:
 *   { "sections": [{ tagName, componentName, line, children_count }] }
 */

import { readFileSync } from "fs";
import { relative } from "path";
import { parse } from "@babel/parser";
import _traverse from "@babel/traverse";
import * as t from "@babel/types";

const traverse = _traverse.default || _traverse;

const [filePath, rootDir] = process.argv.slice(2);

if (!filePath) {
  console.error("Usage: node parse-sections.mjs <filePath> [rootDir]");
  process.exit(1);
}

let source;
try {
  source = readFileSync(filePath, "utf-8");
} catch {
  console.log(JSON.stringify({ sections: [] }));
  process.exit(0);
}

let ast;
try {
  ast = parse(source, {
    sourceType: "module",
    plugins: ["typescript", "jsx"],
  });
} catch {
  console.log(JSON.stringify({ sections: [] }));
  process.exit(0);
}

const sections = [];

// Find the default export or main component's return statement
traverse(ast, {
  ReturnStatement(path) {
    // Only process returns from top-level functions (components)
    const func = path.getFunctionParent();
    if (!func) return;

    // Check if parent is a module-level declaration
    const funcParent = func.parentPath;
    if (
      !funcParent ||
      (!funcParent.isProgram() &&
        !funcParent.isExportDefaultDeclaration() &&
        !funcParent.isExportNamedDeclaration() &&
        // Handle: const X = () => { return ... }
        !(funcParent.isVariableDeclarator() &&
          funcParent.parentPath?.isVariableDeclaration() &&
          (funcParent.parentPath.parentPath?.isProgram() ||
           funcParent.parentPath.parentPath?.isExportNamedDeclaration())))
    ) {
      return;
    }

    const arg = path.node.argument;
    if (!arg) return;

    // Handle JSX fragment or element
    const processElement = (node, depth = 0) => {
      if (!node) return;

      if (t.isJSXElement(node)) {
        const opening = node.openingElement;
        let tagName = "";
        let componentName = null;

        if (t.isJSXIdentifier(opening.name)) {
          tagName = opening.name.name;
          if (tagName[0] === tagName[0].toUpperCase() && tagName[0] !== tagName[0].toLowerCase()) {
            componentName = tagName;
          }
        } else if (t.isJSXMemberExpression(opening.name)) {
          tagName = `${opening.name.object.name}.${opening.name.property.name}`;
        }

        const childElements = node.children.filter(
          (c) => t.isJSXElement(c) || t.isJSXFragment(c),
        );

        sections.push({
          tagName: tagName.toLowerCase() === tagName ? tagName : tagName,
          componentName,
          line: opening.loc?.start?.line || 0,
          children_count: childElements.length,
        });

        // Only recurse one level for top-level sections
        if (depth === 0) {
          for (const child of node.children) {
            if (t.isJSXElement(child)) {
              processElement(child, depth + 1);
            }
          }
        }
      } else if (t.isJSXFragment(node)) {
        // Process children of fragment as if they were top-level
        for (const child of node.children) {
          if (t.isJSXElement(child)) {
            processElement(child, depth);
          }
        }
      } else if (t.isParenthesizedExpression(node)) {
        processElement(node.expression, depth);
      }
    };

    processElement(arg);

    // Stop after first component's return
    path.stop();
  },
});

console.log(JSON.stringify({ sections }));
