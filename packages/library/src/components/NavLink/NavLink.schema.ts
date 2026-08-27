import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

// NavLink accepts two shapes so it works both for hand-authored/JSX usage
// (`href` + `children`) and for the schema/Figma pipeline, where the
// `unifyLabelHref` remap normalises to `label` + `navigate`. All optional and
// non-strict so per-node `className` (Figma styling) and either prop pair pass.
export const NavLinkProps = z.object({
  href: z.string().optional(),
  navigate: z.string().optional(),
  label: z.string().optional(),
  children: z.string().optional(),
  currentPath: z.string().optional(),
  className: z.string().optional(),
  style: StyleSlot.optional(),
});

export type NavLinkPropsType = z.infer<typeof NavLinkProps>;
