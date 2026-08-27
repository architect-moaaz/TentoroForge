import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const ALERT_VARIANTS = ["neutral", "info", "success", "danger", "warning"] as const;

export const AlertProps = z
  .object({
    message: z.string().min(1),
    variant: z.enum(ALERT_VARIANTS).default("neutral"),
    title: z.string().optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type AlertPropsType = z.infer<typeof AlertProps>;
