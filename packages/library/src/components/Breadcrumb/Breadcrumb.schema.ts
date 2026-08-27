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
    style: StyleSlot.optional(),
  })
  .strict();

export type BreadcrumbPropsType = z.infer<typeof BreadcrumbProps>;
export type BreadcrumbItem = z.infer<typeof BreadcrumbItem>;
