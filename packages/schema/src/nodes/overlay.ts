import { z } from "zod";
import { StyleSlot } from "../style-slot";

const MenuItem = z.object({
  label:    z.string().min(1),
  value:    z.string().min(1),
  icon:     z.string().optional(),
  disabled: z.boolean().optional(),
}).strict();

/**
 * A menu's item list: optional, and empty is legal.
 *
 * WHY NOT `.min(1)`, WHICH IS WHAT THIS WAS
 * -----------------------------------------
 * An unconfigured menu is *under-configured*, not malformed — and the cost of
 * calling it malformed is paid by the whole page, not by the menu. `NodeV2`
 * tries the strict shapes first and falls back to `anyRegistered`, which
 * deliberately REFUSES any type a strict shape already covers (otherwise the
 * fallback would launder every failed strict node). So a DropdownMenu with no
 * items matched nothing at all, `PageV2` failed, and the scaffold logged
 * `schema validation failed … rendering raw` and dropped the ENTIRE page out of
 * validated rendering. Observed live: three unconfigured menus on one page took
 * the other nine nodes down with them, and the DropdownMenu that started it
 * would not even open in the shipped app.
 *
 * "You have not filled this in yet" must not be spelled the same way as "this
 * page is corrupt". The components now render a legible empty state
 * (MenuEmptyNote), so an empty list is a state the runtime handles rather than
 * one it has to be protected from — and every other node on the page keeps its
 * validation.
 */
const MenuItems = z.array(MenuItem).default([]);

export const DropdownMenuNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("DropdownMenu"),
  props: z.object({
    trigger:     z.string().min(1),
    triggerIcon: z.string().optional(),
    items:       MenuItems,
    align:       z.enum(["start", "center", "end"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type DropdownMenuNodeT = z.infer<typeof DropdownMenuNode>;

export const PopoverNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Popover"),
  props: z.object({
    trigger: z.string().min(1),
    title:   z.string().optional(),
    content: z.string().min(1),
    align:   z.enum(["start", "center", "end"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type PopoverNodeT = z.infer<typeof PopoverNode>;

export const TooltipNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Tooltip"),
  props: z.object({
    label:   z.string().min(1),
    content: z.string().min(1),
    side:    z.enum(["top", "right", "bottom", "left"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type TooltipNodeT = z.infer<typeof TooltipNode>;

export const DrawerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Drawer"),
  props: z.object({
    trigger:     z.string().min(1),
    title:       z.string().optional(),
    description: z.string().optional(),
    side:        z.enum(["left", "right", "top", "bottom"]).optional(),
    content:     z.string().min(1),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type DrawerNodeT = z.infer<typeof DrawerNode>;

export const ContextMenuNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("ContextMenu"),
  props: z.object({
    label: z.string().min(1),
    items: MenuItems,
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ContextMenuNodeT = z.infer<typeof ContextMenuNode>;

export const HoverCardNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("HoverCard"),
  props: z.object({
    label:   z.string().min(1),
    title:   z.string().optional(),
    content: z.string().min(1),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type HoverCardNodeT = z.infer<typeof HoverCardNode>;

const MenubarItem = z.object({ label: z.string().min(1), value: z.string().min(1) }).strict();
// Same reasoning as MenuItems: a menu title with no entries yet is an
// authoring state the Menubar renders legibly, not a reason to invalidate
// the page it sits on.
const MenubarMenu = z.object({ label: z.string().min(1), items: z.array(MenubarItem).default([]) }).strict();
export const MenubarNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Menubar"),
  props: z.object({
    menus: z.array(MenubarMenu).default([]),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type MenubarNodeT = z.infer<typeof MenubarNode>;
