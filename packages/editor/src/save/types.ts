import type { Page } from "@tentoroforge/schema";
import type { ValidationError } from "../state/types";

export type SaveResult =
  | { ok: true; savedSchema: Page; suggestions: unknown[]; autoApplied?: unknown[] }
  | { ok: false; errors: ValidationError[]; httpStatus: number };

export type LoadResult = { schema: Page };
