import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * SavedViewsPicker — Spec C Slice 7. A dropdown/segmented picker over
 * a list of saved filter+sort configs. Planner emits `views[]` per
 * list page from the plan's declared saved-view catalog.
 */
export const SavedViewsPickerProps = z
  .object({
    views: z
      .array(
        z.object({
          id: z.string().min(1),
          label: z.string().min(1),
          isDefault: z.boolean().optional(),
        })
      )
      .min(1),
    activeViewId: z.string().optional(),
    onSelectWorkflow: z.string().optional(),  // workflow to fire when a view is picked
    style: StyleSlot.optional(),
  })
  .strict();

export type SavedViewsPickerPropsType = z.infer<typeof SavedViewsPickerProps>;
