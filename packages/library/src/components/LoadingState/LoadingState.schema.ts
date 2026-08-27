import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const LoadingStateProps = z
  .object({
    label: z.string().min(1),
    style: StyleSlot.optional(),
  })
  .strict();

export type LoadingStatePropsType = z.infer<typeof LoadingStateProps>;
