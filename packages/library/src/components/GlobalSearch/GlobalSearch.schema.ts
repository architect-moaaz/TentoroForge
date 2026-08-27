import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * GlobalSearch — Spec C Slice 7. App-wide search input; typically
 * mounted in the shell header. Emits queries to a workflow that
 * returns cross-entity results. Complements CommandPalette (which is
 * navigation + action-focused).
 */
export const GlobalSearchProps = z
  .object({
    placeholder: z.string().min(1).default("Search…"),
    workflow: z.string().min(1),  // fires on submit/enter with { query }
    debounceMs: z.number().int().min(0).max(2000).default(200),
    style: StyleSlot.optional(),
  })
  .strict();

export type GlobalSearchPropsType = z.infer<typeof GlobalSearchProps>;
