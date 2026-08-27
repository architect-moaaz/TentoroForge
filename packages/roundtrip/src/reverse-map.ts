/**
 * Reverse Mapper — detects changes in IR regions and maps them back to IR operations.
 *
 * When a user or LLM edits code within an IR boundary:
 *   1. Detect what changed (text content, class names, props)
 *   2. Try to map the change back to an IR operation (setProp)
 *   3. If mapping fails, convert the region to a Custom node
 */

import type { IRNode, NodePath } from "@tentoroforge/ir";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface IROperation {
  type: "setProp" | "replace";
  path: NodePath;
  prop?: string;
  value?: unknown;
  node?: IRNode;
}

export interface ReverseMapResult {
  /** Successfully mapped operations */
  operations: IROperation[];
  /** Regions that couldn't be mapped (will become Custom nodes) */
  unmappedRegions: UnmappedRegion[];
}

export interface UnmappedRegion {
  path: string;
  originalCode: string;
  modifiedCode: string;
}

// ---------------------------------------------------------------------------
// Main reverse mapper
// ---------------------------------------------------------------------------

/**
 * Compare expected IR regions (from compiler) with actual file regions (from disk).
 * Returns operations to bring the IR in sync with what the user changed.
 */
export function reverseMapChanges(
  expectedRegions: Map<string, string>,
  actualRegions: Map<string, string>,
): ReverseMapResult {
  const result: ReverseMapResult = {
    operations: [],
    unmappedRegions: [],
  };

  for (const [pathStr, actualCode] of actualRegions) {
    const expectedCode = expectedRegions.get(pathStr);

    // Region exists in actual but not in expected — new user code, skip
    if (expectedCode === undefined) continue;

    // No change
    if (normalizeWhitespace(actualCode) === normalizeWhitespace(expectedCode)) continue;

    // Try to reverse-map the change
    const path = pathStr.split(".").map(Number);
    const op = tryReverseMap(path, expectedCode, actualCode);

    if (op) {
      result.operations.push(op);
    } else {
      result.unmappedRegions.push({
        path: pathStr,
        originalCode: expectedCode,
        modifiedCode: actualCode,
      });
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Change detection strategies
// ---------------------------------------------------------------------------

function tryReverseMap(
  path: NodePath,
  expected: string,
  actual: string,
): IROperation | null {
  // Strategy 1: Label change (check before text — label tags contain text too)
  const labelChange = detectLabelChange(expected, actual);
  if (labelChange) {
    return {
      type: "setProp",
      path,
      prop: "label",
      value: labelChange.newLabel,
    };
  }

  // Strategy 2: Simple text content change
  const textChange = detectTextContentChange(expected, actual);
  if (textChange) {
    return {
      type: "setProp",
      path,
      prop: "content",
      value: textChange.newText,
    };
  }

  // Strategy 3: Placeholder change
  const placeholderChange = detectPropStringChange(expected, actual, "placeholder");
  if (placeholderChange) {
    return {
      type: "setProp",
      path,
      prop: "placeholder",
      value: placeholderChange,
    };
  }

  // Strategy 4: className/Tailwind change → try to map back to token
  const classChange = detectClassNameChange(expected, actual);
  if (classChange) {
    const tokenOp = tailwindToIRProp(path, classChange.oldClasses, classChange.newClasses);
    if (tokenOp) return tokenOp;
  }

  // Strategy 5: Variant attribute change
  const variantChange = detectPropStringChange(expected, actual, "variant");
  if (variantChange) {
    return {
      type: "setProp",
      path,
      prop: "variant",
      value: variantChange,
    };
  }

  // Can't map — return null (caller will create Custom node)
  return null;
}

// ---------------------------------------------------------------------------
// Detection: text content
// ---------------------------------------------------------------------------

interface TextChange {
  newText: string;
}

function detectTextContentChange(expected: string, actual: string): TextChange | null {
  // Look for simple text replacement between tags
  // e.g., <h2 className="...">Old Text</h2> → <h2 className="...">New Text</h2>
  const tagPattern = /<(\w+)\s[^>]*>([^<]*)<\/\1>/g;

  const expectedMatches = [...expected.matchAll(tagPattern)];
  const actualMatches = [...actual.matchAll(tagPattern)];

  if (expectedMatches.length !== actualMatches.length) return null;

  let changedText: string | null = null;
  let changeCount = 0;

  for (let i = 0; i < expectedMatches.length; i++) {
    const expText = expectedMatches[i][2].trim();
    const actText = actualMatches[i][2].trim();

    if (expText !== actText) {
      changedText = actText;
      changeCount++;
    }
  }

  // Only handle single text change
  if (changeCount === 1 && changedText !== null) {
    return { newText: changedText };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Detection: label
// ---------------------------------------------------------------------------

interface LabelChange {
  newLabel: string;
}

function detectLabelChange(expected: string, actual: string): LabelChange | null {
  // Look for label text in <label> tags
  const labelPattern = /<label[^>]*>([^<]*)<\/label>/g;

  const expectedLabels = [...expected.matchAll(labelPattern)];
  const actualLabels = [...actual.matchAll(labelPattern)];

  if (expectedLabels.length !== actualLabels.length || expectedLabels.length === 0) return null;

  let changedLabel: string | null = null;
  let changeCount = 0;

  for (let i = 0; i < expectedLabels.length; i++) {
    if (expectedLabels[i][1].trim() !== actualLabels[i][1].trim()) {
      changedLabel = actualLabels[i][1].trim();
      changeCount++;
    }
  }

  if (changeCount === 1 && changedLabel !== null) {
    return { newLabel: changedLabel };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Detection: generic string prop in JSX attributes
// ---------------------------------------------------------------------------

function detectPropStringChange(
  expected: string,
  actual: string,
  propName: string,
): string | null {
  // Match propName="value" in both
  const pattern = new RegExp(`${propName}="([^"]*)"`, "g");

  const expMatches = [...expected.matchAll(pattern)];
  const actMatches = [...actual.matchAll(pattern)];

  if (expMatches.length !== actMatches.length || expMatches.length === 0) return null;

  let changed: string | null = null;
  let changeCount = 0;

  for (let i = 0; i < expMatches.length; i++) {
    if (expMatches[i][1] !== actMatches[i][1]) {
      changed = actMatches[i][1];
      changeCount++;
    }
  }

  if (changeCount === 1 && changed !== null) {
    return changed;
  }

  return null;
}

// ---------------------------------------------------------------------------
// Detection: className changes
// ---------------------------------------------------------------------------

interface ClassChange {
  oldClasses: Set<string>;
  newClasses: Set<string>;
}

function detectClassNameChange(expected: string, actual: string): ClassChange | null {
  const classPattern = /className="([^"]*)"/g;

  const expMatches = [...expected.matchAll(classPattern)];
  const actMatches = [...actual.matchAll(classPattern)];

  if (expMatches.length !== actMatches.length) return null;

  let oldClasses: Set<string> | null = null;
  let newClasses: Set<string> | null = null;
  let changeCount = 0;

  for (let i = 0; i < expMatches.length; i++) {
    const expSet = new Set(expMatches[i][1].split(/\s+/).filter(Boolean));
    const actSet = new Set(actMatches[i][1].split(/\s+/).filter(Boolean));

    if (!setsEqual(expSet, actSet)) {
      oldClasses = expSet;
      newClasses = actSet;
      changeCount++;
    }
  }

  if (changeCount === 1 && oldClasses && newClasses) {
    return { oldClasses, newClasses };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Tailwind → IR prop mapping
// ---------------------------------------------------------------------------

const GAP_MAP: Record<string, string> = {
  "gap-1": "xs", "gap-2": "sm", "gap-4": "md", "gap-6": "lg", "gap-8": "xl", "gap-12": "2xl",
};
const PADDING_MAP: Record<string, string> = {
  "p-1": "xs", "p-2": "sm", "p-4": "md", "p-6": "lg", "p-8": "xl", "p-12": "2xl",
};
const TEXT_SIZE_MAP: Record<string, string> = {
  "text-2xl": "heading-1", "text-xl": "heading-2", "text-lg": "heading-3",
  "text-sm": "body", "text-xs": "caption",
};
const FONT_WEIGHT_MAP: Record<string, string> = {
  "font-normal": "normal", "font-medium": "medium", "font-semibold": "semibold", "font-bold": "bold",
};

function tailwindToIRProp(
  path: NodePath,
  oldClasses: Set<string>,
  newClasses: Set<string>,
): IROperation | null {
  const added = new Set([...newClasses].filter((c) => !oldClasses.has(c)));
  const removed = new Set([...oldClasses].filter((c) => !newClasses.has(c)));

  // Gap change
  for (const cls of added) {
    if (GAP_MAP[cls]) {
      return { type: "setProp", path, prop: "gap", value: GAP_MAP[cls] };
    }
  }

  // Padding change
  for (const cls of added) {
    if (PADDING_MAP[cls]) {
      return { type: "setProp", path, prop: "padding", value: PADDING_MAP[cls] };
    }
  }

  // Typography change
  for (const cls of added) {
    if (TEXT_SIZE_MAP[cls]) {
      return { type: "setProp", path, prop: "typography", value: TEXT_SIZE_MAP[cls] };
    }
  }

  // Font weight change
  for (const cls of added) {
    if (FONT_WEIGHT_MAP[cls]) {
      return { type: "setProp", path, prop: "weight", value: FONT_WEIGHT_MAP[cls] };
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function normalizeWhitespace(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

function setsEqual<T>(a: Set<T>, b: Set<T>): boolean {
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
  }
  return true;
}
