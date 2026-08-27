import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const EmptyStateProps = z
  .object({
    message: z.string().min(1),
    icon: z.string().optional(),
    action: z
      .object({
        label: z.string().min(1),
        workflow: z.string().min(1),
      })
      .optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type EmptyStatePropsType = z.infer<typeof EmptyStateProps>;
