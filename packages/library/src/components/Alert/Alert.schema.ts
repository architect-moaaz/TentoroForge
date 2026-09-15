import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

export const ALERT_VARIANTS = ["neutral", "info", "success", "danger", "warning"] as const;

export const AlertProps = z
  .object({
    message: z.string().min(1),
    variant: z.enum(ALERT_VARIANTS).default("neutral"),
    title: z.string().optional(),
    // An alert's live-region politeness. The composer adds this to error
    // alerts for accessibility, but it was not enumerated — so the whole
    // surface was rejected for "ariaLive was unexpected", burning a ~90s
    // compose attempt on a page whose Alert was fine. Support it: the
    // component applies it, deferring to role="alert" when it is absent.
    ariaLive: z.enum(["off", "polite", "assertive"]).optional(),
    style: StyleSlot.optional(),
  });

export type AlertPropsType = z.infer<typeof AlertProps>;
