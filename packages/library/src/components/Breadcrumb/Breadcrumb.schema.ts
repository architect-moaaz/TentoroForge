import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

const BreadcrumbItem = z.object({
  label: z.string().min(1),
  href: z.string().optional(),
}).strict();

export const BreadcrumbProps = z
  .object({
    items: z.array(BreadcrumbItem).min(1),
    separator: z.string().optional(),
    /**
     * Append a final, non-linked crumb for the page the breadcrumb is on,
     * labelled from the route's last segment. Off by default so no existing
     * trail grows a crumb it did not ask for.
     */
    currentPageAuto: z.boolean().optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type BreadcrumbPropsType = z.infer<typeof BreadcrumbProps>;
export type BreadcrumbItem = z.infer<typeof BreadcrumbItem>;
