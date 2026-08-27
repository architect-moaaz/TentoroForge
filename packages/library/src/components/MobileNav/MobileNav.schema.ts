import { z } from "zod";

const NavItem = z.object({
  label: z.string(),
  href: z.string(),
  icon: z.string().optional(),
});

export const MobileNavProps = z.object({
  items: z.array(NavItem).default([]),
  triggerIcon: z.string().default("menu"),
  ariaLabel: z.string().default("Open navigation menu"),
  align: z.enum(["start", "end"]).default("end"),
  /** Extra class applied to the outer wrapper. The wrapper itself
   * is always `md:hidden` so this control disappears on desktop. */
  className: z.string().optional(),
});
export type MobileNavPropsType = z.infer<typeof MobileNavProps>;
