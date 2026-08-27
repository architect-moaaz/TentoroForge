/**
 * Boundary Parser — reads compiled TSX files and extracts IR regions vs user regions.
 *
 * The compiler emits boundary comments:
 *   {/* @ir-node: 0.1.2 *\/}
 *   ...compiled JSX...
 *   {/* @ir-end: 0.1.2 *\/}
 *
 * Regions can be nested (0 contains 0.0 and 0.1).
 * Code between boundaries is IR-managed.
 * Code outside boundaries is user-owned.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ParseResult {
  /** IR regions keyed by path string (e.g., "0.1.2" → code) */
  irRegions: Map<string, string>;
  /** User code blocks that live between/outside IR regions */
  userRegions: UserCodeBlock[];
  /** Import lines split into managed (from compiler) and user-added */
  imports: { managed: string[]; user: string[] };
  /** Whether all IR boundary markers are intact and well-formed */
  irIntact: boolean;
  /** Whether the file has any boundary markers at all */
  hasBoundaries: boolean;
}

export interface UserCodeBlock {
  /** The IR node path this block appears after. null = before first IR region */
  afterIRNode: string | null;
  /** The raw code content */
  content: string;
  /** Line number where this block starts in the source file */
  startLine: number;
}

// ---------------------------------------------------------------------------
// Regex patterns
// ---------------------------------------------------------------------------

const IR_NODE_START = /\{\/\*\s*@ir-node:\s*(.+?)\s*\*\/\}/;
const IR_NODE_END = /\{\/\*\s*@ir-end:\s*(.+?)\s*\*\/\}/;
const IMPORT_LINE = /^import\s+/;
const USE_CLIENT = /^["']use client["'];?\s*$/;

// ---------------------------------------------------------------------------
// Main parser
// ---------------------------------------------------------------------------

/**
 * Parse a compiled TSX file, separating IR-managed regions from user code.
 * Handles nested regions via a stack.
 */
export function parseCompiledFile(source: string): ParseResult {
  const lines = source.split("\n");
  const result: ParseResult = {
    irRegions: new Map(),
    userRegions: [],
    imports: { managed: [], user: [] },
    irIntact: true,
    hasBoundaries: false,
  };

  // Stack for nested regions: each entry is { path, lines[] }
  const regionStack: Array<{ path: string; lines: string[] }> = [];
  let userLines: string[] = [];
  let lastClosedRegion: string | null = null;
  let inImportBlock = false;
  let pastImports = false;
  let userStartLine = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Track imports (before first non-import line)
    if (!pastImports) {
      if (USE_CLIENT.test(trimmed) || trimmed === "") continue;
      if (IMPORT_LINE.test(trimmed)) {
        inImportBlock = true;
        result.imports.managed.push(line);
        continue;
      }
      if (inImportBlock) {
        pastImports = true;
        // Fall through
      }
    }

    // Check for region start
    const startMatch = trimmed.match(IR_NODE_START);
    if (startMatch) {
      result.hasBoundaries = true;
      const path = startMatch[1];

      // If we're not inside any region, flush user code
      if (regionStack.length === 0 && userLines.length > 0) {
        const content = userLines.join("\n").trim();
        if (content) {
          result.userRegions.push({
            afterIRNode: lastClosedRegion,
            content,
            startLine: userStartLine,
          });
        }
        userLines = [];
      }

      // Push onto stack
      regionStack.push({ path, lines: [] });
      continue;
    }

    // Check for region end
    const endMatch = trimmed.match(IR_NODE_END);
    if (endMatch) {
      const path = endMatch[1];
      const top = regionStack[regionStack.length - 1];

      if (top && top.path === path) {
        // Pop the stack and store the region
        regionStack.pop();
        result.irRegions.set(path, top.lines.join("\n"));
        lastClosedRegion = path;
        userStartLine = i + 1;

        // If there's a parent region, add the boundary markers + content to it
        if (regionStack.length > 0) {
          const parent = regionStack[regionStack.length - 1];
          parent.lines.push(`{/* @ir-node: ${path} */}`);
          parent.lines.push(...top.lines);
          parent.lines.push(`{/* @ir-end: ${path} */}`);
        }
      } else {
        // Mismatched — IR is corrupt
        result.irIntact = false;
      }
      continue;
    }

    // Accumulate into current region or user code
    if (regionStack.length > 0) {
      regionStack[regionStack.length - 1].lines.push(line);
    } else if (pastImports) {
      userLines.push(line);
    }
  }

  // Check for unclosed regions
  if (regionStack.length > 0) {
    result.irIntact = false;
  }

  // Flush remaining user code
  if (userLines.length > 0) {
    const content = userLines.join("\n").trim();
    if (content) {
      result.userRegions.push({
        afterIRNode: lastClosedRegion,
        content,
        startLine: userStartLine,
      });
    }
  }

  return result;
}

/**
 * Check if a file has IR boundary markers.
 */
export function hasBoundaryMarkers(source: string): boolean {
  return IR_NODE_START.test(source);
}

/**
 * Strip all boundary markers from a file, leaving only the code.
 * Used for "eject" from IR.
 */
export function stripBoundaryMarkers(source: string): string {
  return source
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      return !IR_NODE_START.test(trimmed) && !IR_NODE_END.test(trimmed);
    })
    .join("\n");
}
