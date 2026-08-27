"use client";
import * as React from "react";
import * as RDropdown from "@radix-ui/react-dropdown-menu";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { DropdownMenuPropsType } from "./DropdownMenu.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { resolveIcon } from "../../icons";

export interface DropdownMenuProps extends DropdownMenuPropsType {
  style?: StyleSlotT;
  onSelect?: (value: string) => void;
}

export function DropdownMenu({ trigger, triggerIcon, items = [], align = "start", style, onSelect }: DropdownMenuProps) {
  const TriggerIcon = triggerIcon ? resolveIcon(triggerIcon) : null;
  return (
    <RDropdown.Root>
      <RDropdown.Trigger asChild>
        <button type="button" data-dropdown-menu="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className="inline-flex items-center gap-1.5 rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {TriggerIcon && <TriggerIcon size={16} aria-hidden="true" />}{trigger}
        </button>
      </RDropdown.Trigger>
      <RDropdown.Portal>
        <RDropdown.Content align={align} sideOffset={4}
          className="z-50 min-w-[10rem] rounded-md border border-input bg-white p-1 shadow-md">
          {items.map((it) => {
            const Icon = it.icon ? resolveIcon(it.icon) : null;
            return (
              <RDropdown.Item key={it.value} disabled={it.disabled} onSelect={() => onSelect?.(it.value)}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted data-[disabled]:pointer-events-none data-[disabled]:opacity-50">
                {Icon && <Icon size={14} aria-hidden="true" />}{it.label}
              </RDropdown.Item>
            );
          })}
        </RDropdown.Content>
      </RDropdown.Portal>
    </RDropdown.Root>
  );
}
