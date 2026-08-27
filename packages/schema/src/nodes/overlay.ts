import { z } from "zod";
import { StyleSlot } from "../style-slot";

const MenuItem = z.object({
  label:    z.string().min(1),
  value:    z.string().min(1),
  icon:     z.string().optional(),
  disabled: z.boolean().optional(),
}).strict();

export const DropdownMenuNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("DropdownMenu"),
  props: z.object({
    trigger:     z.string().min(1),
    triggerIcon: z.string().optional(),
    items:       z.array(MenuItem).min(1),
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
    items: z.array(MenuItem).min(1),
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
const MenubarMenu = z.object({ label: z.string().min(1), items: z.array(MenubarItem).min(1) }).strict();
export const MenubarNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Menubar"),
  props: z.object({
    menus: z.array(MenubarMenu).min(1),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type MenubarNodeT = z.infer<typeof MenubarNode>;
