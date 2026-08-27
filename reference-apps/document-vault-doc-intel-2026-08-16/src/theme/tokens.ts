// Client-safe: just re-exports the library defaults.
//
// Custom token overrides (from src/theme/tokens.custom.json) are merged
// SERVER-SIDE only — see tokens.server.ts. Client code that needs the
// merged theme fetches it via GET /api/editor/theme.
//
// This split avoids bundling `fs` into client bundles (the fs read
// happens only in tokens.server.ts).
import { defaultTokens } from "@tentoroforge/library";
export const tokens = defaultTokens;
