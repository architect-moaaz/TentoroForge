"use client";
import * as React from "react";
import * as RContextMenu from "@radix-ui/react-context-menu";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { ContextMenuPropsType } from "./ContextMenu.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { resolveIcon } from "../../icons";

export interface ContextMenuProps extends ContextMenuPropsType {
  style?: StyleSlotT;
  onSelect?: (value: string) => void;
  children?: React.ReactNode;
}

export function ContextMenu({ label, items = [], style, onSelect, children }: ContextMenuProps) {
  return (
    <RContextMenu.Root>
      <RContextMenu.Trigger asChild>
        <div data-context-menu="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className="flex min-h-[3rem] items-center justify-center rounded-md border border-dashed border-input px-4 py-3 text-sm text-muted-foreground">
          {children ?? label}
        </div>
      </RContextMenu.Trigger>
      <RContextMenu.Portal>
        <RContextMenu.Content className="z-50 min-w-[10rem] rounded-md border border-input bg-white p-1 shadow-md">
          {items.map((it) => {
            const Icon = it.icon ? resolveIcon(it.icon) : null;
            return (
              <RContextMenu.Item key={it.value} disabled={it.disabled} onSelect={() => onSelect?.(it.value)}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted data-[disabled]:pointer-events-none data-[disabled]:opacity-50">
                {Icon && <Icon size={14} aria-hidden="true" />}{it.label}
              </RContextMenu.Item>
            );
          })}
        </RContextMenu.Content>
      </RContextMenu.Portal>
    </RContextMenu.Root>
  );
}
