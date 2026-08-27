/**
 * Round-Trip System — keeps IR and code in sync.
 *
 * Usage:
 *   1. Compile IR with devMode=true → files with boundary markers
 *   2. User/LLM edits a file
 *   3. Parse the file → extract IR regions and user regions
 *   4. Compare with expected compiler output → detect changes
 *   5. Reverse-map changes to IR operations
 *   6. On recompile → merge preserves user code
 */

// Parser
export { parseCompiledFile, hasBoundaryMarkers, stripBoundaryMarkers } from "./parse.js";
export type { ParseResult, UserCodeBlock } from "./parse.js";

// Reverse mapper
export { reverseMapChanges } from "./reverse-map.js";
export type { IROperation, ReverseMapResult, UnmappedRegion } from "./reverse-map.js";

// Merge
export { mergeWithUserCode } from "./merge.js";
export type { MergeResult } from "./merge.js";

// ---------------------------------------------------------------------------
// Convenience: full round-trip cycle
// ---------------------------------------------------------------------------

import { parseCompiledFile } from "./parse.js";
import { reverseMapChanges, type ReverseMapResult, type IROperation } from "./reverse-map.js";
import { mergeWithUserCode, type MergeResult } from "./merge.js";
import type { IRNode } from "@tentoroforge/ir";

/**
 * Perform a full round-trip sync for a single file.
 *
 * @param expectedCode - What the compiler produced (with boundaries)
 * @param actualCode - What's currently on disk (may have user edits)
 * @returns Operations to apply to IR + info about unmapped regions
 */
export function roundTripSync(
  expectedCode: string,
  actualCode: string,
): RoundTripResult {
  const expectedParsed = parseCompiledFile(expectedCode);
  const actualParsed = parseCompiledFile(actualCode);

  // If actual file has no boundaries, it's been fully ejected
  if (!actualParsed.hasBoundaries) {
    return {
      status: "ejected",
      operations: [],
      unmappedRegions: [],
      customNodes: [],
    };
  }

  // If boundaries are broken, file is corrupt
  if (!actualParsed.irIntact) {
    return {
      status: "corrupt",
      operations: [],
      unmappedRegions: [],
      customNodes: [],
    };
  }

  // Compare regions
  const { operations, unmappedRegions } = reverseMapChanges(
    expectedParsed.irRegions,
    actualParsed.irRegions,
  );

  // Convert unmapped regions to Custom nodes
  const customNodes: CustomNodeConversion[] = unmappedRegions.map((region) => ({
    path: region.path.split(".").map(Number),
    customNode: {
      node: "Custom",
      code: region.modifiedCode,
      _sourceIRNode: region.path,
    } as IRNode,
  }));

  const status = operations.length === 0 && customNodes.length === 0
    ? "in-sync"
    : "changed";

  return {
    status,
    operations,
    unmappedRegions: unmappedRegions.map((r) => r.path),
    customNodes,
  };
}

export interface RoundTripResult {
  /** Overall status */
  status: "in-sync" | "changed" | "ejected" | "corrupt";
  /** IR operations to apply (from reverse-mapped changes) */
  operations: IROperation[];
  /** Paths of regions that couldn't be reverse-mapped */
  unmappedRegions: string[];
  /** Custom node conversions for unmapped regions */
  customNodes: CustomNodeConversion[];
}

export interface CustomNodeConversion {
  path: number[];
  customNode: IRNode;
}

/**
 * Recompile and merge: takes new compiled output and an existing file,
 * preserves user code blocks.
 */
export function recompileAndMerge(
  freshCompiled: string,
  existingFile: string,
): MergeResult {
  return mergeWithUserCode(freshCompiled, existingFile);
}
