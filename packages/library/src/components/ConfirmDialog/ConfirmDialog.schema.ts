import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const ConfirmDialogProps = z
  .object({
    triggerLabel: z.string().min(1),
    title: z.string().min(1),
    description: z.string().min(1),
    workflow: z.string().min(1),
    args: z.record(z.unknown()).optional(),
    confirmLabel: z.string().optional(),
    cancelLabel: z.string().optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type ConfirmDialogPropsType = z.infer<typeof ConfirmDialogProps>;
