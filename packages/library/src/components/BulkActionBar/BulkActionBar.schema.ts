import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * BulkActionBar — Spec C Slice 7. Appears when a Table has one or
 * more rows selected. Renders `selectedCount` + a row of workflow
 * actions. Planner emits actions from the workflow catalog per entity.
 */
export const BulkActionBarProps = z
  .object({
    selectedCount: z.number().int().min(0).default(0),
    actions: z
      .array(
        z.object({
          label: z.string().min(1),
          workflow: z.string().min(1),
          variant: z.enum(["primary", "secondary", "ghost", "destructive"]).default("secondary"),
        })
      )
      .min(1),
    onClear: z.string().optional(),  // workflow name to fire on "clear selection"
    style: StyleSlot.optional(),
  })
  .strict();

export type BulkActionBarPropsType = z.infer<typeof BulkActionBarProps>;
