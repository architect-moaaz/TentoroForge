"use client";
import * as React from "react";
import * as RHoverCard from "@radix-ui/react-hover-card";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { HoverCardPropsType } from "./HoverCard.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

export interface HoverCardProps extends HoverCardPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function HoverCard({ label, title, content, style, children }: HoverCardProps) {
  return (
    <RHoverCard.Root openDelay={0} closeDelay={0}>
      <RHoverCard.Trigger asChild>
        <span tabIndex={0} data-hover-card="" style={resolveStyle(style)} {...useMotion(style?.motion)}
          className="inline-flex cursor-default items-center font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {children ?? label}
        </span>
      </RHoverCard.Trigger>
      <RHoverCard.Portal>
        <RHoverCard.Content sideOffset={6}
          className="z-50 w-64 rounded-md border border-input bg-white p-3 text-sm shadow-md">
          {title && <div className="mb-1 font-medium text-foreground">{title}</div>}
          <div className="text-muted-foreground">{content}</div>
        </RHoverCard.Content>
      </RHoverCard.Portal>
    </RHoverCard.Root>
  );
}
