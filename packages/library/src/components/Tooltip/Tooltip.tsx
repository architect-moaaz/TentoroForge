"use client";
import * as React from "react";
import * as RTooltip from "@radix-ui/react-tooltip";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { TooltipPropsType } from "./Tooltip.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { cx } from "../../util/cx";
import { useMotion } from "../../style/useMotion";

export interface TooltipProps extends TooltipPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Tooltip({ label, content, side = "top", style, className, children }: TooltipProps) {
  // `className` was declared in this component's Zod schema AND its node schema
  // and destructured by neither, so a producer writing `props.className` on the
  // node had it silently dropped. Merged last so an authored utility class wins
  // over the built-in one, which is the reason a producer sets it. See util/cx.

  return (
    <RTooltip.Provider delayDuration={0}>
      <RTooltip.Root>
        <RTooltip.Trigger asChild>
          <span tabIndex={0} data-tooltip="" style={resolveStyle(style)} {...useMotion(style?.motion)}
            className={cx("inline-flex cursor-default items-center underline decoration-dotted underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
            {children ?? label}
          </span>
        </RTooltip.Trigger>
        <RTooltip.Portal>
          <RTooltip.Content side={side} sideOffset={4}
            className="z-50 max-w-xs rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-md">
            {content}
            <RTooltip.Arrow className="fill-foreground" />
          </RTooltip.Content>
        </RTooltip.Portal>
      </RTooltip.Root>
    </RTooltip.Provider>
  );
}
