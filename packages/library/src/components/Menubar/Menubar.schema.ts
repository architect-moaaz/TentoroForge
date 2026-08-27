import { z } from "zod";
const MenuItem = z.object({ label: z.string(), value: z.string() });
const Menu = z.object({ label: z.string(), items: z.array(MenuItem) });
export const MenubarProps = z.object({
  menus:     z.array(Menu).default([]),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type MenubarPropsType = z.infer<typeof MenubarProps>;
