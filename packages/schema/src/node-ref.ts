/**
 * node-ref.ts — shared forward-reference holder for NodeV2.
 *
 * This file exists solely to break the circular import that would arise if
 * foundation.ts / layout-v2.ts / motion.ts imported NodeV2Ref directly from
 * page.ts (which imports from those files).
 *
 * Pattern:
 *   1. Node files import `NodeV2Ref` from here and use it inside `z.lazy()`
 *      so it is only dereferenced at parse-time, not at import-time.
 *   2. page.ts calls `setNodeV2Ref(resolvedUnion)` inside its NodeV2 lazy
 *      factory, after all node types are assembled. This wires up the strict
 *      union so that any parse triggered via PageV2 validates children fully.
 *   3. When a node schema is parsed in isolation (e.g. unit tests that import
 *      only layout-v2.ts), _ref is still undefined and NodeV2Ref falls back
 *      to z.any() — preserving the pre-Task-8 behaviour for standalone node
 *      tests. Full PageV2 parsing always goes through NodeV2 (which sets _ref
 *      before any child parse can run), so type-checking is strict there.
 */
import { z } from "zod";

let _ref: z.ZodTypeAny | undefined;

/**
 * Called by page.ts once the full NodeV2 union is assembled.
 * Wires up strict child validation for any parse triggered via PageV2/NodeV2.
 */
export function setNodeV2Ref(schema: z.ZodTypeAny): void {
  _ref = schema;
}

/**
 * A lazy reference to the NodeV2 union. Node files use this inside their
 * own `z.lazy(() => z.array(NodeV2Ref))` children fields.
 *
 * - When resolved through PageV2: _ref is the full strict union (set by
 *   page.ts), so unknown child types are rejected.
 * - When resolved in isolation (standalone node unit tests): _ref is
 *   undefined, falls back to z.any() so existing tests continue to pass.
 */
export const NodeV2Ref: z.ZodTypeAny = z.lazy(() => _ref ?? z.any());
