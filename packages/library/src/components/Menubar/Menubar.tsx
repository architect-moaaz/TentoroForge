"use client";
import * as React from "react";
import * as RMenubar from "@radix-ui/react-menubar";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { MenubarPropsType } from "./Menubar.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { MenuEmptyNote } from "../../util/MenuEmptyNote";

export interface MenubarProps extends MenubarPropsType {
  style?: StyleSlotT;
  onSelect?: (value: string) => void;
}

export function Menubar({ menus = [], style, onSelect }: MenubarProps) {
  return (
    <RMenubar.Root data-menubar="" style={resolveStyle(style)} {...useMotion(style?.motion)}
      className="flex items-center gap-1 rounded-md border border-input bg-white p-1">
      {/* A Menubar with no menus is a 2px-tall white line — the same
          "invisible and undiagnosable" shape MenuEmptyNote exists for, one
          level up. Say what it is instead of collapsing. */}
      {menus.length === 0 && <MenuEmptyNote what="menus" />}
      {menus.map((menu, mi) => (
        <RMenubar.Menu key={mi}>
          <RMenubar.Trigger className="rounded px-2 py-1 text-sm outline-none data-[state=open]:bg-muted">
            {menu.label}
          </RMenubar.Trigger>
          <RMenubar.Portal>
            <RMenubar.Content align="start" sideOffset={4}
              className="z-50 min-w-[10rem] rounded-md border border-input bg-white p-1 shadow-md">
              {(menu.items ?? []).length === 0 && <MenuEmptyNote />}
              {(menu.items ?? []).map((it) => (
                <RMenubar.Item key={it.value} onSelect={() => onSelect?.(it.value)}
                  className="cursor-pointer rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted">
                  {it.label}
                </RMenubar.Item>
              ))}
            </RMenubar.Content>
          </RMenubar.Portal>
        </RMenubar.Menu>
      ))}
    </RMenubar.Root>
  );
}
