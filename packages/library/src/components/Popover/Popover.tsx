"use client";
import * as React from "react";
import * as RPopover from "@radix-ui/react-popover";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { PopoverPropsType } from "./Popover.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface PopoverProps extends PopoverPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Popover({ trigger, title, content, align = "center", style, children }: PopoverProps) {
  return (
    <RPopover.Root>
      <RPopover.Trigger asChild>
        <button type="button" data-popover="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className="inline-flex items-center rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {trigger}
        </button>
      </RPopover.Trigger>
      <RPopover.Portal>
        <RPopover.Content align={align} sideOffset={6}
          className="z-50 w-64 rounded-md border border-input bg-white p-3 text-sm shadow-md">
          {title && <div className="mb-1 font-medium text-foreground">{title}</div>}
          {children ?? <div className="text-muted-foreground">{content}</div>}
        </RPopover.Content>
      </RPopover.Portal>
    </RPopover.Root>
  );
}
