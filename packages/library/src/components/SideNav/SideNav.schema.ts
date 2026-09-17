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
    // The owner's mark, served from the app's own `public/` — written by
    // `project_shell` from `designSystem.logo`, put there by
    // `project_brand_logo`. Given one, the brand block draws the mark where it
    // would otherwise draw the first letter of `appName`.
    logoSrc: z.string().optional(),
    // Never derived from the file name: a mark in the corner of every screen
    // says which application this is, and "a7f3c1e9.png" says nothing aloud.
    logoAlt: z.string().optional(),
    // width / height of the source image. A wordmark is several times wider
    // than it is tall, and without its ratio an SVG with no intrinsic size
    // lays out at zero width.
    logoAspect: z.number().optional(),
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
