"use client";
import * as React from "react";
import * as RPopover from "@radix-ui/react-popover";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { PopoverPropsType } from "./Popover.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { cx } from "../../util/cx";
import { useMotion } from "../../style/useMotion";

export interface PopoverProps extends PopoverPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Popover({ trigger, title, content, align = "center", style, className, children }: PopoverProps) {
  // `className` was declared in this component's Zod schema AND its node schema
  // and destructured by neither, so a producer writing `props.className` on the
  // node had it silently dropped. Merged last so an authored utility class wins
  // over the built-in one, which is the reason a producer sets it. See util/cx.

  return (
    <RPopover.Root>
      <RPopover.Trigger asChild>
        <button type="button" data-popover="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className={cx("inline-flex items-center rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
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
