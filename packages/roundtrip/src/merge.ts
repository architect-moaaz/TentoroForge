/**
 * Merge Logic — recompiles IR and preserves user code blocks.
 *
 * When the IR changes (from UI editor or AI), the compiler produces fresh output.
 * This module merges the fresh output with user-written code that lives
 * outside IR boundaries, preserving user additions.
 */

import { parseCompiledFile, type UserCodeBlock } from "./parse.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MergeResult {
  /** The merged file content */
  content: string;
  /** Whether user code was preserved */
  hasUserCode: boolean;
  /** Number of user code blocks preserved */
  userBlockCount: number;
}

// ---------------------------------------------------------------------------
// Main merge function
// ---------------------------------------------------------------------------

/**
 * Merge freshly compiled output with user code from an existing file.
 *
 * Strategy:
 *   1. Parse the existing file to find user code blocks
 *   2. Parse the fresh compiled output to find insertion points
 *   3. Insert user code blocks at their relative positions
 *   4. Merge imports (keep user imports, update compiler imports)
 */
export function mergeWithUserCode(
  freshCompiled: string,
  existingFile: string,
): MergeResult {
  const existingParsed = parseCompiledFile(existingFile);
  const freshParsed = parseCompiledFile(freshCompiled);

  // If existing file has no boundaries, it's fully user-owned — don't merge
  if (!existingParsed.hasBoundaries) {
    return {
      content: existingFile,
      hasUserCode: true,
      userBlockCount: 0,
    };
  }

  // If no user code, return fresh compiled as-is
  if (existingParsed.userRegions.length === 0 && existingParsed.imports.user.length === 0) {
    return {
      content: freshCompiled,
      hasUserCode: false,
      userBlockCount: 0,
    };
  }

  // Merge imports: imports in existing but not in fresh are "user imports"
  const userImports = findUserImports(existingParsed.imports.managed, freshParsed.imports.managed);
  const mergedImports = mergeImports(freshParsed.imports.managed, userImports);

  // Build the output by walking through the fresh compiled file
  // and inserting user blocks at the right positions
  const freshLines = freshCompiled.split("\n");
  const outputLines: string[] = [];
  let importsDone = false;

  for (let i = 0; i < freshLines.length; i++) {
    const line = freshLines[i];
    const trimmed = line.trim();

    // Replace import block
    if (!importsDone && trimmed.startsWith("import ")) {
      // Skip all fresh import lines
      while (i < freshLines.length && freshLines[i].trim().startsWith("import ")) {
        i++;
      }
      // Insert merged imports
      outputLines.push(...mergedImports);
      outputLines.push("");
      importsDone = true;
      i--; // re-process current line
      continue;
    }

    outputLines.push(line);

    // Check if this line closes an IR region
    const endMatch = trimmed.match(/\{\/\*\s*@ir-end:\s*(.+?)\s*\*\/\}/);
    if (endMatch) {
      const regionPath = endMatch[1];
      // Find user blocks that should appear after this region
      const userBlock = existingParsed.userRegions.find(
        (b) => b.afterIRNode === regionPath,
      );
      if (userBlock) {
        outputLines.push("");
        outputLines.push("    {/* USER CODE — preserved by IR compiler */}");
        outputLines.push(userBlock.content);
        outputLines.push("    {/* END USER CODE */}");
      }
    }
  }

  // Append any user blocks that come after all IR regions
  const trailingBlocks = existingParsed.userRegions.filter(
    (b) => b.afterIRNode !== null &&
    !existingParsed.irRegions.has(b.afterIRNode) === false &&
    !freshParsed.irRegions.has(b.afterIRNode),
  );

  // Also handle user blocks at the very end (afterIRNode is the last closed region)
  const lastRegionPath = [...existingParsed.irRegions.keys()].pop();
  const endBlocks = existingParsed.userRegions.filter(
    (b) => b.afterIRNode === lastRegionPath &&
    !outputLines.some((l) => l.includes(b.content.slice(0, 50))),
  );

  for (const block of endBlocks) {
    // Insert before the closing return/brace
    const lastReturnIdx = outputLines.findLastIndex((l) => l.trim() === ");");
    if (lastReturnIdx > 0) {
      outputLines.splice(lastReturnIdx, 0,
        "",
        "    {/* USER CODE — preserved by IR compiler */}",
        block.content,
        "    {/* END USER CODE */}",
      );
    }
  }

  return {
    content: outputLines.join("\n"),
    hasUserCode: existingParsed.userRegions.length > 0,
    userBlockCount: existingParsed.userRegions.length,
  };
}

// ---------------------------------------------------------------------------
// Import merging
// ---------------------------------------------------------------------------

function mergeImports(freshImports: string[], userImports: string[]): string[] {
  const freshSet = new Set(freshImports.map((i) => i.trim()));
  const merged = [...freshImports];

  for (const userImport of userImports) {
    const trimmed = userImport.trim();
    if (!trimmed) continue;

    // Check if the import source (from "...") already exists
    const fromMatch = trimmed.match(/from\s+["']([^"']+)["']/);
    if (fromMatch) {
      const source = fromMatch[1];
      const existsInFresh = freshImports.some((fi) => fi.includes(`"${source}"`) || fi.includes(`'${source}'`));
      if (!existsInFresh) {
        merged.push(userImport);
      }
      // If source exists, user might have added more named imports — TODO: deep merge
    } else {
      // Side-effect import
      if (!freshSet.has(trimmed)) {
        merged.push(userImport);
      }
    }
  }

  return merged;
}

/**
 * Find imports in existing file that aren't in the fresh compile — these are user imports.
 */
function findUserImports(existingImports: string[], freshImports: string[]): string[] {
  const freshSources = new Set<string>();
  for (const fi of freshImports) {
    const match = fi.match(/from\s+["']([^"']+)["']/);
    if (match) freshSources.add(match[1]);
  }

  return existingImports.filter((ei) => {
    const match = ei.match(/from\s+["']([^"']+)["']/);
    if (match) return !freshSources.has(match[1]);
    // Side-effect imports: keep if not in fresh
    return !freshImports.some((fi) => fi.trim() === ei.trim());
  });
}
