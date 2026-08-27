import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

const SubItem = z
  .object({
    label: z.string(),
    route: z.string(),
    icon: z.string().optional(),
  })
  .strict();

const Group = z
  .object({
    label: z.string().optional(),
    icon: z.string().optional(),
    route: z.string().optional(),
    items: z.array(SubItem).optional(),
  })
  .strict();

export const SideNavProps = z
  .object({
    // Main menu items + their sub-items, derived from the app's nav-flow + pages.
    groups: z.array(Group).optional(),
    appName: z.string().optional(),
    // Light or dark rail — chosen from the design-spec palette luminance.
    mode: z.enum(["dark", "light"]).optional(),
    // Concrete colors from the design-spec palette (override the mode defaults).
    bg: z.string().optional(),
    text: z.string().optional(),
    muted: z.string().optional(),
    accent: z.string().optional(),
    collapsedWidth: z.number().optional(),
    expandedWidth: z.number().optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type SideNavPropsType = z.infer<typeof SideNavProps>;
