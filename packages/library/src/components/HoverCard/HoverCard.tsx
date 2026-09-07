"use client";
import * as React from "react";
import * as RHoverCard from "@radix-ui/react-hover-card";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { HoverCardPropsType } from "./HoverCard.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { cx } from "../../util/cx";
import { useMotion } from "../../style/useMotion";

export interface HoverCardProps extends HoverCardPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function HoverCard({ label, title, content, side, align, openDelay, closeDelay, style, className, children }: HoverCardProps) {
  // `className` was declared in this component's Zod schema AND its node schema
  // and destructured by neither, so a producer writing `props.className` on the
  // node had it silently dropped. Merged last so an authored utility class wins
  // over the built-in one, which is the reason a producer sets it. See util/cx.

  return (
    // A HOVER CARD THAT POPS INSTANTLY ON THE SLIGHTEST MOUSE-OVER IS THE ONE
    // BEHAVIOUR A HOVER CARD MUST NOT HAVE.
    //
    // `openDelay` / `closeDelay` were hardwired to 0 and `sideOffset` to 6, and
    // unlike Tooltip (which has `side`) and Popover (which has `align`) this
    // component had NO placement prop in any of the three layers — so a rich
    // preview card pinned to the bottom of a page could not be moved and could
    // not be given hover intent. Radix's own defaults (700/300) are the
    // conventional intent window; a caller that wants the old instant behaviour
    // passes 0 explicitly, which is now expressible and was not before.
    <RHoverCard.Root openDelay={openDelay ?? 700} closeDelay={closeDelay ?? 300}>
      <RHoverCard.Trigger asChild>
        <span tabIndex={0} data-hover-card="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className={cx("inline-flex cursor-default items-center font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
          {children ?? label}
        </span>
      </RHoverCard.Trigger>
      <RHoverCard.Portal>
        <RHoverCard.Content sideOffset={6} side={side} align={align}
          className="z-50 w-64 rounded-md border border-input bg-white p-3 text-sm shadow-md">
          {title && <div className="mb-1 font-medium text-foreground">{title}</div>}
          <div className="text-muted-foreground">{content}</div>
        </RHoverCard.Content>
      </RHoverCard.Portal>
    </RHoverCard.Root>
  );
}
